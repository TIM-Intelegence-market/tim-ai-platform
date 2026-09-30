"""Broncx chart images: local copies and what a local vision model reads from them.

Broncx often posts a chart with drawn levels and arrows instead of (or next to)
text. The feed bot downloads those images when it picks a post up (Discord's
attachment links expire after about a day) and a local vision model (Ollama,
default ``qwen3.5:9b``) reads what is drawn on them. Nothing leaves the Mac.

A chart reading is weaker than his text: every value is an estimate read off a
picture. It follows the same rules as the text guidance (hypothesis only, never
a confirmation, never a trade plan on its own) and in addition:

- a chart has a direction only when it shows a position tool: the direction
  follows from where the red (risk) and green (reward) boxes sit around the
  entry, computed here, not judged by the model (arrows proved unreliable)
- that direction only counts when the post has no text, or when it matches the
  direction of the text; a post whose text states no direction keeps NONE
- levels are kept only within +-30 % of the current price, are marked
  ``source="chart"`` and are checked against the candles, but never become
  level scenarios of their own
- symbol and timeframe from the chart only fill gaps in the text

Readings are cached in ``chart_readings.jsonl`` next to the posts, so an
analysis never calls the model and a replay reads the same values.
"""

from __future__ import annotations

import base64
import json
import os
import re
import urllib.error
import urllib.request
from dataclasses import dataclass, replace
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any, Callable

from .broncx_feed import (
    _PLAUSIBLE_HIGH,
    _PLAUSIBLE_LOW,
    _SYMBOLS,
    BroncxGuidance,
    BroncxLevel,
    BroncxPost,
    parse_guidance,
)

__all__ = [
    "DEFAULT_VISION_MODEL",
    "ChartImageStore",
    "ChartReading",
    "OllamaVision",
    "VisionError",
    "guidance_for_post",
    "merge_chart_reading",
    "parse_reading",
]

DEFAULT_VISION_MODEL = "qwen3.5:9b"
DEFAULT_OLLAMA_URL = "http://127.0.0.1:11434"
IMAGE_SUFFIXES = {".png", ".jpg", ".jpeg", ".webp", ".gif"}
MAX_IMAGE_BYTES = 10 * 1024 * 1024
_SAFE_NAME = re.compile(r"[^A-Za-z0-9._-]+")
_TIMEFRAME = re.compile(r"^(\d{1,3})\s*(m|min|h|d)$", re.IGNORECASE)
_MINUTES = {1, 3, 5, 15, 30, 45, 60, 120, 240}
_HOURS = {1, 2, 4, 6, 8, 12}
_ROLE_WORDS = (
    (re.compile(r"\b(tp\s?\d?|target|take\s?profit)\b", re.IGNORECASE), "TARGET"),
    (re.compile(r"\b(sl|stop|stop\s?loss|invalid\w*)\b", re.IGNORECASE), "STOP"),
    (re.compile(r"\bentry\b", re.IGNORECASE), "ENTRY"),
)

PROMPT = """You read a trading chart screenshot posted by a trader. Report ONLY what the trader drew or wrote on it.
Never guess. If something is not clearly visible, use null or an empty list.

Do NOT report: the price-axis grid numbers, the current/last price tag, the countdown timer, the chart's own
high/low markers, or the header text (symbol, timeframe and exchange go into their own fields).

Position tool: two stacked boxes that start at the same entry price, one red/pink and one green/teal.
Report the price at the OUTER edge of each box (the edge away from the entry) and the entry price, read from the
colored price labels on the axis. Do not decide long or short yourself.

Answer with one JSON object and nothing else:
{
  "symbol": "ticker in the chart header, e.g. BTCUSDT, or null",
  "timeframe": "chart timeframe in the header, e.g. 15m, 1h, 4h, or null",
  "position_tool": {"entry": 83866.0, "red_box_outer_edge": 84358.7, "green_box_outer_edge": 82641.4} or null,
  "levels": [{"price": 83250.5, "label": "text written next to a drawn line or zone, or empty"}],
  "text": "words the trader wrote on the chart, or empty"
}"""


class VisionError(RuntimeError):
    """The local vision model could not be reached or gave no usable answer."""


@dataclass(frozen=True, slots=True)
class ChartReading:
    image: str  # path relative to the feed directory
    model: str
    read_at: datetime
    bias: str  # SHORT | LONG | NONE
    symbol: str | None
    timeframe: str | None
    levels: tuple[tuple[Decimal, str], ...]  # (price, label)
    invalidation: tuple[tuple[str, Decimal], ...]  # (above|below, price)
    text: str
    error: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "image": self.image,
            "model": self.model,
            "read_at": self.read_at.isoformat(),
            "bias": self.bias,
            "symbol": self.symbol,
            "timeframe": self.timeframe,
            "levels": [{"price": str(price), "label": label} for price, label in self.levels],
            "invalidation": [{"side": side, "price": str(price)} for side, price in self.invalidation],
            "text": self.text,
            "error": self.error,
        }

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "ChartReading":
        return cls(
            image=str(payload["image"]),
            model=str(payload.get("model", "")),
            read_at=datetime.fromisoformat(payload["read_at"]),
            bias=str(payload.get("bias", "NONE")),
            symbol=payload.get("symbol"),
            timeframe=payload.get("timeframe"),
            levels=tuple((Decimal(str(item["price"])), str(item.get("label", ""))) for item in payload.get("levels", ())),
            invalidation=tuple((str(item["side"]), Decimal(str(item["price"]))) for item in payload.get("invalidation", ())),
            text=str(payload.get("text", "")),
            error=payload.get("error"),
        )


def _decimal(value: Any) -> Decimal | None:
    if isinstance(value, bool) or value is None:
        return None
    try:
        number = Decimal(str(value).replace(",", "").strip())
    except (InvalidOperation, ValueError):
        return None
    return number if number.is_finite() and number > 0 else None


def _symbol(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    match = re.match(r"^\s*([A-Za-z]+)", value)
    if not match:
        return None
    word = match.group(1).lower()
    for prefix, symbol in _SYMBOLS.items():
        if word == prefix or (word.startswith(prefix) and word[len(prefix):] in {"usdt", "usdc", "usd", "perp", "busd"}):
            return symbol
    return None


def _timeframe(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    match = _TIMEFRAME.match(value.strip())
    if not match:
        return None
    amount, unit = int(match.group(1)), match.group(2).lower()
    if unit == "h" and amount in _HOURS:
        return f"{amount}h"
    if unit in {"m", "min"} and amount in _MINUTES:
        return f"{amount}m"
    return None


def parse_reading(raw: str, *, image: str, model: str, read_at: datetime) -> ChartReading:
    """Validate the model's JSON strictly; anything malformed is dropped, never repaired by guessing."""
    try:
        payload = json.loads(raw)
    except ValueError:
        match = re.search(r"\{.*\}", raw, re.DOTALL)
        try:
            payload = json.loads(match.group(0)) if match else None
        except ValueError:
            payload = None
    if not isinstance(payload, dict):
        return ChartReading(image, model, read_at, "NONE", None, None, (), (), "", error="model answer was not a JSON object")
    levels: list[tuple[Decimal, str]] = []
    invalidation: list[tuple[str, Decimal]] = []
    bias = "NONE"
    tool = payload.get("position_tool")
    if isinstance(tool, dict):
        entry, red, green = (_decimal(tool.get(key)) for key in ("entry", "red_box_outer_edge", "green_box_outer_edge"))
        # Direction follows from the geometry, not from the model's opinion: risk above entry and reward below is a short.
        if entry is not None and red is not None and green is not None:
            if green < entry < red:
                bias = "SHORT"
            elif red < entry < green:
                bias = "LONG"
            if bias != "NONE":
                levels += [(entry, "entry: position tool"), (green, "target: position tool"), (red, "stop: position tool")]
                invalidation.append(("above" if bias == "SHORT" else "below", red))
    for item in payload.get("levels") or ():
        price = _decimal(item.get("price")) if isinstance(item, dict) else None
        if price is not None and all(price != known for known, _ in levels):
            levels.append((price, str(item.get("label") or "").strip()[:40]))
    return ChartReading(
        image=image,
        model=model,
        read_at=read_at,
        bias=bias,
        symbol=_symbol(payload.get("symbol")),
        timeframe=_timeframe(payload.get("timeframe")),
        levels=tuple(levels[:12]),
        invalidation=tuple(invalidation[:4]),
        text=str(payload.get("text") or "")[:500],
    )


class OllamaVision:
    """Minimal client for a local Ollama vision model (no network beyond this Mac)."""

    def __init__(self, model: str | None = None, url: str | None = None, timeout: float = 300.0,
                 post: Callable[[str, dict[str, Any], float], dict[str, Any]] | None = None) -> None:
        self.model = model or os.environ.get("TIM_BRONCX_VISION_MODEL") or DEFAULT_VISION_MODEL
        self.url = (url or os.environ.get("TIM_OLLAMA_URL") or DEFAULT_OLLAMA_URL).rstrip("/")
        self.timeout = timeout
        self._post = post or _post_json

    def read(self, image: Path) -> str:
        payload = {
            "model": self.model,
            "prompt": PROMPT,
            "images": [base64.b64encode(image.read_bytes()).decode("ascii")],
            "format": "json",
            "stream": False,
            "think": False,
            "options": {"temperature": 0},
        }
        body = self._post(f"{self.url}/api/generate", payload, self.timeout)
        answer = body.get("response") if isinstance(body, dict) else None
        if not isinstance(answer, str) or not answer.strip():
            raise VisionError(f"no answer from {self.model}: {str(body.get('error', ''))[:200] if isinstance(body, dict) else ''}")
        return answer


def _post_json(url: str, payload: dict[str, Any], timeout: float) -> dict[str, Any]:
    request = urllib.request.Request(url, data=json.dumps(payload).encode("utf-8"), headers={"Content-Type": "application/json"}, method="POST")
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as error:
        raise VisionError(f"Ollama answered HTTP {error.code}") from error
    except (urllib.error.URLError, OSError) as error:
        raise VisionError(f"Ollama not reachable at {url}: {type(error).__name__}") from error


class ChartImageStore:
    """Local chart images (``images/<message_id>/``) and their cached readings."""

    def __init__(self, root: Path) -> None:
        self.root = root
        self.images_dir = root / "images"
        self.readings_path = root / "chart_readings.jsonl"

    def images_for(self, message_id: str) -> list[Path]:
        folder = self.images_dir / _SAFE_NAME.sub("_", message_id)
        if not folder.is_dir():
            return []
        return sorted(path for path in folder.iterdir() if path.suffix.lower() in IMAGE_SUFFIXES and not path.name.startswith("."))

    def has_images(self, message_id: str) -> bool:
        return bool(self.images_for(message_id))

    def save(self, message_id: str, index: int, filename: str, data: bytes) -> Path:
        folder = self.images_dir / _SAFE_NAME.sub("_", message_id)
        folder.mkdir(parents=True, exist_ok=True)
        name = _SAFE_NAME.sub("_", Path(filename).name)[:80] or "image"
        target = folder / f"{index}-{name}"
        temporary = folder / f".{target.name}.tmp"
        temporary.write_bytes(data)
        os.replace(temporary, target)
        return target

    def relative(self, path: Path) -> str:
        return path.relative_to(self.root).as_posix()

    def readings(self) -> dict[str, ChartReading]:
        if not self.readings_path.exists():
            return {}
        readings: dict[str, ChartReading] = {}
        for line in self.readings_path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            try:
                reading = ChartReading.from_dict(json.loads(line))
            except (ValueError, KeyError, TypeError, InvalidOperation):
                continue
            readings[reading.image] = reading  # the newest reading of an image wins
        return readings

    def append_reading(self, reading: ChartReading) -> None:
        self.root.mkdir(parents=True, exist_ok=True)
        with self.readings_path.open("a", encoding="utf-8") as stream:
            stream.write(json.dumps(reading.to_dict(), ensure_ascii=False, sort_keys=True) + "\n")

    def readings_for(self, message_id: str, readings: dict[str, ChartReading] | None = None) -> list[ChartReading]:
        known = self.readings() if readings is None else readings
        return [known[key] for key in (self.relative(path) for path in self.images_for(message_id)) if key in known and known[key].error is None]

    def unread(self, posts: list[BroncxPost]) -> list[tuple[BroncxPost, Path]]:
        known = self.readings()
        return [(post, path) for post in posts for path in self.images_for(post.message_id) if self.relative(path) not in known]

    def read_pending(self, posts: list[BroncxPost], vision: OllamaVision, *, limit: int = 3,
                     clock: Callable[[], datetime] = lambda: datetime.now(timezone.utc)) -> list[ChartReading]:
        """Read up to ``limit`` not-yet-read images. A model error is stored so the image is not retried forever."""
        done = []
        for _, path in self.unread(posts)[:limit]:
            image = self.relative(path)
            try:
                reading = parse_reading(vision.read(path), image=image, model=vision.model, read_at=clock())
            except VisionError:
                raise  # model down: keep the image unread and try again next cycle
            except OSError as exc:
                reading = ChartReading(image, vision.model, clock(), "NONE", None, None, (), (), "", error=f"image unreadable: {type(exc).__name__}")
            self.append_reading(reading)
            done.append(reading)
        return done


def merge_chart_reading(text: BroncxGuidance, has_text: bool, readings: list[ChartReading], reference_price: Decimal | None) -> BroncxGuidance:
    """Add what the charts show to the text guidance, under the stricter chart rules."""
    if not readings:
        return text
    notes = list(text.notes)
    chart_biases = {reading.bias for reading in readings if reading.bias in {"SHORT", "LONG"}}
    bias = text.bias
    chart_direction_used = False
    if chart_biases:
        chart_bias = "MIXED" if len(chart_biases) > 1 else next(iter(chart_biases))
        if not has_text:
            bias, chart_direction_used = chart_bias, chart_bias in {"SHORT", "LONG"}
            notes.append(f"bias {chart_bias} read from chart (estimated)")
        elif text.bias == chart_bias:
            chart_direction_used = True
            notes.append(f"chart agrees with text bias {chart_bias}")
        else:
            notes.append(f"chart bias {chart_bias} ignored: text says {text.bias}")

    existing = {level.value for level in text.levels}
    levels = list(text.levels)
    for reading in readings:
        for price, label in reading.levels:
            if price in existing:
                continue
            if reference_price is None or reference_price <= 0 or not _PLAUSIBLE_LOW <= price / reference_price <= _PLAUSIBLE_HIGH:
                notes.append(f"chart level {price} dropped: not within 30 % of the current price")
                continue
            role = next((name for pattern, name in _ROLE_WORDS if pattern.search(label)), "LEVEL")
            levels.append(BroncxLevel(raw=f"chart:{label or price}", value=price, role=role, source="chart"))
            existing.add(price)
    invalidation = list(text.invalidation)
    # The position tool's stop belongs to its direction: it only invalidates a view that direction is part of.
    for reading in readings if chart_direction_used else ():
        if reading.bias != bias:
            continue
        for side, price in reading.invalidation:
            if reference_price is not None and reference_price > 0 and _PLAUSIBLE_LOW <= price / reference_price <= _PLAUSIBLE_HIGH:
                invalidation.append(f"{side} {price} (chart)")
                if price not in existing:
                    levels.append(BroncxLevel(raw=f"chart:invalid {side}", value=price, role="STOP", source="chart"))
                    existing.add(price)

    symbol = text.symbol or next((reading.symbol for reading in readings if reading.symbol), None)
    timeframe = text.timeframe or next((reading.timeframe for reading in readings if reading.timeframe), None)
    if bias in {"SHORT", "LONG"} and (levels or invalidation):
        quality = "STRUCTURED"
    elif bias != "NONE" or levels or invalidation or text.conditions or text.reaffirms_previous:
        quality = "PARTIAL"
    else:
        quality = "UNSTRUCTURED"
    return replace(text, bias=bias, symbol=symbol, timeframe=timeframe, levels=tuple(levels), invalidation=tuple(invalidation),
                   parse_quality=quality, notes=tuple(notes), chart_readings=len(readings))


def guidance_for_post(post: BroncxPost, reference_price: Decimal | None = None) -> BroncxGuidance:
    """Text guidance plus the cached chart readings attached to the post."""
    text = parse_guidance(post.content, reference_price)
    return merge_chart_reading(text, bool(post.content.strip()), list(post.chart_readings), reference_price)

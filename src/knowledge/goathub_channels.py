"""Three GoatHub channels read separately, every call checked against the price afterwards.

The plan agreed with the GoatHub admins (Broncx) has three sources, each with its own reader
and its own scorecard:

* ``futures_broncx``: Broncx's BTC futures analyses (FUTURES-TRADING-BRONCX and
  FUTURES-TRADING-EXPLANATIONS),
* ``spot_goatfather``: goatfather's spot calls and DCA plan (GOATFATHER-CHANNEL),
* ``gold_eydu``: EyDu's gold and silver calls (XAU-XAG).

Messages come from the read-only Discord bot (``scripts/goathub_discord_bot.py``) or from the
screen transcripts in ``goathub-verlauf/kanaele`` (``parse_transcript``). Each call stays a
hypothesis with author, time and the original text: the scorecard says how such calls played
out, it never turns a call into a signal. Outcomes only use candles that opened at or after the
minute the call was posted (no look-ahead). Nothing in this module posts to Discord;
``render_board`` only builds the text for a preview.
"""

from __future__ import annotations

import csv
import hashlib
import re
from dataclasses import dataclass, field, replace
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path
from typing import Any, Iterable, Sequence
from zoneinfo import ZoneInfo

from .broncx_feed import BroncxGuidance, BroncxLevel
from .goathub_feed import ROLE_CALLS, SOURCE_SCREEN, CommunityCall, GoatHubMessage, extract_call

__all__ = [
    "BOARD_LIMIT_CHARS",
    "CallOutcome",
    "ChannelProfile",
    "PROFILES",
    "PriceBar",
    "TrackedCall",
    "chart_reading",
    "check_outcome",
    "evaluate",
    "load_bars_csv",
    "parse_transcript",
    "profile_for",
    "read_call",
    "read_calls",
    "render_board",
    "scorecard",
]

BERLIN = ZoneInfo("Europe/Berlin")
BOARD_LIMIT_CHARS = 2000  # one Discord message

STATUS_OPEN = "open"
STATUS_TARGET = "target_hit"
STATUS_STOPPED = "stopped"
STATUS_EXPIRED = "expired"
STATUS_NOT_CHECKABLE = "not_checkable"  # no direction, or neither target nor stop
STATUS_NO_PRICES = "no_price_data"
STATUSES = (STATUS_OPEN, STATUS_TARGET, STATUS_STOPPED, STATUS_EXPIRED, STATUS_NOT_CHECKABLE, STATUS_NO_PRICES)


@dataclass(frozen=True, slots=True)
class ChannelProfile:
    key: str
    title: str
    channels: tuple[str, ...]  # normalised channel names or ids, see _channel_key
    authors: tuple[str, ...]  # only these authors' posts are calls (bots and guests are skipped)
    horizon: timedelta  # how long a call stays open before it counts as expired
    default_symbol: str | None = None


PROFILES: dict[str, ChannelProfile] = {
    "futures_broncx": ChannelProfile(
        "futures_broncx", "Broncx futures", ("futures-trading-broncx", "futures-trading-explanations"), ("broncx",), timedelta(hours=72),
        default_symbol="BTC"),
    "spot_goatfather": ChannelProfile(
        "spot_goatfather", "goatfather spot", ("goatfather-channel",), ("goatfather",), timedelta(days=30)),
    "gold_eydu": ChannelProfile(
        "gold_eydu", "EyDu gold", ("xau-xag",), ("eydu",), timedelta(hours=72), default_symbol="XAU"),
}

_SILVER = re.compile(r"\b(silver|xag)\b", re.IGNORECASE)
_GOLD = re.compile(r"\b(gold|xau)\b", re.IGNORECASE)
_BUCKET_RISKY = re.compile(r"\brisky\b", re.IGNORECASE)
_BUCKET_SAFE = re.compile(r"\bsafe\b", re.IGNORECASE)
_ACCOUNT_SIZE = re.compile(r"(\d+(?:\.\d+)?)\s?%\s*(?:of\s+(?:my\s+|the\s+|your\s+)?(?:account|acc|portfolio))", re.IGNORECASE)
_DCA_STEP = re.compile(r"\bevery\s+(\d+(?:\.\d+)?)\s?%", re.IGNORECASE)
_MAJORS = ("BTC", "ETH", "SOL")
# "tp hit, letting 25% run" reports on a trade already posted; it is not a new call.
_RESULT_POST = re.compile(r"\b(?:tps?|targets?)\s+(?:\d\s+)?hit\b|\bstopped\s+out\b|\bgot\s+stopped\b", re.IGNORECASE)
_CASHTAG = re.compile(r"\$([A-Za-z][A-Za-z0-9]{1,9})\b")
# Chart descriptions in the transcripts: "Long-Positionsbox ...; Kurs ca. 63.312,1, Ziel ca. 64.869,3, Stop ca. 62.823,3 [?]".
_CHART_BOX = re.compile(r"\b(Long|Short)-Positionsbox", re.IGNORECASE)
_CHART_NUMBER = r"(\d{1,3}(?:\.\d{3})+(?:,\d+)?|\d+(?:,\d+)?)"
_CHART_LEVELS = {
    "TARGET": re.compile(r"\bZiele?\s+ca\.\s+" + _CHART_NUMBER),
    "STOP": re.compile(r"\bStop\s+ca\.\s+" + _CHART_NUMBER),
    "ENTRY": re.compile(r"\bEinstieg\s+ca\.\s+" + _CHART_NUMBER),
}


def _channel_key(value: str) -> str:
    """'#📈 | FUTURES-TRADING-BRONCX' and 'futures-trading-broncx' name the same channel."""
    text = re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-")
    return text


def profile_for(message: GoatHubMessage) -> ChannelProfile | None:
    keys = {_channel_key(message.channel_id), _channel_key(message.channel_name)}
    for profile in PROFILES.values():
        if keys & set(profile.channels):
            return profile
    return None


def _author_key(name: str) -> str:
    return re.sub(r"\s*\[[^\]]*\]\s*", "", name).strip().lower()


# --------------------------------------------------------------------------- transcripts

_HEADER = re.compile(r"^### (\d{2})\.(\d{2})\.(\d{2}) (\d{2}):(\d{2})(?: \(Folgenachricht\))? \| (.+?)\s*$")
_TITLE = re.compile(r"^# (.+?)(?: \(Kategorie .+\))?\s*$")
_SKIP_PREFIXES = ("Hinweis", "Antwort auf", "(Datumstrenner", "Datumstrenner")
# Notes the transcriber added inside a message ("(Trennlinie 6. Oktober 2026 ueber dieser Nachricht)"):
# not the author's words, and their dates would otherwise be read as price levels.
_TRANSCRIBER_NOTE = re.compile(r"\s*\((?:Trennlinie|Antwort auf|Abgrenzung|Datumstrenner|Bearbeitet|evtl\.)(?:[^()]|\([^()]*\))*\)")


def _reaction_count(line: str) -> int:
    return sum(int(item) for item in re.findall(r"(?<![\w.])(\d+)(?=\s*(?:,|$|\())", line.split(":", 1)[1]))


def parse_transcript(path: Path, *, channel_id: str | None = None, received_at: datetime | None = None) -> list[GoatHubMessage]:
    """Messages from a screen transcript (``### 28.07.26 12:08 | Broncx [GOAT]`` blocks).

    Times in the transcripts are Berlin time. Attachments keep their description, reactions are
    summed. Blocks without text and without attachment are skipped. Message ids are stable, so
    importing the same file twice adds nothing.
    """
    text = path.read_text(encoding="utf-8")
    lines = text.splitlines()
    title = next((m.group(1).strip() for m in map(_TITLE.match, lines[:3]) if m), path.stem)
    channel_name = title
    channel = channel_id or _channel_key(re.sub(r"^[^A-Za-z0-9]+", "", title.split("|")[-1]))
    received = received_at or datetime.now(timezone.utc)
    messages: list[GoatHubMessage] = []
    block: list[str] = []
    header: re.Match[str] | None = None

    def flush(index: int) -> None:
        if header is None:
            return
        day, month, year, hour, minute, author = header.groups()
        posted = datetime(2000 + int(year), int(month), int(day), int(hour), int(minute), tzinfo=BERLIN).astimezone(timezone.utc)
        body: list[str] = []
        attachments: list[str] = []
        reactions = 0
        for line in block:
            stripped = line.strip()
            if stripped.startswith("Anhang"):
                attachments.append(stripped.split(":", 1)[1].strip() if ":" in stripped else stripped)
            elif stripped.startswith("Reaktionen:"):
                reactions = _reaction_count(stripped)
            elif stripped == "(kein Text)" or stripped.startswith(_SKIP_PREFIXES):
                continue
            else:
                body.append(_TRANSCRIBER_NOTE.sub("", line).rstrip())
        content = "\n".join(body).strip()
        if not content and not attachments:
            return
        digest = hashlib.sha1(f"{channel}|{header.group(0)}|{index}".encode()).hexdigest()[:20]
        messages.append(GoatHubMessage(
            message_id=f"transcript-{digest}", channel_id=channel, posted_at=posted, content=content or "(Bild)",
            received_at=received, author_name=re.sub(r"\s*\[[^\]]*\]\s*$", "", author).strip(), channel_name=channel_name,
            source=SOURCE_SCREEN, attachments=tuple(attachments), reactions=reactions, channel_role=ROLE_CALLS,
        ))

    index = 0
    for line in lines:
        match = _HEADER.match(line)
        if match:
            flush(index)
            index += 1
            header, block = match, []
        elif line.strip() == "---":
            flush(index)
            header, block = None, []
        elif header is not None:
            block.append(line)
    flush(index)
    return messages


# --------------------------------------------------------------------------- readers

@dataclass(frozen=True, slots=True)
class TrackedCall:
    profile: str
    call: CommunityCall
    extras: dict[str, Any] = field(default_factory=dict)  # spot: bucket, account_pct, dca_step_pct

    @property
    def symbol(self) -> str | None:
        return self.call.guidance.symbol

    @property
    def bias(self) -> str:
        return self.call.guidance.bias

    def to_dict(self) -> dict[str, Any]:
        payload = self.call.to_dict()
        payload["profile"] = self.profile
        payload["extras"] = dict(self.extras)
        return payload


def _spot_extras(text: str) -> dict[str, Any]:
    extras: dict[str, Any] = {}
    risky, safe = bool(_BUCKET_RISKY.search(text)), bool(_BUCKET_SAFE.search(text))
    if risky != safe:
        extras["bucket"] = "risky" if risky else "safe"
    if match := _ACCOUNT_SIZE.search(text):
        extras["account_pct"] = float(match.group(1))
    if match := _DCA_STEP.search(text):
        extras["dca_step_pct"] = float(match.group(1))
    return extras


def _german_number(raw: str) -> Decimal:
    return Decimal(raw.replace(".", "").replace(",", "."))


def chart_reading(attachments: Sequence[str]) -> tuple[str | None, tuple[BroncxLevel, ...]]:
    """Direction and levels of a position box described in a transcript attachment (estimated, source "chart")."""
    for attachment in attachments:
        box = _CHART_BOX.search(attachment)
        if not box:
            continue
        levels = []
        for role, pattern in _CHART_LEVELS.items():
            if match := pattern.search(attachment):
                levels.append(BroncxLevel(match.group(0), _german_number(match.group(1)), role, source="chart"))
        return box.group(1).upper(), tuple(levels)
    return None, ()


def _with_chart(message: GoatHubMessage, call: CommunityCall | None, profile: ChannelProfile) -> CommunityCall | None:
    bias, levels = chart_reading(message.attachments)
    if bias is None:
        return call
    if call is None:
        guidance = BroncxGuidance(bias, profile.default_symbol, None, levels, (), (), (), False, "STRUCTURED" if levels else "PARTIAL",
                                  ("direction and levels read from the chart image",), chart_readings=1, bias_source="chart")
        reasons = [f"Richtung {bias} (Chart)"]
    else:
        guidance = call.guidance
        notes = guidance.notes
        if guidance.bias != bias:
            return replace(call, guidance=replace(guidance, notes=notes + (f"chart box shows {bias}, text says {guidance.bias}; chart levels not used",)))
        guidance = replace(guidance, levels=guidance.levels + levels, chart_readings=guidance.chart_readings + 1)
        reasons = list(call.reasons)
    if levels:
        reasons.append("Level aus Chart (geschätzt)")
    return _regrade(CommunityCall(message, guidance, "C", tuple(dict.fromkeys(reasons))))


def _regrade(call: CommunityCall) -> CommunityCall:
    guidance = call.guidance
    has_level = any(level.role != "STOP" for level in guidance.levels)
    has_stop = bool(guidance.invalidation) or any(level.role == "STOP" for level in guidance.levels)
    grade = "A" if guidance.symbol and has_level and has_stop else "B" if guidance.symbol and (has_level or has_stop) else "C"
    return replace(call, grade=grade)


def read_call(message: GoatHubMessage, profile: ChannelProfile, reference_price: Decimal | None = None) -> TrackedCall | None:
    """One channel's reader: a call (any grade) by the channel's own author, or None.

    Futures: Broncx's channel is about BTC unless he names ETH or SOL, and his position boxes in the
    chart images count as a call. Gold: XAU unless the post is only about silver (XAG); other words
    the generic reader takes for a ticker are dropped. Spot: bucket, account size and DCA step are kept.
    """
    if _author_key(message.author_name) not in profile.authors or _RESULT_POST.search(message.content):
        return None
    call = extract_call(message, reference_price=reference_price)
    if profile.key == "spot_goatfather" and call is not None:
        tags = {tag.upper() for tag in _CASHTAG.findall(message.content)}
        if len(tags) == 1 and call.guidance.symbol not in tags:
            call = _regrade(replace(call, guidance=replace(call.guidance, symbol=tags.pop())))
    if profile.key == "futures_broncx":
        if call is not None and call.guidance.symbol not in _MAJORS:
            call = _regrade(replace(call, guidance=replace(call.guidance, symbol=profile.default_symbol)))
        call = _with_chart(message, call, profile)
    elif profile.key == "gold_eydu" and call is not None:
        silver, gold = bool(_SILVER.search(message.content)), bool(_GOLD.search(message.content))
        symbol = "XAG" if silver and not gold else "XAU"
        if symbol != call.guidance.symbol:
            call = _regrade(replace(call, guidance=replace(call.guidance, symbol=symbol)))
    if call is None:
        return None
    extras = _spot_extras(message.content) if profile.key == "spot_goatfather" else {}
    return TrackedCall(profile.key, call, extras)


def read_calls(messages: Iterable[GoatHubMessage]) -> dict[str, list[TrackedCall]]:
    """Calls per profile, oldest first. Messages from other channels are ignored."""
    result: dict[str, list[TrackedCall]] = {key: [] for key in PROFILES}
    for message in sorted(messages, key=lambda item: item.posted_at):
        profile = profile_for(message)
        if profile is None:
            continue
        tracked = read_call(message, profile)
        if tracked is not None:
            result[profile.key].append(tracked)
    return result


# --------------------------------------------------------------------------- outcome check

@dataclass(frozen=True, slots=True)
class PriceBar:
    open_time: datetime
    open: Decimal
    high: Decimal
    low: Decimal
    close: Decimal


def load_bars_csv(path: Path) -> list[PriceBar]:
    """Bars from a CSV with open_time (ISO 8601 with zone, or epoch milliseconds), open, high, low, close."""
    bars: list[PriceBar] = []
    with path.open(encoding="utf-8", newline="") as handle:
        for row in csv.DictReader(handle):
            raw = row["open_time"].strip()
            when = datetime.fromtimestamp(int(raw) / 1000, tz=timezone.utc) if raw.isdigit() else datetime.fromisoformat(raw)
            if when.tzinfo is None:
                raise ValueError(f"{path}: open_time {raw!r} has no time zone")
            bars.append(PriceBar(when.astimezone(timezone.utc), *(Decimal(row[key]) for key in ("open", "high", "low", "close"))))
    return sorted(bars, key=lambda bar: bar.open_time)


@dataclass(frozen=True, slots=True)
class CallOutcome:
    tracked: TrackedCall
    status: str
    entry: Decimal | None = None
    target: Decimal | None = None
    stop: Decimal | None = None
    resolved_at: datetime | None = None
    last_price: Decimal | None = None
    note: str = ""

    @property
    def complete(self) -> bool:
        """Both a target and a stop on the right side of the entry: only these count for the hit rate."""
        return self.target is not None and self.stop is not None

    def distance_pct(self, price: Decimal | None = None) -> float | None:
        """How far the latest price is from the entry, in percent of the entry."""
        price = price if price is not None else self.last_price
        if self.entry is None or price is None or self.entry == 0:
            return None
        return float(round((price - self.entry) / self.entry * 100, 2))

    def to_dict(self) -> dict[str, Any]:
        message = self.tracked.call.message
        return {
            "profile": self.tracked.profile,
            "message_id": message.message_id,
            "channel": message.channel_name or message.channel_id,
            "author": message.author_label,
            "posted_at": message.posted_at.isoformat(),
            "symbol": self.tracked.symbol,
            "bias": self.tracked.bias,
            "grade": self.tracked.call.grade,
            "status": self.status,
            "complete": self.complete,
            "entry": None if self.entry is None else str(self.entry),
            "target": None if self.target is None else str(self.target),
            "stop": None if self.stop is None else str(self.stop),
            "resolved_at": None if self.resolved_at is None else self.resolved_at.isoformat(),
            "last_price": None if self.last_price is None else str(self.last_price),
            "distance_pct": self.distance_pct(),
            "extras": dict(self.tracked.extras),
            "note": self.note,
            "text": message.content,
        }


def _pick(values: Sequence[Decimal], entry: Decimal, *, above: bool) -> Decimal | None:
    side = [value for value in values if (value > entry if above else value < entry)]
    if not side:
        return None
    return min(side) if above else max(side)


def check_outcome(tracked: TrackedCall, bars: Sequence[PriceBar], *, observed_at: datetime, horizon: timedelta | None = None) -> CallOutcome:
    """Status of one call from the bars that opened at or after the minute it was posted.

    Entry is the open of the first such bar. A target must lie on the profit side of the entry and
    a stop on the loss side, otherwise it is ignored (the reader can mistake a level for a target).
    If one bar touches both, the call counts as stopped: the bar does not say which came first.
    """
    horizon = horizon if horizon is not None else PROFILES[tracked.profile].horizon
    message = tracked.call.message
    if tracked.bias not in ("LONG", "SHORT"):
        return CallOutcome(tracked, STATUS_NOT_CHECKABLE, note="no direction")
    posted_minute = message.posted_at.replace(second=0, microsecond=0)
    after = [bar for bar in bars if posted_minute <= bar.open_time <= observed_at]
    if not after:
        return CallOutcome(tracked, STATUS_NO_PRICES, note="no prices after the post")
    entry = after[0].open
    # Shorthand levels ("65k", "0.25") are scaled with the entry as reference, as for TIM's own reports.
    rescaled = read_call(message, PROFILES[tracked.profile], reference_price=entry)
    guidance = (rescaled or tracked).call.guidance
    levels = [level for level in guidance.levels if not level.ambiguous]
    long = tracked.bias == "LONG"
    targets = [level.value for level in levels if level.role == "TARGET"]
    stops = [level.value for level in levels if level.role == "STOP"]
    target = _pick(targets, entry, above=long)
    stop = _pick(stops, entry, above=not long)
    if target is None and stop is None:
        return CallOutcome(tracked, STATUS_NOT_CHECKABLE, entry=entry, last_price=after[-1].close, note="neither target nor stop")
    deadline = message.posted_at + horizon
    for bar in after:
        if bar.open_time > deadline:
            return CallOutcome(tracked, STATUS_EXPIRED, entry, target, stop, resolved_at=deadline, last_price=after[-1].close)
        hit_stop = stop is not None and (bar.low <= stop if long else bar.high >= stop)
        hit_target = target is not None and (bar.high >= target if long else bar.low <= target)
        if hit_stop:
            note = "target and stop in the same bar, counted as stopped" if hit_target else ""
            return CallOutcome(tracked, STATUS_STOPPED, entry, target, stop, resolved_at=bar.open_time, last_price=after[-1].close, note=note)
        if hit_target:
            return CallOutcome(tracked, STATUS_TARGET, entry, target, stop, resolved_at=bar.open_time, last_price=after[-1].close)
    status = STATUS_EXPIRED if observed_at > deadline else STATUS_OPEN
    return CallOutcome(tracked, status, entry, target, stop, resolved_at=deadline if status == STATUS_EXPIRED else None, last_price=after[-1].close)


def evaluate(calls: dict[str, list[TrackedCall]], bars_by_symbol: dict[str, Sequence[PriceBar]], *, observed_at: datetime) -> dict[str, list[CallOutcome]]:
    """Outcome per call. A symbol without bars gets ``no_price_data`` (e.g. gold until TIM has a gold feed)."""
    result: dict[str, list[CallOutcome]] = {}
    for key, tracked_calls in calls.items():
        outcomes = []
        for tracked in tracked_calls:
            if tracked.call.message.posted_at > observed_at:
                continue
            bars = bars_by_symbol.get(tracked.symbol or "", ())
            if not bars and tracked.bias in ("LONG", "SHORT"):
                outcomes.append(CallOutcome(tracked, STATUS_NO_PRICES, note=f"no price feed for {tracked.symbol or 'unknown symbol'}"))
            else:
                outcomes.append(check_outcome(tracked, bars, observed_at=observed_at))
        result[key] = outcomes
    return result


def scorecard(outcomes: Sequence[CallOutcome], last: int | None = 30) -> dict[str, Any]:
    """Counts per status over the last ``last`` checkable calls.

    The hit rate (targets / (targets + stops)) only uses calls that name both a target and a stop:
    a call with only a stop can never reach a target and one with only a target can never be
    stopped, so counting them would push the rate down or up for no reason.
    """
    checkable = [item for item in outcomes if item.status in (STATUS_OPEN, STATUS_TARGET, STATUS_STOPPED, STATUS_EXPIRED)]
    window = checkable[-last:] if last else checkable
    counts = {status: sum(1 for item in window if item.status == status) for status in (STATUS_TARGET, STATUS_STOPPED, STATUS_OPEN, STATUS_EXPIRED)}
    complete = [item for item in window if item.complete]
    targets = sum(1 for item in complete if item.status == STATUS_TARGET)
    decided = targets + sum(1 for item in complete if item.status == STATUS_STOPPED)
    return {
        "calls": len(window),
        **counts,
        "with_target_and_stop": len(complete),
        "hit_rate": None if decided == 0 else round(targets / decided, 3),
        "hit_rate_basis": decided,
        "not_checkable": sum(1 for item in outcomes if item.status == STATUS_NOT_CHECKABLE),
        "no_price_data": sum(1 for item in outcomes if item.status == STATUS_NO_PRICES),
        "rule": "hypotheses only: a scorecard describes past calls, it is no signal and no advice",
    }


# --------------------------------------------------------------------------- board

_STATUS_LABEL = {
    STATUS_OPEN: "open",
    STATUS_TARGET: "target hit",
    STATUS_STOPPED: "stopped",
    STATUS_EXPIRED: "expired",
    STATUS_NOT_CHECKABLE: "not checkable",
    STATUS_NO_PRICES: "no price data",
}


def _fmt(value: Decimal | None) -> str:
    if value is None:
        return "-"
    return f"{value.normalize():f}" if value < 1000 else f"{value:,.0f}"


def _board_line(outcome: CallOutcome) -> str:
    message = outcome.tracked.call.message
    when = message.posted_at.astimezone(BERLIN).strftime("%d.%m. %H:%M")
    parts = [f"{outcome.tracked.bias.lower()} {outcome.tracked.symbol or '?'}"]
    if outcome.target is not None:
        parts.append(f"target {_fmt(outcome.target)}")
    if outcome.stop is not None:
        parts.append(f"stop {_fmt(outcome.stop)}")
    distance = outcome.distance_pct()
    status = _STATUS_LABEL[outcome.status] + (f", {distance:+.1f}% from entry" if distance is not None and outcome.status == STATUS_OPEN else "")
    return f"- {when} {message.author_label}: {', '.join(parts)} ({status})"


def render_board(outcomes: dict[str, list[CallOutcome]], *, generated_at: datetime, open_limit: int = 4, limit_chars: int = BOARD_LIMIT_CHARS) -> str:
    """Board text for one Discord message: open calls and scorecard per channel. Preview only, never posted here."""
    lines = [f"**TIM × GoatHub board** (paper only, not advice) · {generated_at.astimezone(BERLIN).strftime('%d.%m. %H:%M')} Berlin"]
    for key, profile in PROFILES.items():
        items = outcomes.get(key, [])
        card = scorecard(items)
        rate = "n/a" if card["hit_rate"] is None else f"{card['hit_rate'] * 100:.0f}% of {card['hit_rate_basis']}"
        lines.append("")
        lines.append(f"__{profile.title}__ · last {card['calls']}: {card[STATUS_TARGET]} targets, {card[STATUS_STOPPED]} stops, "
                     f"{card[STATUS_OPEN]} open, {card[STATUS_EXPIRED]} expired · hit rate (target and stop given) {rate}")
        open_calls = [item for item in items if item.status == STATUS_OPEN][-open_limit:]
        recent = open_calls or [item for item in items if item.status in (STATUS_TARGET, STATUS_STOPPED)][-2:]
        if card["no_price_data"]:
            lines.append(f"- {card['no_price_data']} calls without price data")
        lines.extend(_board_line(item) for item in reversed(recent))
    text = "\n".join(lines)
    while len(text) > limit_chars and len(lines) > 1:
        lines.pop()
        text = "\n".join(lines + ["…"])
    return text

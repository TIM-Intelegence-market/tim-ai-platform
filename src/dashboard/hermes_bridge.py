"""Hermes-Agent (TIM-KI) für das Control Center: Status lesen, eine Frage stellen, Verlauf führen.

Hermes (Nous Research) läuft auf dem Mac mit DeepSeek und liest TIM nur über die MCP-Server tim-ops und
tim-graph. Dieses Modul startet pro Frage ``hermes chat --query-file - -Q`` (Frage über stdin, nichts wird von
der Shell interpretiert) und hebt die letzten Antworten in einer JSON-Datei auf. Es liest Schlüssel nie aus,
nur ob einer hinterlegt ist. Es handelt nicht und ändert nichts an Hermes.
"""
from __future__ import annotations

import json
import os
import re
import secrets
import shutil
import subprocess
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

DEFAULT_LOG = Path("data/hermes/chat_log.json")
SCHEMA = "tim_hermes_chat/1"
MAX_QUESTION = 500
MAX_ANSWER = 4000
TIMEOUT_SECONDS = 90
KEEP = 20
_ANSI = re.compile(r"\x1b\[[0-9;?]*[A-Za-z]")
_LOCK = threading.Lock()


class QuestionError(ValueError):
    """Die Frage ist leer, zu lang oder enthält Steuerzeichen."""


def hermes_home() -> Path:
    return Path(os.environ.get("TIM_HERMES_HOME") or Path.home() / ".hermes")


def hermes_binary() -> str | None:
    """Pfad der Hermes-CLI oder None, wenn sie nicht installiert ist."""
    explicit = os.environ.get("TIM_HERMES_BIN")
    if explicit:
        return explicit if Path(explicit).is_file() else None
    found = shutil.which("hermes")
    if found:
        return found
    local = Path.home() / ".local" / "bin" / "hermes"
    return str(local) if local.is_file() else None


def _model_block(text: str) -> dict[str, str]:
    """``provider`` und ``model`` aus dem obersten ``model:``-Block der config.yaml (ohne YAML-Abhängigkeit)."""
    out: dict[str, str] = {}
    lines = text.splitlines()
    for index, line in enumerate(lines):
        if re.match(r"^model:\s*(#.*)?$", line):
            for inner in lines[index + 1:]:
                if inner.strip() and not inner.startswith((" ", "\t")):
                    break
                match = re.match(r"^\s+(provider|model):\s*[\"']?([^\"'#]+?)[\"']?\s*(#.*)?$", inner)
                if match and match.group(1) not in out:
                    out[match.group(1)] = match.group(2).strip()
            break
    return out


def _mcp_servers(text: str) -> list[str]:
    names: list[str] = []
    lines = text.splitlines()
    for index, line in enumerate(lines):
        if re.match(r"^mcp_servers:\s*$", line):
            for inner in lines[index + 1:]:
                if inner.strip() and not inner.startswith((" ", "\t")):
                    break
                match = re.match(r"^  ([A-Za-z0-9_-]+):\s*$", inner)
                if match:
                    names.append(match.group(1))
            break
    return names


def _key_present(env_path: Path, name: str = "DEEPSEEK_API_KEY") -> bool:
    """Nur ob ``name`` in der .env mit Wert steht; der Wert wird nicht gelesen oder zurückgegeben."""
    try:
        for line in env_path.read_text(encoding="utf-8", errors="replace").splitlines():
            key, sep, value = line.strip().partition("=")
            if sep and key.strip() == name and value.strip().strip("\"'"):
                return True
    except OSError:
        return False
    return False


def load_log(path: Path | None = None) -> list[dict[str, Any]]:
    target = Path(path or DEFAULT_LOG)
    if not target.is_file():
        return []
    try:
        data = json.loads(target.read_text(encoding="utf-8"))
    except ValueError:
        return []
    entries = data.get("entries") if isinstance(data, dict) else None
    return [e for e in entries or [] if isinstance(e, dict)]


def _save_log(entries: list[dict[str, Any]], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps({"schema": SCHEMA, "entries": entries[-KEEP:]}, ensure_ascii=False, indent=1), encoding="utf-8")
    os.replace(tmp, path)


def status(log_path: Path | None = None, now: datetime | None = None) -> dict[str, Any]:
    """Installiert, Provider/Modell, Schlüssel hinterlegt, MCP-Server, letzte Antwort. Nie ein Schlüsselwert."""
    now = now or datetime.now(timezone.utc)
    home = hermes_home()
    binary = hermes_binary()
    config_text = ""
    try:
        config_text = (home / "config.yaml").read_text(encoding="utf-8", errors="replace")
    except OSError:
        pass
    model = _model_block(config_text)
    log = load_log(log_path)
    last = log[-1] if log else None
    today = now.date().isoformat()
    return {
        "installed": binary is not None, "binary": binary, "home": str(home), "configured": bool(config_text),
        "provider": model.get("provider"), "model": model.get("model"),
        "key_present": _key_present(home / ".env"), "mcp_servers": _mcp_servers(config_text),
        "last": last, "asked_today": sum(1 for e in log if str(e.get("at", "")).startswith(today)),
        "read_only": True, "checked_at": now.isoformat(),
    }


def clean_question(question: Any, limit: int = MAX_QUESTION) -> str:
    text = str(question or "").replace("\r\n", "\n").strip()
    if not text:
        raise QuestionError("Bitte eine Frage eingeben.")
    if len(text) > limit:
        raise QuestionError(f"Die Frage ist zu lang ({len(text)} Zeichen, höchstens {limit}).")
    if any(ord(ch) < 32 and ch not in "\n\t" for ch in text):
        raise QuestionError("Die Frage enthält Steuerzeichen.")
    return text


def ask(question: Any, log_path: Path | None = None, binary: str | None = None, timeout: int = TIMEOUT_SECONDS,
        now: datetime | None = None, limit: int = MAX_QUESTION, record: bool = True) -> dict[str, Any]:
    """Eine Frage an Hermes; die Antwort (oder der Fehler) landet als Eintrag im Verlauf und wird zurückgegeben.

    ``record=False`` und ein größeres ``limit`` sind für TIMs eigene Aufträge (Zweitmeinung, Tagesbericht): die
    stehen in ihren eigenen Dateien und nicht im Frageverlauf der Seite.
    """
    text = clean_question(question, limit)
    now = now or datetime.now(timezone.utc)
    path = Path(log_path or DEFAULT_LOG)
    binary = binary or hermes_binary()
    entry: dict[str, Any] = {"id": secrets.token_hex(4), "at": now.isoformat(), "question": text, "answer": "", "ok": False,
                             "seconds": None, "error": None}
    if binary is None:
        entry["error"] = "Hermes ist auf diesem Rechner nicht installiert."
    else:
        started = datetime.now(timezone.utc)
        try:
            with _LOCK:  # eine Frage nach der anderen; Hermes teilt sich die MCP-Server mit sich selbst
                run = subprocess.run([binary, "chat", "--query-file", "-", "-Q", "--run-budget", str(timeout)],
                                     input=text, capture_output=True, text=True, timeout=timeout + 15, check=False,
                                     env={**os.environ, "NO_COLOR": "1", "TERM": "dumb"})
            answer = _ANSI.sub("", run.stdout or "").strip()
            if run.returncode == 0 and answer:
                entry.update(ok=True, answer=answer[:MAX_ANSWER])
            else:
                detail = _ANSI.sub("", (run.stderr or "").strip())[-300:] or f"Exit-Code {run.returncode}"
                entry["error"] = f"Hermes hat nicht geantwortet: {detail}"
        except subprocess.TimeoutExpired:
            entry["error"] = f"Keine Antwort innerhalb von {timeout} s."
        except OSError as exc:
            entry["error"] = f"Hermes ließ sich nicht starten: {exc}"
        entry["seconds"] = round((datetime.now(timezone.utc) - started).total_seconds(), 1)
    if not record:
        return entry
    with _LOCK:
        entries = load_log(path)
        entries.append(entry)
        _save_log(entries, path)
    return entry

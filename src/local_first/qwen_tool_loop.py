"""A small, read-only tool loop for local Qwen before it proposes a patch.

Qwen gets six tools through Ollama's ``/api/chat`` tool calling: list a folder, read a file,
search the code, run the task's required tests, check a draft patch and submit it. None of
them writes to the repository or accepts a shell command. Reading is limited to ``src/``,
``tests/`` and ``docs/``; test runs go through the sandboxed ``SafePatchExecutor`` runner.
The submitted patch still faces every gate in ``run_local_qwen_developer.py``.

Ollama's Qwen 3.5 tool-call parser is not reliable yet (ollama#14493), so calls that arrive
as text (``<tool_call>{...}</tool_call>`` or ``<function=name><parameter=k>v</parameter>``)
are parsed here too. Every run records how many calls were native, parsed or invalid.
"""

from __future__ import annotations

import json
import re
import time
from dataclasses import dataclass, field
from pathlib import Path, PurePosixPath
from typing import Any, Callable, Protocol

from src.local_first.patch_executor import FORBIDDEN_PATH_PARTS, redact_tokens

READ_ROOTS = ("src", "tests", "docs")
TEXT_SUFFIXES = {".py", ".md", ".txt", ".json", ".toml", ".ini", ".cfg", ".yml", ".yaml"}
MAX_STEPS = 12
MAX_SECONDS = 600.0  # leaves room for helpers inside the 30-minute task timeout
# One turn on a 16 GB Mac takes about 60 s and grows with every file read; the developer's default
# 120 s client timeout cut a real run (issue #172) mid-loop. A turn may use the rest of the budget.
CHAT_TURN_SECONDS = 300.0
MAX_CALLS_PER_STEP = 3
MAX_NUDGES = 2
MAX_TEST_RUNS = 2
MAX_TOOL_OUTPUT_CHARS = 6_000
MAX_TOTAL_TOOL_CHARS = 60_000
MAX_READ_LINES = 300
MAX_FILE_BYTES = 400_000
MAX_SEARCH_HITS = 40
MAX_LIST_ENTRIES = 200
MAX_PARSE_CHARS = 40_000  # bounds the text-call regexes on runaway model output
CHAT_OPTIONS = {"temperature": 0.2, "num_ctx": 32768, "num_predict": 8192}
SECRET_RE = re.compile(r"(?i)(api[_-]?key|token|password|secret|authorization)\s*[:=]\s*[^\s,;]+")
SENSITIVE_NAME = re.compile(r"(?i)(secret|credential|private|\.env|token|password|keychain)")
TOOL_CALL_TAG = re.compile(r"<tool_call>\s*(\{.*?\})\s*</tool_call>", re.DOTALL)
FUNCTION_TAG = re.compile(r"<function=([A-Za-z_][A-Za-z0-9_]*)>(.*?)</function>", re.DOTALL)
PARAMETER_TAG = re.compile(r"<parameter=([A-Za-z_][A-Za-z0-9_]*)>\s*(.*?)\s*</parameter>", re.DOTALL)

_PATCH_ITEMS = {
    "type": "array",
    "description": "Patches. Existing file: {path, edits:[{search, replace}]}. New file: {path, content}.",
    "items": {
        "type": "object",
        "properties": {
            "path": {"type": "string"},
            "content": {"type": "string"},
            "edits": {"type": "array", "items": {"type": "object", "properties": {
                "search": {"type": "string"}, "replace": {"type": "string"}}, "required": ["search", "replace"]}},
        },
        "required": ["path"],
    },
}


def _tool(name: str, description: str, properties: dict[str, Any], required: list[str]) -> dict[str, Any]:
    return {"type": "function", "function": {"name": name, "description": description, "parameters": {
        "type": "object", "properties": properties, "required": required}}}


TOOLS = [
    _tool("list_dir", "List files and folders under src/, tests/ or docs/.",
          {"path": {"type": "string", "description": "Folder, e.g. src/local_first"}}, ["path"]),
    _tool("read_file", "Read a text file under src/, tests/ or docs/ with line numbers.",
          {"path": {"type": "string"}, "start_line": {"type": "integer"}, "end_line": {"type": "integer"}},
          ["path"]),
    _tool("search_code", "Find an exact text (case-sensitive) in files under src/, tests/ or docs/.",
          {"text": {"type": "string", "description": "Exact text, e.g. def build_task"},
           "path": {"type": "string", "description": "Folder to search, default src"}}, ["text"]),
    _tool("run_required_tests", "Run the task's required tests on the current, unchanged code.", {}, []),
    _tool("check_patch", "Validate a draft patch without writing it. Returns OK or the problem.",
          {"patches": _PATCH_ITEMS}, ["patches"]),
    _tool("submit_patch", "Submit the final patch. Ends your turn. Call check_patch first.",
          {"patches": _PATCH_ITEMS}, ["patches"]),
]
TOOL_NAMES = {item["function"]["name"] for item in TOOLS}


class ChatClient(Protocol):
    async def chat(self, messages: list[dict[str, Any]], *, tools: list[dict[str, Any]] | None = None,
                   options: dict[str, Any] | None = None, timeout: float | None = None) -> dict[str, Any]: ...


@dataclass(slots=True)
class LoopResult:
    proposal: dict[str, Any] | None
    stats: dict[str, Any] = field(default_factory=dict)


def _clean(text: str) -> str:
    return redact_tokens(SECRET_RE.sub(r"\1=<REDACTED>", text))


def _coerce(value: str) -> Any:
    try:
        return json.loads(value)
    except (json.JSONDecodeError, ValueError):
        return value


def parse_text_tool_calls(content: str) -> list[tuple[str, dict[str, Any]]]:
    """Recover tool calls a model printed as text instead of emitting natively."""
    content = (content or "")[:MAX_PARSE_CHARS]
    calls: list[tuple[str, dict[str, Any]]] = []
    for raw in TOOL_CALL_TAG.findall(content):
        value = _coerce(raw)
        if isinstance(value, dict) and isinstance(value.get("name"), str):
            args = value.get("arguments", value.get("parameters", {}))
            args = _coerce(args) if isinstance(args, str) else args
            calls.append((value["name"], args if isinstance(args, dict) else {}))
    for name, body in FUNCTION_TAG.findall(content):
        calls.append((name, {key: _coerce(value) for key, value in PARAMETER_TAG.findall(body)}))
    if calls:
        return calls
    stripped = content.strip()
    if stripped.startswith("```"):
        stripped = stripped.strip("`").removeprefix("json").strip()
    value = _coerce(stripped) if stripped.startswith("{") else None
    if isinstance(value, dict):
        if isinstance(value.get("patches"), list):
            return [("submit_patch", {"patches": value["patches"]})]
        if isinstance(value.get("name"), str) and isinstance(value.get("arguments"), dict):
            return [(value["name"], value["arguments"])]
    return []


def _native_calls(message: dict[str, Any]) -> list[tuple[str, dict[str, Any]]] | None:
    raw = message.get("tool_calls")
    if not isinstance(raw, list) or not raw:
        return None
    calls: list[tuple[str, dict[str, Any]]] = []
    for item in raw:
        function = item.get("function") if isinstance(item, dict) else None
        if not isinstance(function, dict) or not isinstance(function.get("name"), str):
            calls.append(("", {}))
            continue
        args = function.get("arguments", {})
        args = _coerce(args) if isinstance(args, str) else args
        calls.append((function["name"], args if isinstance(args, dict) else {}))
    return calls


class RepoReader:
    """Read-only, bounded view of src/, tests/ and docs/."""

    def __init__(self, repo_root: Path) -> None:
        self.root = repo_root.resolve()

    def resolve(self, relative: Any, *, want_dir: bool = False) -> Path:
        if not isinstance(relative, str) or not relative.strip() or "\\" in relative or "\0" in relative:
            raise ValueError("path must be a relative POSIX path")
        rel = PurePosixPath(relative.strip().strip("/"))
        if rel.is_absolute() or ".." in rel.parts or not rel.parts or rel.parts[0] not in READ_ROOTS:
            raise ValueError("path must be under src/, tests/ or docs/")
        if any(part.lower() in FORBIDDEN_PATH_PARTS or SENSITIVE_NAME.search(part) or part.startswith(".")
               for part in rel.parts):
            raise ValueError("path is not readable for the worker")
        path = self.root / rel
        # Resolve every component: a symlinked folder must not lead into .tim, .git or elsewhere.
        resolved = path.resolve()
        read_root = (self.root / rel.parts[0]).resolve()
        if (path.is_symlink() or (self.root / rel.parts[0]).is_symlink()
                or (resolved != read_root and read_root not in resolved.parents)
                or resolved.relative_to(self.root).parts != rel.parts):
            raise ValueError("path leaves the readable folders")
        if want_dir and not path.is_dir():
            raise ValueError("folder not found")
        if not want_dir and not path.is_file():
            raise ValueError("file not found")
        return path

    def list_dir(self, path: Any) -> str:
        folder = self.resolve(path, want_dir=True)
        entries = []
        for child in sorted(folder.iterdir(), key=lambda item: item.name):
            if child.name.startswith(".") or child.name == "__pycache__" or child.is_symlink():
                continue
            if SENSITIVE_NAME.search(child.name) or child.name.lower() in FORBIDDEN_PATH_PARTS:
                continue
            entries.append(child.name + ("/" if child.is_dir() else ""))
            if len(entries) >= MAX_LIST_ENTRIES:
                entries.append("... (truncated)")
                break
        return "\n".join(entries) or "(empty)"

    def read_file(self, path: Any, start_line: Any = 1, end_line: Any = None) -> str:
        file = self.resolve(path)
        if file.suffix not in TEXT_SUFFIXES or file.stat().st_size > MAX_FILE_BYTES:
            raise ValueError("only text files up to 400 KB can be read")
        lines = file.read_text(encoding="utf-8", errors="replace").splitlines()
        start = max(1, int(start_line or 1))
        end = min(len(lines), int(end_line) if end_line else start + MAX_READ_LINES - 1,
                  start + MAX_READ_LINES - 1)
        body = "\n".join(f"{number}: {lines[number - 1]}" for number in range(start, end + 1))
        more = f"\n... file has {len(lines)} lines; ask for start_line={end + 1}" if end < len(lines) else ""
        return f"{path} lines {start}-{end}\n{body}{more}"

    def search(self, text: Any, path: Any = "src") -> str:
        if not isinstance(text, str) or not 2 <= len(text) <= 200:
            raise ValueError("search text must have 2-200 characters")
        folder = self.resolve(path or "src", want_dir=True)
        hits: list[str] = []
        for file in sorted(folder.rglob("*")):
            if (not file.is_file() or file.is_symlink() or file.suffix not in TEXT_SUFFIXES
                    or "__pycache__" in file.parts or file.stat().st_size > MAX_FILE_BYTES):
                continue
            relative = file.relative_to(self.root)
            if any(part.startswith(".") or SENSITIVE_NAME.search(part) or part.lower() in FORBIDDEN_PATH_PARTS
                   for part in relative.parts):
                continue
            try:
                lines = file.read_text(encoding="utf-8", errors="replace").splitlines()
            except OSError:
                continue
            for number, line in enumerate(lines, start=1):
                if text in line:
                    hits.append(f"{relative.as_posix()}:{number}: {line.strip()[:200]}")
                    if len(hits) >= MAX_SEARCH_HITS:
                        return "\n".join(hits) + "\n... (more hits; narrow the folder)"
        return "\n".join(hits) or "no matches"


class QwenToolLoop:
    def __init__(self, client: ChatClient, repo_root: Path, *,
                 check_patch: Callable[[list[Any]], None],
                 run_tests: Callable[[], dict[str, Any]],
                 max_steps: int = MAX_STEPS, max_seconds: float = MAX_SECONDS,
                 clock: Callable[[], float] = time.monotonic) -> None:
        self.client = client
        self.reader = RepoReader(repo_root)
        self.check_patch = check_patch
        self.run_tests = run_tests
        self.max_steps = max_steps
        self.max_seconds = max_seconds
        self.clock = clock
        self.test_runs = 0
        self.output_chars = 0
        self.stats: dict[str, Any] = {
            "steps": 0, "native_calls": 0, "text_parsed_calls": 0, "invalid_calls": 0,
            "nudges": 0, "calls_by_tool": {}, "submitted": False, "ended": "budget_exhausted",
        }

    def _execute(self, name: str, args: dict[str, Any]) -> str:
        if name == "list_dir":
            return self.reader.list_dir(args.get("path"))
        if name == "read_file":
            return self.reader.read_file(args.get("path"), args.get("start_line", 1), args.get("end_line"))
        if name == "search_code":
            return self.reader.search(args.get("text"), args.get("path", "src"))
        if name == "run_required_tests":
            if self.test_runs >= MAX_TEST_RUNS:
                return "test budget used up; submit your patch"
            self.test_runs += 1
            result = self.run_tests()
            output = (str(result.get("stdout", ""))[-3000:] + "\n" + str(result.get("stderr", ""))[-1500:]).strip()
            return f"returncode={result.get('returncode')}\n{output}"
        if name == "check_patch":
            self.check_patch(args.get("patches"))
            return "OK: the patch is valid. Call submit_patch with exactly this patch."
        raise ValueError(f"unknown tool {name!r}; use one of {sorted(TOOL_NAMES)}")

    def _result(self, name: str, args: dict[str, Any]) -> str:
        if self.output_chars >= MAX_TOTAL_TOOL_CHARS and name not in {"check_patch", "submit_patch"}:
            return "reading budget used up; check and submit your patch now"
        try:
            text = self._execute(name, args)
        except Exception as exc:  # every tool error goes back to the model as text
            text = f"ERROR: {str(exc)[:500]}"
        text = _clean(text)[:MAX_TOOL_OUTPUT_CHARS]
        self.output_chars += len(text)
        return text

    async def run(self, system_prompt: str, user_prompt: str) -> LoopResult:
        messages: list[dict[str, Any]] = [{"role": "system", "content": system_prompt},
                                          {"role": "user", "content": user_prompt}]
        last_submitted: dict[str, Any] | None = None
        deadline = self.clock() + self.max_seconds
        for _ in range(self.max_steps):
            remaining = deadline - self.clock()
            if remaining <= 0:
                self.stats["ended"] = "time_budget_exhausted"
                break
            self.stats["steps"] += 1
            try:
                turn_seconds = max(1.0, min(CHAT_TURN_SECONDS, remaining))
                message = await self.client.chat(messages, tools=TOOLS, options=dict(CHAT_OPTIONS),
                                                 timeout=turn_seconds)
            except Exception as exc:  # tools unsupported or Ollama error: caller falls back to one-shot
                self.stats["ended"] = f"chat_error:{type(exc).__name__}"
                return LoopResult(None, self.stats)
            calls = _native_calls(message)
            if calls is not None:
                self.stats["native_calls"] += len(calls)
            else:
                calls = parse_text_tool_calls(str(message.get("content", "")))
                self.stats["text_parsed_calls"] += len(calls)
            assistant = {"role": "assistant", "content": str(message.get("content", ""))[:4000]}
            if message.get("tool_calls"):
                assistant["tool_calls"] = message["tool_calls"]
            messages.append(assistant)
            if not calls:
                if self.stats["nudges"] >= MAX_NUDGES:
                    self.stats["ended"] = "no_tool_calls"
                    break
                self.stats["nudges"] += 1
                messages.append({"role": "user", "content":
                                 "Use a tool. When your patch is ready, call check_patch and then submit_patch."})
                continue
            for name, args in calls[:MAX_CALLS_PER_STEP]:
                counts = self.stats["calls_by_tool"]
                counts[name or "?"] = counts.get(name or "?", 0) + 1
                if name not in TOOL_NAMES:
                    self.stats["invalid_calls"] += 1
                if name == "submit_patch":
                    last_submitted = {"patches": args.get("patches")}
                    try:
                        self.check_patch(args.get("patches"))
                    except Exception as exc:
                        messages.append({"role": "tool", "tool_name": name,
                                         "content": _clean(f"REJECTED: {str(exc)[:500]}. Fix it and submit again.")})
                        continue
                    self.stats["submitted"] = True
                    self.stats["ended"] = "submitted"
                    return LoopResult(last_submitted, self.stats)
                messages.append({"role": "tool", "tool_name": name or "unknown", "content": self._result(name, args)})
        # Out of steps: hand back the last submission so the normal gates can explain what is wrong.
        return LoopResult(last_submitted, self.stats)

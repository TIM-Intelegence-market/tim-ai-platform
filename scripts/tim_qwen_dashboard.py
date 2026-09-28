#!/usr/bin/env python3
"""Local-only control surface for the existing TIM Qwen self-repair worker.

This module deliberately does not implement a second worker.  It observes and
submits explicitly approved, sandboxed developer tasks to the established
``tim-local-qwen`` workflow.
"""
from __future__ import annotations

import argparse
import html
import json
import os
import re
import signal
import subprocess
import sys
import time
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.error import URLError
from urllib.request import Request, urlopen


DEFAULT_QWEN_REPO = Path("/Users/tim/Documents/TIM/tim-local-qwen")
DEFAULT_OLLAMA_URL = "http://127.0.0.1:11434"
LAUNCH_AGENT = "com.tim.local-qwen-worker"
TASK_ID = re.compile(r"[A-Za-z0-9_-]{1,120}\Z")
SECRET = re.compile(r"(?i)(api[_-]?key|token|password|secret|authorization)\s*[:=]\s*[^\s,;]+")


def _read_json(path: Path) -> dict:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
        return value if isinstance(value, dict) else {}
    except (OSError, ValueError):
        return {}


def _pid(lock: Path) -> int | None:
    try:
        value = lock.read_text(encoding="utf-8").strip().split("=", 1)[1]
        return int(value)
    except (OSError, IndexError, ValueError):
        return None


def _alive(pid: int | None) -> bool:
    if pid is None:
        return False
    try:
        os.kill(pid, 0)
    except OSError:
        return False
    return True


def _git(repo: Path, *args: str) -> str:
    try:
        completed = subprocess.run(["git", *args], cwd=repo, text=True, capture_output=True,
                                   timeout=5, check=False)
        return completed.stdout.strip() if completed.returncode == 0 else "UNAVAILABLE"
    except OSError:
        return "UNAVAILABLE"


def _ollama(url: str) -> dict:
    try:
        with urlopen(url.rstrip("/") + "/api/tags", timeout=3) as response:
            payload = json.loads(response.read())
        models = [str(item.get("name")) for item in payload.get("models", []) if isinstance(item, dict)]
        return {"reachable": True, "models": models}
    except (URLError, OSError, ValueError, TimeoutError):
        return {"reachable": False, "models": []}


def _latest(directory: Path) -> dict:
    try:
        files = [path for path in directory.glob("*.json") if path.is_file()]
        return _read_json(max(files, key=lambda path: path.stat().st_mtime_ns)) if files else {}
    except OSError:
        return {}


def _log_tail(path: Path) -> dict:
    """Expose only a small, redacted local diagnostic tail."""
    try:
        lines = path.read_text(encoding="utf-8", errors="replace").splitlines()[-20:]
        return {"path": str(path), "available": True,
                "tail": [SECRET.sub(r"\1=<REDACTED>", line)[:500] for line in lines]}
    except OSError:
        return {"path": str(path), "available": False, "tail": []}


def snapshot(repo: Path, qwen_repo: Path, ollama_url: str, model: str = "qwen2.5-coder:7b") -> dict:
    """Collect bounded, read-only state for humans and the local dashboard."""
    state = qwen_repo / ".tim/local-first"
    developer_inbox = state / "developer-inbox"
    operational_inbox = Path.home() / "Library/Application Support/TIM/local-first/inbox"
    tasks = []
    for inbox, kind in ((developer_inbox, "developer"), (operational_inbox, "operational")):
        for path in sorted(inbox.glob("*.json")) if inbox.exists() else []:
            item = _read_json(path)
            tasks.append({"id": str(item.get("task_id", path.stem))[:120], "kind": kind,
                          "next_action": str(item.get("next_action", item.get("objective", "")))[:400]})
    daemon_lock = state / "daemon.lock"
    worker_lock = state / "supervisor.lock"
    last = _latest(state / "developer-results")
    acceptance = _latest(state / "acceptance-results")
    tests = last.get("tests", {}) if isinstance(last.get("tests"), dict) else {}
    logs = Path.home() / "Library/Logs/TIM"
    ollama = _ollama(ollama_url)
    candidates = (model, "qwen2.5:7b")
    ollama["configured_model"] = model
    ollama["selected_model"] = next((candidate for candidate in candidates if candidate in ollama["models"]), None)
    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "mode": "LOCAL_ONLY_OBSERVE_AND_EXPLICIT_SANDBOX_SUBMIT",
        "qwen": {"daemon": {"lock_present": daemon_lock.exists(), "pid": _pid(daemon_lock),
                               "alive": _alive(_pid(daemon_lock))},
                 "worker": {"lock_present": worker_lock.exists(), "pid": _pid(worker_lock),
                            "alive": _alive(_pid(worker_lock))}, "ollama": ollama},
        "current_task": tasks[0] if tasks else None, "queued_tasks": tasks[:20],
        "repository": {"path": str(repo), "branch": _git(repo, "branch", "--show-current"),
                       "head": _git(repo, "rev-parse", "--short", "HEAD"),
                       "dirty": bool(_git(repo, "status", "--porcelain"))},
        "repair": {"last_status": str(last.get("status", "IDLE")), "task_id": str(last.get("task_id", "")),
                   "retry_cycle": last.get("supervisor_repair_cycle", 0),
                   "next_action": str(last.get("next_action", "")),
                   "acceptance": str(acceptance.get("status", "NONE"))},
        "tests": {"returncode": tests.get("returncode"), "executed": tests.get("tests", []),
                  "last_task": str(last.get("task_id", ""))},
        "safety_gates": {"live_trading": "DISABLED", "execution": "DISABLED", "production_data_writes": "FORBIDDEN",
                         "github_writes": "FORBIDDEN_WITHOUT_EXPLICIT_APPROVAL", "task_submission": "EXPLICIT_SANDBOX_ONLY"},
        "logs": {"stdout": _log_tail(logs / "local-first.out.log"),
                 "stderr": _log_tail(logs / "local-first.err.log")},
    }


def _page(data: dict) -> str:
    payload = json.dumps(data).replace("</", "<\\/")
    return """<!doctype html><meta charset=utf-8><title>TIM QWEN-DASHBOARD</title>
<style>body{font:15px system-ui;margin:2rem;background:#10151c;color:#e8edf2}h1{color:#9ee7c4}.grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(260px,1fr));gap:12px}.card{background:#18222e;padding:14px;border-radius:8px}pre{white-space:pre-wrap;word-break:break-word;color:#c7d5e0}</style>
<h1>TIM QWEN-DASHBOARD</h1><p>Local only · observe status · no trading or execution controls</p><div id=app class=grid></div>
<script>const draw=d=>{let x=document.querySelector('#app');x.textContent='';for(const[k,v]of Object.entries(d)){let c=document.createElement('section');c.className='card';let h=document.createElement('h2');h.textContent=k.replaceAll('_',' ');let p=document.createElement('pre');p.textContent=typeof v==='string'?v:JSON.stringify(v,null,2);c.append(h,p);x.append(c)}};async function poll(){try{draw(await (await fetch('/api/status',{cache:'no-store'})).json())}catch(e){document.querySelector('#app').textContent='Status unavailable'}}poll();setInterval(poll,5000)</script>"""


def serve(repo: Path, qwen_repo: Path, ollama_url: str, port: int) -> None:
    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):  # noqa: N802
            if self.path not in ("/", "/api/status"):
                self.send_error(404); return
            body = (json.dumps(snapshot(repo, qwen_repo, ollama_url), indent=2) if self.path == "/api/status"
                    else _page(snapshot(repo, qwen_repo, ollama_url))).encode()
            self.send_response(200); self.send_header("Content-Type", "application/json" if self.path == "/api/status" else "text/html; charset=utf-8")
            self.send_header("Cache-Control", "no-cache, no-store, must-revalidate"); self.send_header("Content-Length", str(len(body))); self.end_headers(); self.wfile.write(body)
        def log_message(self, *_): pass
    server = ThreadingHTTPServer(("127.0.0.1", port), Handler)
    print(f"TIM QWEN-DASHBOARD: http://127.0.0.1:{server.server_address[1]}", flush=True)
    try: server.serve_forever()
    except KeyboardInterrupt: pass
    finally: server.server_close()


def _master_prompt(repo: Path, prompt_id: str) -> Path:
    choices = sorted((repo / "TIM_MASTER_PROMPTS").glob(f"{prompt_id.zfill(2)}_*.md"))
    if not choices: raise ValueError("unknown master prompt")
    return choices[0]


def _qwen(text: str, url: str, model: str) -> str:
    policy = "TIM local assistant. Produce planning or test guidance only. Never trade, execute orders, change production data, use credentials, or write GitHub. If asked, refuse and explain the safety gate."
    installed = _ollama(url)["models"]
    selected = next((candidate for candidate in (model, "qwen2.5:7b") if candidate in installed), None)
    if selected is None:
        raise RuntimeError("No configured local Qwen model is installed; no model was downloaded.")
    body = json.dumps({"model": selected, "prompt": policy + "\n\n" + text, "stream": False}).encode()
    request = Request(url.rstrip("/") + "/api/generate", data=body, headers={"Content-Type": "application/json"}, method="POST")
    with urlopen(request, timeout=120) as response: return str(json.loads(response.read()).get("response", ""))


def run_master(repo: Path, prompt_id: str, question: str, url: str, model: str) -> str:
    prompt = _master_prompt(repo, prompt_id).read_text(encoding="utf-8")
    answer = _qwen(f"Master prompt {prompt_id}:\n{prompt}\n\nUser task (planning/test only): {question}", url, model)
    root = repo / ".tim/qwen-dashboard/master-runs"; root.mkdir(parents=True, exist_ok=True)
    path = root / f"{int(time.time())}-prompt-{prompt_id.zfill(2)}.txt"; path.write_text(answer, encoding="utf-8")
    return str(path)


def enqueue(qwen_repo: Path, task_file: Path) -> str:
    task = _read_json(task_file)
    task_id = str(task.get("task_id", ""))
    if not TASK_ID.fullmatch(task_id) or task.get("risk") != "A3" or task.get("sandboxed") is not True:
        raise ValueError("task requires a safe task_id, risk=A3 and sandboxed=true")
    if not isinstance(task.get("allowed_paths"), list) or not isinstance(task.get("tests"), list):
        raise ValueError("task requires explicit allowed_paths and tests")
    target = qwen_repo / ".tim/local-first/developer-inbox" / f"{task_id}.json"
    if target.exists(): raise ValueError("task already queued")
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(task, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return str(target)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="TIM Qwen local-only terminal and dashboard")
    parser.add_argument("--repo-root", type=Path, default=Path(__file__).resolve().parents[1]); parser.add_argument("--qwen-repo", type=Path, default=DEFAULT_QWEN_REPO)
    parser.add_argument("--ollama-url", default=DEFAULT_OLLAMA_URL); parser.add_argument("--model", default="qwen2.5-coder:7b")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("status"); dash = sub.add_parser("dashboard"); dash.add_argument("--port", type=int, default=8766)
    master = sub.add_parser("master"); master_sub = master.add_subparsers(dest="master_command", required=True); master_sub.add_parser("list"); render = master_sub.add_parser("render"); render.add_argument("id"); run = master_sub.add_parser("run"); run.add_argument("id"); run.add_argument("question")
    terminal = sub.add_parser("terminal"); terminal.add_argument("question", nargs="?")
    task = sub.add_parser("task"); task_sub = task.add_subparsers(dest="task_command", required=True); submit = task_sub.add_parser("enqueue"); submit.add_argument("--file", type=Path, required=True); submit.add_argument("--confirm-sandbox-submit", action="store_true")
    agent = sub.add_parser("daemon"); agent.add_argument("action", choices=("start", "stop"))
    args = parser.parse_args(argv); repo, qwen_repo = args.repo_root.resolve(), args.qwen_repo.resolve()
    if args.command == "status": print(json.dumps(snapshot(repo, qwen_repo, args.ollama_url), indent=2)); return 0
    if args.command == "dashboard": serve(repo, qwen_repo, args.ollama_url, args.port); return 0
    if args.command == "master":
        if args.master_command == "list": print("\n".join(path.name for path in sorted((repo / "TIM_MASTER_PROMPTS").glob("[0-9][0-9]_*.md")))); return 0
        path = _master_prompt(repo, args.id)
        if args.master_command == "render": print(path.read_text(encoding="utf-8")); return 0
        try:
            print(run_master(repo, args.id, args.question, args.ollama_url, args.model))
            return 0
        except (OSError, URLError, ValueError, RuntimeError) as error:
            print(f"TIM_QWEN_SAFE_STOP: local master prompt was not run ({type(error).__name__}).", file=sys.stderr)
            return 2
    if args.command == "terminal":
        question = args.question or input("TIM Qwen> ")
        try:
            print(_qwen(question, args.ollama_url, args.model))
            return 0
        except (OSError, URLError, ValueError, RuntimeError) as error:
            print(f"TIM_QWEN_SAFE_STOP: local model unavailable or rejected the request ({type(error).__name__}).", file=sys.stderr)
            return 2
    if args.command == "task":
        if not args.confirm_sandbox_submit: raise SystemExit("Refusing task submission: pass --confirm-sandbox-submit after reviewing the task file.")
        print(enqueue(qwen_repo, args.file)); return 0
    command = ["launchctl", "kickstart", "-k", f"gui/{os.getuid()}/{LAUNCH_AGENT}"] if args.action == "start" else ["launchctl", "bootout", f"gui/{os.getuid()}/{LAUNCH_AGENT}"]
    return subprocess.run(command, check=False).returncode


if __name__ == "__main__": raise SystemExit(main())

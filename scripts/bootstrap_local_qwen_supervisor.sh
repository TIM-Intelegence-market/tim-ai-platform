#!/usr/bin/env bash
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO_ROOT"

VENV="$REPO_ROOT/.venv"
PYTHON=""

if [[ -x "$VENV/bin/python" ]]; then
  if "$VENV/bin/python" - <<'PY' >/dev/null 2>&1
import sys
raise SystemExit(0 if sys.version_info[:2] == (3, 13) else 1)
PY
  then
    PYTHON="$VENV/bin/python"
  fi
fi

if [[ -z "$PYTHON" ]]; then
  for candidate in \
    "$(command -v python3.13 2>/dev/null || true)" \
    /opt/homebrew/bin/python3.13 \
    /opt/homebrew/opt/python@3.13/bin/python3.13 \
    /usr/local/bin/python3.13; do
    if [[ -n "$candidate" && -x "$candidate" ]]; then
      PYTHON="$candidate"
      break
    fi
  done
fi

if [[ -z "$PYTHON" ]]; then
  echo "QWEN_BOOTSTRAP_BLOCKED: Python 3.13 not found."
  echo "Install it once with: brew install python@3.13"
  exit 13
fi

echo "QWEN_BOOTSTRAP_PYTHON=$PYTHON"

if [[ "$PYTHON" != "$VENV/bin/python" ]]; then
  if [[ -e "$VENV" ]]; then
    echo "QWEN_BOOTSTRAP_BLOCKED: existing .venv is not Python 3.13; inspect it before replacement."
    exit 13
  fi
  uv venv --python "$PYTHON" "$VENV"
fi

uv pip install --python "$VENV/bin/python" -r requirements.txt

export TIM_RUNTIME_ENV=test
export TIM_LOCAL_GRAPHIFY=0
export TIM_LIVE_TRADING=0
export TIM_EXECUTION_ENABLED=0

GITHUB_ARGS=()
GH_WORKER_CONFIG="${TIM_QWEN_GH_CONFIG_DIR:-$HOME/.config/gh-tim-mac-worker}"
if [[ -d "$GH_WORKER_CONFIG" ]] && command -v gh >/dev/null 2>&1; then
  WORKER_LOGIN="$(GH_CONFIG_DIR="$GH_WORKER_CONFIG" gh api user --jq .login 2>/dev/null || true)"
  if [[ -n "$WORKER_LOGIN" ]]; then
    GITHUB_ARGS=(--github-worker-login "$WORKER_LOGIN" --github-config-dir "$GH_WORKER_CONFIG" --enable-github-escalation)
  fi
fi

"$VENV/bin/python" -m pytest -q \
  tests/test_local_first_patch_executor.py \
  tests/test_local_first_worker.py \
  tests/test_local_qwen_developer.py \
  tests/test_local_qwen_required_outputs.py \
  tests/test_local_qwen_supervisor.py \
  tests/test_local_qwen_daemon_supervisor.py \
  tests/test_local_qwen_launchd_installer.py \
  tests/test_ollama_health.py

"$VENV/bin/python" scripts/install_local_qwen_launchd.py \
  --repo-root "$REPO_ROOT" \
  --python "$VENV/bin/python" \
  --model qwen3.5:9b \
  --fallback-models '' \
  --pilot-task-id "${TIM_QWEN_PILOT_TASK_ID:-tim-worker-idle}" \
  --enable-codex-advisor \
  --codex-model "${TIM_CODEX_MODEL:-gpt-5.6-luna}" \
  "${GITHUB_ARGS[@]}" \
  --interval 5

if [[ "${TIM_QWEN_BOOTSTRAP_LOAD:-0}" == "1" ]]; then
  "$VENV/bin/python" scripts/install_local_qwen_launchd.py \
    --repo-root "$REPO_ROOT" \
    --python "$VENV/bin/python" \
    --model qwen3.5:9b \
    --fallback-models '' \
    --pilot-task-id "${TIM_QWEN_PILOT_TASK_ID:-tim-worker-idle}" \
    --enable-codex-advisor \
    --codex-model "${TIM_CODEX_MODEL:-gpt-5.6-luna}" \
    "${GITHUB_ARGS[@]}" \
    --interval 5 \
    --load
  sleep 5
fi

echo "QWEN_BOOTSTRAP_COMPLETE"
echo "PYTHON=$($VENV/bin/python --version 2>&1)"
echo "VENV=$VENV"
launchctl print "gui/$(id -u)/com.tim.local-qwen-worker" 2>&1 | head -80 || true

echo "--- SUPERVISOR OUT ---"
tail -n 80 "$HOME/Library/Logs/TIM/local-first.out.log" 2>/dev/null || true

echo "--- SUPERVISOR ERR ---"
tail -n 80 "$HOME/Library/Logs/TIM/local-first.err.log" 2>/dev/null || true

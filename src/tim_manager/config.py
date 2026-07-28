from __future__ import annotations

import json
from pathlib import Path
from typing import Any


PROJECT_ROOT = Path(__file__).resolve().parents[2]
CONFIG_ROOT = PROJECT_ROOT / "config" / "tim_manager"
ARTIFACT_ROOT = PROJECT_ROOT / "artifacts" / "tim_manager"


def load_config(name: str) -> dict[str, Any]:
    path = CONFIG_ROOT / name
    with path.open("r", encoding="utf-8") as handle:
        return json.load(handle)


def canonical_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


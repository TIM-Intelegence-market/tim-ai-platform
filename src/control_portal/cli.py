from __future__ import annotations

import argparse
import os
from pathlib import Path

from .app import PortalConfig, PortalServer


def parser() -> argparse.ArgumentParser:
    value = argparse.ArgumentParser(description="TIM Engineering Console")
    value.add_argument("--repo-root", type=Path, default=Path.cwd())
    value.add_argument("--state-root", type=Path, default=Path("/srv/tim/data/local-first-runtime"))
    value.add_argument("--db", type=Path, default=Path("/srv/tim/data/control-portal/portal.sqlite3"))
    value.add_argument("--host", default="127.0.0.1")
    value.add_argument("--port", type=int, default=8090)
    value.add_argument(
        "--allowed-host",
        action="append",
        default=[],
        help="Expected HTTP Host value. Repeat for domain aliases.",
    )
    value.add_argument("--cookie-secure", action="store_true")
    value.add_argument("--bootstrap", action="store_true", help="Explicit first local administrator setup; never use behind the proxy")
    value.add_argument("--ollama-url", default=os.getenv("OLLAMA_BASE_URL", "http://127.0.0.1:11434"))
    return value


def main() -> int:
    args = parser().parse_args()
    environment_hosts = [
        item.strip()
        for item in os.getenv("TIM_PORTAL_ALLOWED_HOSTS", "").split(",")
        if item.strip()
    ]
    allowed = tuple(args.allowed_host or environment_hosts or ["127.0.0.1", "localhost"])
    config = PortalConfig(
        repo_root=args.repo_root.resolve(),
        state_root=args.state_root.resolve(),
        db_path=args.db.resolve(),
        host=args.host,
        port=args.port,
        allowed_hosts=allowed,
        cookie_secure=args.cookie_secure or os.getenv("TIM_PORTAL_COOKIE_SECURE") == "1",
        allow_bootstrap=args.bootstrap,
        ollama_url=args.ollama_url,
    )
    server = PortalServer(config)
    print(f"TIM_CONTROL_PORTAL listening=http://{config.host}:{config.port}", flush=True)
    try:
        server.server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

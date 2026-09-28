#!/usr/bin/env bash
# Idempotent setup for the isolated TIM pytest PostgreSQL cluster.
# Creates a user-owned cluster on port 5433 plus role/database tim_test.
# NEVER touches production (port 5432, separate server, separate data dir).
# The role password is generated at runtime into a 0600 file only.
# Nothing secret is printed, committed, or passed on argv.
set -euo pipefail

PG_BIN="/Library/PostgreSQL/18/bin"
PGDATA="${HOME}/Library/Application Support/TIM/test-postgres"
SECRET_FILE="${HOME}/Library/Application Support/TIM/test-database-password"
SOCKET_DIR="${PGDATA}/sockets"
REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
VENV_PY="${REPO_ROOT}/.venv/bin/python"

if [[ ! -x "${PG_BIN}/initdb" ]]; then
  echo "PostgreSQL 18 binaries not found at ${PG_BIN}" >&2
  exit 2
fi

if [[ ! -d "${PGDATA}" ]]; then
  "${PG_BIN}/initdb" -D "${PGDATA}" -E UTF8 -U tim-user \
    --auth-local=peer --auth-host=scram-sha-256 >/dev/null
  mkdir -p "${SOCKET_DIR}"
  cat >> "${PGDATA}/postgresql.conf" << 'EOF'

# TIM isolated test cluster (pytest only, never production)
port = 5433
listen_addresses = 'localhost'
unix_socket_directories = '/Users/tim/Library/Application Support/TIM/test-postgres/sockets'
max_connections = 20
shared_buffers = 64MB
EOF
  echo "cluster initialized"
else
  echo "cluster exists, reusing"
fi

if ! "${PG_BIN}/pg_ctl" -D "${PGDATA}" status >/dev/null 2>&1; then
  "${PG_BIN}/pg_ctl" -D "${PGDATA}" \
    -l "${HOME}/Library/Application Support/TIM/test-postgres.log" start >/dev/null
  echo "server started"
else
  echo "server running"
fi

# All credential-bearing steps run inside Python (no argv/env exposure).
SOCKET_DIR="${SOCKET_DIR}" REPO_ROOT="${REPO_ROOT}" SECRET_FILE="${SECRET_FILE}" "${VENV_PY}" - << 'PYEOF'
import asyncio
import os
import secrets
import sys
from pathlib import Path

sys.path.insert(0, os.environ["REPO_ROOT"])

import asyncpg

SOCKET = os.environ["SOCKET_DIR"]
SECRET = Path(os.environ["SECRET_FILE"])


async def main() -> None:
    conn = await asyncpg.connect(host=SOCKET, port=5433, database="postgres", user="tim-user")
    try:
        exists = await conn.fetchval("SELECT 1 FROM pg_roles WHERE rolname='tim_test'")
        if exists:
            print("role tim_test exists")
            return
        pw = secrets.token_urlsafe(32)
        quoted = await conn.fetchval("SELECT quote_literal($1)", pw)
        await conn.execute(
            "CREATE ROLE tim_test LOGIN NOSUPERUSER NOCREATEDB "
            "NOCREATEROLE NOREPLICATION PASSWORD %s" % quoted
        )
        await conn.execute("CREATE DATABASE tim_test OWNER tim_test")
        await conn.execute("REVOKE CONNECT ON DATABASE postgres FROM PUBLIC")
        await conn.execute("ALTER DATABASE tim_test SET app.tim_test_environment = 'true'")
        SECRET.write_text(pw + "\n")
        SECRET.chmod(0o600)
        print("role+database created, secret file written (0600)")
    finally:
        await conn.close()


asyncio.run(main())
PYEOF

echo "setup complete: 127.0.0.1:5433/tim_test"
echo "configure tests with: eval \"\$(scripts/test_db_url.sh)\" (session only, never commit)"

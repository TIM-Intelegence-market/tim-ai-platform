# Isolated PostgreSQL Test Database

DB-backed TIM tests run against a dedicated local server that is physically
separate from production. No test may ever fall back to production.

## Layout

```text
production : 127.0.0.1:5432/tim          (role tim,  system/postgresql-18)
tests      : 127.0.0.1:5433/tim_test     (role tim_test, user-owned cluster)
```

The test cluster lives in `~/Library/Application Support/TIM/test-postgres`
(port 5433, localhost only, 20 connections). The `tim_test` role is
non-superuser without createdb rights and exists only on the test server.

## Create / (re)start

```bash
./scripts/setup_test_postgres.sh   # idempotent: initdb + start + role/db/marker
```

The role password is generated at runtime into the 0600 file
`~/Library/Application Support/TIM/test-database-password`. It is never
printed or committed. Start/stop manually with `pg_ctl -D <datadir>`; no
launchd integration (deliberate: tests must opt in explicitly).

## Configure a pytest session (session only, never commit)

```bash
eval "$(scripts/test_db_url.sh)"   # sets TIM_DURABLE_TEST_DATABASE_URL
pytest tests/test_durable_ingestion_database_v2.py
```

## How pytest resolves the database

1. DB tests read `TIM_DURABLE_TEST_DATABASE_URL` and `SKIP_SAFE` without it.
2. `tests/conftest.py` forces `TIM_RUNTIME_ENV=test` and monkeypatches
   `asyncpg.connect/create_pool` through `require_safe_test_database`.
3. `Database.connect()` and `initialize_schema()` call
   `guard_database_connection`, which enforces the same check inside test
   context (`TIM_RUNTIME_ENV=test` or `PYTEST_CURRENT_TEST`).

## How the safety guard works (`src/database/safety.py`)

A URL is accepted only if ALL hold:

- `TIM_DURABLE_TEST_DATABASE_URL` is set and the requested target equals it
- host is loopback, port is explicit (no PGPORT ambiguity)
- database name differs from the runtime name (`tim` by default)
- database name matches `test|pytest|isolated`
- the target is not equal to any configured runtime URL

Anything else raises `DatabaseSafetyError` before a socket is opened.
Production URLs are therefore rejected by construction, not by convention.

## Database identity marker

```sql
SHOW app.tim_test_environment;  -- 'true' on tim_test (database-scoped GUC)
SELECT current_database();      -- must return tim_test
```

Tests can assert both without credentials. Safety never relies on the marker
alone; the name/port/server checks above always apply.

## Verify the current target (no credentials shown)

```bash
.venv/bin/python -c "
from config.secrets import redact_database_url
import os; print(redact_database_url(os.environ['TIM_DURABLE_TEST_DATABASE_URL']))"
```

## Reset strategy

- Per-test fixtures `DELETE` all TIM tables before and after each test
  (deterministic, fast, repeatable; see `tests/test_durable_ingestion_database_v2.py`).
- Full re-init any time: schema + migrations are idempotent
  (`CREATE TABLE IF NOT EXISTS`, transactional migration files).
- Never point reset helpers at production; the guard rejects it.

## If the test database is missing

DB tests `SKIP_SAFE` when `TIM_DURABLE_TEST_DATABASE_URL` is unset.
If set but unreachable, tests fail with a connection error against
port 5433 only. Production is never attempted as a fallback.

# TIM PostgreSQL 18 Setup

TIM uses only a local PostgreSQL connection:

- host: `127.0.0.1`
- port: `5432`
- database: `tim`
- role: `tim`
- optional acceleration extension: `timescaledb`

Run the idempotent setup from the project root:

```bash
./scripts/setup_postgres.sh
```

PostgreSQL asks for the installer-created administrator password for role
`postgres`. TIM does not store that administrator password. The script creates
or normalizes the non-superuser role `tim`, creates the `tim` database, checks
that TimescaleDB is actually available, applies `src/database/schema.sql`, and
performs a final connection check.

If the local `postgres` password was forgotten, double-click
`TIM_Reset_Postgres_Password.command`. It stops only the local PostgreSQL 18
service, uses PostgreSQL single-user mode to set a new password, restarts the
service, and verifies the new credential. macOS asks once for the Mac
administrator password. No online account is involved.

If TimescaleDB is unavailable for the installed PostgreSQL build, TIM uses
standard PostgreSQL tables with deterministic time indexes. The schema detects
the extension explicitly and creates hypertables only when supported. Missing
TimescaleDB always remains visible in health metadata; it does not block the
OBSERVE platform.

After `TIM POSTGRES READY` appears, start the OBSERVE service:

```bash
.venv/bin/python main.py --init-schema
```

No private exchange credentials, orders, or live-trading permissions are part
of this setup.

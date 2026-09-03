#!/usr/bin/env bash
set -euo pipefail

PSQL_BIN="${TIM_ADMIN_PSQL:-/Library/PostgreSQL/18/bin/psql}"
ADMIN_USER="${TIM_ADMIN_DATABASE_USER:-postgres}"
ADMIN_DATABASE="${TIM_ADMIN_DATABASE_NAME:-postgres}"

if [[ ! -x "$PSQL_BIN" ]]; then
  echo '{"status":"BLOCKED","reason":"configured psql binary is unavailable"}' >&2
  exit 2
fi

"$PSQL_BIN" -X -v ON_ERROR_STOP=1 -U "$ADMIN_USER" -d "$ADMIN_DATABASE" -At <<'SQL'
SELECT json_build_object(
  'status','INSPECTED',
  'server_version',current_setting('server_version'),
  'config_file',current_setting('config_file'),
  'hba_file',current_setting('hba_file'),
  'data_directory',current_setting('data_directory'),
  'listen_addresses',current_setting('listen_addresses'),
  'port',current_setting('port'),
  'ssl',current_setting('ssl'),
  'password_encryption',current_setting('password_encryption'),
  'current_user',current_user,
  'is_superuser',(SELECT rolsuper FROM pg_roles WHERE rolname=current_user),
  'user_databases',(SELECT json_agg(json_build_object('name',datname,'owner',pg_get_userbyid(datdba)) ORDER BY datname) FROM pg_database WHERE datname NOT IN ('template0','template1','postgres')),
  'non_system_roles',(SELECT json_agg(json_build_object('name',rolname,'superuser',rolsuper,'create_role',rolcreaterole,'create_db',rolcreatedb) ORDER BY rolname) FROM pg_roles WHERE rolname !~ '^pg_' AND rolname <> 'postgres'),
  'client_sessions',(SELECT count(*) FROM pg_stat_activity WHERE backend_type='client backend' AND pid<>pg_backend_pid())
);
SQL

#!/usr/bin/env bash
# Prints a session-only export for the isolated TIM test database.
# Usage: eval "$(scripts/test_db_url.sh)"
# The password is read from the 0600 secret file into the current shell only.
# Never commit the output. Never point this at production (port is fixed).
set -euo pipefail

SECRET_FILE="${HOME}/Library/Application Support/TIM/test-database-password"
if [[ ! -f "${SECRET_FILE}" ]]; then
  echo "test secret missing; run scripts/setup_test_postgres.sh first" >&2
  exit 2
fi
TEST_PW="$(cat "${SECRET_FILE}")"
printf 'export TIM_DURABLE_TEST_DATABASE_URL="postgresql://tim_test:%s@127.0.0.1:5433/tim_test"\n' "${TEST_PW}"

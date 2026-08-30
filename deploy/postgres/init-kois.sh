#!/bin/bash
set -euo pipefail

# Runs only on first init of an empty data volume.
# POSTGRES_USER is the superuser (postgres). The app role is KOIS_DB_USER.

if [[ -z "${KOIS_DB_USER:-}" || -z "${KOIS_DB_PASSWORD:-}" || -z "${KOIS_DB_NAME:-}" ]]; then
  echo "KOIS_DB_USER, KOIS_DB_PASSWORD, and KOIS_DB_NAME must be set on the db container." >&2
  exit 1
fi

psql -v ON_ERROR_STOP=1 --username "$POSTGRES_USER" --dbname "$POSTGRES_DB" <<EOSQL
CREATE USER ${KOIS_DB_USER} WITH PASSWORD '${KOIS_DB_PASSWORD}';
CREATE DATABASE ${KOIS_DB_NAME} OWNER ${KOIS_DB_USER};
GRANT ALL PRIVILEGES ON DATABASE ${KOIS_DB_NAME} TO ${KOIS_DB_USER};
EOSQL

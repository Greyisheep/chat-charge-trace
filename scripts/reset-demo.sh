#!/usr/bin/env bash
# Reset the demo to a clean slate: wipe orders and agent conversation state.
# Product catalog is code, not data, so it is untouched.
#
# Usage: ./scripts/reset-demo.sh
# Assumes the postgres container from docker-compose.yml is running.

set -euo pipefail

CONTAINER="${OJA_PG_CONTAINER:-oja-postgres}"

echo "Resetting demo data in container '$CONTAINER'..."

docker exec -i "$CONTAINER" psql -U oja -d oja -v ON_ERROR_STOP=1 <<'SQL'
-- Shop orders plus ADK DatabaseSessionService tables (names as created by
-- google-adk). Each guarded separately: missing tables are fine on a fresh
-- database.
DO $$
DECLARE
  t text;
BEGIN
  FOREACH t IN ARRAY ARRAY['orders', 'events', 'sessions', 'app_states', 'user_states']
  LOOP
    IF to_regclass('public.' || t) IS NOT NULL THEN
      EXECUTE format('TRUNCATE TABLE %I CASCADE', t);
    END IF;
  END LOOP;
END $$;
SQL

echo "Done. Orders and agent sessions are empty; the catalog is untouched."

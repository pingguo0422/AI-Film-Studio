#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"
COMPOSE_FILE="compose.postgres.yml"
DB_PASSWORD="${AFS_POSTGRES_PASSWORD:-afs-local-dev-only-change-me}"
DB_PORT="${AFS_POSTGRES_PORT:-5432}"
export AFS_DATABASE_URL="postgresql+psycopg://afs:${DB_PASSWORD}@localhost:${DB_PORT}/afs_test"
export AFS_TEST_POSTGRES_URL="$AFS_DATABASE_URL"

if ! command -v docker >/dev/null 2>&1; then
  echo "ERROR: Docker is required for the bundled PostgreSQL 16 integration environment." >&2
  exit 2
fi

docker compose -f "$COMPOSE_FILE" up -d --wait postgres
cleanup() {
  if [[ "${AFS_KEEP_POSTGRES:-1}" != "1" ]]; then
    docker compose -f "$COMPOSE_FILE" down -v
  fi
}
trap cleanup EXIT

python - <<'PY'
import os, time
import psycopg
url = os.environ["AFS_TEST_POSTGRES_URL"].replace("postgresql+psycopg://", "postgresql://", 1)
last = None
for _ in range(30):
    try:
        with psycopg.connect(url, connect_timeout=2) as conn:
            print("PostgreSQL connection: PASS", conn.execute("select version()").fetchone()[0].split(",")[0])
        break
    except Exception as exc:
        last = exc
        time.sleep(2)
else:
    raise SystemExit(f"PostgreSQL did not become available: {last}")
PY

alembic upgrade head
alembic check
pytest -q

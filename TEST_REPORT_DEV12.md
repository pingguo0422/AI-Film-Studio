# Test Report — Foundation 1.5 dev.12

| Check | Result | Notes |
|---|---|---|
| `pytest -q` | PASS | 139 passed, 12 skipped |
| Python `compileall` | PASS | backend, integrations, scripts |
| `node --check frontend/control-center/assets/app.js` | PASS | |
| `bash -n scripts/run_postgres_integration.sh` | PASS | |
| SQLite fresh migration | PASS | Full Alembic head |
| SQLite `alembic check` | PASS | No new upgrade operations detected |
| SQLite downgrade/re-upgrade | PASS | One revision down, then head |
| PostgreSQL 16 offline SQL | PASS | 1,208 lines generated; no live database involved |
| Live PostgreSQL 16 migration/contracts | NOT EXECUTED | No Docker/server/`AFS_TEST_POSTGRES_URL` in environment |
| PostgreSQL 8-way same-key action test | SKIPPED | Requires live PostgreSQL |
| PostgreSQL 8-way different-key action test | SKIPPED | Requires live PostgreSQL |
| Browser E2E | NOT EXECUTED | No browser automation runtime configured |

All 12 skipped tests are PostgreSQL-only and require `AFS_TEST_POSTGRES_URL`.

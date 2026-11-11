# Test Report — Foundation 1.5 dev.11

| Check | Result | Notes |
|---|---|---|
| `pytest -q` | PASS | 139 passed, 11 skipped |
| Python `compileall` | PASS | backend, integrations, scripts |
| `node --check` | PASS | control-center app.js |
| SQLite fresh migration | PASS | migrated to head |
| SQLite `alembic check` | PASS | no new upgrade operations detected |
| SQLite downgrade/upgrade | PASS | one revision down, then head |
| PostgreSQL offline migration SQL | PASS | 1,208 lines generated; not a live DB test |
| PostgreSQL concurrent action test | NOT EXECUTED | skipped: `AFS_TEST_POSTGRES_URL` absent |

The suite's 11 skipped tests are PostgreSQL-only tests. The new concurrent director-action test is included in that group.

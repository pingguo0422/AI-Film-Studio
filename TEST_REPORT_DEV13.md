# Test Report — AFS Foundation 1.5 dev.13

## Automated suite

Command: `pytest -q`

Result: **141 passed, 12 skipped** (21.06 seconds).

The 12 skipped tests require `AFS_TEST_POSTGRES_URL`; no live PostgreSQL server was available in this execution environment.

## New tests

1. `test_inactive_project_cannot_execute_and_leaves_no_side_effects`
   - An approved action on an archived project returns HTTP 409.
   - No ActionExecution, Task, or `DIRECTOR_ACTION_EXECUTED` audit record is persisted.
2. `test_service_principal_cannot_execute_even_with_owner_membership`
   - A service principal is rejected with HTTP 403 even when it has an owner membership record.
   - No ActionExecution or Task is persisted.

## Additional checks

- `python -m compileall -q backend integrations scripts`: PASS
- `node --check frontend/control-center/assets/app.js`: PASS
- `bash -n scripts/run_postgres_integration.sh`: PASS
- SQLite fresh `alembic upgrade head`: PASS
- SQLite `alembic check`: PASS (`No new upgrade operations detected`)
- SQLite downgrade one revision and re-upgrade: PASS
- PostgreSQL offline `alembic upgrade head --sql`: PASS; 1,208 generated SQL lines. This is not a live database migration.

## Not executed

- Live PostgreSQL 16 migrations and concurrency tests.
- Browser E2E tests.
- Penetration testing or production deployment.

## Status

IMPLEMENTED / EXECUTED (local SQLite-backed API tests and static checks) / TESTED (local suite)
NOT EXECUTED (live PostgreSQL 16) / NOT ACCEPTED / NOT PRODUCTION READY

# Test Report — AFS Foundation 1.5 dev.14

## Automated backend suite

Command: `pytest -q`

Result: **141 passed, 12 skipped**.

The 12 skipped tests require `AFS_TEST_POSTGRES_URL`. No live PostgreSQL server is available in this execution environment.

## Browser UI E2E

Command: `AFS_CHROMIUM_EXECUTABLE=/usr/bin/chromium python scripts/run_control_center_browser_e2e.py`

Result: **PASS**.

The actual Control Center HTML, CSS and JavaScript were loaded in Chromium. The browser completed project connection, inbox selection, action payload binding during approval, separate execute confirmation, result rendering and activity timeline rendering. API responses were deterministic browser mocks; no claim of live HTTP/API persistence is made. See `artifacts/browser_ui_e2e_dev14.log`.

## Additional checks

- `python -m compileall -q backend integrations scripts`: PASS
- `python -m py_compile scripts/run_control_center_browser_e2e.py`: PASS
- `node --check frontend/control-center/assets/app.js`: PASS
- `bash -n scripts/run_postgres_integration.sh`: PASS
- SQLite fresh `alembic upgrade head`: PASS
- SQLite `alembic check`: PASS (`No new upgrade operations detected`)
- SQLite downgrade one revision and re-upgrade: PASS
- PostgreSQL dialect offline `alembic upgrade head --sql`: PASS; generated SQL is not a live database migration
- GET `/health`: 200, version `1.5.0-dev.14`
- GET `/control-center/`: 200
- GET `/openapi.json`: 200; execute route present

## Not executed

- Live PostgreSQL 16 migration, contract and concurrency tests.
- Browser-to-live-server E2E, deployed CSP/security checks, cross-browser tests.
- Penetration testing, production deployment and human acceptance.

## Status

IMPLEMENTED / EXECUTED (local checks and Chromium UI E2E with mocked APIs) / TESTED (local suite)
NOT EXECUTED (live PostgreSQL 16 and deployed browser integration) / NOT ACCEPTED / NOT PRODUCTION READY

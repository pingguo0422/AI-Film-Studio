# Test Report — AFS Foundation 1.5 dev.16

## Executed

- Full pytest suite: **141 passed, 12 skipped**. The 12 skips are PostgreSQL-only tests because `AFS_TEST_POSTGRES_URL` is not configured locally.
- Mocked Chromium Control Center workflow: **PASS**, executed using `/usr/bin/chromium` via `AFS_CHROMIUM_EXECUTABLE`. This loads the shipped HTML/CSS/JS and exercises status-aware inbox filtering, approval, retention of the selected approved case, second confirmation, execution result rendering, and activity timeline rendering.
- Python compileall: PASS.
- JavaScript syntax (`node --check`): PASS.
- Python compile checks for E2E scripts: PASS.
- SQLite migration, drift, downgrade/re-upgrade: see build verification log.

## Not executed / not claimed

- Live PostgreSQL 16 migration and concurrency suite: NOT EXECUTED locally.
- Browser-to-live-FastAPI HTTP workflow: NOT EXECUTED successfully locally. Although the live runner now supports the system Chromium path, this environment blocks Chromium navigation to `127.0.0.1` with `ERR_BLOCKED_BY_ADMINISTRATOR`.
- GitHub Actions workflow: authored but NOT RUN from this environment.
- Human acceptance: NOT ACCEPTED. Production readiness: NOT PRODUCTION READY.

The live PostgreSQL/browser workflow remains the acceptance gate and must be run in GitHub Actions against its disposable PostgreSQL 16 service.

Additional verification:
- Fresh SQLite Alembic upgrade to head: PASS.
- SQLite `alembic check`: PASS; no new upgrade operations detected.
- SQLite downgrade one revision and re-upgrade to head: PASS.
- FastAPI TestClient `/health`, `/control-center/`, `/openapi.json`, and action execution route presence: PASS; reported version `1.5.0-dev.16`.
- GitHub Actions YAML parses and explicit read-only `contents` permission is present.

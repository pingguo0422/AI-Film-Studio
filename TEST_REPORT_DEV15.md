# Test Report — AFS Foundation 1.5 dev.15

## Local automated tests

- `pytest -q`: **141 passed, 12 skipped** (23.16s).
- The 12 skipped tests require `AFS_TEST_POSTGRES_URL`; no live PostgreSQL service was available in this execution environment.
- `python -m compileall -q backend integrations scripts`: PASS.
- `node --check frontend/control-center/assets/app.js`: PASS.
- `bash -n scripts/run_postgres_integration.sh`: PASS.
- `python -m py_compile` for the mocked and live browser runners and E2E seeder: PASS.

## Database checks

- SQLite fresh migration to head: PASS.
- SQLite `alembic check`: PASS (`No new upgrade operations detected`).
- SQLite downgrade one revision and re-upgrade to head: PASS.
- PostgreSQL 16 offline migration SQL generation: PASS; generated SQL is for inspection only and is not a live PostgreSQL migration test.

## Live API smoke (SQLite-backed)

- E2E seeder created a project, human principal, owner membership, short-lived token and open director decision case: PASS.
- FastAPI started over local HTTP; authenticated `/v1/me` and decision inbox read: PASS.
- Actual HTTP API flow: read open case → approve with exact `create_task` snapshot → execute with idempotency key → read execution → read activity timeline: PASS.
- Task and action execution records were persisted in SQLite. This does not establish PostgreSQL behavior.

## Browser / CI checks

- dev.14 deterministic Chromium UI-only test remains the prior baseline; it uses mocked API responses.
- dev.15 live browser-to-API test script and GitHub Actions job are implemented and syntax-checked.
- Live Chromium execution could not be performed locally: Playwright's Chromium binary is absent and download was blocked by DNS/network restrictions (`EAI_AGAIN`).
- Docker daemon and live PostgreSQL 16 were unavailable locally.
- The GitHub Actions workflow has not yet run; CI success must be observed before claiming live integration acceptance.

## Result

**IMPLEMENTED / EXECUTED / TESTED (local SQLite + live HTTP API smoke).**

**NOT EXECUTED:** live PostgreSQL 16, PostgreSQL concurrency suite, live Chromium-to-FastAPI-to-PostgreSQL browser E2E.

**NOT ACCEPTED. NOT PRODUCTION READY.**

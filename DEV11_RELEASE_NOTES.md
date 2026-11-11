# AFS Foundation 1.5 dev.11 — PostgreSQL Concurrency Verification Preparation

## Scope

This release is a focused hardening and verification-preparation increment on top of dev.10. It does not expand the action allowlist or execution authority.

- Added a PostgreSQL-only concurrency contract test for eight simultaneous human execution requests against the same approved decision case.
- The test asserts one ActionExecution, one created Task, one audit event, one shared execution ID, and exactly one `created=True` response.
- The test exercises the existing `SELECT ... FOR UPDATE` decision-case lock and the database uniqueness constraints using independent SQLAlchemy sessions.
- Updated package/API version to `1.5.0.dev11` / `1.5.0-dev.11`.

## Verification

- Full local pytest suite: **139 passed, 11 skipped**.
- The additional PostgreSQL concurrency test is among the skipped tests because `AFS_TEST_POSTGRES_URL` is not configured.
- Python compileall: PASS.
- Frontend JavaScript syntax check: PASS.
- SQLite fresh migration to head: PASS.
- SQLite Alembic drift check: PASS (no new upgrade operations detected).
- SQLite downgrade one revision and upgrade to head: PASS.
- PostgreSQL Alembic offline SQL generation: PASS (generated SQL only; no live PostgreSQL connection).

## Not performed

- Live PostgreSQL integration or concurrency execution.
- Real-browser E2E.
- Penetration testing.
- Deployment or operator acceptance.

## Status

IMPLEMENTED / EXECUTED / TESTED (local SQLite, static checks, FastAPI test suite)

PostgreSQL concurrency test: IMPLEMENTED, NOT EXECUTED.

NOT ACCEPTED / NOT PRODUCTION READY.

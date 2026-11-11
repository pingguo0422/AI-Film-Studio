# Test Report — AFS Foundation 1.5 dev.9

## Automated tests

`pytest -q`: **139 passed, 10 skipped**.

The 10 skipped tests require `AFS_TEST_POSTGRES_URL` and a live PostgreSQL instance.

## New coverage

- Approved decision can bind an exact `create_task` action snapshot.
- Execution creates one queued task and a durable action execution/audit record.
- Repeating the same idempotency key returns the same execution result.
- A second idempotency key cannot execute the same approved decision twice.
- Open/unapproved decisions cannot execute.
- Non-approved dispositions cannot carry an executable action.
- Invalid action payload fields are rejected before the decision is committed.
- `request_rework` delegates to the existing quality evaluation gate and creates the linked rework task.

## Environment verification

- `python -m compileall -q backend integrations scripts`: PASS.
- SQLite fresh `alembic upgrade head`: PASS.
- SQLite `alembic check`: PASS — no new upgrade operations detected.
- SQLite `alembic downgrade -1` followed by `upgrade head`: PASS.
- PostgreSQL offline `alembic upgrade head --sql`: PASS; SQL generated for review only.
- FastAPI `/health` and OpenAPI action route: PASS.

## Boundaries

No live PostgreSQL server, external model provider, browser E2E, load test, penetration test or production deployment was used. Fake/local test infrastructure is not evidence of production readiness.

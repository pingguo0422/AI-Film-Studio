# AFS Foundation 1.5 dev.10 — Executive Director Action Control UI

## Scope

This release connects the dev.9 approval-bound action gateway to the browser control center.

- During an open-case review, a human reviewer may select `create_task` or `request_rework`, enter the complete JSON payload, inspect it in the confirmation prompt, and submit it atomically with the `approved` decision.
- Approval without an action remains supported. Reject/defer/close never accept an action binding.
- An approved action snapshot is rendered read-only. Execution requires a second explicit human confirmation and calls the execute endpoint with only an idempotency key; the browser does not send action parameters at execution time.
- The idempotency key is retained in the current browser session per decision case, so retrying the same request reuses the key.
- Added a read-only GET endpoint for the recorded execution result. The detail panel restores the result after refresh.
- Activity timeline now includes bounded, project-scoped action-execution events. It exposes event metadata only, not the execution result payload.

## Safety boundaries

- The action allowlist remains `create_task` and `request_rework`.
- No action is executed merely by approving a decision.
- No Agent assignment, inline Worker dispatch, arbitrary plugin/code execution, creative-asset mutation, or external side effect is introduced.
- UI uses textContent for returned content; JSON is displayed in `pre` elements, not injected as HTML.
- Execution result retrieval requires project read permission; execution still requires a human principal with project approve permission.

## Verification

- Full pytest suite: 139 passed, 10 skipped.
- `python -m compileall -q backend integrations scripts`: PASS.
- `node --check frontend/control-center/assets/app.js`: PASS.
- SQLite fresh migration to head: PASS.
- SQLite `alembic check`: PASS (no new upgrade operations detected).
- SQLite downgrade one revision and upgrade to head: PASS.
- PostgreSQL Alembic offline SQL generation: PASS (generated SQL only; not a live PostgreSQL test).
- FastAPI TestClient `/health`, `/control-center/`, `/openapi.json`: 200; health version `1.5.0-dev.10`.
- API tests cover execution-result readback and timeline event inclusion without leaking result payload.

## Status

IMPLEMENTED / EXECUTED / TESTED (local SQLite + FastAPI TestClient + static JS syntax checks)

NOT ACCEPTED / NOT PRODUCTION READY.

Not performed: live PostgreSQL concurrency/locking tests, real-browser E2E, penetration testing, deployment, human operator acceptance.

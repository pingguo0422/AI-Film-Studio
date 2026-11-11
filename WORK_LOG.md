# Work Log — Foundation 1.5 dev.9

## Baseline

- Started from the preserved `AFS_Foundation_1.5_dev.8` workspace.
- Created a separate `AFS_Foundation_1.5_dev.9` directory; dev.8 remains unchanged.
- Updated package and health version to `1.5.0-dev.9`.

## Implemented

- Added migration `d9a4f2c8b710` for decision-case action snapshots and `action_executions`.
- Added explicit approval-time action binding with strict allowlist and bounded payload validation.
- Added action execution service and authenticated API endpoint.
- Implemented `create_task` and `request_rework` executors.
- Added idempotent replay and one-execution-per-approved-case controls.
- Added action execution audit records and tests.
- Documented deliberate exclusion of Agent assignment because runtime enforcement is not yet present.

## Executed and tested

- Focused action/review tests: 11 passed at first integration checkpoint.
- New action gateway tests after rework coverage: 5 passed.
- Full suite: 139 passed / 10 skipped.
- Python compileall passed.
- SQLite fresh migration, drift check, downgrade and re-upgrade passed.
- PostgreSQL offline migration SQL generated; no live PG test claimed.

## Remaining

- Add control-center action review/binding/execute UI.
- Add durable failed-attempt records and operational retry tooling.
- Add live PostgreSQL locking/concurrency tests.
- Add exact AgentVersion assignment support in scheduler before exposing assign-agent action.
- Add compensation model before exposing actions with external side effects.

# Code Review — Foundation 1.5 dev.11

## Change reviewed

- Added a PostgreSQL integration contract test for concurrent execution of one approval-bound action.
- Updated release/API version identifiers only; no schema migration or runtime action semantics changed.

## Concurrency reasoning

`execute_approved_action()` obtains the decision case with `SELECT ... FOR UPDATE`. On PostgreSQL, concurrent requests for the same case serialize on that row. The first transaction creates the task, execution record, and audit event and commits. Subsequent transactions then observe the existing execution and return it for the same idempotency key. The unique constraints on `(project_id, idempotency_key)` and `decision_case_id` provide a second line of defense.

The new PostgreSQL test uses eight independent sessions synchronized at a barrier and checks that only one task/execution/audit record is persisted.

## Findings and limits

- The concurrency test has been authored but could not be executed because this environment has no configured `AFS_TEST_POSTGRES_URL` and no available Docker CLI.
- SQLite does not provide equivalent row-lock semantics; SQLite tests must not be presented as proof of PostgreSQL concurrency safety.
- No code change was made to claim live concurrency correctness without the required database execution evidence.
- Browser E2E, security testing, deployment, and human acceptance remain outstanding.

## Review outcome

No new runtime behavior or database migration was introduced. The added test is structurally aligned with the current locking and uniqueness strategy, but the production concurrency claim remains unverified until the PostgreSQL-only test runs against a real PostgreSQL 16 instance.

# Code Review — AFS Foundation 1.5 dev.9

## Review outcome

No blocking defects remain in the implemented local execution path after regression and migration checks. This is a scoped code review, not an independent security audit.

## Security and correctness checks

- Execution API does not accept action type or action payload; it loads the approved snapshot from the decision case.
- Approval service rejects action binding on rejected/deferred/closed decisions and validates exact key sets and bounded values.
- Execution requires a human principal and current project `approve` permission at the route boundary.
- The execution service rechecks approved status, action snapshot, project active state, action type and payload shape.
- Unique constraints enforce one execution per decision case and project-scoped idempotency key uniqueness.
- Same-key replay returns the stored result; different-key replay for the same case is rejected.
- Task creation/rework and action record/audit are part of the same outer database transaction.
- Rework reuses existing evaluation preconditions and dependency/downstream gating.
- No inline Worker invocation or external side effect is performed.

## Findings / limitations

1. Agent assignment is intentionally not implemented because the scheduler does not yet guarantee exact AgentVersion routing.
2. Failed precondition attempts are not persisted as failed execution records; a separate durable attempt/audit model is needed.
3. PostgreSQL `FOR UPDATE` semantics and concurrent execution races are not live-tested here. SQLite tests do not establish PostgreSQL locking correctness.
4. Compensation for external side effects is not implemented; the current allowlist only creates internal durable work and rework links.
5. The control-center browser UI has not yet been extended with an action-payload review/approval form or execute button. The API path is available; the UI must show the exact action snapshot before it can be considered an operator-ready workflow.
6. The current `DirectorDecisionDetail` exposes the authorized action snapshot to project readers. If action payloads later contain restricted data, response-level field policy or redaction must be added.

## Recommendation

Proceed to dev.10 only after adding UI support for explicit action binding and execution confirmation, plus live PostgreSQL concurrency tests. Do not expand the action allowlist until those gates pass.

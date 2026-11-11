# Code Review — Foundation 1.5 dev.10

## Reviewed changes

1. Control Center approval form binds an optional action only when the selected decision is `approved`.
2. The action payload is parsed as JSON client-side for usability, then strictly validated by the existing Pydantic/service allowlist on the server.
3. The execution button appears only when the approved case includes an authorized action snapshot.
4. The execution request contains only a session-persisted idempotency key; no client-supplied action type or payload can override the approved snapshot.
5. GET execution readback is project-scoped and requires read permission. POST execution continues to require a human principal and approve permission.
6. Timeline additions expose only action type/status/time/reference, not result_snapshot or audit details.
7. Dynamic content is rendered with `textContent` / DOM nodes; no HTML string injection was introduced.

## Remaining risks / limitations

- No live PostgreSQL test has validated row-lock and uniqueness behavior under concurrent execute requests.
- No browser automation or real operator usability test has been run.
- `request_rework` depends on a valid evaluation ID and existing quality gate; the form is intentionally generic JSON rather than a guided evaluation picker.
- The UI currently persists idempotency keys in sessionStorage, scoped to the browser tab. Clearing session storage removes the key; the server still prevents a second execution of the same decision case and returns a conflict if a different key is submitted after execution.
- The UI cannot recover the original idempotency key after session storage is cleared, but GET readback still shows the durable execution result.
- Failed precondition attempts are not persisted as ActionExecution rows; they surface as API errors.
- Agent assignment is still withheld until exact AgentVersion assignment enforcement exists in the scheduler.

## Review disposition

No blocker found in the implemented local workflow. Production readiness remains blocked on live PostgreSQL concurrency testing, browser E2E, security testing, and human acceptance.

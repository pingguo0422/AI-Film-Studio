# Executive Director Action Authorization & Execution Gateway — dev.9

## Purpose

Dev.9 adds a narrow, approval-bound execution path. A decision disposition and an executable action are separate concepts: approval may authorize one immutable action snapshot, and a later authenticated human request may execute that exact snapshot once.

## Flow

1. An authorized human submits `decision=approved` and an `authorized_action` in the same decision request.
2. The service validates and persists the action snapshot in `director_decision_cases.authorized_action_snapshot` as part of the one-time case disposition.
3. A human project member with `project:approve` calls the execute endpoint. The request contains only an idempotency key; it cannot replace the action payload.
4. The gateway locks the case where supported, verifies approved state, action snapshot, active project, actor type and idempotency boundaries.
5. The registered executor runs the action and writes `ActionExecution`, the resulting task/evaluation links, outbox events and audit entry in the same database transaction.
6. A repeated request with the same idempotency key returns the original result. A second key for the same case is rejected.

## Supported action types

### `create_task`

Payload: `task_type`, `title`, `input_snapshot`, optional `priority` (0–100), optional `max_attempts` (1–20). Unknown keys are rejected. The task is created queued and receives a stable gateway-generated idempotency key. It is not dispatched directly; the existing Worker claim path remains responsible for execution.

### `request_rework`

Payload: `evaluation_id`, optional `task_type`. The evaluation must belong to the same project, have decision `rework`, contain required changes, and reference a succeeded source task. Existing rework logic computes downstream impact, creates the rework task, gates eligible queued descendants and updates the evaluation link.

## API

Approve with a bound action:

```json
{
  "decision": "approved",
  "note": "Approve this exact task creation",
  "authorized_action": {
    "action_type": "create_task",
    "payload": {
      "task_type": "script_revision",
      "title": "Revise scene 12",
      "input_snapshot": {"scene_id": "12"},
      "priority": 40
    }
  }
}
```

Execute the approved snapshot:

```json
{"idempotency_key": "director-action-project-001"}
```

Endpoint: `POST /v1/projects/{project_id}/director/decision-cases/{case_id}/execute`.

The execution endpoint intentionally accepts no action type or payload. This prevents post-approval substitution.

## Invariants

- Only human principals with current project approval permission can approve or invoke execution.
- Action payload is validated at approval and checked again at execution.
- Non-approved cases, inactive projects, cross-project evaluations and unsupported action types fail closed.
- One decision case can produce at most one `ActionExecution` row.
- Project-scoped idempotency keys cannot be reused for a different case or action digest.
- Task creation/rework and execution record/audit are committed atomically by the request transaction.
- A successful gateway action creates or links durable work; it does not run a Worker inline.
- Approval without an `authorized_action` remains a valid human disposition but cannot be executed.

## Deliberate exclusions

- Agent assignment is not exposed. The current Worker selection contract does not yet enforce a persisted exact AgentVersion assignment; accepting an Agent ID without scheduler enforcement would be misleading and unsafe.
- External side effects, asset mutation, plan materialization, worker dispatch, task cancellation/retry and arbitrary Python/plugin invocation are not exposed.
- Failed precondition attempts are returned as API errors and do not currently create a durable failed `ActionExecution` row. Operational failed-attempt audit and compensation workflows remain follow-up work.
- Live PostgreSQL concurrency tests and production security certification have not been run.

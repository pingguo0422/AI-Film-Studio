# AFS Foundation 1.4 — Worker Runtime

## Runtime shape

```text
Task API / producer
       |
       v
PostgreSQL tasks + task_dependencies
       |
       | claim ready task (FOR UPDATE SKIP LOCKED)
       v
AFS Worker process
       |
       +-- task_type -> explicit SkillRegistration
       +-- exact AgentVersion / SkillVersion / AgentSkillBinding validation
       +-- AgentRun + SkillRun immutable input lineage
       +-- registered executor
       +-- independent DB lease heartbeat during long execution
       +-- task result / retry / cancellation state transition
```

The database is the durable queue and lease authority. Workers are stateless processes and may be run in more than one process against PostgreSQL. Task dependencies are respected by the existing ready-task claim query. A worker only claims task types for which it has an explicit registration; it does not dynamically import executable code from task payloads.

## Registering a capability

Create a `SkillRegistration` with:

- `task_type`: exact task type accepted by this worker;
- `agent_id` and `agent_version_id`: exact Agent version;
- `skill_version_id`: exact Skill version;
- `executor`: an explicitly supplied callable returning a JSON object.

The orchestrator verifies that the Agent and Skill are active and that the exact `AgentSkillBinding` exists. The runtime does not call a model provider unless a separately registered executor does so.

## Running the Heaven Ship 8.1 worker

Configure `AFS_DATABASE_URL`, apply migrations, create a project and enqueue a task of type `FOOTAGE_MODE_81_SOURCE_VALIDATION` with `project_id` in its input snapshot. Then run:

```bash
python scripts/worker_footage_mode_81.py \
  --worker-id afs-footage-mode-worker-01 \
  --lease-seconds 120 \
  --heartbeat-interval 30 \
  --poll-interval 1
```

Use `--max-tasks 1` for a one-task smoke run. SIGINT/SIGTERM stops the polling loop after the current task returns; it does not forcibly terminate an executor.

## Lease and cancellation behavior

- Claim assigns a unique lease token and expiry.
- A separate SQLAlchemy session renews the lease while the executor runs.
- Completion/failure must still present the current lease token; stale workers cannot complete a task after lease loss.
- Cancellation is cooperative. The heartbeat keeps the lease valid while a running executor reaches its return boundary; completion then acknowledges the cancellation instead of persisting success.
- Executors must make external side effects idempotent using task/run identifiers. The runtime cannot roll back side effects in external systems.

## Worker process registry and process fencing (dev.3)

`Worker.run_forever()` registers the process in `worker_instances`, updates its heartbeat independently of task execution, and marks it offline on graceful shutdown. Each registration receives a fresh `instance_token`. Re-registering the same `worker_id` rotates that token and fences the previous process generation. Every registry heartbeat, task heartbeat, pre-claim check and final task-result commit verifies the active token. A fenced process stops polling and cannot mark the replacement offline. Its in-flight `AgentRun`/`SkillRun` records are closed with a `WORKER_GENERATION_FENCED` failure marker; the task itself remains leased until normal expiry/recovery so the fenced process does not rewrite task state. `mark_stale_workers()` identifies processes whose registry heartbeat has expired. Registry heartbeat and task lease heartbeat remain separate mechanisms: the former reports process liveness; the latter protects ownership of one running task.

A configured `worker_id` should still be stable per logical worker slot. If two processes start with the same ID, the later successful registration takes over and invalidates the earlier generation. An already-running external side effect cannot be rolled back; executors must remain idempotent and the old task lease is recovered through normal expiry/retry.

## Outbox and Inbox delivery (dev.3)

`OutboxPublisher` claims events with a database lease, calls the configured publisher callback outside the transaction, then acknowledges success or records a bounded retry with exponential backoff. Expired claims are recovered. Once `max_attempts` is exhausted, the event enters `dead` state. The runnable webhook adapter is `scripts/run_outbox_publisher.py`.

Delivery is at-least-once, not exactly-once. The publisher sends a stable `Idempotency-Key`; the remote receiver must deduplicate it. `InboxConsumer` provides consumer-scoped idempotency and commits handler side effects together with the processed receipt. It uses atomic `INSERT ... ON CONFLICT DO NOTHING` on PostgreSQL and SQLite, then reads/locks the winning receipt; concurrent deliveries of the same key therefore execute the handler once when the transaction commits successfully. An inbound HTTP/broker adapter and authentication are intentionally deployment-specific; do not expose the consumer through an unauthenticated endpoint.

Terminal task failures and exhausted task leases create a `task_dead_letters` record containing the task input snapshot and final error. Resolution is explicit and not an automatic retry.

## Explicit limitations

- PostgreSQL `SKIP LOCKED` multi-worker behavior, concurrent Inbox delivery and live migrations have not yet been executed against a live PostgreSQL server in this development environment. Offline PostgreSQL SQL generation is only a review artifact.
- The PostgreSQL 16 CI workflow is authored but has not been run from this environment. Eight PostgreSQL-only tests remain skipped locally.
- Redis is not used; PostgreSQL is the durable queue/lease authority.
- Process-generation fencing is implemented, but fencing cannot reverse external side effects already emitted by an in-flight executor; those effects require idempotency.
- There is no process supervisor, autoscaler, or production observability stack.
- Executors run in-process (a dedicated thread is used so the worker can renew leases). This is not a hardened sandbox and must not execute untrusted code.
- No external LLM/image/video/audio provider is enabled by this slice.
- The Footage-Mode worker imports and validates the existing 8.1 result; it does not rerun the optimizer or generate new shots.

## Crash recovery and durable orchestration (dev.4)

When `reap_expired_leases()` recovers an expired task lease, it also locks and closes any `AgentRun` and `SkillRun` records still in `queued` or `running`. These abandoned attempt records are marked `interrupted` and receive a `WORKER_LEASE_EXPIRED` marker plus recovery timestamp. If cancellation was requested, the run records are marked `cancelled`. The task itself follows its normal retry policy (`retry_wait`, `failed` plus dead letter, or `cancelled`). A subsequent attempt creates new run records; the previous attempt is never silently rewritten as a success.

Orchestration plans now retain stable `step_key` values, dependency keys, materialized `task_id`, output/error snapshots and timestamps. `materialize_plan_tasks()` creates one project-scoped idempotent task per step and writes corresponding `task_dependencies` edges. It can be called again safely: existing step task IDs are reused and missing dependency edges are repaired. `refresh_plan_status()` reconstructs plan/step state from task rows, so a process restart does not rely on in-memory progress.

The dev.4 integration test exercises three distinct specialist Agents in sequence: Script Director → Visual Director → Shot Director. Each step pins an exact AgentVersion and exact SkillVersion binding; the database task DAG blocks later steps until prerequisites succeed. The test uses deterministic local executors. Production provider execution and agent decision policy remain separate future work.


## Executive Director planning and human approval (dev.5)

`propose_plan_from_request()` is the provider-neutral handoff from the Executive Director to the durable orchestrator. It receives a project/task request and an injected `planning_strategy(request, capability_catalog)` callable. The capability catalog is built only from active Agents and Skills connected by an exact `AgentSkillBinding`, and it exposes immutable AgentVersion/SkillVersion IDs and digests. The strategy returns a JSON DAG using capability keys rather than arbitrary executable names. Each requested capability must resolve to exactly one active bound AgentVersion/SkillVersion pair; missing or ambiguous matches stop proposal creation rather than silently selecting a substitute.

The strategy is an adapter seam: a future Executive-Director Agent can call an LLM or other reasoning provider and return the same structured plan draft. This foundation slice itself does not call a model, infer semantic capabilities, or dynamically load code. The strategy is supplied by the host runtime and tested with a deterministic local function.

Every proposal is saved as a `draft` with `approval_status=pending` and a canonical SHA-256 digest over its snapshot. `decide_plan_approval()` accepts only `actor_kind=human` and requires an active project membership with owner, producer or director role. Approval/rejection is appended to `audit_logs`. `materialize_plan_tasks()` refuses pending/rejected plans and rechecks the snapshot digest before creating tasks. A changed approved snapshot requires a new plan proposal; it is not silently overwritten. The caller must supply the authenticated principal ID; production authentication and RBAC enforcement at the API boundary remain deployment work.

This is intentionally a two-stage control plane: the AI Executive Director proposes and coordinates; a human approves the execution plan; the Worker runtime executes exact version-bound capabilities. Agents cannot approve their own plans.

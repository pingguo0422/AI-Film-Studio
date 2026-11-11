# Executive Director Decision Engine — Foundation 1.5 dev.3

## Purpose

The Executive Director is the coordinating intelligence at the center of AFS. It does not
replace specialist Agents, Skills, or human creative authority. Its job in this increment is
to maintain a reliable view of project execution and produce actionable, evidence-backed
decision proposals.

## Implemented service

`backend/app/services/director_decision_engine.py`

```python
from backend.app.services.director_decision_engine import build_director_brief

brief = build_director_brief(
    db,
    project_id=project_id,
    stale_after_seconds=900,
    max_records=500,
)
```

The service reads a bounded project snapshot from durable AFS records and emits:

- task status counts and project-level risk counts;
- failed tasks, stale running tasks, expired leases, and blocked dependencies;
- DAG violations where a task is running before prerequisites succeed;
- multiple active AgentRuns attached to the same task;
- quality rework and escalation decisions;
- orchestration plans awaiting/rejected by human approval;
- evidence references, severity, proposed action, and required approval class;
- deterministic state and brief SHA-256 digests.

## Authority boundaries

The engine is `read_only_proposal` by design. It does not perform retries, lease recovery,
worker reassignment, plan mutation, plan approval, asset locking, or modification of
completed artifacts. Suggested recovery actions must be executed through their existing
service contracts and permission checks. Plan approvals remain human-only.

## Safety and consistency

- Queries are scoped to one `project_id`.
- `max_records` is a hard cap; exceeding it raises an error instead of producing a partial brief.
- The brief identifies the exact observed state with a SHA-256 digest.
- Evidence references point to task, plan, evaluation, and AgentRun IDs.
- The result is deterministic for an identical state and fixed `now` timestamp.
- No public API endpoint is exposed in this increment. Authentication, project membership
  authorization, and audit controls must be in place before exposing project briefs remotely.

## Not yet implemented

- LLM-assisted strategic reasoning or conflict negotiation. The current engine is deterministic.
- Automatic plan repair or replanning. The engine only recommends and routes decisions.
- Human approval UI, notification delivery, and a persistent decision-case workflow.
- Cross-project portfolio optimization and production SLA policy.
- Live PostgreSQL execution and concurrency/load verification in this environment.


## Foundation 1.5 dev.4 — persisted decision cases

`create_decision_cases_from_brief()` validates the read-only brief digest and persists one project-scoped case per recommendation. Each case pins the source brief digest, source state digest, recommendation snapshot, severity, approval class and evidence references. Equivalent recommendations for the same state and proposal digest converge on the same case; changed state or recommendation content creates a new traceable snapshot.

`decide_director_case()` records one of `approved`, `rejected`, `deferred` or `closed`. It requires a human actor and an active project membership. `owner` can decide all classes; `producer`/`director` can decide human-required and director-review cases; system-recovery cases require `owner` or `producer`. Decisions are conditional transitions from `open` and are recorded in `audit_logs`.

An `approved` decision is an authorization record only. It does not run the suggested recovery, reassign a Worker, retry a task, approve a plan, lock an asset, or change a creative artifact. Proposal snapshots cannot be updated or deleted through direct database writes. No public API route is exposed in dev.4.

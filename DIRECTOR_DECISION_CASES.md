# Director Decision Cases — Foundation 1.5 dev.4

## Purpose

The Executive Director's deterministic brief is a read-only diagnosis. dev.4 adds a durable decision layer so recommendations can be reviewed, authorized, deferred or rejected without granting the AI authority to execute production actions.

## Lifecycle

1. `build_director_brief()` observes a bounded, project-scoped state snapshot and emits recommendations with evidence references and SHA-256 digests.
2. `create_decision_cases_from_brief()` verifies the brief digest and persists each recommendation as a `DirectorDecisionCase`.
3. The case pins `source_brief_sha256`, `source_state_digest`, recommendation code, severity, approval class, evidence references and the exact recommendation snapshot.
4. Equivalent recommendations for the same state and proposal digest converge on one project-scoped case key. Changed state or changed recommendation content creates a new case.
5. An authorized human may decide `approved`, `rejected`, `deferred` or `closed` once while the case is `open`.
6. Every decision writes an `AuditLog` record in the same transaction.

## Authorization

- `actor_kind` must be `human`; Agents cannot decide.
- The principal must have an active `ProjectMember` row.
- `owner` can decide all approval classes.
- `producer` and `director` can decide `human_required` and `director_review` cases.
- `producer` can decide `system_recovery` cases; `owner` can also decide them.
- Informational (`not_required`) cases can be dispositioned by owner, producer or director.

Membership rows are selected with a row lock where supported. The decision transition is an atomic conditional update from `open`, so a second/competing decision fails closed.

## Immutability and audit

The proposal/evidence/source fields cannot be updated, and cases cannot be deleted, by direct database writes. SQLite triggers and PostgreSQL triggers are created by migration `a41d7c2e9b60`. A database check constraint ensures terminal status, decision, actor and timestamp fields are consistent.

The mutable fields are limited to the one-time disposition: `status`, `decision`, `decided_by`, `decision_note` and `decided_at`. The service writes a corresponding audit record. The decision audit details explicitly state `execution_performed=false`.

## Authority boundary

`approved` means the human authorized the recommendation for a later, separately governed action pathway. It does not itself retry a task, recover a lease, reassign a Worker, approve an orchestration plan, lock an asset, or alter a creative output. The case service is not exposed through an API route in dev.4 because production API authentication and project authorization are not yet complete.

## Validation

- Unit and integration tests cover digest verification, project isolation, idempotency, role checks, Agent rejection, one-time decisions, audit logging, no action execution, snapshot immutability and no-delete retention.
- Final local suite: 106 passed, 10 PostgreSQL-only skipped.
- SQLite migration upgrade/check/downgrade/re-upgrade: PASS.
- PostgreSQL trigger SQL is generated for review; live PostgreSQL execution remains unverified.

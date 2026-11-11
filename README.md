# AI Film Studio — Foundation 1.5 Development Workspace

**Build:** `1.5.0-dev.17`  
**Status:** Live browser-to-API/PostgreSQL acceptance workflow implemented in CI; local API workflow smoke passed on SQLite; CI/live PostgreSQL execution pending; not accepted for production.

AFS remains agent-first: Agents are the decision-making and collaboration core; Skills are versioned professional capabilities; models are replaceable tools; the platform provides project, asset, version, execution and human-approval governance. Footage-Mode remains an independent specialist package connected only through `integrations/footage_mode/`.

## Foundation 1.5 dev.1 baseline

The prior dev.1 capabilities remain; see `WORK_LOG.md` and `EXECUTIVE_ORCHESTRATOR.md`.

## Foundation 1.5 dev.2 scope

- Added a richer exact-version capability registry. AgentVersion profiles can declare specialties, tags, modalities, languages, supported task types and quality rubric metadata; SkillVersion capabilities remain the callable professional skills. Capability selection can constrain tags, modality, language, task type and excluded Agent codes. Ambiguous matches fail closed.
- Extended Executive Director planning to resolve constrained requirements without bypassing the exact `AgentSkillBinding` relation or human plan approval.
- Added idempotent project-scoped Agent-to-Agent handoff messages using `agent_messages`. Reusing an idempotency key with different content is rejected.
- Added durable `AgentEvaluation` records and deterministic weighted quality gates. A different Agent identity must review the output. Outcomes are `accepted`, `rework` or `escalate`; reviewer version, rubric, score, findings and required changes are retained.
- Added rework task creation with source input/output snapshots, explicit change instructions, incremented rework-round metadata, dependency on the completed source task and idempotent reuse.
- Added an OpenAI-compatible Chat Completions adapter with environment-only credentials, normalized provider failures and a deterministic fake adapter explicitly marked `test_fake`. No live provider call is claimed.
- Added strict model-backed semantic rubric validation and persistence through the independent Agent evaluation path.
- Added task-scoped context assembly with project/sensitivity/task filtering, source-version provenance and hard size limits.
- Rework now computes transitive downstream impact and gates queued/retry-wait descendants behind the rework task; running/terminal work is surfaced for human replanning.
- Added migration `9c6e2a41b7d0` for quality evaluations and message idempotency.

## Run locally

```bash
python -m venv .venv
source .venv/bin/activate
pip install -e '.[test]'
export AFS_DATABASE_URL='sqlite+pysqlite:///./afs_dev.db'
alembic upgrade head
pytest -q
```

For PostgreSQL 16 integration, configure `AFS_DATABASE_URL` and `AFS_TEST_POSTGRES_URL`, apply migrations, then run the full suite. The repository includes `.github/workflows/postgres-integration.yml` for CI, including a Chromium browser workflow against the live FastAPI service.

## Verification boundaries

Local verification for dev.16: **141 passed, 12 skipped**. The skipped PostgreSQL-only tests require a live PostgreSQL URL. Fresh SQLite migration, drift check, downgrade and re-upgrade passed. PostgreSQL 16 offline SQL was generated for review only; no live PostgreSQL migration or concurrency test is claimed. The live HTTP API approval-to-execution smoke passed on SQLite; the live Chromium/PostgreSQL CI workflow is authored but has not yet been executed.

The deterministic weighted-rubric mechanism remains the persistence/decision gate. A semantic reviewer can now supply its rubric through an explicitly selected model adapter; tests use a fake adapter, and no live model request was made in this environment. The injected Executive Director planning strategy remains provider-neutral and is not itself an LLM integration. Evaluation snapshots are immutable by service convention, but general database-level update prevention is not yet installed; the rework task link is a one-time service-managed association.

The Outbox publisher remains at-least-once; receivers must deduplicate by idempotency key. Worker generation fencing cannot reverse external side effects already emitted by an in-flight executor. Production auth/RBAC/RLS, hardened sandboxing, process supervision/autoscaling and production observability remain out of scope. Footage-Mode 8.1 output is imported and validated; the optimizer is not rerun.

See `MODEL_AND_CONTEXT_RUNTIME.md`, `EXECUTIVE_ORCHESTRATOR.md`, `CODE_REVIEW.md`, `RELEASE_STATUS.md`, `TEST_REPORT.md`, `WORK_LOG.md`, `WORKER_RUNTIME.md` and `DB_SCHEMA.md`.


## Foundation 1.5 dev.3 — Executive Director decision engine

This increment adds a deterministic, read-only Executive Director decision brief service.
It correlates durable task state, dependency readiness, Worker leases, active AgentRuns,
quality evaluations, and orchestration-plan approval state into evidence-linked proposals.

- Service: `backend/app/services/director_decision_engine.py`
- Entry point: `build_director_brief(db, project_id=..., now=...)`
- Detects failed/stale/lease-expired tasks, dependency blocks, DAG execution conflicts,
  duplicate active AgentRuns, quality rework/escalation, and plans awaiting human approval.
- Output includes deterministic state and brief SHA-256 digests, evidence references,
  severity, proposed action, and explicit approval requirements.
- It is intentionally read-only: it does not retry tasks, seize leases, modify plans,
  approve plans, rewrite completed outputs, or lock assets.
- API exposure is deferred until authenticated project-level authorization is implemented.

See `EXECUTIVE_DIRECTOR_DECISION_ENGINE.md` and `RELEASE_STATUS.md`.


## Foundation 1.5 dev.4 — Director Decision Case & Human Review Workflow

- Persists each Executive Director recommendation as a project-scoped decision case.
- Pins the exact source brief digest, source state digest, recommendation snapshot, severity, approval class and evidence references.
- Equivalent recommendations from the same state and proposal digest are idempotent; changed state or recommendation snapshots create new traceable cases.
- Human decisions (`approved`, `rejected`, `deferred`, `closed`) require active persisted project membership and role-specific authorization.
- Every decision appends an audit log record. AI/Agent principals cannot decide.
- Proposal snapshots are protected against update and deletion by SQLite/PostgreSQL database triggers; decision-state consistency is enforced by database constraints.
- `approved` records authorization only. No task retry, lease recovery, worker reassignment, plan approval, asset lock or creative mutation is executed by this service.
- Decision brief collection and total-snapshot caps now include dependency edges; state digests include additional decision-relevant task, evaluation and AgentRun fields.

See `DIRECTOR_DECISION_CASES.md` and `RELEASE_STATUS.md`.


## Foundation 1.5 dev.5 — Model-backed Executive Director planning

- Added provider-neutral model-backed production planning through the explicit ModelAdapter registry.
- Model output is bounded, treated as untrusted, locally validated, matched to exact active Agent/Skill versions, and persisted as a draft pending human approval.
- No plan approval, task materialization, Worker invocation or creative asset mutation is performed by the model planner.

See `EXECUTIVE_DIRECTOR_AGENT.md` and `RELEASE_STATUS.md`.

## Foundation 1.5 dev.6 — Authentication and project RBAC

- Added stable human/service Principal identities and opaque API bearer tokens stored only as SHA-256 digests.
- Added bounded token expiry, self-revocation and an out-of-band operator provisioning command.
- Backfilled legacy project-member identities and added a restrictive principal foreign key.
- Added centralized project role permissions and authenticated identity/project membership endpoints.
- Added membership audit records, owner-role escalation protection and last-owner safeguards.

See `AUTHENTICATION_AND_PROJECT_RBAC.md`, `CODE_REVIEW.md` and `RELEASE_STATUS.md`. This is not yet OIDC/SAML, interactive login, MFA, RLS or production security certification.


## Foundation 1.5 dev.7 — Authenticated Executive Director Review API

- Added project-scoped decision inbox listing with status filtering and bounded offset pagination.
- Added decision detail responses exposing recommendation snapshots, evidence references and source provenance digests.
- Added human-only disposition endpoint for approve/reject/defer/close.
- Reuses dev.6 bearer identity, centralized project RBAC and case-specific domain authorization.
- Decision and audit entry commit in one transaction; conditional state transition prevents duplicate dispositions.
- Approval remains authorization only: this API does not materialize tasks, dispatch Workers or mutate creative assets.
- No schema migration was required.

See `EXECUTIVE_DIRECTOR_REVIEW_API.md`, `CODE_REVIEW.md`, `TEST_REPORT.md` and `RELEASE_STATUS.md`.


## Foundation 1.5 dev.8 — Executive Director Review & Control Center

- Added the same-origin browser UI at `/control-center/` for project connection, decision inbox, recommendation detail, evidence/provenance review and human decisions.
- Added a bounded read-only Agent/task/audit activity timeline with sensitive payloads excluded.
- Added restrictive CSP and browser security headers; UI tokens remain in tab-scoped `sessionStorage`.
- No schema migration and no approved-action executor. Human approval does not execute production actions.

See `EXECUTIVE_DIRECTOR_CONTROL_CENTER.md` for local launch instructions and security boundaries.


## Foundation 1.5 dev.9 — Action Authorization & Execution Gateway

- Human approval can bind an exact validated action snapshot to a director decision case.
- Added one-time, idempotent execution records and an authenticated execution endpoint.
- Allowlisted actions: create a queued production task; request rework through the existing quality-evaluation gate.
- The execute endpoint accepts only an idempotency key and cannot replace the approved payload.
- No inline Worker dispatch or external side effect is performed. Agent assignment is deferred until scheduler-enforced exact AgentVersion routing exists.

See `ACTION_AUTHORIZATION_GATEWAY.md`, `CODE_REVIEW.md`, `TEST_REPORT.md` and `RELEASE_STATUS.md`.


## Foundation 1.5 dev.10–dev.12 — Operator execution workflow and reliability

- dev.10 connected approval-bound action snapshots to the Director Control Center; approval and execution remain separate human actions.
- dev.11 added an 8-way PostgreSQL same-idempotency-key execution contract.
- dev.12 adds a repeatable PostgreSQL 16 local integration harness and an 8-way distinct-key race test proving the intended case-level single-execution invariant when run against PostgreSQL.
- Run `scripts/run_postgres_integration.sh` with Docker Compose v2 to start PostgreSQL 16, apply migrations, check drift, and run the full test suite. Set `AFS_POSTGRES_PASSWORD` and optionally `AFS_POSTGRES_PORT` first; the harness retains its named database volume by default.
- The dev.12 local run did not have Docker or a live PostgreSQL server; PostgreSQL-only tests remain skipped and must be run before acceptance.

See `DEV12_RELEASE_NOTES.md`, `CODE_REVIEW_DEV12.md`, `TEST_REPORT_DEV12.md` and `RELEASE_STATUS.md`.


## Foundation 1.5 dev.13 — Action execution security gates

- Adds negative-path API regression tests for archived projects and non-human service principals.
- Confirms rejected execution attempts do not create tasks, execution rows, or execution audit events.
- Preserves the dev.12 PostgreSQL 16 integration harness and concurrent same-case execution tests.
- Local result: 141 passed / 12 skipped. Live PostgreSQL and browser E2E remain unexecuted and are release gates.

## dev.14 browser workflow validation

See [`BROWSER_E2E.md`](BROWSER_E2E.md) for the optional Chromium UI workflow test. It exercises the shipped Control Center frontend with deterministic mocked API responses. Backend persistence and authorization remain covered by pytest; live PostgreSQL integration remains a separate release gate.


## Foundation 1.5 dev.17 — Python package discovery fix

The editable-install failure observed in GitHub Actions was caused by setuptools auto-discovering multiple top-level directories. `pyproject.toml` now explicitly includes only the intended Python packages (`backend` and `integrations`, including subpackages) and excludes tests, frontend assets, generated artifacts, and source-baseline materials from package discovery. The application version is aligned to `1.5.0-dev.17`.

## Foundation 1.5 dev.16 — Live operator integration acceptance path

- Adds an isolated PostgreSQL-backed browser E2E seeder that creates a disposable project, human operator, short-lived API token and open director decision case.
- Adds a Chromium runner that visits the real HTTP-served Control Center and uses persisted bearer authentication and real API endpoints for inbox, approval, execution, readback and activity timeline.
- Extends PostgreSQL CI to apply migrations, check drift, run PostgreSQL-enabled pytest and the mocked UI regression, start FastAPI and run the live browser workflow in one job.
- Retains the dev.14 mocked browser test as a separate UI-only check; mocked and live integration results are not interchangeable.
- Local tests: 141 passed / 12 skipped. Local HTTP API approval → execution → readback → timeline smoke passed against SQLite. Live PostgreSQL and Chromium browser execution are still pending CI.

See `DEV15_RELEASE_NOTES.md`, `BROWSER_E2E.md`, `CODE_REVIEW_DEV15.md`, `TEST_REPORT_DEV15.md` and `RELEASE_STATUS.md`.


## Foundation 1.5 dev.16 — Decision review continuity fix

After a human disposition, the Control Center now changes the inbox filter to the resulting status before refreshing. This preserves the selected case detail and keeps the separately confirmed execution action available. The mocked Chromium regression now models status-filtered results, so the previous bug is exercised rather than hidden by an always-returned mock item. The live browser runner also accepts `AFS_CHROMIUM_EXECUTABLE`.

The dev.16 local mocked Chromium workflow was executed with the system Chromium and passed. Full pytest remains 141 passed / 12 PostgreSQL-only skips. Live PostgreSQL 16 and browser-to-live-API-over-PostgreSQL acceptance still require the GitHub Actions workflow to run; this environment blocks Chromium navigation to the local FastAPI server.

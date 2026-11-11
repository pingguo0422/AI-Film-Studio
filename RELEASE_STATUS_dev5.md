# AFS Foundation 1.5 dev.5 — Release status

**Status: IMPLEMENTED / EXECUTED / TESTED (local SQLite + FakeModelAdapter); NOT ACCEPTED; NOT PRODUCTION READY.**

## Added in dev.5

- Added the first model-backed Executive Director planning service using the provider-neutral `ModelAdapterRegistry`.
- Added explicit provider/model routing; no implicit model selection.
- Added bounded production requests, capability catalogs, step counts and step input payloads.
- Added strict local validation for planner output, identifiers, dependencies, reserved orchestration fields and JSON-compatible values.
- Reused the existing exact AgentVersion/SkillVersion capability resolver and deterministic DAG/cycle validation.
- Persisted pending, draft orchestration plans with provider/model/request/correlation and request/catalog/output SHA-256 provenance.
- Preserved the human approval gate; dev.5 does not approve plans, materialize step tasks, invoke Workers or modify creative assets.

## Verification

- Python compilation: PASS.
- Full automated suite: **114 passed, 10 skipped**.
- The 10 skipped tests require `AFS_TEST_POSTGRES_URL`; no live PostgreSQL service was available.
- Fresh SQLite Alembic upgrade to head: PASS.
- SQLite Alembic drift check: PASS — no new upgrade operations detected.
- Model-planning tests use `FakeModelAdapter` and validate pending-plan persistence, provenance, rejection of invalid output, unknown capabilities, dependency cycles, reserved fields and explicit provider/model registration.
- Live external model-provider call: NOT RUN.
- Live PostgreSQL migration/concurrency validation: NOT RUN.

## Governance and safety boundary

- Model output is an untrusted proposal and is validated locally.
- Capability selection must resolve to an exact active AgentVersion/SkillVersion binding.
- A plan remains `draft` with `approval_status=pending`.
- Human approval is separate and must be performed through the existing approval service.
- Plan approval is not performed by the model-backed planning service.
- No public planning endpoint was added because API AuthN/AuthZ and project RBAC/RLS are not complete.

## Remaining gaps

- Authenticated human-facing Director planning/review inbox and API.
- Live provider contract tests, provider cost/latency controls, cancellation and credential-vault integration.
- Live PostgreSQL 16 migration, locking and concurrency verification.
- Multi-Agent negotiation, iterative replanning, semantic quality review and conflict resolution.
- Explicit approved-action executors with policy checks, idempotency and audit.
- Deployment hardening, observability, load testing and production acceptance.

This is a development increment and a planning vertical slice, not a complete autonomous Executive Director and not production-readiness certification.

## 1.5.0.dev18

- Pin the PostgreSQL/browser GitHub Actions job to `ubuntu-24.04` for a stable runner image.
- Install the Playwright-managed Chromium binary without `--with-deps`, avoiding an unnecessary apt package-index/DNS dependency in the browser-install step.
- Add an explicit headless Chromium launch and DOM smoke check before database and browser integration tests.
- Keep PostgreSQL 16 migrations, migration drift checks, the full PostgreSQL test suite, mocked UI regression, and live browser-to-API-to-PostgreSQL E2E in the workflow.
- Align package and FastAPI application versions with `1.5.0.dev18`.

## 1.5.0.dev17

- Fix setuptools editable-install failure by explicitly configuring package discovery for `backend` and `integrations`.
- Exclude non-package project directories (`tests`, `frontend`, `artifacts`, and `source-baseline`) from Python package discovery.
- Align FastAPI application version with package version `1.5.0.dev17`.
- Validate editable build metadata and package imports locally; PostgreSQL and live browser acceptance remain pending GitHub Actions.

## 1.5.0.dev16

- Keep the reviewed decision case visible after a disposition by switching the inbox filter to the resulting status; prevents the approved-action execution control from disappearing after approval.
- Extend the mocked Chromium regression to model status-filtered inbox results and assert that the approved detail and second-confirmation execution control remain available.
- Allow the live Chromium runner to use `AFS_CHROMIUM_EXECUTABLE` for environments with a system browser.
- Harden CI with explicit read-only repository permissions and a bounded job timeout.

# Changelog

## 1.5.0-dev.9

- Added human-approved immutable action snapshots to director decision cases.
- Added Action Authorization & Execution Gateway with allowlisted `create_task` and `request_rework` actions.
- Added one-time per-case execution and project-scoped idempotency controls.
- Added atomic execution records and audit events.
- Added action gateway integration tests and migration `d9a4f2c8b710`.
- Explicitly deferred Agent assignment pending scheduler-enforced exact AgentVersion routing.

## 1.5.0.dev14

- Added a Chromium browser workflow test for the Executive Director Control Center (actual frontend assets; deterministic mocked API responses).
- Added browser E2E setup and scope documentation.
- Aligned API and health version reporting with dev.14.
- No database schema or action authorization scope changes.

## 1.5.0.dev15

- Added disposable PostgreSQL-backed live browser E2E seed workflow.
- Added Chromium browser test against the real FastAPI Control Center and persisted API workflow.
- Extended PostgreSQL 16 CI to run migrations, full PostgreSQL tests, and live browser-to-API acceptance.

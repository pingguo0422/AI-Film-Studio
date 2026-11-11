# AFS Foundation 1.5 dev.18 — Release Notes

## Purpose

Address the dev.17 GitHub Actions failure at `Install Chromium`. The supplied runner log showed `playwright install --with-deps chromium` invoking Ubuntu apt and failing to resolve `azure.archive.ubuntu.com`, `archive.ubuntu.com`, and `security.ubuntu.com`. This was an environment package-source DNS failure, not an AFS application exception.

## Changes

- Pin the workflow runner to `ubuntu-24.04` instead of the moving `ubuntu-latest` label.
- Replace `python -m playwright install --with-deps chromium` with `python -m playwright install chromium`; this downloads the Playwright-managed browser but does not invoke apt to install OS packages.
- Add `scripts/check_chromium_launch.py`, which launches headless Chromium, renders a local page, and checks its title and DOM before the PostgreSQL and live browser tests.
- Preserve the PostgreSQL 16 service, Alembic migration and drift checks, complete PostgreSQL-enabled pytest suite, mocked UI regression, seeded live workflow, live FastAPI server, and real browser/API/database E2E.
- Align package and FastAPI versions to `1.5.0.dev18`.

## Validation boundaries

The change is implemented in this package. Local source-level checks and the available test suite are recorded in `TEST_REPORT_DEV18.md`. The hosted GitHub Actions run is required to verify browser download and launch on the pinned runner, real PostgreSQL 16 behavior, and live browser-to-API-to-PostgreSQL behavior.

`ACCEPTED`: NO. `PRODUCTION READY`: NO.

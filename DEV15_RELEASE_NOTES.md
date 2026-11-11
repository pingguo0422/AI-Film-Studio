# AFS Foundation 1.5 dev.15 — Release Notes

## Objective

Move the Executive Director Control Center from a mocked browser workflow to a repeatable browser-to-live-FastAPI-to-PostgreSQL integration acceptance path.

## Delivered

- Added `scripts/seed_live_browser_e2e.py` to create an isolated project, human principal, owner membership, API token, and open decision case in the configured integration database.
- The bearer token is written only to a mode-0600 env file and is never printed by the seeder.
- Added `scripts/run_control_center_live_e2e.py` to navigate Chromium to the real HTTP-served Control Center and exercise authenticated inbox/detail, human approval, exact action snapshot binding, separate explicit execution, execution readback, and activity timeline.
- Upgraded the PostgreSQL GitHub Actions workflow to install Chromium, apply real PostgreSQL 16 migrations, check drift, run the full PostgreSQL-enabled test suite and mocked UI regression, start FastAPI, and run live browser E2E.
- Retained the dev.14 mocked browser test as a separate deterministic UI-only check.
- Updated package/API/health versions to `1.5.0.dev15`.

## Local verification scope

The current execution environment may block Chromium navigation to local HTTP origins and has no Docker daemon. Therefore the live browser/PostgreSQL workflow is implemented but must be executed by CI or another suitable environment. Do not claim live integration success from local syntax checks or mocked UI tests.

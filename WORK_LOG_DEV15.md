# Work Log — dev.15

1. Created dev.15 as an independent copy of dev.14; prior release directories remain unchanged.
2. Added an isolated PostgreSQL-backed browser E2E seeder. Raw bearer token is emitted only into a mode-0600 temporary env file.
3. Added a Chromium live E2E runner that uses the shipped Control Center over HTTP and real authenticated FastAPI endpoints.
4. Expanded CI to provision PostgreSQL 16, apply migrations, check drift, run PostgreSQL-enabled pytest, launch FastAPI, and execute the live browser flow.
5. Kept mocked Chromium UI test explicitly separate from live integration acceptance.
6. Updated app/package version to 1.5.0.dev15.
7. Local execution and remaining environment limitations are recorded in TEST_REPORT_DEV15.md and RELEASE_STATUS.md.

# AFS Foundation 1.5 dev.14 — Release Notes

## Objective

Add a repeatable Chromium browser workflow check for the Executive Director Control Center without weakening the existing backend authorization and persistence gates.

## Delivered

- Added `scripts/run_control_center_browser_e2e.py`.
- The test loads the actual shipped `index.html`, `app.css`, and `app.js` in Chromium.
- Covers project connection, inbox selection, action payload binding during approval, the separate explicit execute confirmation, execution result rendering, and activity timeline rendering.
- Uses deterministic mocked API responses because the current execution environment blocks Chromium navigation to local HTTP/file URLs. The test does not claim real HTTP or DB integration.
- Added `BROWSER_E2E.md` with setup, execution and scope boundaries.
- Added optional `e2e` dependency group (`playwright`).
- Updated package, API and health versions to `1.5.0.dev14`.

## Verification

- Browser UI E2E: PASS (Chromium; mocked API)
- Full pytest: 141 passed / 12 skipped
- Python compile: PASS
- Frontend JavaScript syntax: PASS
- PostgreSQL integration shell syntax: PASS
- SQLite fresh migration / drift check / downgrade / re-upgrade: PASS
- PostgreSQL offline migration SQL generation: PASS (not a live DB test)
- Health, Control Center and OpenAPI smoke checks: PASS

## Not accepted

- Live PostgreSQL 16 migration and concurrency tests remain unexecuted.
- API persistence was not exercised from Chromium in this browser run; it is covered by the independent pytest API/service tests.
- Network deployment/browser security policy and penetration testing remain unexecuted.
- Human acceptance and production readiness: NO.

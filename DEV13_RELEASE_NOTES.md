# AFS Foundation 1.5 dev.13 — Action Execution Security & Recovery Gates

## Scope

This increment does not add new action types or broaden Agent autonomy. It hardens the human-authorized execution boundary with negative-path API tests.

## Changes

- Added an API regression test proving an archived/inactive project cannot execute an otherwise approved action.
- Asserted that this rejected attempt creates no ActionExecution, Task, or `DIRECTOR_ACTION_EXECUTED` audit row.
- Added an API regression test proving a service principal cannot execute an approved action even if it has an owner membership record.
- Updated package and health endpoint version to `1.5.0.dev13`.
- Preserved dev.12 PostgreSQL integration harness and concurrency tests unchanged.

## Verification

- Full local test suite: see `TEST_REPORT_DEV13.md`.
- PostgreSQL-only integration tests remain dependent on a live PostgreSQL 16 service and are not claimed as executed in this environment.
- No browser E2E or production deployment is claimed.

## Status

IMPLEMENTED / EXECUTED (local SQLite-backed API tests and static checks) / TESTED (local suite)
NOT EXECUTED (live PostgreSQL 16) / NOT ACCEPTED / NOT PRODUCTION READY

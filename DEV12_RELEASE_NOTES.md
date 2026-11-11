# Foundation 1.5 dev.12 — PostgreSQL Reliability Harness

## Scope

This increment strengthens reproducibility and coverage of the human-authorized Executive Director action path. It does not expand the action allowlist or grant Agents autonomous execution authority.

## Changes

- Added `compose.postgres.yml`, a dedicated PostgreSQL 16 test service with a persistent named volume and health check.
- Added `scripts/run_postgres_integration.sh` to start the database, verify connectivity, apply Alembic migrations, check migration drift, and run the full suite with PostgreSQL-only tests enabled.
- Added an 8-way PostgreSQL contract test in which distinct idempotency keys race to execute the same approved decision case. Expected invariant: exactly one execution, one task, and seven conflicts.
- Retained the dev.11 8-way same-idempotency-key test. Expected invariant: one execution result is replayed to all callers and only one caller creates it.
- Updated package and API health version to `1.5.0.dev12`.

## Verification

- Local suite: 139 passed, 12 skipped. All 12 skipped tests require `AFS_TEST_POSTGRES_URL`.
- Python compile, frontend JavaScript syntax, shell syntax: passed.
- SQLite fresh migration, `alembic check`, downgrade one revision, and re-upgrade: passed.
- PostgreSQL 16 offline migration SQL generated: passed (1,208 lines); this is not a live PostgreSQL migration.
- Docker/PostgreSQL runtime was unavailable in this execution environment. The local runner and CI workflow are implemented but have not been executed here.

## Status

IMPLEMENTED / EXECUTED (local SQLite and static checks) / TESTED (local suite)
NOT EXECUTED (live PostgreSQL 16) / NOT ACCEPTED / NOT PRODUCTION READY

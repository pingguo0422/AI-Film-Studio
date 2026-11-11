# Work Log — AFS Foundation 1.5 dev.13

1. Confirmed dev.12 source directory and preserved it unchanged.
2. Created dev.13 as an independent copy.
3. Re-ran dev.12 baseline suite: 139 passed / 12 skipped.
4. Added negative-path API tests for archived projects and service principals.
5. Updated package and API health versions to 1.5.0.dev13.
6. Executed full suite: 141 passed / 12 skipped.
7. Executed Python compile, frontend JS syntax, shell syntax, SQLite fresh migration, migration drift, downgrade/re-upgrade, and PostgreSQL offline SQL generation.
8. Confirmed Docker, psql, and pg_isready are unavailable; live PostgreSQL tests remain unexecuted.
9. Generated release report, code review, manifest, build verification log, and ZIP archive.

# Test Report — Foundation 1.5 dev.10

## Automated suite

`pytest -q`: **139 passed, 10 skipped**.

The skipped tests require `AFS_TEST_POSTGRES_URL`; no live PostgreSQL service was available/configured for this run.

## Additional checks

- Python compileall: PASS
- Node syntax check for Control Center app.js: PASS
- SQLite fresh Alembic upgrade: PASS
- SQLite Alembic drift check: PASS — no new upgrade operations detected
- SQLite downgrade one revision + upgrade to head: PASS
- PostgreSQL offline Alembic SQL generation: PASS (not a live database migration)
- FastAPI TestClient health, Control Center HTML, OpenAPI: HTTP 200
- Health reports `1.5.0-dev.10`
- ZIP CRC validation: PASS

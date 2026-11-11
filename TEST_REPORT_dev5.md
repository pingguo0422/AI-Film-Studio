# Test report — AFS Foundation 1.5 dev.5

## Automated tests

```text
python -m compileall -q backend integrations scripts
PASS

pytest -q
114 passed, 10 skipped
```

The 10 skipped tests require a configured PostgreSQL service (`AFS_TEST_POSTGRES_URL`).

## New dev.5 coverage

- Model-backed planning through an explicitly registered provider/model adapter.
- Pending draft plan persistence with provider/model/request/correlation provenance.
- Request and step-input size bounds.
- Rejection of extra top-level output fields.
- Rejection of unknown specialist capabilities.
- Rejection of dependency cycles.
- Rejection of reserved internal orchestration fields.
- Rejection when an explicit provider/model adapter is unavailable.
- No DAG step tasks are materialized during proposal generation.

All model-planning tests use `FakeModelAdapter`; no live provider call is claimed.

## Database checks

- Fresh SQLite `alembic upgrade head`: PASS.
- SQLite `alembic check`: PASS — no new upgrade operations detected.
- dev.5 introduces no schema migration.
- Live PostgreSQL execution: NOT RUN.

## Verification boundaries

No live PostgreSQL server, external model provider, authenticated public API, production deployment, real human approval workflow or Worker execution was exercised. This report does not imply production acceptance.

# Test Report — AFS Foundation 1.5 dev.17

## Executed locally

| Check | Result | Notes |
|---|---|---|
| `pip install -e . --no-deps --no-build-isolation` | PASS | Editable build/install completed |
| `pip install -e ".[test,e2e]" --no-deps --no-build-isolation` | PASS | Extras metadata built successfully |
| Distribution extras metadata | PASS | `test`, `e2e` |
| Distribution top-level packages | PASS | `backend`, `integrations` only |
| `import backend.app.main` | PASS | App version `1.5.0-dev.17` |
| `pytest -q` | PASS | 141 passed, 12 skipped |

## Not executed / not claimed

- Build-isolated `pip install -e ".[test,e2e]"` with dependency downloads: not re-executed locally because this environment could not resolve package indexes.
- Live PostgreSQL 16 migrations and concurrency tests: not executed locally.
- Live Chromium browser-to-FastAPI-to-PostgreSQL E2E: not executed locally.
- GitHub Actions dev.17 workflow: pending user push.
- Human acceptance: not granted.

Additional packaging checks:
- `pip wheel . --no-deps --no-build-isolation`: PASS; wheel contains `backend` and `integrations`, and does not package `tests`, `frontend`, or generated artifacts.
- A local attempt of the dependency-resolving install reached and passed editable metadata preparation, then stopped because this sandbox could not resolve the package index to obtain `psycopg`. This is an environment/network limitation after the original package-discovery stage, not a recurrence of the setuptools discovery error.

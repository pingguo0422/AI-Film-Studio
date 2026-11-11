# Test Report — AFS Foundation 1.5 dev.18

## Executed locally

| Check | Result | Notes |
|---|---|---|
| `pytest -q` | PASS | 141 passed, 12 skipped; skipped tests require live PostgreSQL configuration |
| `python -m compileall -q backend integrations scripts tests` | PASS | Python source compilation |
| GitHub Actions YAML parse | PASS | Confirmed the job and steps parse as YAML |
| `pip wheel . --no-deps --no-build-isolation` | PASS | Wheel built as `afs_foundation-1.5.0.dev18-py3-none-any.whl` |
| Wheel package contents | PASS | Includes `backend` and `integrations`; excludes tests, frontend, and generated artifacts |
| JavaScript syntax checks | PASS | `node --check` on frontend JavaScript files |

## Not executed / not claimed

- Playwright Chromium download: NOT EXECUTED locally; this sandbox has no browser binary and network access is unavailable.
- Chromium launch smoke check: attempted locally but could not launch because the Playwright-managed Chromium executable is not installed in this sandbox. This is an environment limitation, not a passing browser test. The GitHub Actions job installs Chromium before running the smoke check.
- Full build-isolated dependency-resolving `pip install -e '.[test,e2e]'`: NOT REPEATED locally; dependency-index network access is unavailable.
- Live PostgreSQL 16 migrations and concurrency tests: NOT EXECUTED locally.
- Live Chromium browser-to-FastAPI-to-PostgreSQL E2E: NOT EXECUTED locally.
- GitHub Actions dev.18 workflow: NOT EXECUTED; requires user push.
- Human acceptance: NO.

## Interpretation

The local application test suite and package build pass. The specific dev.17 CI failure path is changed so the Chromium install step no longer invokes apt through Playwright `--with-deps`. The remote workflow must still prove that the pinned Ubuntu runner can download and launch Chromium and complete all PostgreSQL and live browser tests.

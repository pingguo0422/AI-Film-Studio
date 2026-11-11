# AFS Foundation 1.5 dev.17 — Release Notes

## Purpose

Fix the first GitHub Actions failure reported for dev.16. The failure occurred during `pip install -e '[test,e2e]'`, before database or browser tests began.

## Root cause

Setuptools automatic flat-layout discovery found multiple top-level directories (`backend`, `frontend`, `artifacts`, `integrations`) and refused to build the editable distribution.

## Change

`pyproject.toml` now explicitly configures package discovery:
- Include `backend`, `backend.*`, `integrations`, and `integrations.*`.
- Exclude tests, frontend assets, generated artifacts, and source-baseline materials.
- Disable implicit namespace-package discovery.

The package and FastAPI application versions are both `1.5.0.dev17`. No application runtime, database schema, authorization, or execution behavior was intentionally changed.

## Validation

- Editable package build/install with `--no-build-isolation --no-deps`: PASS.
- Editable package build/install with extras `.[test,e2e]` and `--no-build-isolation --no-deps`: PASS.
- Installed distribution metadata exposes extras `test` and `e2e`: PASS.
- Discovered top-level Python packages are exactly `backend` and `integrations`: PASS.
- `backend.app.main` import and app version check: PASS.
- Full local pytest suite: 141 passed, 12 skipped. The 12 skips require a live PostgreSQL test URL.

The local environment could not access package indexes, so the exact build-isolated dependency download step was not re-executed here. GitHub Actions must run the unmodified CI command `pip install -e '[test,e2e]'` to confirm in its network-enabled runner. PostgreSQL 16 migration/concurrency and live Chromium-to-API-to-PostgreSQL tests have not yet been executed for dev.17.

## Status

`IMPLEMENTED`: package discovery configuration.
`EXECUTED`: local editable build checks and pytest.
`TESTED`: listed local checks only.
`ACCEPTED`: NO.
`PRODUCTION READY`: NO.

An additional local `pip install -e ".[test,e2e]" --no-build-isolation` attempt passed the editable metadata preparation stage and then could not fetch `psycopg` because the sandbox has no package-index DNS/network access. This is recorded separately from the package-discovery fix. The GitHub Actions runner must perform the full dependency-resolving command.

# Code Review — AFS Foundation 1.5 dev.17

## Scope

Packaging metadata and version alignment only.

## Findings and resolution

- **P1 — ambiguous setuptools package discovery:** resolved by explicitly limiting discovered packages to `backend` and `integrations` and their subpackages.
- **P2 — application/package version mismatch after increment:** resolved by setting both package metadata and FastAPI app version to dev.17.

## Review notes

The package discovery configuration deliberately excludes `tests`, `frontend`, `artifacts`, and `source-baseline`. Frontend files remain in the source checkout for the existing FastAPI static mount; this change controls Python distribution package discovery and does not delete or relocate those assets.

No database migrations, API behavior, authorization rules, action execution semantics, or workflow test definitions were changed.

## Review outcome

The specific reported setuptools discovery failure is addressed by the configuration and local editable-build checks. Remote CI remains required to validate the exact build-isolated install command and subsequent PostgreSQL/browser jobs.

# Release Status — AFS Foundation 1.5 dev.16

**Version:** `1.5.0.dev16`

**Status:** IMPLEMENTED / EXECUTED / TESTED (local SQLite + mocked Chromium UI regression)

**Acceptance:** NOT ACCEPTED

**Production readiness:** NOT PRODUCTION READY

## Implemented

- Preserves selected decision detail after human disposition by switching the inbox to the resulting status.
- Mocked browser regression models status-aware filtering and guards against disappearance of the approved-action execution control.
- Live browser runner supports an explicit system Chromium executable path.
- CI uses read-only repository contents permission and a bounded job timeout.

## Remaining acceptance gates

- Execute PostgreSQL 16 migrations and all PostgreSQL-dependent tests in GitHub Actions.
- Execute Chromium → live FastAPI → PostgreSQL approval, second-confirmation execution, persistence, and activity timeline workflow in GitHub Actions.
- Review the resulting CI logs and artifacts.
- Human acceptance after evidence review.

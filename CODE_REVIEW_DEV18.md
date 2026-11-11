# Code Review — AFS Foundation 1.5 dev.18

## Scope

GitHub Actions runner stability and Playwright browser installation/launch verification. No application authorization, decision, task execution, or database schema behavior is intentionally changed.

## Findings addressed

- **P1 — browser installation depended on apt package sources:** the prior `playwright install --with-deps chromium` invoked apt and failed in the supplied GitHub runner log because Ubuntu repository hostnames could not be resolved. The CI browser-install step now installs only the Playwright-managed Chromium binary and does not invoke apt.
- **P2 — moving runner image:** `ubuntu-latest` resolved to an Ubuntu 26.04/resolute environment in the supplied log. The workflow now pins `ubuntu-24.04`.
- **P2 — no isolated browser launch gate:** a focused smoke script now verifies that Chromium can launch and render a local page before the expensive integration workflow proceeds.

## Preserved safeguards

The workflow still runs real PostgreSQL 16 migrations, migration drift checks, the complete PostgreSQL-enabled pytest suite, the deterministic mocked UI regression, and the live browser-to-FastAPI-to-PostgreSQL workflow. No test stage was removed or marked optional.

## Review limitations

The launch smoke check cannot prove that GitHub's browser CDN download or runner shared-library availability will succeed until the hosted workflow runs. A green workflow is still required for remote validation; human acceptance remains separate.

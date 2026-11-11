# Code Review — dev.15

## Scope reviewed

- `scripts/seed_live_browser_e2e.py`
- `scripts/run_control_center_live_e2e.py`
- `.github/workflows/postgres-integration.yml`
- package and FastAPI version changes
- `BROWSER_E2E.md` and release evidence

## Findings and controls

1. **Disposable data creation:** the seeder creates uniquely named project/principal/case records in the configured database. Documentation and CI scope it to an isolated integration database; it must never target production/shared data.
2. **Bearer token handling:** the token is issued through the production token helper, written to a mode-0600 temporary env file, omitted from stdout, and masked before it enters GitHub Actions environment state. CI token TTL is one day.
3. **Human approval and execution:** the browser workflow submits a human decision with a fixed action payload, waits for the persisted approved state, then requires a separate UI confirmation to execute.
4. **Readback:** the runner independently reads the approved case, execution record and activity timeline through authenticated HTTP APIs.
5. **Test separation:** the previous mocked browser test remains explicitly UI-only. The new live runner does not stub `fetch` and navigates to the actual HTTP-served app.
6. **CI evidence:** workflow definition is not execution evidence. Until a CI run is green, live PostgreSQL and browser integration remain unverified.

## Residual risks / limitations

- The E2E seeder is destructive only in the sense that it adds test records; no automatic cleanup is performed to preserve failure evidence. Use an ephemeral database.
- The live workflow validates the supported owner-role path, not the full role matrix or adversarial browser security.
- No production deployment, penetration test, OIDC/SSO, MFA, RLS, external provider, or human acceptance is claimed.
- The local environment could not install Chromium or start Docker; live browser/PostgreSQL execution is delegated to the authored CI workflow and remains pending.

No new production execution permissions or action types were added.

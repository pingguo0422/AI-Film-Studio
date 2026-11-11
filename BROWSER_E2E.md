# Control Center Browser E2E

Two browser checks are provided; they prove different things and must not be conflated.

## Deterministic UI-only check (mock API)

```bash
pip install -e '.[e2e]'
python -m playwright install chromium
python scripts/run_control_center_browser_e2e.py
```

This loads the shipped HTML/CSS/JS in Chromium and stubs `fetch` in-page. It is useful for repeatable UI behavior checks when local browser networking is restricted. It does **not** validate HTTP, authentication, API persistence, or PostgreSQL.

## Live API + PostgreSQL check

Use only a disposable PostgreSQL 16 integration database. The workflow below creates a project, human principal, short-lived bearer token, membership, and open director decision case. The token is written to a mode-0600 temporary env file and is never printed.

```bash
pip install -e '.[test,e2e]'
python -m playwright install chromium
python scripts/check_chromium_launch.py
export AFS_DATABASE_URL='postgresql+psycopg://...'
alembic upgrade head
python scripts/seed_live_browser_e2e.py --env-file /tmp/afs-e2e.env
set -a && source /tmp/afs-e2e.env && set +a
uvicorn backend.app.main:app --host 127.0.0.1 --port 8000
```

In a second shell with the same `AFS_E2E_*` variables:

```bash
python scripts/run_control_center_live_e2e.py
```

If Chromium is installed outside Playwright’s browser cache, set `AFS_CHROMIUM_EXECUTABLE` to its executable path for either browser runner.

The CI workflow pins the hosted runner to `ubuntu-24.04`, installs the Playwright Chromium browser without invoking `apt` through `--with-deps`, and runs `scripts/check_chromium_launch.py` before the integration tests. The launch check catches missing shared libraries or browser startup failures early; it does not replace either browser E2E test.

The live check navigates Chromium to the actual HTTP-served Control Center, authenticates using a real persisted API token, reads the PostgreSQL-backed inbox, submits human approval with an exact action snapshot, executes only after a second browser confirmation, and verifies the persisted execution and activity timeline through authenticated API reads.

The GitHub Actions workflow `PostgreSQL 16 + live Control Center E2E` runs migrations, migration drift checks, the full PostgreSQL-enabled pytest suite, and this live browser workflow in one job.

## Boundaries

- The live E2E creates an isolated project and task in its target database. Never point it at production or a shared development database.
- The API token is short-lived and stored only in the temporary env file; delete the file after local runs.
- A passing mocked UI check is not a passing live integration check.
- CI configuration is implemented in source, but it is not considered executed until a GitHub Actions run reports success.

# Executive Director Review & Control Center — Foundation 1.5 dev.8

## Purpose

A first usable browser control surface over the authenticated dev.7 review API. The UI is served at `/control-center/` and uses the same-origin `/v1` API.

## Capabilities

- Connect with an existing AFS API bearer token and project UUID.
- Verify the current principal through `GET /v1/me` and project membership through `GET /v1/projects/{project_id}/membership`.
- Browse the decision inbox by status with bounded pagination.
- Inspect a decision snapshot, evidence references, impact/risk fields when present, and source brief/state digests.
- Submit human approve/reject/defer/close decisions with a bounded note.
- View a bounded, read-only activity timeline combining Agent runs, tasks and project audit events.

## Security properties

- Token is held in `sessionStorage`, not persistent `localStorage`; logout clears it. Closing the browser tab clears the session value.
- UI uses same-origin API calls and no third-party scripts, fonts, analytics or network assets.
- Dynamic content is rendered with DOM `textContent`; untrusted proposal text is never inserted as HTML.
- Content Security Policy disallows inline scripts/styles, objects, framing and cross-origin connections. `nosniff`, `no-referrer` and frame-denial headers are set.
- Timeline returns event titles/status/timestamps only; raw audit details, Agent payloads, prompts, task input/output snapshots and error payloads are not exposed.
- API continues to enforce dev.6 Bearer authentication, project membership, RBAC and domain-specific decision authorization. UI controls are not an authorization boundary.
- Decisions remain dispositions only. No task materialization, Worker dispatch, creative asset mutation or production action occurs.

## Local run

```bash
pip install -e '.[test]'
export AFS_DATABASE_URL='sqlite+pysqlite:///./afs_dev.db'
alembic upgrade head
python scripts/provision_principal.py --display-name 'Project Owner' --project-id '<PROJECT_UUID>' --role owner
uvicorn backend.app.main:app --host 127.0.0.1 --port 8000
```

Open `http://127.0.0.1:8000/control-center/`, then enter the one-time API token and project UUID. Provisioning prints the raw token once; do not store it in source control or logs.

## Current limitations

- This is a static browser UI served by FastAPI, not a separate production frontend build.
- No OIDC/SSO, MFA, browser-session backend, token refresh, user invitation flow or secret-manager integration.
- No assignment workflow, notifications, WebSocket/SSE live updates, cross-project/global inbox or audit search/export.
- Activity timeline is a bounded summary of persisted task, AgentRun and audit records, not a complete event-sourced history. It is manually refreshed and does not imply real-time observability.
- No approved-action executor or action authorization gateway in this increment.
- UI has been syntax-checked and served/tested through FastAPI TestClient; no real browser automation, accessibility audit or penetration test was run.
- SQLite is the executed database target. PostgreSQL integration tests remain skipped without `AFS_TEST_POSTGRES_URL`; no live PostgreSQL claim is made.

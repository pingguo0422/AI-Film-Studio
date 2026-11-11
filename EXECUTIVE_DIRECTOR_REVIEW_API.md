# Executive Director Review API — Foundation 1.5 dev.8

The authenticated API behavior from dev.7 remains in place. The UI is served at `/control-center/`.

## Endpoints

All endpoints below require `Authorization: Bearer <AFS API token>`.

| Method | Route | Purpose | Permission |
|---|---|---|---|
| GET | `/v1/projects/{project_id}/director/decision-cases` | List decision cases; status, limit and offset filters | `project:read` |
| GET | `/v1/projects/{project_id}/director/decision-cases/{case_id}` | Read recommendation snapshot, evidence and source digests | `project:read` |
| POST | `/v1/projects/{project_id}/director/decision-cases/{case_id}/decision` | Human approve/reject/defer/close | Human + `project:approve` + domain role policy |
| GET | `/v1/projects/{project_id}/director/activity` | Bounded read-only Agent/task/audit timeline; `limit` 1–100 | `project:read` |

The activity endpoint returns only event kind, safe title, status, timestamp and reference ID. It does not expose audit detail JSON, Agent payloads, task snapshots, prompts or error payloads.

## Decision safety

- The recommendation snapshot and evidence references are read-only in the UI.
- Decision POST reuses existing persisted role policy and transactional audit handling.
- Approval records authorization/disposition only. It does not materialize tasks, dispatch Workers, alter schedules or mutate creative assets.

## UI

`GET /control-center/` serves the same-origin static Control Center. See `EXECUTIVE_DIRECTOR_CONTROL_CENTER.md` for security behavior, local setup and limitations.

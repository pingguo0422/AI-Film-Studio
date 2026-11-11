# Authentication and Project RBAC — Foundation 1.5 dev.6

## Scope

This increment adds the first usable API authentication and project-authorization boundary. It is deliberately an API-token foundation, not a complete end-user identity product or an OIDC/SAML integration.

- `Principal` is the stable internal identity for a human or service account.
- `ApiToken` is a high-entropy opaque bearer credential with a bounded lifetime and revocation state.
- Only a SHA-256 digest and a short token prefix are stored. The raw token is shown once by the out-of-band provisioning tool.
- `ProjectMember.principal_id` is now protected by a database foreign key to `principals.id`.
- Legacy principal IDs already referenced by `project_members` are backfilled as active human principals named `Legacy principal`.
- Project permission checks are centralized in `backend/app/security/authorization.py`.

## Token lifecycle

Provision a principal and optional initial project membership from a trusted operator environment:

```bash
export AFS_DATABASE_URL='postgresql+psycopg://...'
python scripts/provision_principal.py \
  --display-name 'Initial Project Owner' \
  --kind human \
  --project-id '<existing-project-uuid>' \
  --role owner \
  --ttl-days 30
```

The command prints the bearer token once. Put it in a secret manager immediately; do not paste it into source control, tickets, logs, or chat. `--principal-id` can be used to bind a token to a legacy principal UUID already present in `project_members`.

Token expiry is required and bounded to 1–365 days. Tokens can be revoked by their owning principal through `DELETE /v1/me/tokens/{token_id}`. There is no refresh-token flow. Operators can deactivate a principal directly through a controlled administrative process; an inactive principal cannot authenticate.

## HTTP endpoints

All endpoints below require `Authorization: Bearer afs_pat_...`, except `/health`.

| Method | Path | Permission / behavior |
|---|---|---|
| GET | `/v1/me` | Return authenticated principal identity |
| DELETE | `/v1/me/tokens/{token_id}` | Revoke one of the caller's own tokens |
| GET | `/v1/projects/{project_id}/membership` | `project:read`; return caller's active membership |
| GET | `/v1/projects/{project_id}/members` | `project:manage_members`; list active members |
| PUT | `/v1/projects/{project_id}/members/{principal_id}` | `project:manage_members`; add/reactivate/update a member |
| DELETE | `/v1/projects/{project_id}/members/{principal_id}` | `project:manage_members`; deactivate a member |

Non-members receive 404 for project-scoped authorization failures to avoid disclosing project existence. Missing, malformed, expired, revoked, or inactive-principal credentials receive 401 with a Bearer challenge.

## Default role matrix

| Project role | Read | Contribute | Manage members | Approve | Administer |
|---|:---:|:---:|:---:|:---:|:---:|
| owner | ✓ | ✓ | ✓ | ✓ | ✓ |
| producer | ✓ | ✓ | ✓ | ✓ | — |
| director | ✓ | ✓ | — | ✓ | — |
| department_lead | ✓ | ✓ | — | — | — |
| collaborator | ✓ | ✓ | — | — | — |
| viewer | ✓ | — | — | — | — |

Additional safeguards:

- Only a project owner may grant or modify privileged roles (`owner`, `producer`, `director`); producers may manage lower-privilege project roles.
- The last active project owner cannot be demoted or deactivated.
- Membership mutations lock the project row to serialize owner-role changes on databases that support row-level `FOR UPDATE` locks.
- Member additions, role changes, and deactivations append `AuditLog` records.
- New membership operations require an existing active `Principal`.

## Security boundaries and known gaps

- This is opaque API-token authentication, not interactive username/password login, OIDC, SAML, MFA, browser sessions, or federated identity.
- Token issuance is intentionally out-of-band and requires trusted database/operator access. There is no public token-creation endpoint.
- The token is a bearer secret: HTTPS is mandatory outside local development. Reverse-proxy TLS, secret-manager storage, log redaction, key/credential rotation operations and deployment network policy remain deployment responsibilities.
- Token rate limiting, anomaly detection, global principal administration endpoints and automated expiry cleanup are not implemented.
- The new `/v1` identity and membership endpoints enforce the new boundary. Existing internal service functions remain callable by trusted application code; any future HTTP exposure of planning, approval, asset or task operations must explicitly depend on authentication and project permission checks. Do not expose those service functions directly.
- Project RBAC is implemented; PostgreSQL row-level security (RLS) is not. Composite project foreign keys and query-level project scoping remain important, and live PostgreSQL integration is still required.
- Human-only approval services continue to enforce `actor_kind` and role requirements independently. A service principal must never be passed as a human reviewer.

## Non-goals of dev.6

No human-facing login UI, user invitation/email verification, OIDC provider discovery/JWKS, password storage, MFA, refresh tokens, project RLS policies, or public Executive Director planning/decision endpoints are included.

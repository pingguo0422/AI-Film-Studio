"""Out-of-band operator tool to create a principal and issue its first API token.

Run only from a trusted administration environment with AFS_DATABASE_URL set.
The raw token is printed once; store it in a secret manager immediately.
"""
from __future__ import annotations
import argparse
import sys
from pathlib import Path
from uuid import UUID
from sqlalchemy import select

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
from backend.app.db.session import SessionLocal
from backend.app.db.ids import uuid7
from backend.app.models import MemberRole, Principal, Project, ProjectMember
from backend.app.security.tokens import issue_api_token


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--display-name", required=True)
    parser.add_argument("--kind", choices=["human", "service"], default="human")
    parser.add_argument("--principal-id", help="Reuse a legacy project_members principal UUID")
    parser.add_argument("--project-id", help="Optional initial project membership UUID")
    parser.add_argument("--role", choices=[r.value for r in MemberRole], default="owner")
    parser.add_argument("--ttl-days", type=int, default=30)
    args = parser.parse_args()

    principal_id = UUID(args.principal_id) if args.principal_id else uuid7()
    db = SessionLocal()
    try:
        principal = db.get(Principal, principal_id)
        if principal is None:
            principal = Principal(id=principal_id, principal_kind=args.kind, display_name=args.display_name, is_active=True)
            db.add(principal)
            db.flush()
        else:
            if not principal.is_active:
                parser.error("the requested principal exists but is inactive")
            principal.display_name = args.display_name
            principal.principal_kind = args.kind

        if args.project_id:
            project_id = UUID(args.project_id)
            if db.get(Project, project_id) is None:
                parser.error("project_id does not identify an existing project")
            member = db.scalar(select(ProjectMember).where(ProjectMember.project_id == project_id, ProjectMember.principal_id == principal_id))
            if member is None:
                db.add(ProjectMember(project_id=project_id, principal_id=principal_id, role=MemberRole(args.role), is_active=True))
            else:
                member.role = MemberRole(args.role)
                member.is_active = True

        token_row, raw_token = issue_api_token(db, principal_id=principal_id, ttl_days=args.ttl_days)
        db.commit()
        print(f"principal_id={principal_id}")
        print(f"token_id={token_row.id}")
        print(f"expires_at={token_row.expires_at.isoformat()}")
        print("api_token=" + raw_token)
        print("WARNING: this token is shown once. Store it in a secret manager; do not commit it.")
        return 0
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


if __name__ == "__main__":
    raise SystemExit(main())

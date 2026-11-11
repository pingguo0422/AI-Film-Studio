#!/usr/bin/env python3
"""Create isolated PostgreSQL-backed data for the live Control Center E2E.

The generated bearer token is written only to the requested env file (mode 0600).
Use this only against a disposable integration database.
"""
from __future__ import annotations

import argparse
import os
from pathlib import Path
from uuid import uuid4
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from backend.app.db.ids import uuid7
from backend.app.db.session import SessionLocal
from backend.app.models import (
    DirectorDecisionCase,
    MemberRole,
    Principal,
    Project,
    ProjectMember,
)
from backend.app.security.tokens import issue_api_token


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--env-file", required=True)
    args = parser.parse_args()
    env_path = Path(args.env_file).resolve()
    env_path.parent.mkdir(parents=True, exist_ok=True)

    project_id = uuid7()
    principal_id = uuid7()
    case_id = uuid7()
    with SessionLocal() as db:
        project = Project(
            id=project_id,
            code=f"E2E_{uuid4().hex[:10].upper()}",
            name="AFS Live Browser E2E",
            description="Disposable integration test project",
            status="active",
        )
        principal = Principal(
            id=principal_id,
            principal_kind="human",
            display_name="Live E2E Operator",
            is_active=True,
        )
        db.add_all([project, principal])
        db.flush()
        db.add(ProjectMember(
            project_id=project_id,
            principal_id=principal_id,
            role=MemberRole.owner,
            is_active=True,
        ))
        case = DirectorDecisionCase(
            id=case_id,
            project_id=project_id,
            case_key=uuid4().hex + uuid4().hex,
            source_brief_sha256="a" * 64,
            source_state_digest="b" * 64,
            recommendation_code="LIVE_BROWSER_E2E_CREATE_TASK",
            severity="medium",
            approval_required="director_review",
            evidence_refs=["e2e:live-postgresql:scene-8.1"],
            proposal_snapshot={
                "summary": "Create a script revision task through the live operator workflow",
                "impact": {"scope": "integration-test-only", "source": "dev15"},
            },
            status="open",
        )
        db.add(case)
        _, token = issue_api_token(db, principal_id=principal_id, ttl_days=1)
        db.commit()

    contents = (
        f"AFS_E2E_PROJECT_ID={project_id}\n"
        f"AFS_E2E_CASE_ID={case_id}\n"
        f"AFS_E2E_API_TOKEN={token}\n"
    )
    env_path.write_text(contents, encoding="utf-8")
    os.chmod(env_path, 0o600)
    print(f"Live E2E seed created: project={project_id}, case={case_id}")
    print("Bearer token written to a mode-0600 env file; token value not logged.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

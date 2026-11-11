from pathlib import Path
from datetime import datetime, timezone

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, delete, update
from sqlalchemy.exc import DatabaseError
from sqlalchemy.orm import Session

from backend.app.models import DirectorDecisionCase, Project
from backend.app.db.ids import uuid7


@pytest.fixture
def migrated_db(tmp_path, monkeypatch):
    root = Path(__file__).resolve().parents[1]
    db_path = tmp_path / "decision_case_migration.sqlite"
    monkeypatch.setenv("AFS_DATABASE_URL", f"sqlite+pysqlite:///{db_path}")
    cfg = Config(str(root / "alembic.ini"))
    cfg.set_main_option("script_location", str(root / "backend" / "migrations"))
    cfg.set_main_option("path_separator", "os")
    command.upgrade(cfg, "head")
    engine = create_engine(f"sqlite+pysqlite:///{db_path}")
    try:
        yield engine
    finally:
        engine.dispose()


def seed_case(db):
    project = Project(code=f"MIG_{uuid7().hex[:8]}", name="Migration Test")
    db.add(project)
    db.flush()
    case = DirectorDecisionCase(
        project_id=project.id,
        case_key="a" * 64,
        source_brief_sha256="b" * 64,
        source_state_digest="c" * 64,
        recommendation_code="TASK_FAILED",
        severity="high",
        approval_required="director_review",
        evidence_refs=["task:123"],
        proposal_snapshot={"code": "TASK_FAILED"},
        status="open",
    )
    db.add(case)
    db.flush()
    return case


def test_migration_installs_immutable_proposal_snapshot_trigger(migrated_db):
    with Session(migrated_db) as db:
        case = seed_case(db)
        with pytest.raises(DatabaseError):
            db.execute(update(DirectorDecisionCase).where(DirectorDecisionCase.id == case.id)
                       .values(proposal_snapshot={"tampered": True}))
        db.rollback()


def test_migration_installs_no_delete_audit_retention_trigger(migrated_db):
    with Session(migrated_db) as db:
        case = seed_case(db)
        with pytest.raises(DatabaseError):
            db.execute(delete(DirectorDecisionCase).where(DirectorDecisionCase.id == case.id))
        db.rollback()


def test_migration_installs_decision_consistency_constraint(migrated_db):
    from sqlalchemy import text
    with migrated_db.begin() as conn:
        project_id = conn.execute(text("INSERT INTO projects (id, code, name, status, created_at, updated_at) VALUES (:id, :code, :name, :status, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP) RETURNING id"), {
            "id": str(uuid7()), "code": f"CHK_{uuid7().hex[:8]}", "name": "Check", "status": "active"
        }).scalar_one()
        with pytest.raises(DatabaseError):
            conn.execute(text("""INSERT INTO director_decision_cases
                (id, project_id, case_key, source_brief_sha256, source_state_digest,
                 recommendation_code, severity, approval_required, evidence_refs,
                 proposal_snapshot, status, decision, decided_by, decision_note, created_at, decided_at)
                VALUES (:id, :project_id, :case_key, :brief, :state, 'TASK_FAILED', 'high',
                        'director_review', '[]', '{}', 'approved', NULL, NULL, NULL,
                        CURRENT_TIMESTAMP, NULL)"""), {
                "id": str(uuid7()), "project_id": str(project_id), "case_key": "d" * 64,
                "brief": "b" * 64, "state": "c" * 64
            })


def test_migration_makes_terminal_disposition_one_time(migrated_db):
    from sqlalchemy import update
    with Session(migrated_db) as db:
        project = Project(code=f"ONCE_{uuid7().hex[:8]}", name="One-time Test")
        db.add(project)
        db.flush()
        principal = uuid7()
        case = DirectorDecisionCase(
            project_id=project.id, case_key="e" * 64, source_brief_sha256="b" * 64,
            source_state_digest="c" * 64, recommendation_code="TASK_FAILED", severity="high",
            approval_required="director_review", evidence_refs=[], proposal_snapshot={"code": "TASK_FAILED"},
            status="approved", decision="approved", decided_by=principal,
            created_at=datetime.now(timezone.utc),
            decided_at=datetime.now(timezone.utc),
        )
        db.add(case)
        db.flush()
        with pytest.raises(DatabaseError):
            db.execute(update(DirectorDecisionCase).where(DirectorDecisionCase.id == case.id)
                       .values(decision_note="rewrite decision history"))
        db.rollback()


def test_identity_migration_backfills_legacy_members_and_installs_principal_fk(tmp_path, monkeypatch):
    from sqlalchemy import text
    from sqlalchemy.exc import IntegrityError

    root = Path(__file__).resolve().parents[1]
    db_path = tmp_path / "identity_backfill.sqlite"
    monkeypatch.setenv("AFS_DATABASE_URL", f"sqlite+pysqlite:///{db_path}")
    cfg = Config(str(root / "alembic.ini"))
    cfg.set_main_option("script_location", str(root / "backend" / "migrations"))
    cfg.set_main_option("path_separator", "os")
    command.upgrade(cfg, "a41d7c2e9b60")

    project_id, principal_id = uuid7(), uuid7()
    engine = create_engine(f"sqlite+pysqlite:///{db_path}")
    with engine.begin() as conn:
        conn.execute(text("INSERT INTO projects (id, code, name, status, created_at, updated_at) VALUES (:id, :code, :name, 'active', CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)"),
                      {"id": str(project_id), "code": "LEGACY_MEMBER", "name": "Legacy"})
        conn.execute(text("INSERT INTO project_members (id, project_id, principal_id, role, is_active, created_at) VALUES (:id, :project_id, :principal_id, 'director', 1, CURRENT_TIMESTAMP)"),
                      {"id": str(uuid7()), "project_id": str(project_id), "principal_id": str(principal_id)})
    engine.dispose()

    command.upgrade(cfg, "head")
    engine = create_engine(f"sqlite+pysqlite:///{db_path}")
    with engine.connect() as conn:
        principal = conn.execute(text("SELECT principal_kind, display_name FROM principals WHERE id = :id"), {"id": str(principal_id)}).one()
        assert principal == ("human", "Legacy principal")
    with engine.connect() as conn:
        conn.exec_driver_sql("PRAGMA foreign_keys=ON")
        conn.commit()
        with pytest.raises(IntegrityError):
            with conn.begin():
                conn.execute(text("INSERT INTO project_members (id, project_id, principal_id, role, is_active, created_at) VALUES (:id, :project_id, :principal_id, 'viewer', 1, CURRENT_TIMESTAMP)"),
                             {"id": str(uuid7()), "project_id": str(project_id), "principal_id": str(uuid7())})
    engine.dispose()

from datetime import datetime, timezone

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from backend.app.db.base import Base
from backend.app.db.ids import uuid7
from backend.app.models import AuditLog, DirectorDecisionCase, MemberRole, Project, ProjectMember, Task, Principal
from backend.app.services.task_service import create_task
from backend.app.services.director_decision_engine import build_director_brief
from backend.app.services.director_decision_cases import (
    DirectorDecisionCaseError,
    DirectorDecisionCasePermissionError,
    create_decision_cases_from_brief,
    decide_director_case,
    list_open_director_cases,
)


@pytest.fixture
def db_session():
    engine = create_engine("sqlite+pysqlite:///:memory:", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    with Session(engine) as db:
        yield db
    engine.dispose()


def seed_project(db, code="CASE"):
    project = Project(code=f"{code}_{uuid7().hex[:8]}", name="Decision Case Test")
    db.add(project)
    db.flush()
    return project


def add_member(db, project_id, role, *, active=True):
    principal = uuid7()
    db.add(Principal(id=principal, principal_kind="human", display_name="Test member")); db.flush()
    db.add(ProjectMember(project_id=project_id, principal_id=principal, role=role, is_active=active))
    db.flush()
    return principal


def build_failed_task_brief(db, project):
    task = create_task(db, project_id=project.id, task_type="SCRIPT", title="Script breakdown", input_snapshot={})
    task.status = "failed"
    db.flush()
    brief = build_director_brief(db, project_id=project.id, now=datetime(2026, 11, 11, 10, 0, tzinfo=timezone.utc))
    return task, brief


def test_case_creation_is_idempotent_and_pins_source_brief(db_session):
    project = seed_project(db_session)
    _, brief = build_failed_task_brief(db_session, project)
    first = create_decision_cases_from_brief(db_session, project_id=project.id, brief=brief)
    second = create_decision_cases_from_brief(db_session, project_id=project.id, brief=brief)
    assert len(first) == 1
    assert [case.id for case in first] == [case.id for case in second]
    assert first[0].source_brief_sha256 == brief["brief_sha256"]
    assert first[0].source_state_digest == brief["state_digest"]
    assert first[0].status == "open"
    assert first[0].evidence_refs


def test_equivalent_brief_for_same_state_reuses_existing_case(db_session):
    import hashlib
    import json
    project = seed_project(db_session)
    _, brief = build_failed_task_brief(db_session, project)
    first = create_decision_cases_from_brief(db_session, project_id=project.id, brief=brief)
    equivalent = dict(brief)
    equivalent["generated_at"] = "2026-11-11T10:05:00+00:00"
    unsigned = dict(equivalent)
    unsigned.pop("brief_sha256", None)
    equivalent["brief_sha256"] = hashlib.sha256(json.dumps(
        unsigned, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str
    ).encode("utf-8")).hexdigest()
    second = create_decision_cases_from_brief(db_session, project_id=project.id, brief=equivalent)
    assert [case.id for case in first] == [case.id for case in second]
    assert second[0].source_brief_sha256 == brief["brief_sha256"]


def test_modified_brief_is_rejected_by_digest_check(db_session):
    project = seed_project(db_session)
    _, brief = build_failed_task_brief(db_session, project)
    brief["recommendations"][0]["title"] = "Tampered"
    with pytest.raises(DirectorDecisionCaseError, match="digest mismatch"):
        create_decision_cases_from_brief(db_session, project_id=project.id, brief=brief)


def test_brief_from_another_project_is_rejected(db_session):
    project_a = seed_project(db_session, "A")
    project_b = seed_project(db_session, "B")
    _, brief = build_failed_task_brief(db_session, project_a)
    with pytest.raises(DirectorDecisionCaseError, match="does not match"):
        create_decision_cases_from_brief(db_session, project_id=project_b.id, brief=brief)


def test_non_human_actor_cannot_decide(db_session):
    project = seed_project(db_session)
    _, brief = build_failed_task_brief(db_session, project)
    case = create_decision_cases_from_brief(db_session, project_id=project.id, brief=brief)[0]
    principal = add_member(db_session, project.id, MemberRole.director)
    with pytest.raises(DirectorDecisionCasePermissionError, match="only a human"):
        decide_director_case(db_session, project_id=project.id, case_id=case.id,
            actor_id=principal, actor_kind="agent", decision="approved")


def test_wrong_role_cannot_decide_director_review_case(db_session):
    project = seed_project(db_session)
    _, brief = build_failed_task_brief(db_session, project)
    case = create_decision_cases_from_brief(db_session, project_id=project.id, brief=brief)[0]
    principal = add_member(db_session, project.id, MemberRole.collaborator)
    with pytest.raises(DirectorDecisionCasePermissionError, match="cannot decide"):
        decide_director_case(db_session, project_id=project.id, case_id=case.id,
            actor_id=principal, actor_kind="human", decision="approved")


def test_inactive_project_member_cannot_decide(db_session):
    project = seed_project(db_session)
    _, brief = build_failed_task_brief(db_session, project)
    case = create_decision_cases_from_brief(db_session, project_id=project.id, brief=brief)[0]
    principal = add_member(db_session, project.id, MemberRole.director, active=False)
    with pytest.raises(DirectorDecisionCasePermissionError, match="active project member"):
        decide_director_case(db_session, project_id=project.id, case_id=case.id,
            actor_id=principal, actor_kind="human", decision="approved")


def test_authorized_human_decision_is_audited_and_does_not_execute_action(db_session):
    project = seed_project(db_session)
    task, brief = build_failed_task_brief(db_session, project)
    case = create_decision_cases_from_brief(db_session, project_id=project.id, brief=brief)[0]
    principal = add_member(db_session, project.id, MemberRole.director)
    decided = decide_director_case(db_session, project_id=project.id, case_id=case.id,
        actor_id=principal, actor_kind="human", decision="approved", note="Reviewed; authorize separate recovery review.")
    db_session.refresh(task)
    assert decided.status == "approved"
    assert decided.decided_by == principal
    assert task.status == "failed"  # approval records intent; it does not mutate execution state
    audit = db_session.scalar(select(AuditLog).where(AuditLog.object_id == case.id))
    assert audit.action == "DIRECTOR_CASE_APPROVED"
    assert audit.details["execution_performed"] is False


def test_system_recovery_case_requires_producer_or_owner(db_session):
    project = seed_project(db_session)
    task = create_task(db_session, project_id=project.id, task_type="RECOVERY", title="Recover", input_snapshot={})
    task.status = "running"
    task.lease_expires_at = datetime(2026, 11, 10, tzinfo=timezone.utc)
    db_session.flush()
    brief = build_director_brief(db_session, project_id=project.id, now=datetime(2026, 11, 11, tzinfo=timezone.utc))
    case = next(c for c in create_decision_cases_from_brief(db_session, project_id=project.id, brief=brief)
                if c.approval_required == "system_recovery")
    director = add_member(db_session, project.id, MemberRole.director)
    with pytest.raises(DirectorDecisionCasePermissionError, match="cannot decide"):
        decide_director_case(db_session, project_id=project.id, case_id=case.id,
            actor_id=director, actor_kind="human", decision="approved")
    producer = add_member(db_session, project.id, MemberRole.producer)
    result = decide_director_case(db_session, project_id=project.id, case_id=case.id,
        actor_id=producer, actor_kind="human", decision="deferred", note="Inspect worker generation first")
    assert result.status == "deferred"


def test_case_cannot_be_decided_twice(db_session):
    project = seed_project(db_session)
    _, brief = build_failed_task_brief(db_session, project)
    case = create_decision_cases_from_brief(db_session, project_id=project.id, brief=brief)[0]
    principal = add_member(db_session, project.id, MemberRole.owner)
    decide_director_case(db_session, project_id=project.id, case_id=case.id,
        actor_id=principal, actor_kind="human", decision="rejected")
    with pytest.raises(DirectorDecisionCaseError, match="only open"):
        decide_director_case(db_session, project_id=project.id, case_id=case.id,
            actor_id=principal, actor_kind="human", decision="approved")


def test_open_case_list_is_project_scoped_and_bounded(db_session):
    project_a = seed_project(db_session, "A")
    project_b = seed_project(db_session, "B")
    _, brief_a = build_failed_task_brief(db_session, project_a)
    _, brief_b = build_failed_task_brief(db_session, project_b)
    create_decision_cases_from_brief(db_session, project_id=project_a.id, brief=brief_a)
    create_decision_cases_from_brief(db_session, project_id=project_b.id, brief=brief_b)
    assert len(list_open_director_cases(db_session, project_id=project_a.id)) == 1
    with pytest.raises(DirectorDecisionCaseError, match="between 1 and 500"):
        list_open_director_cases(db_session, project_id=project_a.id, limit=0)

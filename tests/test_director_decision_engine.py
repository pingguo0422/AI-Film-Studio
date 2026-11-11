from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from backend.app.db.base import Base
from backend.app.db.ids import uuid7
from backend.app.models import Project, Task, TaskDependency, OrchestrationPlan
from backend.app.services.task_service import create_task, add_task_dependency
from backend.app.services.director_decision_engine import (
    DirectorDecisionError, build_director_brief,
)


@pytest.fixture
def db_session():
    engine = create_engine("sqlite+pysqlite:///:memory:", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    with Session(engine) as db:
        yield db
    engine.dispose()


def seed_project(db):
    project = Project(code=f"DIR_{uuid7().hex[:8]}", name="Director Decision Test")
    db.add(project)
    db.flush()
    return project


def test_brief_detects_blocked_failed_and_stale_tasks_without_mutating_state(db_session):
    project = seed_project(db_session)
    now = datetime(2026, 11, 9, 12, 0, tzinfo=timezone.utc)
    upstream = create_task(db_session, project_id=project.id, task_type="SCRIPT", title="Script", input_snapshot={})
    upstream.status = "failed"
    blocked = create_task(db_session, project_id=project.id, task_type="VISUAL", title="Visual Bible", input_snapshot={})
    add_task_dependency(db_session, project_id=project.id, task_id=blocked.id, depends_on_task_id=upstream.id)
    stale = create_task(db_session, project_id=project.id, task_type="SHOT", title="Shot plan", input_snapshot={})
    stale.status = "running"
    stale.updated_at = now - timedelta(hours=1)
    stale.lease_expires_at = now - timedelta(minutes=5)
    before = (upstream.status, blocked.status, stale.status)

    brief = build_director_brief(db_session, project_id=project.id, now=now, stale_after_seconds=600)
    codes = {item["code"] for item in brief["recommendations"]}
    assert {"TASK_FAILED", "TASK_BLOCKED_BY_DEPENDENCY", "TASK_RUNNING_STALE", "TASK_LEASE_EXPIRED"} <= codes
    assert brief["mode"] == "read_only_proposal"
    assert brief["governance"]["mutated_project_state"] is False
    assert before == (upstream.status, blocked.status, stale.status)


def test_pending_plan_requires_human_approval(db_session):
    project = seed_project(db_session)
    root = create_task(db_session, project_id=project.id, task_type="ROOT", title="Production", input_snapshot={})
    plan = OrchestrationPlan(project_id=project.id, task_id=root.id, status="draft", approval_status="pending",
                             plan_sha256="a" * 64, plan_snapshot={"steps": []})
    db_session.add(plan)
    db_session.flush()
    brief = build_director_brief(db_session, project_id=project.id)
    item = next(item for item in brief["recommendations"] if item["code"] == "PLAN_AWAITING_HUMAN_APPROVAL")
    assert item["approval_required"] == "human_required"
    assert brief["summary"]["human_decision_required"] is True


def test_running_task_with_unfinished_prerequisite_is_critical_conflict(db_session):
    project = seed_project(db_session)
    parent = create_task(db_session, project_id=project.id, task_type="A", title="A", input_snapshot={})
    child = create_task(db_session, project_id=project.id, task_type="B", title="B", input_snapshot={})
    child.status = "running"
    add_task_dependency(db_session, project_id=project.id, task_id=child.id, depends_on_task_id=parent.id)
    brief = build_director_brief(db_session, project_id=project.id)
    item = next(item for item in brief["recommendations"] if item["code"] == "RUNNING_WITH_UNSATISFIED_DEPENDENCY")
    assert item["severity"] == "critical"
    assert f"task:{parent.id}" in item["evidence_refs"]


def test_brief_digest_is_stable_for_same_snapshot_and_changes_with_state(db_session):
    project = seed_project(db_session)
    task = create_task(db_session, project_id=project.id, task_type="SCRIPT", title="Script", input_snapshot={})
    now = datetime(2026, 11, 9, 12, 0, tzinfo=timezone.utc)
    first = build_director_brief(db_session, project_id=project.id, now=now)
    again = build_director_brief(db_session, project_id=project.id, now=now)
    assert first["brief_sha256"] == again["brief_sha256"]
    task.status = "failed"
    changed = build_director_brief(db_session, project_id=project.id, now=now)
    assert changed["state_digest"] != first["state_digest"]


def test_record_cap_fails_closed_instead_of_returning_partial_brief(db_session):
    project = seed_project(db_session)
    create_task(db_session, project_id=project.id, task_type="A", title="A", input_snapshot={})
    create_task(db_session, project_id=project.id, task_type="B", title="B", input_snapshot={})
    with pytest.raises(DirectorDecisionError, match="exceeds max_records"):
        build_director_brief(db_session, project_id=project.id, max_records=1)


def test_invalid_threshold_is_rejected(db_session):
    project = seed_project(db_session)
    with pytest.raises(DirectorDecisionError, match="must be positive"):
        build_director_brief(db_session, project_id=project.id, stale_after_seconds=0)


def test_multiple_active_runs_on_same_task_are_flagged(db_session):
    from backend.app.models import Agent, AgentVersion, AgentRun
    project = seed_project(db_session)
    task = create_task(db_session, project_id=project.id, task_type="DUP", title="Duplicate execution", input_snapshot={})
    agent = Agent(code=f"AG_{uuid7().hex[:8]}", display_name="Worker Agent")
    db_session.add(agent)
    db_session.flush()
    version = AgentVersion(agent_id=agent.id, version_number=1, definition_snapshot={}, definition_sha256="f" * 64)
    db_session.add(version)
    db_session.flush()
    now = datetime.now(timezone.utc)
    for _ in range(2):
        db_session.add(AgentRun(project_id=project.id, task_id=task.id, agent_id=agent.id,
                                agent_version_id=version.id, status="running", input_snapshot={},
                                started_at=now))
    db_session.flush()
    brief = build_director_brief(db_session, project_id=project.id)
    item = next(item for item in brief["recommendations"] if item["code"] == "MULTIPLE_ACTIVE_RUNS")
    assert item["severity"] == "critical"


def test_quality_escalation_is_surfaced_as_human_required(db_session):
    from backend.app.models import Agent, AgentVersion, AgentRun, AgentEvaluation
    project = seed_project(db_session)
    task = create_task(db_session, project_id=project.id, task_type="REVIEW", title="Historical review", input_snapshot={})
    author = Agent(code=f"AUTHOR_{uuid7().hex[:8]}", display_name="Author")
    reviewer = Agent(code=f"REVIEWER_{uuid7().hex[:8]}", display_name="Reviewer")
    db_session.add_all([author, reviewer])
    db_session.flush()
    author_version = AgentVersion(agent_id=author.id, version_number=1, definition_snapshot={}, definition_sha256="a" * 64)
    reviewer_version = AgentVersion(agent_id=reviewer.id, version_number=1, definition_snapshot={}, definition_sha256="b" * 64)
    db_session.add_all([author_version, reviewer_version])
    db_session.flush()
    run = AgentRun(project_id=project.id, task_id=task.id, agent_id=author.id,
                   agent_version_id=author_version.id, status="succeeded", input_snapshot={})
    db_session.add(run)
    db_session.flush()
    evaluation = AgentEvaluation(project_id=project.id, task_id=task.id, agent_run_id=run.id,
        reviewer_agent_version_id=reviewer_version.id, decision="escalate", score=0.2,
        rework_round=2, rubric_snapshot={}, findings=[{"finding": "source conflict"}],
        required_changes=[], idempotency_key="director-escalation-test")
    db_session.add(evaluation)
    db_session.flush()
    brief = build_director_brief(db_session, project_id=project.id)
    item = next(item for item in brief["recommendations"] if item["code"] == "QUALITY_ESCALATION")
    assert item["approval_required"] == "human_required"
    assert brief["summary"]["human_decision_required"] is True


def test_total_project_snapshot_cap_includes_dependency_edges(db_session):
    project = seed_project(db_session)
    first = create_task(db_session, project_id=project.id, task_type="A", title="A", input_snapshot={})
    second = create_task(db_session, project_id=project.id, task_type="B", title="B", input_snapshot={})
    third = create_task(db_session, project_id=project.id, task_type="C", title="C", input_snapshot={})
    add_task_dependency(db_session, project_id=project.id, task_id=second.id, depends_on_task_id=first.id)
    add_task_dependency(db_session, project_id=project.id, task_id=third.id, depends_on_task_id=first.id)
    with pytest.raises(DirectorDecisionError, match="total project decision snapshot"):
        build_director_brief(db_session, project_id=project.id, max_records=4)

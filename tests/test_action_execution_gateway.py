from __future__ import annotations
from uuid import UUID, uuid4
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool
from backend.app.api.dependencies import get_db
from backend.app.db.base import Base
from backend.app.main import app
from backend.app.models import ActionExecution, AuditLog, DirectorDecisionCase, MemberRole, Principal, Project, ProjectMember, Task
from backend.app.security.tokens import issue_api_token


@pytest.fixture
def gateway_engine():
    engine = create_engine("sqlite+pysqlite:///:memory:", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    yield engine
    engine.dispose()


def setup_case(engine, *, status="open", principal_kind="human"):
    with Session(engine) as db:
        project = Project(code=f"ACT_{uuid4().hex[:8]}", name="Action gateway test")
        actor = Principal(principal_kind=principal_kind, display_name="Producer")
        db.add_all([project, actor]); db.flush()
        db.add(ProjectMember(project_id=project.id, principal_id=actor.id, role=MemberRole.owner, is_active=True))
        _, token = issue_api_token(db, principal_id=actor.id)
        case = DirectorDecisionCase(
            project_id=project.id, case_key=f"case-{uuid4().hex}",
            source_brief_sha256="a" * 64, source_state_digest="b" * 64,
            recommendation_code="TASK_FAILED", severity="high", approval_required="director_review",
            evidence_refs=["task:source"], proposal_snapshot={"title": "Recover failed task"}, status="open",
        )
        db.add(case); db.flush()
        if status == "approved":
            case.status = case.decision = "approved"
            case.decided_by = actor.id
            from backend.app.models import utcnow
            case.decided_at = utcnow()
            case.authorized_action_snapshot = {
                "action_type": "create_task",
                "payload": {"task_type": "script_revision", "title": "Revise failed scene", "input_snapshot": {"source": "manual-approval"}},
            }
        project_id, case_id = str(project.id), str(case.id)
        db.commit()
    return project_id, case_id, token


def override_db(engine):
    def _override():
        with Session(engine) as db:
            yield db
    app.dependency_overrides[get_db] = _override


def test_approval_binds_exact_action_and_execute_is_idempotent(gateway_engine):
    project_id, case_id, token = setup_case(gateway_engine)
    override_db(gateway_engine)
    try:
        client = TestClient(app)
        headers = {"Authorization": f"Bearer {token}"}
        decision = client.post(
            f"/v1/projects/{project_id}/director/decision-cases/{case_id}/decision",
            headers=headers,
            json={"decision": "approved", "note": "Approved exact task creation", "authorized_action": {
                "action_type": "create_task",
                "payload": {"task_type": "script_revision", "title": "Revise scene 12", "input_snapshot": {"scene_id": "12"}, "priority": 40},
            }},
        )
        assert decision.status_code == 200, decision.text
        assert decision.json()["authorized_action_snapshot"]["payload"]["title"] == "Revise scene 12"

        execute_url = f"/v1/projects/{project_id}/director/decision-cases/{case_id}/execute"
        first = client.post(execute_url, headers=headers, json={"idempotency_key": "create-task-action-001"})
        assert first.status_code == 200, first.text
        result = first.json()
        assert result["status"] == "succeeded"
        task_id = result["result_snapshot"]["task_id"]
        recorded = client.get(execute_url, headers=headers)
        assert recorded.status_code == 200
        assert recorded.json()["id"] == result["id"]
        assert recorded.json()["result_snapshot"]["task_id"] == task_id

        repeated = client.post(execute_url, headers=headers, json={"idempotency_key": "create-task-action-001"})
        assert repeated.status_code == 200
        assert repeated.json()["id"] == result["id"]

        conflict = client.post(execute_url, headers=headers, json={"idempotency_key": "different-key-0001"})
        assert conflict.status_code == 409

        with Session(gateway_engine) as db:
            task = db.get(Task, UUID(task_id))
            assert task is not None and task.title == "Revise scene 12"
            assert db.scalar(select(Task).where(Task.project_id == task.project_id)).id == task.id
            assert db.scalar(select(ActionExecution).where(ActionExecution.decision_case_id == UUID(case_id))) is not None
            audit = db.scalar(select(AuditLog).where(AuditLog.action == "DIRECTOR_ACTION_EXECUTED"))
            assert audit is not None
            assert audit.details["action_type"] == "create_task"
    finally:
        app.dependency_overrides.pop(get_db, None)


def test_unapproved_case_cannot_execute(gateway_engine):
    project_id, case_id, token = setup_case(gateway_engine)
    override_db(gateway_engine)
    try:
        response = TestClient(app).post(
            f"/v1/projects/{project_id}/director/decision-cases/{case_id}/execute",
            headers={"Authorization": f"Bearer {token}"},
            json={"idempotency_key": "unapproved-action-001"},
        )
        assert response.status_code == 409
        with Session(gateway_engine) as db:
            assert db.scalar(select(ActionExecution)) is None
            assert db.scalar(select(Task)) is None
    finally:
        app.dependency_overrides.pop(get_db, None)


def test_approval_rejects_action_with_non_approved_decision(gateway_engine):
    project_id, case_id, token = setup_case(gateway_engine)
    override_db(gateway_engine)
    try:
        response = TestClient(app).post(
            f"/v1/projects/{project_id}/director/decision-cases/{case_id}/decision",
            headers={"Authorization": f"Bearer {token}"},
            json={"decision": "rejected", "authorized_action": {
                "action_type": "create_task", "payload": {"task_type": "x", "title": "x", "input_snapshot": {}}
            }},
        )
        assert response.status_code == 422
        with Session(gateway_engine) as db:
            case = db.scalar(select(DirectorDecisionCase))
            assert case.status == "open"
            assert case.authorized_action_snapshot is None
    finally:
        app.dependency_overrides.pop(get_db, None)


def test_action_payload_is_validated_at_approval(gateway_engine):
    project_id, case_id, token = setup_case(gateway_engine)
    override_db(gateway_engine)
    try:
        response = TestClient(app).post(
            f"/v1/projects/{project_id}/director/decision-cases/{case_id}/decision",
            headers={"Authorization": f"Bearer {token}"},
            json={"decision": "approved", "authorized_action": {
                "action_type": "create_task", "payload": {"task_type": "x", "title": "x", "input_snapshot": {}, "status": "running"}
            }},
        )
        assert response.status_code == 422
        with Session(gateway_engine) as db:
            case = db.scalar(select(DirectorDecisionCase))
            assert case.status == "open"
    finally:
        app.dependency_overrides.pop(get_db, None)


def test_request_rework_action_uses_existing_quality_gate(gateway_engine):
    from backend.app.models import Agent, AgentEvaluation, AgentRun, AgentVersion
    with Session(gateway_engine) as db:
        project = Project(code=f"REWORK_{uuid4().hex[:8]}", name="Rework action")
        actor = Principal(principal_kind="human", display_name="Producer")
        agent = Agent(code=f"AGENT_{uuid4().hex[:8]}", display_name="Script Agent")
        db.add_all([project, actor, agent]); db.flush()
        db.add(ProjectMember(project_id=project.id, principal_id=actor.id, role=MemberRole.owner, is_active=True))
        _, token = issue_api_token(db, principal_id=actor.id)
        version = AgentVersion(agent_id=agent.id, version_number=1, definition_snapshot={"name": "Script Agent"}, definition_sha256="c" * 64)
        db.add(version); db.flush()
        source = Task(project_id=project.id, task_type="script", title="Original scene", status="succeeded", input_snapshot={"scene": 8}, priority=30, max_attempts=3)
        db.add(source); db.flush()
        run = AgentRun(project_id=project.id, task_id=source.id, agent_id=agent.id, agent_version_id=version.id, status="succeeded", input_snapshot={"source": True}, output_snapshot={"draft": "v1"})
        db.add(run); db.flush()
        evaluation = AgentEvaluation(
            project_id=project.id, task_id=source.id, agent_run_id=run.id,
            reviewer_agent_version_id=version.id, decision="rework", score=0.4, rework_round=0,
            rubric_snapshot={"rubric": "screenplay"}, findings=["weak motivation"],
            required_changes=["clarify character motivation"], idempotency_key=f"eval-{uuid4().hex}",
        )
        db.add(evaluation); db.flush()
        case = DirectorDecisionCase(
            project_id=project.id, case_key=f"case-{uuid4().hex}",
            source_brief_sha256="d" * 64, source_state_digest="e" * 64,
            recommendation_code="QUALITY_REWORK", severity="high", approval_required="director_review",
            evidence_refs=[f"evaluation:{evaluation.id}"], proposal_snapshot={"summary": "Request quality rework"},
            status="approved", decision="approved", decided_by=actor.id,
            authorized_action_snapshot={"action_type": "request_rework", "payload": {"evaluation_id": str(evaluation.id)}},
        )
        from backend.app.models import utcnow
        case.decided_at = utcnow()
        db.add(case); db.flush()
        project_id, case_id, evaluation_id = str(project.id), str(case.id), evaluation.id
        db.commit()
    override_db(gateway_engine)
    try:
        response = TestClient(app).post(
            f"/v1/projects/{project_id}/director/decision-cases/{case_id}/execute",
            headers={"Authorization": f"Bearer {token}"},
            json={"idempotency_key": "quality-rework-action-001"},
        )
        assert response.status_code == 200, response.text
        result = response.json()["result_snapshot"]
        with Session(gateway_engine) as db:
            evaluation = db.get(AgentEvaluation, evaluation_id)
            rework = db.get(Task, __import__("uuid").UUID(result["task_id"]))
            assert evaluation.rework_task_id == rework.id
            assert rework.input_snapshot["required_changes"] == ["clarify character motivation"]
            assert rework.status == "queued"
    finally:
        app.dependency_overrides.pop(get_db, None)


def test_inactive_project_cannot_execute_and_leaves_no_side_effects(gateway_engine):
    project_id, case_id, token = setup_case(gateway_engine, status="approved")
    with Session(gateway_engine) as db:
        project = db.get(Project, UUID(project_id))
        project.status = "archived"
        db.commit()
    override_db(gateway_engine)
    try:
        response = TestClient(app).post(
            f"/v1/projects/{project_id}/director/decision-cases/{case_id}/execute",
            headers={"Authorization": f"Bearer {token}"},
            json={"idempotency_key": "inactive-project-action-001"},
        )
        assert response.status_code == 409, response.text
        with Session(gateway_engine) as db:
            assert db.scalar(select(ActionExecution)) is None
            assert db.scalar(select(Task)) is None
            assert db.scalar(select(AuditLog).where(AuditLog.action == "DIRECTOR_ACTION_EXECUTED")) is None
    finally:
        app.dependency_overrides.pop(get_db, None)


def test_service_principal_cannot_execute_even_with_owner_membership(gateway_engine):
    project_id, case_id, token = setup_case(gateway_engine, status="approved", principal_kind="service")
    override_db(gateway_engine)
    try:
        response = TestClient(app).post(
            f"/v1/projects/{project_id}/director/decision-cases/{case_id}/execute",
            headers={"Authorization": f"Bearer {token}"},
            json={"idempotency_key": "service-principal-action-001"},
        )
        assert response.status_code == 403, response.text
        with Session(gateway_engine) as db:
            assert db.scalar(select(ActionExecution)) is None
            assert db.scalar(select(Task)) is None
    finally:
        app.dependency_overrides.pop(get_db, None)

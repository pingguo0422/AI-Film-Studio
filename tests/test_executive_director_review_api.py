from __future__ import annotations
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool
from sqlalchemy import create_engine

from backend.app.api.dependencies import get_db
from backend.app.db.base import Base
from backend.app.main import app
from backend.app.models import ActionExecution, AuditLog, DirectorDecisionCase, MemberRole, Principal, Project, ProjectMember
from backend.app.security.tokens import issue_api_token


@pytest.fixture
def review_db_engine():
    engine = create_engine(
        "sqlite+pysqlite:///:memory:", connect_args={"check_same_thread": False}, poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    yield engine
    engine.dispose()


def _seed_case(db: Session, project_id, *, approval_required="director_review"):
    case = DirectorDecisionCase(
        project_id=project_id,
        case_key=f"case-{uuid4().hex}",
        source_brief_sha256="a" * 64,
        source_state_digest="b" * 64,
        recommendation_code="REPLAN_SEQUENCE",
        severity="high",
        approval_required=approval_required,
        evidence_refs=["scene:12", "task:44"],
        proposal_snapshot={"summary": "Reorder the production sequence", "impact": {"schedule": "2 days"}},
        status="open",
    )
    db.add(case)
    db.flush()
    return case


def _override_db(engine):
    def override_get_db():
        with Session(engine) as db:
            yield db
    app.dependency_overrides[get_db] = override_get_db


def test_review_inbox_and_detail_are_project_scoped(review_db_engine):
    with Session(review_db_engine) as db:
        project = Project(code="REVIEW_API", name="Review API")
        viewer = Principal(principal_kind="human", display_name="Viewer")
        db.add_all([project, viewer])
        db.flush()
        db.add(ProjectMember(project_id=project.id, principal_id=viewer.id, role=MemberRole.viewer, is_active=True))
        _, token = issue_api_token(db, principal_id=viewer.id)
        case = _seed_case(db, project.id)
        project_id, case_id = str(project.id), str(case.id)
        other_project = Project(code="REVIEW_OTHER", name="Other project")
        db.add(other_project)
        db.flush()
        other_case = _seed_case(db, other_project.id)
        other_case_id = str(other_case.id)
        db.commit()

    _override_db(review_db_engine)
    try:
        client = TestClient(app)
        headers = {"Authorization": f"Bearer {token}"}
        inbox = client.get(f"/v1/projects/{project_id}/director/decision-cases", headers=headers)
        assert inbox.status_code == 200
        assert inbox.json()["total"] == 1
        assert inbox.json()["items"][0]["evidence_count"] == 2

        detail = client.get(f"/v1/projects/{project_id}/director/decision-cases/{case_id}", headers=headers)
        assert detail.status_code == 200
        assert detail.json()["proposal_snapshot"]["summary"] == "Reorder the production sequence"

        cross_project = client.get(
            f"/v1/projects/{project_id}/director/decision-cases/{other_case_id}", headers=headers,
        )
        assert cross_project.status_code == 404
    finally:
        app.dependency_overrides.pop(get_db, None)


def test_review_inbox_supports_status_filter_and_pagination(review_db_engine):
    with Session(review_db_engine) as db:
        project = Project(code="REVIEW_PAGE", name="Review pagination")
        owner = Principal(principal_kind="human", display_name="Owner")
        db.add_all([project, owner])
        db.flush()
        db.add(ProjectMember(project_id=project.id, principal_id=owner.id, role=MemberRole.owner, is_active=True))
        _, token = issue_api_token(db, principal_id=owner.id)
        first = _seed_case(db, project.id)
        second = _seed_case(db, project.id)
        second.status = "deferred"
        second.decision = "deferred"
        second.decided_by = owner.id
        from backend.app.models import utcnow
        second.decided_at = utcnow()
        project_id = str(project.id)
        db.commit()

    _override_db(review_db_engine)
    try:
        client = TestClient(app)
        headers = {"Authorization": f"Bearer {token}"}
        open_only = client.get(f"/v1/projects/{project_id}/director/decision-cases?status=open&limit=1", headers=headers)
        assert open_only.status_code == 200
        assert open_only.json()["total"] == 1
        assert len(open_only.json()["items"]) == 1

        all_items = client.get(f"/v1/projects/{project_id}/director/decision-cases?status=all&limit=10", headers=headers)
        assert all_items.status_code == 200
        assert all_items.json()["total"] == 2
    finally:
        app.dependency_overrides.pop(get_db, None)


def test_human_director_can_decide_case_and_action_is_not_executed(review_db_engine):
    with Session(review_db_engine) as db:
        project = Project(code="REVIEW_DECIDE", name="Review decision")
        director = Principal(principal_kind="human", display_name="Director")
        db.add_all([project, director])
        db.flush()
        db.add(ProjectMember(project_id=project.id, principal_id=director.id, role=MemberRole.director, is_active=True))
        _, token = issue_api_token(db, principal_id=director.id)
        case = _seed_case(db, project.id, approval_required="director_review")
        project_id, case_id, case_uuid = str(project.id), str(case.id), case.id
        db.commit()

    _override_db(review_db_engine)
    try:
        client = TestClient(app)
        response = client.post(
            f"/v1/projects/{project_id}/director/decision-cases/{case_id}/decision",
            headers={"Authorization": f"Bearer {token}"},
            json={"decision": "approved", "note": "Approved for replanning review."},
        )
        assert response.status_code == 200, response.text
        assert response.json()["status"] == "approved"
        assert response.json()["decision_note"] == "Approved for replanning review."
        with Session(review_db_engine) as db:
            audit = db.scalar(select(AuditLog).where(AuditLog.action == "DIRECTOR_CASE_APPROVED"))
            assert audit is not None
            assert audit.details["execution_performed"] is False
            stored = db.get(DirectorDecisionCase, case_uuid)
            assert stored.status == "approved"
    finally:
        app.dependency_overrides.pop(get_db, None)


def test_viewer_cannot_decide_and_service_principal_cannot_decide(review_db_engine):
    with Session(review_db_engine) as db:
        project = Project(code="REVIEW_DENY", name="Review deny")
        viewer = Principal(principal_kind="human", display_name="Viewer")
        service = Principal(principal_kind="service", display_name="Agent service")
        db.add_all([project, viewer, service])
        db.flush()
        db.add_all([
            ProjectMember(project_id=project.id, principal_id=viewer.id, role=MemberRole.viewer, is_active=True),
            ProjectMember(project_id=project.id, principal_id=service.id, role=MemberRole.producer, is_active=True),
        ])
        _, viewer_token = issue_api_token(db, principal_id=viewer.id)
        _, service_token = issue_api_token(db, principal_id=service.id)
        case = _seed_case(db, project.id)
        project_id, case_id = str(project.id), str(case.id)
        db.commit()

    _override_db(review_db_engine)
    try:
        client = TestClient(app)
        url = f"/v1/projects/{project_id}/director/decision-cases/{case_id}/decision"
        viewer_response = client.post(url, headers={"Authorization": f"Bearer {viewer_token}"}, json={"decision": "approved"})
        assert viewer_response.status_code == 404  # no approve permission; project existence is concealed
        service_response = client.post(url, headers={"Authorization": f"Bearer {service_token}"}, json={"decision": "approved"})
        assert service_response.status_code == 403
    finally:
        app.dependency_overrides.pop(get_db, None)


def test_decision_is_single_transition_and_note_is_bounded(review_db_engine):
    with Session(review_db_engine) as db:
        project = Project(code="REVIEW_ONCE", name="Review once")
        owner = Principal(principal_kind="human", display_name="Owner")
        db.add_all([project, owner])
        db.flush()
        db.add(ProjectMember(project_id=project.id, principal_id=owner.id, role=MemberRole.owner, is_active=True))
        _, token = issue_api_token(db, principal_id=owner.id)
        case = _seed_case(db, project.id)
        project_id, case_id = str(project.id), str(case.id)
        db.commit()

    _override_db(review_db_engine)
    try:
        client = TestClient(app)
        url = f"/v1/projects/{project_id}/director/decision-cases/{case_id}/decision"
        headers = {"Authorization": f"Bearer {token}"}
        first = client.post(url, headers=headers, json={"decision": "deferred", "note": "Need more evidence."})
        assert first.status_code == 200
        second = client.post(url, headers=headers, json={"decision": "approved"})
        assert second.status_code == 409
        too_long = client.post(url, headers=headers, json={"decision": "approved", "note": "x" * 4001})
        assert too_long.status_code == 422
    finally:
        app.dependency_overrides.pop(get_db, None)


def test_review_endpoints_require_authentication_and_validate_status(review_db_engine):
    with Session(review_db_engine) as db:
        project = Project(code="REVIEW_AUTH", name="Review auth")
        owner = Principal(principal_kind="human", display_name="Owner")
        db.add_all([project, owner])
        db.flush()
        db.add(ProjectMember(project_id=project.id, principal_id=owner.id, role=MemberRole.owner, is_active=True))
        _, token = issue_api_token(db, principal_id=owner.id)
        project_id = str(project.id)
        db.commit()
    _override_db(review_db_engine)
    try:
        client = TestClient(app)
        url = f"/v1/projects/{project_id}/director/decision-cases"
        assert client.get(url).status_code == 401
        invalid = client.get(url + "?status=pending", headers={"Authorization": f"Bearer {token}"})
        assert invalid.status_code == 422
    finally:
        app.dependency_overrides.pop(get_db, None)


def test_activity_timeline_is_project_scoped_bounded_and_does_not_expose_audit_payloads(review_db_engine):
    from backend.app.models import AuditLog
    with Session(review_db_engine) as db:
        project = Project(code="TIMELINE", name="Timeline")
        viewer = Principal(principal_kind="human", display_name="Viewer")
        db.add_all([project, viewer])
        db.flush()
        db.add(ProjectMember(project_id=project.id, principal_id=viewer.id, role=MemberRole.viewer, is_active=True))
        _, token = issue_api_token(db, principal_id=viewer.id)
        db.add(AuditLog(
            project_id=project.id, actor_id=viewer.id, actor_kind="human", action="test.event",
            object_type="test_object", details={"secret": "must-not-be-exposed"},
        ))
        case = _seed_case(db, project.id)
        db.add(ActionExecution(
            project_id=project.id, decision_case_id=case.id, action_type="create_task",
            action_sha256="c" * 64, idempotency_key="timeline-action-001", status="succeeded",
            requested_by=viewer.id, result_snapshot={"task_id": "private-result"},
        ))
        project_id = str(project.id)
        db.commit()

    _override_db(review_db_engine)
    try:
        client = TestClient(app)
        response = client.get(
            f"/v1/projects/{project_id}/director/activity?limit=10",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert response.status_code == 200, response.text
        payload = response.json()
        assert payload["limit"] == 10
        assert any(item["title"] == "test.event · test_object" for item in payload["items"])
        assert any(item["kind"] == "action_execution" and item["status"] == "succeeded" for item in payload["items"])
        assert "secret" not in response.text
        assert "private-result" not in response.text
        assert client.get(f"/v1/projects/{project_id}/director/activity?limit=101", headers={"Authorization": f"Bearer {token}"}).status_code == 422
    finally:
        app.dependency_overrides.pop(get_db, None)

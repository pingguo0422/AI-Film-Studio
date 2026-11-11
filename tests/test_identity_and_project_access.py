from datetime import datetime, timedelta, timezone
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from backend.app.api.dependencies import get_db
from backend.app.db.base import Base
from backend.app.main import app
from backend.app.models import ApiToken, AuditLog, MemberRole, Principal, Project, ProjectMember
from backend.app.security.authorization import AuthorizationError, ProjectPermission, require_project_permission
from backend.app.security.tokens import AuthenticationError, authenticate_api_token, issue_api_token, token_digest


@pytest.fixture
def db_engine():
    engine = create_engine("sqlite+pysqlite:///:memory:", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    yield engine
    engine.dispose()


@pytest.fixture
def db_session(db_engine):
    with Session(db_engine) as db:
        yield db


def seed(db):
    project = Project(code="AUTH_TEST", name="Auth test")
    owner = Principal(principal_kind="human", display_name="Owner")
    viewer = Principal(principal_kind="human", display_name="Viewer")
    db.add_all([project, owner, viewer])
    db.flush()
    db.add_all([
        ProjectMember(project_id=project.id, principal_id=owner.id, role=MemberRole.owner, is_active=True),
        ProjectMember(project_id=project.id, principal_id=viewer.id, role=MemberRole.viewer, is_active=True),
    ])
    _, owner_token = issue_api_token(db, principal_id=owner.id)
    _, viewer_token = issue_api_token(db, principal_id=viewer.id)
    db.commit()
    return project, owner, viewer, owner_token, viewer_token


def test_raw_token_is_not_persisted_and_authenticates_principal(db_session):
    principal = Principal(principal_kind="service", display_name="Render worker")
    db_session.add(principal)
    db_session.flush()
    row, raw = issue_api_token(db_session, principal_id=principal.id)
    assert raw.startswith("afs_pat_")
    assert row.token_hash == token_digest(raw)
    assert raw != row.token_hash
    assert authenticate_api_token(db_session, raw).id == principal.id
    issued_audit = db_session.scalar(select(AuditLog).where(AuditLog.action == "api_token.issued"))
    assert issued_audit is not None
    assert "api_token" == issued_audit.object_type


def test_revoked_expired_and_malformed_tokens_are_rejected(db_session):
    principal = Principal(principal_kind="human", display_name="Operator")
    db_session.add(principal)
    db_session.flush()
    row, raw = issue_api_token(db_session, principal_id=principal.id)
    row.revoked_at = datetime.now(timezone.utc)
    with pytest.raises(AuthenticationError):
        authenticate_api_token(db_session, raw)
    with pytest.raises(AuthenticationError):
        authenticate_api_token(db_session, "not-a-token")

    row2, raw2 = issue_api_token(db_session, principal_id=principal.id)
    row2.expires_at = datetime.now(timezone.utc) - timedelta(seconds=1)
    with pytest.raises(AuthenticationError, match="expired"):
        authenticate_api_token(db_session, raw2)


def test_inactive_principal_cannot_receive_or_use_token(db_session):
    principal = Principal(principal_kind="human", display_name="Disabled", is_active=False)
    db_session.add(principal)
    db_session.flush()
    with pytest.raises(ValueError, match="active principal"):
        issue_api_token(db_session, principal_id=principal.id)


def test_role_permission_matrix_and_inactive_membership(db_session):
    project, owner, viewer, _, _ = seed(db_session)
    assert require_project_permission(db_session, project_id=project.id, principal_id=owner.id, permission=ProjectPermission.administer)
    with pytest.raises(AuthorizationError):
        require_project_permission(db_session, project_id=project.id, principal_id=viewer.id, permission=ProjectPermission.contribute)
    member = db_session.scalar(select(ProjectMember).where(ProjectMember.principal_id == viewer.id))
    member.is_active = False
    with pytest.raises(AuthorizationError):
        require_project_permission(db_session, project_id=project.id, principal_id=viewer.id, permission=ProjectPermission.read)


def test_api_requires_bearer_and_exposes_current_principal(db_engine):
    with Session(db_engine) as db:
        _, owner, _, owner_token, _ = seed(db)
        owner_id = str(owner.id)
    def override_get_db():
        with Session(db_engine) as db:
            yield db
    app.dependency_overrides[get_db] = override_get_db
    try:
        client = TestClient(app)
        assert client.get("/v1/me").status_code == 401
        response = client.get("/v1/me", headers={"Authorization": f"Bearer {owner_token}"})
        assert response.status_code == 200
        assert response.json()["id"] == owner_id
    finally:
        app.dependency_overrides.pop(get_db, None)


def test_project_member_management_is_role_gated_and_audited(db_engine):
    with Session(db_engine) as db:
        project, owner, viewer, owner_token, viewer_token = seed(db)
        target = Principal(principal_kind="human", display_name="New collaborator")
        db.add(target)
        db.commit()
        project_id, target_id = str(project.id), str(target.id)
    def override_get_db():
        with Session(db_engine) as db:
            yield db
    app.dependency_overrides[get_db] = override_get_db
    try:
        client = TestClient(app)
        denied = client.put(
            f"/v1/projects/{project_id}/members/{target_id}",
            headers={"Authorization": f"Bearer {viewer_token}"},
            json={"role": "collaborator"},
        )
        assert denied.status_code == 404
        allowed = client.put(
            f"/v1/projects/{project_id}/members/{target_id}",
            headers={"Authorization": f"Bearer {owner_token}"},
            json={"role": "collaborator"},
        )
        assert allowed.status_code == 200
        assert allowed.json()["role"] == "collaborator"
        with Session(db_engine) as db:
            audit = db.scalar(select(AuditLog).where(AuditLog.action == "project_member.added"))
            assert audit is not None
            assert audit.details["target_principal_id"] == target_id
    finally:
        app.dependency_overrides.pop(get_db, None)


def test_last_project_owner_cannot_be_deactivated(db_engine):
    with Session(db_engine) as db:
        project, owner, _, owner_token, _ = seed(db)
        project_id, owner_id = str(project.id), str(owner.id)
    def override_get_db():
        with Session(db_engine) as db:
            yield db
    app.dependency_overrides[get_db] = override_get_db
    try:
        response = TestClient(app).delete(
            f"/v1/projects/{project_id}/members/{owner_id}",
            headers={"Authorization": f"Bearer {owner_token}"},
        )
        assert response.status_code == 409
    finally:
        app.dependency_overrides.pop(get_db, None)


def test_project_producer_cannot_grant_owner_or_modify_owner(db_engine):
    with Session(db_engine) as db:
        project = Project(code="PRODUCER_GUARD", name="Producer guard")
        producer = Principal(principal_kind="human", display_name="Producer")
        owner = Principal(principal_kind="human", display_name="Owner")
        newcomer = Principal(principal_kind="human", display_name="New owner")
        db.add_all([project, producer, owner, newcomer])
        db.flush()
        db.add_all([
            ProjectMember(project_id=project.id, principal_id=producer.id, role=MemberRole.producer, is_active=True),
            ProjectMember(project_id=project.id, principal_id=owner.id, role=MemberRole.owner, is_active=True),
        ])
        _, producer_token = issue_api_token(db, principal_id=producer.id)
        db.commit()
        project_id, owner_id, newcomer_id = str(project.id), str(owner.id), str(newcomer.id)

    def override_get_db():
        with Session(db_engine) as db:
            yield db
    app.dependency_overrides[get_db] = override_get_db
    try:
        client = TestClient(app)
        headers = {"Authorization": f"Bearer {producer_token}"}
        grant = client.put(f"/v1/projects/{project_id}/members/{newcomer_id}", headers=headers, json={"role": "owner"})
        assert grant.status_code == 403
        grant_director = client.put(f"/v1/projects/{project_id}/members/{newcomer_id}", headers=headers, json={"role": "director"})
        assert grant_director.status_code == 403
        demote = client.put(f"/v1/projects/{project_id}/members/{owner_id}", headers=headers, json={"role": "viewer"})
        assert demote.status_code == 403
        remove = client.delete(f"/v1/projects/{project_id}/members/{owner_id}", headers=headers)
        assert remove.status_code == 403
    finally:
        app.dependency_overrides.pop(get_db, None)


def test_last_owner_cannot_demote_self(db_engine):
    with Session(db_engine) as db:
        project = Project(code="LAST_OWNER_DEMOTE", name="Last owner")
        owner = Principal(principal_kind="human", display_name="Only owner")
        db.add_all([project, owner])
        db.flush()
        db.add(ProjectMember(project_id=project.id, principal_id=owner.id, role=MemberRole.owner, is_active=True))
        _, token = issue_api_token(db, principal_id=owner.id)
        db.commit()
        project_id, owner_id = str(project.id), str(owner.id)
    def override_get_db():
        with Session(db_engine) as db:
            yield db
    app.dependency_overrides[get_db] = override_get_db
    try:
        response = TestClient(app).put(
            f"/v1/projects/{project_id}/members/{owner_id}",
            headers={"Authorization": f"Bearer {token}"},
            json={"role": "viewer"},
        )
        assert response.status_code == 409
    finally:
        app.dependency_overrides.pop(get_db, None)


def test_principal_can_revoke_own_api_token(db_engine):
    with Session(db_engine) as db:
        principal = Principal(principal_kind="human", display_name="Token owner")
        db.add(principal)
        db.flush()
        token_row, raw = issue_api_token(db, principal_id=principal.id)
        token_id = str(token_row.id)
        token_uuid = token_row.id
        db.commit()
    def override_get_db():
        with Session(db_engine) as db:
            yield db
    app.dependency_overrides[get_db] = override_get_db
    try:
        response = TestClient(app).delete(
            f"/v1/me/tokens/{token_id}", headers={"Authorization": f"Bearer {raw}"}
        )
        assert response.status_code == 204
        with Session(db_engine) as db:
            stored = db.get(ApiToken, token_uuid)
            assert stored.revoked_at is not None
            revoked_audit = db.scalar(select(AuditLog).where(AuditLog.action == "api_token.revoked"))
            assert revoked_audit is not None
            with pytest.raises(AuthenticationError):
                authenticate_api_token(db, raw)
    finally:
        app.dependency_overrides.pop(get_db, None)

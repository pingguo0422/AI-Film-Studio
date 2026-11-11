import pytest
from sqlalchemy import create_engine, event
from sqlalchemy.orm import Session
from backend.app.db.base import Base
from backend.app.db.ids import uuid7
from backend.app.models import Project, ProjectMember, MemberRole, Entity, EntityVersion, ApprovalRecord, ApprovalStatus, EntityVersionPointer, AuditLog, Principal
from backend.app.services.approval_service import decide_approval, ApprovalPermissionError, ApprovalTransitionError

def make_session():
    engine = create_engine("sqlite+pysqlite:///:memory:")
    @event.listens_for(engine, "connect")
    def enable_fk(dbapi_connection, _):
        dbapi_connection.execute("PRAGMA foreign_keys=ON")
    Base.metadata.create_all(engine)
    return Session(engine)

def setup_record(db):
    project_id, principal_id, entity_id, version_id, record_id = [uuid7() for _ in range(5)]
    db.add(Project(id=project_id, code="PRJ_APPROVAL", name="Approval test")); db.flush()
    db.add(Principal(id=principal_id, principal_kind="human", display_name="Reviewer")); db.flush()
    db.add(ProjectMember(project_id=project_id, principal_id=principal_id, role=MemberRole.director, is_active=True)); db.flush()
    db.add(Entity(id=entity_id, project_id=project_id, entity_type="VISUAL_BIBLE", title="Visual Bible")); db.flush()
    db.add(EntityVersion(id=version_id, project_id=project_id, entity_id=entity_id, version_number=1, content={}, content_sha256="a"*64)); db.flush()
    record = ApprovalRecord(id=record_id, project_id=project_id, entity_id=entity_id, entity_version_id=version_id, reviewer_id=principal_id, status=ApprovalStatus.pending)
    db.add(record); db.commit()
    return record_id, principal_id

def test_agent_cannot_approve_even_when_assigned_reviewer():
    with make_session() as db:
        rid, actor = setup_record(db)
        with pytest.raises(ApprovalPermissionError):
            decide_approval(db, record_id=rid, actor_id=actor, actor_kind="agent", target_status=ApprovalStatus.approved)

def test_assigned_human_project_director_can_approve():
    with make_session() as db:
        rid, actor = setup_record(db)
        record = decide_approval(db, record_id=rid, actor_id=actor, actor_kind="human", target_status=ApprovalStatus.approved, note="Reviewed")
        assert record.status == ApprovalStatus.approved
        assert record.decision_note == "Reviewed"
        assert record.decided_at is not None
        pointer = db.query(EntityVersionPointer).filter_by(entity_id=record.entity_id).one()
        assert pointer.approved_version_id == record.entity_version_id
        audit = db.query(AuditLog).filter_by(object_id=record.entity_version_id).one()
        assert audit.action == "APPROVAL_APPROVED"

def test_multistep_workflow_does_not_approve_pointer_early():
    from backend.app.models import ApprovalWorkflow, ApprovalStep
    with make_session() as db:
        project_id, entity_id, version_id, workflow_id = [uuid7() for _ in range(4)]
        reviewer_a, reviewer_b, record_a, record_b = [uuid7() for _ in range(4)]
        db.add(Project(id=project_id, code="PRJ_MULTI", name="Multi-step")); db.flush()
        db.add_all([Principal(id=reviewer_a, principal_kind="human", display_name="Reviewer A"), Principal(id=reviewer_b, principal_kind="human", display_name="Reviewer B")]); db.flush()
        db.add_all([
            ProjectMember(project_id=project_id, principal_id=reviewer_a, role=MemberRole.director, is_active=True),
            ProjectMember(project_id=project_id, principal_id=reviewer_b, role=MemberRole.director, is_active=True),
        ]); db.flush()
        db.add(Entity(id=entity_id, project_id=project_id, entity_type="VISUAL_BIBLE", title="VB")); db.flush()
        db.add(EntityVersion(id=version_id, project_id=project_id, entity_id=entity_id, version_number=1, content={}, content_sha256="b"*64)); db.flush()
        db.add(ApprovalWorkflow(id=workflow_id, project_id=project_id, code="TWO_STEP", name="Two step", is_active=True)); db.flush()
        db.add_all([
            ApprovalStep(workflow_id=workflow_id, step_order=1, required_role="director", is_required=True),
            ApprovalStep(workflow_id=workflow_id, step_order=2, required_role="director", is_required=True),
        ]); db.flush()
        db.add_all([
            ApprovalRecord(id=record_a, project_id=project_id, entity_id=entity_id, entity_version_id=version_id, workflow_id=workflow_id, step_order=1, reviewer_id=reviewer_a, status=ApprovalStatus.pending),
            ApprovalRecord(id=record_b, project_id=project_id, entity_id=entity_id, entity_version_id=version_id, workflow_id=workflow_id, step_order=2, reviewer_id=reviewer_b, status=ApprovalStatus.pending),
        ]); db.commit()
        decide_approval(db, record_id=record_a, actor_id=reviewer_a, actor_kind="human", target_status=ApprovalStatus.approved)
        db.flush()
        assert db.query(EntityVersionPointer).filter_by(entity_id=entity_id).one_or_none() is None
        decide_approval(db, record_id=record_b, actor_id=reviewer_b, actor_kind="human", target_status=ApprovalStatus.approved)
        db.flush()
        pointer = db.query(EntityVersionPointer).filter_by(entity_id=entity_id).one()
        assert pointer.approved_version_id == version_id

def test_withdrawal_is_not_available_until_submitter_identity_is_modelled():
    with make_session() as db:
        rid, actor = setup_record(db)
        with pytest.raises(ApprovalTransitionError):
            decide_approval(db, record_id=rid, actor_id=actor, actor_kind="human", target_status=ApprovalStatus.withdrawn)

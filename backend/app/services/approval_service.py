"""Human-authorized approval transitions. Agents may prepare, never approve."""
from datetime import datetime, timezone
from uuid import UUID
from sqlalchemy import select
from sqlalchemy.orm import Session
from backend.app.models import ApprovalRecord, ApprovalStatus, ApprovalStep, ApprovalWorkflow, MemberRole, ProjectMember, EntityVersionPointer, AuditLog

class ApprovalError(Exception):
    pass

class ApprovalPermissionError(ApprovalError):
    pass

class ApprovalTransitionError(ApprovalError):
    pass

TERMINAL = {ApprovalStatus.approved, ApprovalStatus.rejected, ApprovalStatus.changes_requested}

def decide_approval(
    db: Session,
    *,
    record_id: UUID,
    actor_id: UUID,
    actor_kind: str,
    target_status: ApprovalStatus,
    note: str | None = None,
) -> ApprovalRecord:
    """Apply one approval decision after verifying human identity and project role.

    This function intentionally has no `is_authorized` boolean supplied by callers.
    Authorization is resolved against persisted project membership and workflow step.
    """
    if actor_kind != "human":
        raise ApprovalPermissionError("only a human principal may decide an approval")
    if target_status not in TERMINAL:
        raise ApprovalTransitionError("target status must be an approval decision state")
    record = db.get(ApprovalRecord, record_id)
    if record is None:
        raise ApprovalTransitionError("approval record not found")
    if record.status != ApprovalStatus.pending:
        raise ApprovalTransitionError("only pending approval records can be decided")
    if record.reviewer_id != actor_id:
        raise ApprovalPermissionError("actor is not the assigned reviewer")
    membership = db.scalar(select(ProjectMember).where(
        ProjectMember.project_id == record.project_id,
        ProjectMember.principal_id == actor_id,
        ProjectMember.is_active.is_(True),
    ))
    if membership is None:
        raise ApprovalPermissionError("actor is not an active project member")
    if record.workflow_id is not None:
        workflow = db.get(ApprovalWorkflow, record.workflow_id)
        if workflow is None or workflow.project_id != record.project_id:
            raise ApprovalPermissionError("approval workflow does not belong to the record project")
        step = db.scalar(select(ApprovalStep).where(
            ApprovalStep.workflow_id == record.workflow_id,
            ApprovalStep.step_order == record.step_order,
        ))
        if step is None:
            raise ApprovalTransitionError("approval step is not configured")
        try:
            required_role = MemberRole(step.required_role)
        except ValueError as exc:
            raise ApprovalTransitionError("approval step has an unknown required role") from exc
        if membership.role not in {MemberRole.owner, required_role}:
            raise ApprovalPermissionError("project role is not authorized for this approval step")
    elif membership.role not in {MemberRole.owner, MemberRole.producer, MemberRole.director}:
        raise ApprovalPermissionError("role is not authorized for an unconfigured approval")

    record.status = target_status
    record.decision_note = note
    record.decided_at = datetime.now(timezone.utc)
    db.add(record)

    if target_status == ApprovalStatus.approved:
        # A multi-step workflow is complete only when every required step has
        # at least one approved record for this exact immutable version.
        db.flush()
        workflow_complete = record.workflow_id is None
        if record.workflow_id is not None:
            required_steps = set(db.scalars(select(ApprovalStep.step_order).where(
                ApprovalStep.workflow_id == record.workflow_id,
                ApprovalStep.is_required.is_(True),
            )).all())
            approved_steps = set(db.scalars(select(ApprovalRecord.step_order).where(
                ApprovalRecord.workflow_id == record.workflow_id,
                ApprovalRecord.entity_version_id == record.entity_version_id,
                ApprovalRecord.status == ApprovalStatus.approved,
            ).distinct()).all())
            workflow_complete = bool(required_steps) and required_steps.issubset(approved_steps)
        if workflow_complete:
            pointer = db.scalar(select(EntityVersionPointer).where(
                EntityVersionPointer.project_id == record.project_id,
                EntityVersionPointer.entity_id == record.entity_id,
            ))
            if pointer is None:
                pointer = EntityVersionPointer(
                    project_id=record.project_id,
                    entity_id=record.entity_id,
                    approved_version_id=record.entity_version_id,
                )
                db.add(pointer)
            else:
                pointer.approved_version_id = record.entity_version_id

    db.add(AuditLog(
        project_id=record.project_id,
        actor_id=actor_id,
        actor_kind="human",
        action=f"APPROVAL_{target_status.value.upper()}",
        object_type="ENTITY_VERSION",
        object_id=record.entity_version_id,
        details={"approval_record_id": str(record.id), "note": note},
    ))
    db.flush()
    return record

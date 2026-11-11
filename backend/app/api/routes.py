from __future__ import annotations
from uuid import UUID
from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from sqlalchemy import select, func
from sqlalchemy.orm import Session
from backend.app.api.dependencies import get_current_principal, get_db
from backend.app.api.schemas import (
    DirectorDecisionDetail, DirectorDecisionInbox, DirectorDecisionSubmit,
    DirectorDecisionSummary, DirectorActivityEvent, DirectorActivityTimeline, MemberList, MemberUpsert, MembershipRead, PrincipalRead,
    ActionExecutionSubmit, ActionExecutionRead,
)
from backend.app.models import ActionExecution, Agent, AgentRun, ApiToken, AuditLog, DirectorDecisionCase, MemberRole, Principal, Project, ProjectMember, Task, utcnow
from backend.app.security.authorization import AuthorizationError, ProjectPermission, require_project_permission
from backend.app.services.action_execution import ActionExecutionError, execute_approved_action
from backend.app.services.director_decision_cases import (
    DirectorDecisionCaseError, DirectorDecisionCasePermissionError, decide_director_case,
)

router = APIRouter(prefix="/v1", tags=["identity-and-project-access"])


def _project_exists(db: Session, project_id: UUID) -> None:
    if db.get(Project, project_id) is None:
        raise HTTPException(status_code=404, detail="project not found")


def _lock_project_for_membership_change(db: Session, project_id: UUID) -> None:
    # Serialize owner-role changes on the project row to prevent concurrent
    # requests from independently removing the last two active owners.
    project = db.scalar(select(Project).where(Project.id == project_id).with_for_update())
    if project is None:
        raise HTTPException(status_code=404, detail="project not found")


def _authorize(db: Session, *, project_id: UUID, principal: Principal, permission: ProjectPermission) -> ProjectMember:
    try:
        return require_project_permission(db, project_id=project_id, principal_id=principal.id, permission=permission)
    except AuthorizationError as exc:
        # Do not disclose whether a project exists to a non-member.
        raise HTTPException(status_code=404, detail="project not found") from exc


@router.get("/me", response_model=PrincipalRead)
def read_me(principal: Principal = Depends(get_current_principal)):
    return principal


@router.delete("/me/tokens/{token_id}", status_code=status.HTTP_204_NO_CONTENT)
def revoke_my_token(
    token_id: UUID,
    principal: Principal = Depends(get_current_principal),
    db: Session = Depends(get_db),
):
    token = db.scalar(select(ApiToken).where(ApiToken.id == token_id, ApiToken.principal_id == principal.id))
    if token is None:
        raise HTTPException(status_code=404, detail="token not found")
    if token.revoked_at is None:
        token.revoked_at = utcnow()
        db.add(AuditLog(
            project_id=None, actor_id=principal.id, actor_kind=principal.principal_kind,
            action="api_token.revoked", object_type="api_token", object_id=token.id,
            details={"token_prefix": token.token_prefix},
        ))
        db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get("/projects/{project_id}/membership", response_model=MembershipRead)
def read_my_membership(
    project_id: UUID,
    principal: Principal = Depends(get_current_principal),
    db: Session = Depends(get_db),
):
    _project_exists(db, project_id)
    member = _authorize(db, project_id=project_id, principal=principal, permission=ProjectPermission.read)
    return member


@router.get("/projects/{project_id}/members", response_model=MemberList)
def list_project_members(
    project_id: UUID,
    principal: Principal = Depends(get_current_principal),
    db: Session = Depends(get_db),
):
    _project_exists(db, project_id)
    _authorize(db, project_id=project_id, principal=principal, permission=ProjectPermission.manage_members)
    rows = db.scalars(select(ProjectMember).where(ProjectMember.project_id == project_id, ProjectMember.is_active.is_(True)).order_by(ProjectMember.created_at)).all()
    return MemberList(items=rows)


@router.put("/projects/{project_id}/members/{target_principal_id}", response_model=MembershipRead)
def upsert_project_member(
    project_id: UUID,
    target_principal_id: UUID,
    payload: MemberUpsert,
    principal: Principal = Depends(get_current_principal),
    db: Session = Depends(get_db),
):
    _lock_project_for_membership_change(db, project_id)
    actor_membership = _authorize(db, project_id=project_id, principal=principal, permission=ProjectPermission.manage_members)
    actor_role = actor_membership.role if isinstance(actor_membership.role, MemberRole) else MemberRole(actor_membership.role)
    target = db.get(Principal, target_principal_id)
    if target is None or not target.is_active:
        raise HTTPException(status_code=404, detail="active principal not found")
    member = db.scalar(select(ProjectMember).where(ProjectMember.project_id == project_id, ProjectMember.principal_id == target_principal_id))
    before_role = member.role if member and isinstance(member.role, MemberRole) else (MemberRole(member.role) if member else None)
    privileged_roles = {MemberRole.owner, MemberRole.producer, MemberRole.director}
    if payload.role in privileged_roles and actor_role != MemberRole.owner:
        raise HTTPException(status_code=403, detail="only a project owner may grant privileged project roles")
    if before_role in privileged_roles and actor_role != MemberRole.owner:
        raise HTTPException(status_code=403, detail="only a project owner may modify a privileged project member")
    if before_role == MemberRole.owner and payload.role != MemberRole.owner:
        active_owners = db.scalar(select(func.count()).select_from(ProjectMember).where(
            ProjectMember.project_id == project_id, ProjectMember.is_active.is_(True), ProjectMember.role == MemberRole.owner
        )) or 0
        if active_owners <= 1:
            raise HTTPException(status_code=409, detail="cannot demote the last active project owner")
    before = before_role.value if before_role else None
    if member is None:
        member = ProjectMember(project_id=project_id, principal_id=target_principal_id, role=payload.role, is_active=True)
        db.add(member)
        action = "project_member.added"
    else:
        member.role = payload.role
        member.is_active = True
        action = "project_member.updated"
    db.add(AuditLog(project_id=project_id, actor_id=principal.id, actor_kind=principal.principal_kind,
                    action=action, object_type="project_member", object_id=member.id,
                    details={"target_principal_id": str(target_principal_id), "before_role": before, "after_role": payload.role.value}))
    db.commit()
    db.refresh(member)
    return member


@router.delete("/projects/{project_id}/members/{target_principal_id}", status_code=status.HTTP_204_NO_CONTENT)
def deactivate_project_member(
    project_id: UUID,
    target_principal_id: UUID,
    principal: Principal = Depends(get_current_principal),
    db: Session = Depends(get_db),
):
    _lock_project_for_membership_change(db, project_id)
    actor_membership = _authorize(db, project_id=project_id, principal=principal, permission=ProjectPermission.manage_members)
    actor_role = actor_membership.role if isinstance(actor_membership.role, MemberRole) else MemberRole(actor_membership.role)
    member = db.scalar(select(ProjectMember).where(ProjectMember.project_id == project_id, ProjectMember.principal_id == target_principal_id, ProjectMember.is_active.is_(True)))
    if member is None:
        raise HTTPException(status_code=404, detail="active project member not found")
    role = member.role if isinstance(member.role, MemberRole) else MemberRole(member.role)
    privileged_roles = {MemberRole.owner, MemberRole.producer, MemberRole.director}
    if role in privileged_roles and actor_role != MemberRole.owner:
        raise HTTPException(status_code=403, detail="only a project owner may deactivate a privileged project member")
    if role == MemberRole.owner:
        active_owners = db.scalar(select(func.count()).select_from(ProjectMember).where(
            ProjectMember.project_id == project_id, ProjectMember.is_active.is_(True), ProjectMember.role == MemberRole.owner
        )) or 0
        if active_owners <= 1:
            raise HTTPException(status_code=409, detail="cannot deactivate the last active project owner")
    member.is_active = False
    db.add(AuditLog(project_id=project_id, actor_id=principal.id, actor_kind=principal.principal_kind,
                    action="project_member.deactivated", object_type="project_member", object_id=member.id,
                    details={"target_principal_id": str(target_principal_id), "previous_role": role.value}))
    db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get(
    "/projects/{project_id}/director/decision-cases",
    response_model=DirectorDecisionInbox,
    tags=["executive-director-review"],
)
def list_director_decision_cases(
    project_id: UUID,
    case_status: str = Query(default="open", alias="status", pattern="^(open|approved|rejected|deferred|closed|all)$"),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0, le=100000),
    principal: Principal = Depends(get_current_principal),
    db: Session = Depends(get_db),
):
    """List the authenticated principal's project-scoped director review inbox."""
    _project_exists(db, project_id)
    _authorize(db, project_id=project_id, principal=principal, permission=ProjectPermission.read)
    filters = [DirectorDecisionCase.project_id == project_id]
    if case_status != "all":
        filters.append(DirectorDecisionCase.status == case_status)
    total = db.scalar(select(func.count()).select_from(DirectorDecisionCase).where(*filters)) or 0
    rows = db.scalars(
        select(DirectorDecisionCase).where(*filters)
        .order_by(DirectorDecisionCase.created_at.desc(), DirectorDecisionCase.id.desc())
        .limit(limit).offset(offset)
    ).all()
    items = [DirectorDecisionSummary(
        id=row.id, project_id=row.project_id, recommendation_code=row.recommendation_code,
        severity=row.severity, approval_required=row.approval_required, status=row.status,
        evidence_count=len(row.evidence_refs or []), created_at=row.created_at, decided_at=row.decided_at,
    ) for row in rows]
    return DirectorDecisionInbox(items=items, total=total, limit=limit, offset=offset)


@router.get(
    "/projects/{project_id}/director/decision-cases/{case_id}",
    response_model=DirectorDecisionDetail,
    tags=["executive-director-review"],
)
def read_director_decision_case(
    project_id: UUID,
    case_id: UUID,
    principal: Principal = Depends(get_current_principal),
    db: Session = Depends(get_db),
):
    _project_exists(db, project_id)
    _authorize(db, project_id=project_id, principal=principal, permission=ProjectPermission.read)
    case = db.scalar(select(DirectorDecisionCase).where(
        DirectorDecisionCase.id == case_id, DirectorDecisionCase.project_id == project_id,
    ))
    if case is None:
        raise HTTPException(status_code=404, detail="director decision case not found")
    return DirectorDecisionDetail.from_case(case)


@router.post(
    "/projects/{project_id}/director/decision-cases/{case_id}/decision",
    response_model=DirectorDecisionDetail,
    tags=["executive-director-review"],
)
def submit_director_decision(
    project_id: UUID,
    case_id: UUID,
    payload: DirectorDecisionSubmit,
    principal: Principal = Depends(get_current_principal),
    db: Session = Depends(get_db),
):
    _project_exists(db, project_id)
    if principal.principal_kind != "human":
        raise HTTPException(status_code=403, detail="only human principals may decide director cases")
    _authorize(db, project_id=project_id, principal=principal, permission=ProjectPermission.approve)
    try:
        case = decide_director_case(
            db, project_id=project_id, case_id=case_id, actor_id=principal.id,
            actor_kind=principal.principal_kind, decision=payload.decision, note=payload.note,
            authorized_action=payload.authorized_action.model_dump() if payload.authorized_action else None,
        )
        db.commit()
        db.refresh(case)
        return DirectorDecisionDetail.from_case(case)
    except DirectorDecisionCasePermissionError as exc:
        db.rollback()
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    except DirectorDecisionCaseError as exc:
        db.rollback()
        message = str(exc)
        code = 404 if "not found" in message else (409 if "already decided" in message or "only open" in message else 422)
        raise HTTPException(status_code=code, detail=message) from exc


@router.get(
    "/projects/{project_id}/director/decision-cases/{case_id}/execute",
    response_model=ActionExecutionRead,
    tags=["executive-director-actions"],
)
def read_director_action_execution(
    project_id: UUID,
    case_id: UUID,
    principal: Principal = Depends(get_current_principal),
    db: Session = Depends(get_db),
):
    _project_exists(db, project_id)
    _authorize(db, project_id=project_id, principal=principal, permission=ProjectPermission.read)
    execution = db.scalar(select(ActionExecution).where(
        ActionExecution.project_id == project_id,
        ActionExecution.decision_case_id == case_id,
    ))
    if execution is None:
        raise HTTPException(status_code=404, detail="action execution not found")
    return ActionExecutionRead(
        id=execution.id, decision_case_id=execution.decision_case_id,
        action_type=execution.action_type, action_sha256=execution.action_sha256,
        status=execution.status, result_snapshot=execution.result_snapshot,
        created_at=execution.created_at,
    )


@router.post(
    "/projects/{project_id}/director/decision-cases/{case_id}/execute",
    response_model=ActionExecutionRead,
    tags=["executive-director-actions"],
)
def execute_director_approved_action(
    project_id: UUID,
    case_id: UUID,
    payload: ActionExecutionSubmit,
    principal: Principal = Depends(get_current_principal),
    db: Session = Depends(get_db),
):
    _project_exists(db, project_id)
    if principal.principal_kind != "human":
        raise HTTPException(status_code=403, detail="only human principals may execute approved actions")
    _authorize(db, project_id=project_id, principal=principal, permission=ProjectPermission.approve)
    try:
        execution, _created = execute_approved_action(
            db, project_id=project_id, case_id=case_id, actor_id=principal.id,
            actor_kind=principal.principal_kind, idempotency_key=payload.idempotency_key,
        )
        db.commit()
        db.refresh(execution)
        return ActionExecutionRead(
            id=execution.id, decision_case_id=execution.decision_case_id,
            action_type=execution.action_type, action_sha256=execution.action_sha256,
            status=execution.status, result_snapshot=execution.result_snapshot,
            created_at=execution.created_at,
        )
    except ActionExecutionError as exc:
        db.rollback()
        message = str(exc)
        code = 404 if "not found" in message else (409 if any(term in message for term in ("already", "not approved", "conflicts", "concurrently", "not active")) else 422)
        raise HTTPException(status_code=code, detail=message) from exc


@router.get(
    "/projects/{project_id}/director/activity",
    response_model=DirectorActivityTimeline,
    tags=["executive-director-review"],
)
def read_director_activity_timeline(
    project_id: UUID,
    limit: int = Query(default=50, ge=1, le=100),
    principal: Principal = Depends(get_current_principal),
    db: Session = Depends(get_db),
):
    """Return a bounded, read-only project activity timeline without raw payloads."""
    _project_exists(db, project_id)
    _authorize(db, project_id=project_id, principal=principal, permission=ProjectPermission.read)
    events: list[DirectorActivityEvent] = []

    run_rows = db.execute(
        select(AgentRun, Agent, Task)
        .join(Agent, Agent.id == AgentRun.agent_id)
        .join(Task, (Task.id == AgentRun.task_id) & (Task.project_id == AgentRun.project_id))
        .where(AgentRun.project_id == project_id)
        .order_by(AgentRun.created_at.desc())
        .limit(limit)
    ).all()
    for run, agent, task in run_rows:
        events.append(DirectorActivityEvent(
            id=f"run:{run.id}", kind="agent_run", title=f"{agent.display_name} · {task.title}",
            status=run.status, occurred_at=run.finished_at or run.started_at or run.created_at,
            reference_id=run.id,
        ))

    task_rows = db.scalars(
        select(Task).where(Task.project_id == project_id)
        .order_by(Task.updated_at.desc()).limit(limit)
    ).all()
    for task in task_rows:
        events.append(DirectorActivityEvent(
            id=f"task:{task.id}", kind="task", title=task.title, status=task.status,
            occurred_at=task.updated_at or task.created_at, reference_id=task.id,
        ))

    execution_rows = db.scalars(
        select(ActionExecution).where(ActionExecution.project_id == project_id)
        .order_by(ActionExecution.created_at.desc()).limit(limit)
    ).all()
    for execution in execution_rows:
        events.append(DirectorActivityEvent(
            id=f"action:{execution.id}", kind="action_execution",
            title=f"导演授权动作 · {execution.action_type}", status=execution.status,
            occurred_at=execution.created_at, reference_id=execution.id,
        ))

    audit_rows = db.scalars(
        select(AuditLog).where(AuditLog.project_id == project_id)
        .order_by(AuditLog.created_at.desc()).limit(limit)
    ).all()
    for audit in audit_rows:
        events.append(DirectorActivityEvent(
            id=f"audit:{audit.id}", kind="audit", title=f"{audit.action} · {audit.object_type}",
            status=audit.actor_kind, occurred_at=audit.created_at, reference_id=audit.object_id,
        ))

    events.sort(key=lambda item: item.occurred_at, reverse=True)
    return DirectorActivityTimeline(items=events[:limit], limit=limit)

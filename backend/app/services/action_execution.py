"""Approval-bound, idempotent execution gateway for a deliberately small action set."""
from __future__ import annotations
import hashlib
import json
from datetime import datetime, timezone
from typing import Any
from uuid import UUID
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session
from backend.app.db.ids import uuid7
from backend.app.models import ActionExecution, AuditLog, DirectorDecisionCase, Project
from backend.app.services.task_service import create_task, TaskRuntimeError
from backend.app.services.agent_evaluation import request_rework, EvaluationError


class ActionExecutionError(ValueError):
    pass


def _digest(value: dict[str, Any]) -> str:
    raw = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def execute_approved_action(
    db: Session, *, project_id: UUID, case_id: UUID, actor_id: UUID,
    actor_kind: str, idempotency_key: str,
) -> tuple[ActionExecution, bool]:
    """Execute exactly the JSON snapshot bound at approval; never accept client action payloads here."""
    if actor_kind != "human":
        raise ActionExecutionError("only a human principal may invoke an approved action")
    if not isinstance(idempotency_key, str) or not 8 <= len(idempotency_key) <= 160:
        raise ActionExecutionError("idempotency_key must contain 8..160 characters")
    case = db.scalar(select(DirectorDecisionCase).where(
        DirectorDecisionCase.id == case_id,
        DirectorDecisionCase.project_id == project_id,
    ).with_for_update())
    if case is None:
        raise ActionExecutionError("decision case not found")
    if case.status != "approved" or case.decision != "approved":
        raise ActionExecutionError("decision case is not approved")
    action = case.authorized_action_snapshot
    if not isinstance(action, dict) or set(action) != {"action_type", "payload"}:
        raise ActionExecutionError("approved decision has no executable action bound to its approval")
    action_type, payload = action["action_type"], action["payload"]
    if not isinstance(payload, dict):
        raise ActionExecutionError("approved action snapshot is malformed")
    action_hash = _digest(action)

    existing_key = db.scalar(select(ActionExecution).where(
        ActionExecution.project_id == project_id,
        ActionExecution.idempotency_key == idempotency_key,
    ))
    if existing_key is not None:
        if existing_key.decision_case_id != case_id or existing_key.action_sha256 != action_hash:
            raise ActionExecutionError("idempotency key conflicts with a different approved action")
        return existing_key, False
    existing_case = db.scalar(select(ActionExecution).where(ActionExecution.decision_case_id == case_id))
    if existing_case is not None:
        raise ActionExecutionError("this approved decision has already been executed")

    project = db.get(Project, project_id)
    if project is None or project.status != "active":
        raise ActionExecutionError("project is not active")

    execution_id = uuid7()
    if action_type == "create_task":
        # Revalidate the persisted snapshot at the execution boundary.
        if set(payload) - {"task_type", "title", "input_snapshot", "priority", "max_attempts"}:
            raise ActionExecutionError("approved create_task snapshot contains unsupported fields")
        task = create_task(
            db, project_id=project_id, task_type=payload["task_type"], title=payload["title"],
            input_snapshot=payload["input_snapshot"], priority=payload.get("priority", 50),
            max_attempts=payload.get("max_attempts", 3),
            idempotency_key=f"director-action:{execution_id}",
        )
        task.created_by = actor_id
        result = {"task_id": str(task.id), "task_status": task.status, "created": True}
    elif action_type == "request_rework":
        try:
            evaluation_id = UUID(str(payload["evaluation_id"]))
            from backend.app.models import AgentEvaluation
            evaluation = db.scalar(select(AgentEvaluation).where(
                AgentEvaluation.id == evaluation_id,
                AgentEvaluation.project_id == project_id,
            ).with_for_update())
            if evaluation is None:
                raise ActionExecutionError("evaluation not found in this project")
            task = request_rework(db, evaluation_id=evaluation_id, task_type=payload.get("task_type"))
            task.created_by = actor_id
        except (EvaluationError, TaskRuntimeError, ValueError) as exc:
            raise ActionExecutionError(str(exc)) from exc
        result = {"task_id": str(task.id), "task_status": task.status, "evaluation_id": str(evaluation_id), "created": True}
    else:
        raise ActionExecutionError("unsupported approved action type")

    execution = ActionExecution(
        id=execution_id, project_id=project_id, decision_case_id=case_id,
        action_type=action_type, action_sha256=action_hash,
        idempotency_key=idempotency_key, status="succeeded", requested_by=actor_id,
        result_snapshot=result, created_at=datetime.now(timezone.utc),
    )
    try:
        with db.begin_nested():
            db.add(execution)
            db.flush()
    except IntegrityError as exc:
        raise ActionExecutionError("approved action was concurrently executed; retry with the same idempotency key") from exc
    db.add(AuditLog(
        project_id=project_id, actor_id=actor_id, actor_kind="human",
        action="DIRECTOR_ACTION_EXECUTED", object_type="ACTION_EXECUTION", object_id=execution.id,
        details={"decision_case_id": str(case_id), "action_type": action_type,
                 "action_sha256": action_hash, "result": result},
    ))
    db.flush()
    return execution, True

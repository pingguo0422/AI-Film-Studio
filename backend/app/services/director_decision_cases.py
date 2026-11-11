"""Persist Executive Director recommendations and collect human decisions.

This service records decisions only. It deliberately does not execute proposed
recovery, scheduling, approval, asset-locking, or creative-edit actions.
"""
from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
import re
from typing import Any
from uuid import UUID

from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from backend.app.db.ids import uuid7
from backend.app.models import AuditLog, DirectorDecisionCase, MemberRole, ProjectMember


class DirectorDecisionCaseError(ValueError):
    pass


class DirectorDecisionCasePermissionError(DirectorDecisionCaseError):
    pass


_ALLOWED_DECISIONS = {"approved", "rejected", "deferred", "closed"}
_ALLOWED_SEVERITIES = {"critical", "high", "medium", "low", "info"}
_ALLOWED_APPROVAL_CLASSES = {"not_required", "human_required", "director_review", "system_recovery"}
_HEX_64 = re.compile(r"^[0-9a-f]{64}$")


def _canonical_digest(payload: dict[str, Any]) -> str:
    encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def _validate_brief(brief: dict[str, Any], project_id: UUID) -> None:
    if not isinstance(brief, dict) or brief.get("mode") != "read_only_proposal":
        raise DirectorDecisionCaseError("only a read_only_proposal brief can create decision cases")
    if brief.get("project_id") != str(project_id):
        raise DirectorDecisionCaseError("brief project_id does not match target project")
    digest = brief.get("brief_sha256")
    state_digest = brief.get("state_digest")
    if not isinstance(digest, str) or not _HEX_64.fullmatch(digest):
        raise DirectorDecisionCaseError("brief_sha256 is missing or invalid")
    if not isinstance(state_digest, str) or not _HEX_64.fullmatch(state_digest):
        raise DirectorDecisionCaseError("state_digest is missing or invalid")
    unsigned = dict(brief)
    unsigned.pop("brief_sha256", None)
    if _canonical_digest(unsigned) != digest:
        raise DirectorDecisionCaseError("brief digest mismatch; brief may have been modified")
    if not isinstance(brief.get("recommendations"), list):
        raise DirectorDecisionCaseError("brief recommendations must be a list")


def create_decision_cases_from_brief(
    db: Session,
    *,
    project_id: UUID,
    brief: dict[str, Any],
) -> list[DirectorDecisionCase]:
    """Persist one immutable proposal snapshot per recommendation, idempotently.

    Repeating the same brief returns the same cases. A changed brief produces a
    new set of cases, preserving the provenance of each observed state.
    """
    _validate_brief(brief, project_id)
    created_or_existing: list[DirectorDecisionCase] = []
    for recommendation in brief["recommendations"]:
        if not isinstance(recommendation, dict):
            raise DirectorDecisionCaseError("each recommendation must be an object")
        code = recommendation.get("code")
        severity = recommendation.get("severity")
        approval_required = recommendation.get("approval_required")
        evidence_refs = recommendation.get("evidence_refs")
        if not isinstance(code, str) or not code or len(code) > 64:
            raise DirectorDecisionCaseError("recommendation code is invalid")
        if severity not in _ALLOWED_SEVERITIES:
            raise DirectorDecisionCaseError(f"invalid recommendation severity: {severity!r}")
        if approval_required not in _ALLOWED_APPROVAL_CLASSES:
            raise DirectorDecisionCaseError(f"invalid approval_required class: {approval_required!r}")
        if not isinstance(evidence_refs, list) or any(not isinstance(ref, str) or not ref for ref in evidence_refs):
            raise DirectorDecisionCaseError("evidence_refs must be a list of non-empty strings")
        key_payload = {
            "project_id": str(project_id),
            "state_digest": brief["state_digest"],
            "recommendation_code": code,
            "evidence_refs": sorted(set(evidence_refs)),
            "recommendation_sha256": _canonical_digest(recommendation),
        }
        case_key = _canonical_digest(key_payload)
        existing = db.scalar(select(DirectorDecisionCase).where(
            DirectorDecisionCase.project_id == project_id,
            DirectorDecisionCase.case_key == case_key,
        ))
        if existing is not None:
            created_or_existing.append(existing)
            continue
        case = DirectorDecisionCase(
            id=uuid7(),
            project_id=project_id,
            case_key=case_key,
            source_brief_sha256=brief["brief_sha256"],
            source_state_digest=brief["state_digest"],
            recommendation_code=code,
            severity=severity,
            approval_required=approval_required,
            evidence_refs=sorted(set(evidence_refs)),
            proposal_snapshot=dict(recommendation),
            status="open",
            created_at=datetime.now(timezone.utc),
        )
        try:
            # The unique project/case key is the concurrency boundary. A savepoint
            # lets a competing request win without aborting the caller's transaction.
            with db.begin_nested():
                db.add(case)
                db.flush()
            created_or_existing.append(case)
        except IntegrityError:
            existing = db.scalar(select(DirectorDecisionCase).where(
                DirectorDecisionCase.project_id == project_id,
                DirectorDecisionCase.case_key == case_key,
            ))
            if existing is None:
                raise
            created_or_existing.append(existing)
    return created_or_existing


def decide_director_case(
    db: Session,
    *,
    project_id: UUID,
    case_id: UUID,
    actor_id: UUID,
    actor_kind: str,
    decision: str,
    note: str | None = None,
    authorized_action: dict[str, Any] | None = None,
) -> DirectorDecisionCase:
    """Record a human disposition after checking persisted project membership.

    `approved` authorizes a separately implemented action pathway; this function
    never performs the proposed action itself.
    """
    if actor_kind != "human":
        raise DirectorDecisionCasePermissionError("only a human principal may decide a director case")
    if decision not in _ALLOWED_DECISIONS:
        raise DirectorDecisionCaseError(f"decision must be one of {sorted(_ALLOWED_DECISIONS)}")
    if note is not None and (not isinstance(note, str) or len(note) > 4000):
        raise DirectorDecisionCaseError("decision note must be text no longer than 4000 characters")
    if authorized_action is not None:
        if decision != "approved":
            raise DirectorDecisionCaseError("an executable action can only be bound to an approved decision")
        if not isinstance(authorized_action, dict) or set(authorized_action) != {"action_type", "payload"}:
            raise DirectorDecisionCaseError("authorized_action must contain exactly action_type and payload")
        action_type, payload = authorized_action.get("action_type"), authorized_action.get("payload")
        if not isinstance(payload, dict):
            raise DirectorDecisionCaseError("authorized action payload must be an object")
        if action_type == "create_task":
            allowed = {"task_type", "title", "input_snapshot", "priority", "max_attempts"}
            if set(payload) - allowed or not {"task_type", "title", "input_snapshot"}.issubset(payload):
                raise DirectorDecisionCaseError("create_task payload has missing or unsupported fields")
            if not isinstance(payload["task_type"], str) or not 1 <= len(payload["task_type"].strip()) <= 64:
                raise DirectorDecisionCaseError("task_type must contain 1..64 characters")
            if not isinstance(payload["title"], str) or not 1 <= len(payload["title"].strip()) <= 240:
                raise DirectorDecisionCaseError("title must contain 1..240 characters")
            if not isinstance(payload["input_snapshot"], dict) or len(str(payload["input_snapshot"])) > 32000:
                raise DirectorDecisionCaseError("input_snapshot must be a bounded object")
            priority = payload.get("priority", 50)
            attempts = payload.get("max_attempts", 3)
            if isinstance(priority, bool) or not isinstance(priority, int) or not 0 <= priority <= 100:
                raise DirectorDecisionCaseError("priority must be an integer from 0 to 100")
            if isinstance(attempts, bool) or not isinstance(attempts, int) or not 1 <= attempts <= 20:
                raise DirectorDecisionCaseError("max_attempts must be an integer from 1 to 20")
        elif action_type == "request_rework":
            if set(payload) - {"evaluation_id", "task_type"} or "evaluation_id" not in payload:
                raise DirectorDecisionCaseError("request_rework payload requires evaluation_id and optional task_type")
            try:
                UUID(str(payload["evaluation_id"]))
            except (ValueError, TypeError):
                raise DirectorDecisionCaseError("evaluation_id must be a UUID")
            if payload.get("task_type") is not None and (not isinstance(payload["task_type"], str) or not 1 <= len(payload["task_type"]) <= 64):
                raise DirectorDecisionCaseError("task_type must contain 1..64 characters")
        else:
            raise DirectorDecisionCaseError("unsupported authorized action type")
        if len(json.dumps(authorized_action, ensure_ascii=False)) > 40000:
            raise DirectorDecisionCaseError("authorized action exceeds 40 KB")

    case = db.scalar(select(DirectorDecisionCase).where(
        DirectorDecisionCase.id == case_id,
        DirectorDecisionCase.project_id == project_id,
    ).with_for_update())
    if case is None:
        raise DirectorDecisionCaseError("director decision case not found in project")
    if case.status != "open":
        raise DirectorDecisionCaseError("only open decision cases can be decided")

    membership = db.scalar(select(ProjectMember).where(
        ProjectMember.project_id == project_id,
        ProjectMember.principal_id == actor_id,
        ProjectMember.is_active.is_(True),
    ).with_for_update())
    if membership is None:
        raise DirectorDecisionCasePermissionError("actor is not an active project member")

    role = membership.role.value if isinstance(membership.role, MemberRole) else str(membership.role)
    if role == MemberRole.owner.value:
        allowed = True
    elif case.approval_required in {"human_required", "director_review"}:
        allowed = role in {MemberRole.producer.value, MemberRole.director.value}
    elif case.approval_required == "system_recovery":
        allowed = role == MemberRole.producer.value
    else:
        allowed = role in {MemberRole.producer.value, MemberRole.director.value}
    if not allowed:
        raise DirectorDecisionCasePermissionError(
            f"project role {role!r} cannot decide case requiring {case.approval_required!r}"
        )

    decided_at = datetime.now(timezone.utc)
    result = db.execute(update(DirectorDecisionCase).where(
        DirectorDecisionCase.id == case_id,
        DirectorDecisionCase.project_id == project_id,
        DirectorDecisionCase.status == "open",
    ).values(
        status=decision,
        decision=decision,
        decided_by=actor_id,
        decision_note=note,
        authorized_action_snapshot=authorized_action,
        decided_at=decided_at,
    ))
    if result.rowcount != 1:
        raise DirectorDecisionCaseError("decision case was already decided concurrently")

    db.add(AuditLog(
        project_id=project_id,
        actor_id=actor_id,
        actor_kind="human",
        action=f"DIRECTOR_CASE_{decision.upper()}",
        object_type="DIRECTOR_DECISION_CASE",
        object_id=case_id,
        details={
            "case_key": case.case_key,
            "recommendation_code": case.recommendation_code,
            "source_brief_sha256": case.source_brief_sha256,
            "note": note,
            "execution_performed": False,
        },
    ))
    db.flush()
    db.refresh(case)
    return case


def list_open_director_cases(
    db: Session, *, project_id: UUID, limit: int = 100,
) -> list[DirectorDecisionCase]:
    if not 1 <= limit <= 500:
        raise DirectorDecisionCaseError("limit must be between 1 and 500")
    return list(db.scalars(select(DirectorDecisionCase).where(
        DirectorDecisionCase.project_id == project_id,
        DirectorDecisionCase.status == "open",
    ).order_by(DirectorDecisionCase.created_at, DirectorDecisionCase.id).limit(limit)).all())

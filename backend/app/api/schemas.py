from __future__ import annotations
from datetime import datetime
from typing import Literal
from uuid import UUID
from pydantic import BaseModel, ConfigDict, Field, model_validator
from backend.app.models import MemberRole


class PrincipalRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    principal_kind: str
    display_name: str


class MembershipRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    principal_id: UUID
    role: MemberRole
    is_active: bool
    created_at: datetime


class MemberUpsert(BaseModel):
    role: MemberRole


class MemberList(BaseModel):
    items: list[MembershipRead]


DirectorCaseStatus = Literal["open", "approved", "rejected", "deferred", "closed"]
DirectorCaseDecision = Literal["approved", "rejected", "deferred", "closed"]


class DirectorDecisionSummary(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    project_id: UUID
    recommendation_code: str
    severity: str
    approval_required: str
    status: DirectorCaseStatus
    evidence_count: int
    created_at: datetime
    decided_at: datetime | None


class DirectorDecisionDetail(DirectorDecisionSummary):
    case_key: str
    source_brief_sha256: str
    source_state_digest: str
    evidence_refs: list[str]
    proposal_snapshot: dict
    decision: DirectorCaseDecision | None
    decided_by: UUID | None
    decision_note: str | None
    authorized_action_snapshot: dict | None = None

    @classmethod
    def from_case(cls, case):
        data = {
            "id": case.id,
            "project_id": case.project_id,
            "recommendation_code": case.recommendation_code,
            "severity": case.severity,
            "approval_required": case.approval_required,
            "status": case.status,
            "evidence_count": len(case.evidence_refs or []),
            "created_at": case.created_at,
            "decided_at": case.decided_at,
            "case_key": case.case_key,
            "source_brief_sha256": case.source_brief_sha256,
            "source_state_digest": case.source_state_digest,
            "evidence_refs": case.evidence_refs or [],
            "proposal_snapshot": case.proposal_snapshot or {},
            "decision": case.decision,
            "decided_by": case.decided_by,
            "decision_note": case.decision_note,
            "authorized_action_snapshot": case.authorized_action_snapshot,
        }
        return cls.model_validate(data)


class DirectorDecisionInbox(BaseModel):
    items: list[DirectorDecisionSummary]
    total: int
    limit: int
    offset: int


class AuthorizedActionSpec(BaseModel):
    model_config = ConfigDict(extra="forbid")
    action_type: Literal["create_task", "request_rework"]
    payload: dict


class DirectorDecisionSubmit(BaseModel):
    decision: DirectorCaseDecision
    note: str | None = Field(default=None, max_length=4000)
    authorized_action: AuthorizedActionSpec | None = None

    @model_validator(mode="after")
    def action_only_with_approval(self):
        if self.authorized_action is not None and self.decision != "approved":
            raise ValueError("authorized_action can only accompany an approved decision")
        return self


class ActionExecutionSubmit(BaseModel):
    idempotency_key: str = Field(min_length=8, max_length=160, pattern=r"^[A-Za-z0-9][A-Za-z0-9._:-]*$")


class ActionExecutionRead(BaseModel):
    id: UUID
    decision_case_id: UUID
    action_type: str
    action_sha256: str
    status: str
    result_snapshot: dict
    created_at: datetime


class DirectorActivityEvent(BaseModel):
    id: str
    kind: Literal["agent_run", "task", "audit", "action_execution"]
    title: str
    status: str
    occurred_at: datetime
    reference_id: UUID | None = None


class DirectorActivityTimeline(BaseModel):
    items: list[DirectorActivityEvent]
    limit: int

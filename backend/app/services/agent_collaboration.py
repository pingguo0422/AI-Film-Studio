"""Persistent, idempotent Agent-to-Agent handoff messages."""
from __future__ import annotations
from uuid import UUID
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session
from backend.app.models import Agent, AgentMessage, Task


class AgentMessageConflict(ValueError):
    pass


def send_agent_message(db: Session, *, project_id: UUID, from_agent_id: UUID,
                       to_agent_id: UUID | None, message_type: str, payload: dict,
                       idempotency_key: str, task_id: UUID | None = None,
                       correlation_id: UUID | None = None) -> tuple[AgentMessage, bool]:
    if not isinstance(message_type, str) or not message_type.strip() or len(message_type) > 48:
        raise ValueError("message_type must contain 1..48 characters")
    if not isinstance(idempotency_key, str) or not idempotency_key.strip() or len(idempotency_key) > 160:
        raise ValueError("idempotency_key must contain 1..160 characters")
    if not isinstance(payload, dict):
        raise ValueError("payload must be an object")
    sender = db.get(Agent, from_agent_id)
    recipient = db.get(Agent, to_agent_id) if to_agent_id else None
    if sender is None or sender.lifecycle_state != "active":
        raise ValueError("sender Agent is missing or inactive")
    if to_agent_id and (recipient is None or recipient.lifecycle_state != "active"):
        raise ValueError("recipient Agent is missing or inactive")
    if task_id is not None:
        task = db.scalar(select(Task).where(Task.id == task_id, Task.project_id == project_id))
        if task is None:
            raise ValueError("task does not belong to project")
    existing = db.scalar(select(AgentMessage).where(
        AgentMessage.project_id == project_id,
        AgentMessage.idempotency_key == idempotency_key,
    ))
    if existing:
        expected = (existing.from_agent_id, existing.to_agent_id, existing.task_id,
                    existing.message_type, existing.payload, existing.correlation_id)
        actual = (from_agent_id, to_agent_id, task_id, message_type, payload, correlation_id)
        if expected != actual:
            raise AgentMessageConflict("idempotency key was reused with a different message")
        return existing, False
    row = AgentMessage(project_id=project_id, task_id=task_id, from_agent_id=from_agent_id,
                       to_agent_id=to_agent_id, message_type=message_type,
                       correlation_id=correlation_id, payload=payload, idempotency_key=idempotency_key)
    try:
        with db.begin_nested():
            db.add(row)
            db.flush()
        return row, True
    except IntegrityError:
        existing = db.scalar(select(AgentMessage).where(
            AgentMessage.project_id == project_id,
            AgentMessage.idempotency_key == idempotency_key,
        ))
        if existing is None:
            raise
        expected = (existing.from_agent_id, existing.to_agent_id, existing.task_id,
                    existing.message_type, existing.payload, existing.correlation_id)
        actual = (from_agent_id, to_agent_id, task_id, message_type, payload, correlation_id)
        if expected != actual:
            raise AgentMessageConflict("idempotency key was reused with a different message")
        return existing, False

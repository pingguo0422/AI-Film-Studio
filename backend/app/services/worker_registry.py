"""Durable worker process registry with process-generation fencing."""
from __future__ import annotations
from datetime import datetime, timedelta, timezone
from uuid import uuid4
from sqlalchemy import select
from sqlalchemy.orm import Session
from backend.app.models import WorkerInstance


class WorkerOwnershipLost(LookupError):
    """This process generation no longer owns the registered worker identity."""
    pass


def register_worker(db: Session, *, worker_id: str, capabilities: list[str], process_id: int | None = None,
                    host_name: str | None = None, metadata_snapshot: dict | None = None,
                    now: datetime | None = None) -> WorkerInstance:
    """Register a process generation. Re-registration fences every prior generation."""
    if not worker_id or len(worker_id) > 128:
        raise ValueError("worker_id must be 1-128 characters")
    if not isinstance(capabilities, list) or any(not isinstance(x, str) or not x for x in capabilities):
        raise ValueError("capabilities must be a list of non-empty strings")
    if metadata_snapshot is not None and not isinstance(metadata_snapshot, dict):
        raise ValueError("metadata_snapshot must be an object")
    now = now or datetime.now(timezone.utc)
    row = db.scalar(select(WorkerInstance).where(WorkerInstance.worker_id == worker_id).with_for_update())
    token = str(uuid4())
    if row is None:
        row = WorkerInstance(worker_id=worker_id, instance_token=token, process_id=process_id, host_name=host_name,
            status="online", capabilities=capabilities, metadata_snapshot=metadata_snapshot or {},
            started_at=now, last_heartbeat_at=now)
        db.add(row)
    else:
        row.instance_token = token
        row.process_id = process_id
        row.host_name = host_name
        row.status = "online"
        row.capabilities = capabilities
        row.metadata_snapshot = metadata_snapshot or {}
        row.started_at = now
        row.last_heartbeat_at = now
        row.stopped_at = None
    db.flush()
    return row


def _owned_worker(db: Session, *, worker_id: str, instance_token: str) -> WorkerInstance:
    if not instance_token:
        raise ValueError("instance_token is required")
    row = db.scalar(select(WorkerInstance).where(WorkerInstance.worker_id == worker_id).with_for_update())
    if row is None or row.instance_token != instance_token or row.status not in {"online", "stopping"}:
        raise WorkerOwnershipLost("worker process no longer owns the active registry generation")
    return row


def heartbeat_worker(db: Session, *, worker_id: str, instance_token: str, now: datetime | None = None) -> WorkerInstance:
    now = now or datetime.now(timezone.utc)
    row = _owned_worker(db, worker_id=worker_id, instance_token=instance_token)
    row.last_heartbeat_at = now
    db.flush()
    return row


def stop_worker(db: Session, *, worker_id: str, instance_token: str, now: datetime | None = None) -> WorkerInstance:
    now = now or datetime.now(timezone.utc)
    row = _owned_worker(db, worker_id=worker_id, instance_token=instance_token)
    row.status = "offline"
    row.stopped_at = now
    row.last_heartbeat_at = now
    db.flush()
    return row


def mark_stale_workers(db: Session, *, stale_after_seconds: int = 90, now: datetime | None = None) -> int:
    if not isinstance(stale_after_seconds, int) or isinstance(stale_after_seconds, bool) or stale_after_seconds < 1:
        raise ValueError("stale_after_seconds must be a positive integer")
    now = now or datetime.now(timezone.utc)
    cutoff = now - timedelta(seconds=stale_after_seconds)
    rows = db.scalars(select(WorkerInstance).where(
        WorkerInstance.status.in_(["online", "stopping"]),
        WorkerInstance.last_heartbeat_at < cutoff,
    ).with_for_update(skip_locked=True)).all()
    for row in rows:
        row.status = "stale"
    db.flush()
    return len(rows)

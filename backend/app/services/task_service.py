"""Transactional task lifecycle, dependency DAG, leases and delivery deduplication."""
from __future__ import annotations
from datetime import datetime, timedelta, timezone
from uuid import UUID, uuid4
from sqlalchemy import and_, exists, or_, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, aliased
from backend.app.db.ids import uuid7
from backend.app.models import Task, TaskDependency, OutboxEvent, InboxEvent, TaskDeadLetter, AgentRun, SkillRun

TERMINAL = {"succeeded", "failed", "cancelled"}
ALLOWED = {
    "queued": {"running", "cancelled"},
    "retry_wait": {"running", "cancelled"},
    "running": {"succeeded", "retry_wait", "failed", "cancelled"},
    "succeeded": set(), "failed": set(), "cancelled": set(),
}

class TaskRuntimeError(Exception): pass
class TaskDependencyError(TaskRuntimeError): pass
class TaskNotFoundError(TaskRuntimeError): pass
class TaskDependencyCycleError(TaskDependencyError): pass
class InvalidTaskTransition(TaskRuntimeError): pass
class LeaseConflict(TaskRuntimeError): pass
class TaskCancelled(TaskRuntimeError): pass


def add_task_dependency(db: Session, *, project_id: UUID, task_id: UUID, depends_on_task_id: UUID) -> TaskDependency:
    if task_id == depends_on_task_id:
        raise TaskDependencyCycleError("a task cannot depend on itself")
    task_ids = set(db.scalars(select(Task.id).where(Task.project_id == project_id, Task.id.in_([task_id, depends_on_task_id]))).all())
    if task_ids != {task_id, depends_on_task_id}:
        raise TaskNotFoundError("both tasks must exist in the same project")
    adjacency: dict[UUID, list[UUID]] = {}
    for source, target in db.execute(select(TaskDependency.task_id, TaskDependency.depends_on_task_id).where(TaskDependency.project_id == project_id)).all():
        adjacency.setdefault(source, []).append(target)
    stack, visited = [depends_on_task_id], set()
    while stack:
        current = stack.pop()
        if current == task_id: raise TaskDependencyCycleError("dependency would create a cycle")
        if current not in visited:
            visited.add(current); stack.extend(adjacency.get(current, []))
    edge = TaskDependency(project_id=project_id, task_id=task_id, depends_on_task_id=depends_on_task_id)
    db.add(edge); db.flush(); return edge


def create_task(db: Session, *, project_id: UUID, task_type: str, title: str, input_snapshot: dict,
                priority: int = 50, max_attempts: int = 3, idempotency_key: str | None = None) -> Task:
    if not task_type or not title or not isinstance(input_snapshot, dict): raise ValueError("task_type, title and object input_snapshot are required")
    if not isinstance(max_attempts, int) or isinstance(max_attempts, bool) or max_attempts < 1 or max_attempts > 20:
        raise ValueError("max_attempts must be an integer from 1 to 20")
    if idempotency_key:
        existing = db.scalar(select(Task).where(Task.project_id == project_id, Task.idempotency_key == idempotency_key))
        if existing:
            if existing.task_type != task_type or existing.title != title or existing.input_snapshot != input_snapshot:
                raise TaskRuntimeError("idempotency key already used with different task input")
            return existing
    task = Task(project_id=project_id, task_type=task_type, title=title, input_snapshot=input_snapshot,
                priority=priority, max_attempts=max_attempts, idempotency_key=idempotency_key, status="queued")
    try:
        with db.begin_nested():
            db.add(task); db.flush()
    except IntegrityError:
        if idempotency_key:
            existing = db.scalar(select(Task).where(Task.project_id == project_id, Task.idempotency_key == idempotency_key))
            if existing and existing.task_type == task_type and existing.title == title and existing.input_snapshot == input_snapshot:
                return existing
        raise
    enqueue_outbox(db, aggregate_type="task", aggregate_id=task.id, event_type="task.created",
                   idempotency_key=f"task-created:{task.id}", payload={"project_id": str(project_id), "task_id": str(task.id)})
    return task


def enqueue_outbox(db: Session, *, aggregate_type: str, aggregate_id: UUID, event_type: str,
                   idempotency_key: str, payload: dict) -> OutboxEvent:
    if not idempotency_key or len(idempotency_key) > 160: raise ValueError("invalid outbox idempotency key")
    existing = db.scalar(select(OutboxEvent).where(OutboxEvent.idempotency_key == idempotency_key))
    if existing:
        if existing.event_type != event_type or existing.payload != payload or existing.aggregate_id != aggregate_id:
            raise TaskRuntimeError("outbox idempotency key conflicts with existing event")
        return existing
    event = OutboxEvent(aggregate_type=aggregate_type, aggregate_id=aggregate_id, event_type=event_type,
                        idempotency_key=idempotency_key, payload=payload)
    try:
        with db.begin_nested(): db.add(event); db.flush()
        return event
    except IntegrityError:
        existing = db.scalar(select(OutboxEvent).where(OutboxEvent.idempotency_key == idempotency_key))
        if existing and existing.event_type == event_type and existing.payload == payload and existing.aggregate_id == aggregate_id:
            return existing
        raise


def receive_inbox(db: Session, *, consumer_key: str, idempotency_key: str, event_type: str, payload: dict) -> tuple[InboxEvent, bool]:
    existing = db.scalar(select(InboxEvent).where(InboxEvent.consumer_key == consumer_key, InboxEvent.idempotency_key == idempotency_key))
    if existing:
        if existing.event_type != event_type or existing.payload != payload:
            raise TaskRuntimeError("inbox idempotency key conflicts with existing event")
        return existing, False
    row = InboxEvent(consumer_key=consumer_key, idempotency_key=idempotency_key, event_type=event_type, payload=payload)
    try:
        with db.begin_nested(): db.add(row); db.flush()
        return row, True
    except IntegrityError:
        existing = db.scalar(select(InboxEvent).where(InboxEvent.consumer_key == consumer_key, InboxEvent.idempotency_key == idempotency_key))
        if existing and existing.event_type == event_type and existing.payload == payload: return existing, False
        raise


def claim_next_task(db: Session, *, worker_id: str, lease_seconds: int = 120, now: datetime | None = None,
                    task_id: UUID | None = None, project_id: UUID | None = None, task_type: str | None = None) -> tuple[Task, str] | None:
    if not worker_id or len(worker_id) > 128: raise ValueError("worker_id must be 1-128 characters")
    if not isinstance(lease_seconds, int) or isinstance(lease_seconds, bool) or not 1 <= lease_seconds <= 3600:
        raise ValueError("lease_seconds must be 1-3600")
    now = now or datetime.now(timezone.utc)
    prerequisite = aliased(Task)
    blocked = exists(select(TaskDependency.id).join(prerequisite, prerequisite.id == TaskDependency.depends_on_task_id)
                     .where(TaskDependency.project_id == Task.project_id, TaskDependency.task_id == Task.id,
                            prerequisite.project_id == Task.project_id, prerequisite.status != "succeeded"))
    conditions = [Task.status.in_(["queued", "retry_wait"]),
        or_(Task.retry_after.is_(None), Task.retry_after <= now),
        ~blocked,
    ]
    if task_id is not None: conditions.append(Task.id == task_id)
    if project_id is not None: conditions.append(Task.project_id == project_id)
    if task_type is not None: conditions.append(Task.task_type == task_type)
    candidates = db.scalars(select(Task).where(*conditions).order_by(Task.priority.asc(), Task.created_at.asc()).with_for_update(skip_locked=True).limit(1)).all()
    for task in candidates:
        token = str(uuid4())
        result = db.execute(update(Task).where(Task.id == task.id, Task.status == task.status).values(
            status="running", lease_owner=worker_id, lease_token=token,
            lease_expires_at=now + timedelta(seconds=lease_seconds), attempt_count=Task.attempt_count + 1,
            started_at=now, updated_at=now,
        ))
        if result.rowcount == 1:
            db.flush(); db.refresh(task); return task, token
    return None


def _leased_task(db: Session, task_id: UUID, lease_token: str, now: datetime, *, allow_cancel_requested: bool = False) -> Task:
    task = db.scalar(select(Task).where(Task.id == task_id).with_for_update())
    if task is None: raise TaskNotFoundError("task not found")
    expires = task.lease_expires_at
    if expires is not None and expires.tzinfo is None:
        expires = expires.replace(tzinfo=timezone.utc)
    if task.status != "running" or task.lease_token != lease_token or expires is None or expires <= now:
        raise LeaseConflict("task lease is missing, expired, or owned by another worker")
    if task.cancel_requested and not allow_cancel_requested: raise TaskCancelled("task cancellation has been requested")
    return task


def heartbeat_task(db: Session, *, task_id: UUID, lease_token: str, lease_seconds: int = 120, now: datetime | None = None, allow_cancel_requested: bool = False) -> Task:
    if not isinstance(lease_seconds, int) or isinstance(lease_seconds, bool) or not 1 <= lease_seconds <= 3600:
        raise ValueError("lease_seconds must be 1-3600")
    now = now or datetime.now(timezone.utc); task = _leased_task(db, task_id, lease_token, now, allow_cancel_requested=allow_cancel_requested)
    task.lease_expires_at = now + timedelta(seconds=lease_seconds); db.flush(); return task


def complete_task(db: Session, *, task_id: UUID, lease_token: str, output_snapshot: dict, now: datetime | None = None) -> Task:
    now = now or datetime.now(timezone.utc); task = _leased_task(db, task_id, lease_token, now)
    if not isinstance(output_snapshot, dict): raise ValueError("output_snapshot must be an object")
    task.status = "succeeded"; task.finished_at = now; task.output_snapshot = output_snapshot
    task.lease_owner = task.lease_token = None; task.lease_expires_at = None; task.retry_after = None
    enqueue_outbox(db, aggregate_type="task", aggregate_id=task.id, event_type="task.succeeded",
                   idempotency_key=f"task-succeeded:{task.id}", payload={"task_id": str(task.id)})
    db.flush(); return task


def _record_task_dead_letter(db: Session, task: Task) -> None:
    existing = db.scalar(select(TaskDeadLetter).where(TaskDeadLetter.task_id == task.id))
    if existing is None:
        db.add(TaskDeadLetter(project_id=task.project_id, task_id=task.id, task_type=task.task_type,
            attempt_count=task.attempt_count, input_snapshot=dict(task.input_snapshot),
            error_detail=dict(task.error_detail or {"code": "TASK_FAILED"})))


def fail_task(db: Session, *, task_id: UUID, lease_token: str, error_detail: dict, retry_delay_seconds: int = 0,
              retryable: bool = True, now: datetime | None = None) -> Task:
    now = now or datetime.now(timezone.utc); task = _leased_task(db, task_id, lease_token, now)
    task.error_detail = error_detail; task.lease_owner = task.lease_token = None; task.lease_expires_at = None
    if retryable and task.attempt_count < task.max_attempts:
        task.status = "retry_wait"; task.retry_after = now + timedelta(seconds=max(0, retry_delay_seconds)); task.finished_at = None
    else:
        task.status = "failed"; task.finished_at = now
        _record_task_dead_letter(db, task)
    db.flush(); return task


def cancel_task(db: Session, *, task_id: UUID, now: datetime | None = None) -> Task:
    now = now or datetime.now(timezone.utc); task = db.scalar(select(Task).where(Task.id == task_id).with_for_update())
    if task is None: raise TaskNotFoundError("task not found")
    if task.status in TERMINAL: return task
    if task.status == "running": task.cancel_requested = True
    else:
        task.status = "cancelled"; task.finished_at = now
    db.flush(); return task



def transition_task(db: Session, *, task_id: UUID, target_status: str, now: datetime | None = None) -> Task:
    """Apply a non-worker state transition; running/succeeded require their dedicated lease APIs."""
    now = now or datetime.now(timezone.utc)
    task = db.scalar(select(Task).where(Task.id == task_id).with_for_update())
    if task is None: raise TaskNotFoundError("task not found")
    if target_status not in ALLOWED.get(task.status, set()):
        raise InvalidTaskTransition(f"transition {task.status!r} -> {target_status!r} is not allowed")
    if target_status == "running":
        raise InvalidTaskTransition("running can only be entered by claim_next_task")
    if target_status == "succeeded":
        raise InvalidTaskTransition("succeeded can only be entered by complete_task")
    if target_status == "cancelled" and task.status == "running":
        task.cancel_requested = True
        db.flush(); return task
    task.status = target_status
    if target_status in TERMINAL: task.finished_at = now
    db.flush(); return task


def acknowledge_task_cancel(db: Session, *, task_id: UUID, lease_token: str, now: datetime | None = None) -> Task:
    """Worker acknowledges a cooperative cancellation while holding the active lease."""
    now = now or datetime.now(timezone.utc)
    task = db.scalar(select(Task).where(Task.id == task_id).with_for_update())
    if task is None: raise TaskNotFoundError("task not found")
    expires = task.lease_expires_at
    if expires is not None and expires.tzinfo is None: expires = expires.replace(tzinfo=timezone.utc)
    if task.status != "running" or task.lease_token != lease_token or expires is None or expires <= now:
        raise LeaseConflict("task lease is missing, expired, or owned by another worker")
    if not task.cancel_requested: raise InvalidTaskTransition("task cancellation was not requested")
    task.status = "cancelled"; task.finished_at = now
    task.lease_owner = task.lease_token = None; task.lease_expires_at = None
    db.flush(); return task

def _interrupt_open_task_runs(db: Session, *, task: Task, now: datetime, terminal_status: str) -> int:
    """Close run records left open by a process that disappeared before finalizing.

    Run history is append-only across attempts: the abandoned attempt is marked
    interrupted/cancelled, and a retry creates new AgentRun/SkillRun rows.
    """
    runs = db.scalars(select(AgentRun).where(
        AgentRun.task_id == task.id, AgentRun.status.in_(["queued", "running"])
    ).with_for_update()).all()
    changed = 0
    for agent_run in runs:
        child_runs = db.scalars(select(SkillRun).where(
            SkillRun.agent_run_id == agent_run.id,
            SkillRun.status.in_(["queued", "running"]),
        ).with_for_update()).all()
        for skill_run in child_runs:
            skill_run.status = terminal_status
            skill_run.output_snapshot = {
                "code": "WORKER_LEASE_EXPIRED",
                "message": "worker disappeared before the skill run was finalized",
                "task_attempt": task.attempt_count,
                "recovered_at": now.isoformat(),
            }
            skill_run.finished_at = now
            changed += 1
        agent_run.status = terminal_status
        agent_run.error_detail = {
            "code": "WORKER_LEASE_EXPIRED",
            "message": "worker disappeared before the agent run was finalized",
            "task_attempt": task.attempt_count,
            "recovered_at": now.isoformat(),
        }
        agent_run.finished_at = now
        changed += 1
    return changed


def reap_expired_leases(db: Session, *, now: datetime | None = None) -> int:
    """Recover expired task leases and close their unfinished run lineage atomically."""
    now = now or datetime.now(timezone.utc)
    expired = db.scalars(select(Task).where(Task.status == "running", Task.lease_expires_at <= now).with_for_update(skip_locked=True)).all()
    count = 0
    for task in expired:
        task.lease_owner = task.lease_token = None; task.lease_expires_at = None
        task.error_detail = {"code": "LEASE_EXPIRED", "message": "worker lease expired"}
        terminal_status = "cancelled" if task.cancel_requested else "interrupted"
        _interrupt_open_task_runs(db, task=task, now=now, terminal_status=terminal_status)
        if task.cancel_requested: task.status = "cancelled"; task.finished_at = now
        elif task.attempt_count < task.max_attempts: task.status = "retry_wait"; task.retry_after = now
        else:
            task.status = "failed"; task.finished_at = now
            _record_task_dead_letter(db, task)
        count += 1
    db.flush(); return count

"""Database-backed, provider-neutral AFS worker loop.

Workers are stateless processes: task state and leases live in the AFS database.
PostgreSQL SKIP LOCKED claim semantics permit multiple worker processes without a
central in-memory queue. Executors are explicitly registered by task type.
"""
from __future__ import annotations

import logging
import os
import socket
import threading
from dataclasses import dataclass
from typing import Callable
from uuid import UUID, uuid4

from sqlalchemy.orm import Session, sessionmaker

from backend.app.services.orchestrator import execute_one_skill_task
from backend.app.services.task_service import heartbeat_task
from backend.app.services.worker_registry import (
    register_worker, heartbeat_worker, stop_worker, WorkerOwnershipLost,
)

logger = logging.getLogger(__name__)
SkillExecutor = Callable[[dict], dict]


@dataclass(frozen=True)
class SkillRegistration:
    task_type: str
    agent_id: UUID
    agent_version_id: UUID
    skill_version_id: UUID
    executor: SkillExecutor


class WorkerConfigurationError(ValueError):
    pass


class WorkerFencedError(WorkerOwnershipLost):
    """Raised when this process generation has been replaced by another process."""
    pass


class Worker:
    """Poll and execute registered task types using database leases."""

    def __init__(self, *, session_factory: sessionmaker[Session], worker_id: str,
                 registrations: list[SkillRegistration], lease_seconds: int = 120,
                 heartbeat_interval_seconds: float | None = None):
        if not worker_id or len(worker_id) > 128:
            raise WorkerConfigurationError("worker_id must be 1-128 characters")
        if not registrations:
            raise WorkerConfigurationError("at least one SkillRegistration is required")
        task_types = [r.task_type for r in registrations]
        if any(not t or len(t) > 64 for t in task_types) or len(set(task_types)) != len(task_types):
            raise WorkerConfigurationError("task types must be unique non-empty values up to 64 chars")
        if not isinstance(lease_seconds, int) or isinstance(lease_seconds, bool) or not 1 <= lease_seconds <= 3600:
            raise WorkerConfigurationError("lease_seconds must be 1-3600")
        interval = heartbeat_interval_seconds if heartbeat_interval_seconds is not None else lease_seconds / 3
        if not isinstance(interval, (int, float)) or isinstance(interval, bool) or interval <= 0 or interval >= lease_seconds:
            raise WorkerConfigurationError("heartbeat interval must be positive and shorter than lease")
        self.session_factory = session_factory
        self.worker_id = worker_id
        self.registrations = tuple(registrations)
        self.lease_seconds = lease_seconds
        self.heartbeat_interval_seconds = interval
        self._next_registration_index = 0
        self.instance_token = str(uuid4())
        self._registry_active = False

    def run_once(self) -> dict | None:
        """Execute at most one matching task; return None when this worker has no work."""
        if self._registry_active:
            with self.session_factory() as ownership_db:
                try:
                    heartbeat_worker(ownership_db, worker_id=self.worker_id, instance_token=self.instance_token)
                    ownership_db.commit()
                except WorkerOwnershipLost as exc:
                    ownership_db.rollback()
                    raise WorkerFencedError(str(exc)) from exc
        count = len(self.registrations)
        ordered = [self.registrations[(self._next_registration_index + offset) % count] for offset in range(count)]
        for offset, registration in enumerate(ordered):
            def heartbeat(task_id: UUID, lease_token: str) -> None:
                with self.session_factory() as heartbeat_db:
                    heartbeat_task(heartbeat_db, task_id=task_id, lease_token=lease_token,
                                   lease_seconds=self.lease_seconds, allow_cancel_requested=True)
                    if self._registry_active:
                        try:
                            heartbeat_worker(heartbeat_db, worker_id=self.worker_id, instance_token=self.instance_token)
                        except WorkerOwnershipLost as exc:
                            raise WorkerFencedError(str(exc)) from exc
                    heartbeat_db.commit()

            try:
                with self.session_factory() as db:
                    result = execute_one_skill_task(
                        db, worker_id=self.worker_id,
                        agent_id=registration.agent_id,
                        agent_version_id=registration.agent_version_id,
                        skill_version_id=registration.skill_version_id,
                        executor=registration.executor,
                        lease_seconds=self.lease_seconds,
                        task_type=registration.task_type,
                        heartbeat_callback=heartbeat,
                        heartbeat_interval_seconds=self.heartbeat_interval_seconds,
                    )
                    db.commit()
            except Exception:
                self._next_registration_index = (self._next_registration_index + offset + 1) % count
                raise
            if result is not None:
                logger.info("worker task completed", extra={"worker_id": self.worker_id,
                            "task_id": result.get("task_id"), "status": result.get("status")})
                self._next_registration_index = (self._next_registration_index + offset + 1) % count
                return result
        return None

    def run_forever(self, *, stop_event: threading.Event | None = None,
                    idle_sleep_seconds: float = 1.0, max_tasks: int | None = None) -> int:
        if idle_sleep_seconds <= 0:
            raise ValueError("idle_sleep_seconds must be positive")
        if max_tasks is not None and (not isinstance(max_tasks, int) or isinstance(max_tasks, bool) or max_tasks < 1):
            raise ValueError("max_tasks must be positive when provided")
        stop = stop_event or threading.Event()
        processed = 0
        heartbeat_stop = threading.Event()
        heartbeat_interval = max(1.0, min(15.0, self.lease_seconds / 3))
        with self.session_factory() as db:
            registry_row = register_worker(db, worker_id=self.worker_id,
                capabilities=sorted({r.task_type for r in self.registrations}),
                process_id=os.getpid(), host_name=socket.gethostname())
            self.instance_token = registry_row.instance_token
            db.commit()
        self._registry_active = True

        def maintain_registry_heartbeat():
            while not heartbeat_stop.wait(heartbeat_interval):
                try:
                    with self.session_factory() as heartbeat_db:
                        heartbeat_worker(heartbeat_db, worker_id=self.worker_id, instance_token=self.instance_token)
                        heartbeat_db.commit()
                except Exception:
                    logger.exception("worker registry heartbeat failed", extra={"worker_id": self.worker_id})

        registry_thread = threading.Thread(target=maintain_registry_heartbeat,
            name=f"afs-registry-{self.worker_id}", daemon=True)
        registry_thread.start()
        try:
            while not stop.is_set() and (max_tasks is None or processed < max_tasks):
                try:
                    result = self.run_once()
                except WorkerFencedError:
                    logger.warning("worker process generation fenced; stopping", extra={"worker_id": self.worker_id})
                    break
                except Exception:
                    logger.exception("worker iteration failed", extra={"worker_id": self.worker_id})
                    if stop.wait(idle_sleep_seconds or 0.1):
                        break
                    continue
                if result is None:
                    if stop.wait(idle_sleep_seconds):
                        break
                else:
                    processed += 1
            return processed
        finally:
            heartbeat_stop.set()
            registry_thread.join(timeout=heartbeat_interval + 1)
            with self.session_factory() as db:
                try:
                    stop_worker(db, worker_id=self.worker_id, instance_token=self.instance_token)
                    db.commit()
                except WorkerOwnershipLost:
                    db.rollback()  # A replacement process already fenced this generation.
                finally:
                    self._registry_active = False

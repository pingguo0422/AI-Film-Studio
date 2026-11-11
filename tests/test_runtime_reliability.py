from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import create_engine, select, event
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from backend.app.db.base import Base
from backend.app.db.ids import uuid7
from backend.app.models import (
    Project, OutboxEvent, InboxEvent, WorkerInstance, TaskDeadLetter, Task,
)
from backend.app.services.task_service import create_task, claim_next_task, fail_task
from backend.app.services.worker_registry import (
    register_worker, heartbeat_worker, stop_worker, mark_stale_workers,
)
from backend.app.services.event_delivery import (
    OutboxPublisher, InboxConsumer, claim_outbox_event, fail_outbox_event,
    reap_expired_outbox_claims,
)


def make_factory():
    engine = create_engine("sqlite+pysqlite:///:memory:", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    @event.listens_for(engine, "connect")
    def fk(conn, _):
        conn.execute("PRAGMA foreign_keys=ON")
    Base.metadata.create_all(engine)
    return sessionmaker(engine, expire_on_commit=False, class_=Session)


def seed_project(factory):
    with factory() as db:
        project = Project(id=uuid7(), code="PRJ_RELIABILITY", name="Reliability")
        db.add(project)
        db.commit()
        return project.id


def test_worker_registry_register_heartbeat_stale_and_stop():
    factory = make_factory()
    now = datetime(2026, 1, 1, tzinfo=timezone.utc)
    with factory() as db:
        row = register_worker(db, worker_id="worker-a", capabilities=["SHOT_PLAN"],
                              process_id=123, host_name="node-a", now=now)
        assert row.status == "online"
        token = row.instance_token
        heartbeat_worker(db, worker_id="worker-a", instance_token=token, now=now + timedelta(seconds=10))
        db.commit()
    with factory() as db:
        assert mark_stale_workers(db, stale_after_seconds=30, now=now + timedelta(seconds=50)) == 1
        db.commit()
    with factory() as db:
        row = db.scalar(select(WorkerInstance).where(WorkerInstance.worker_id == "worker-a"))
        assert row.status == "stale"
        row.status = "online"
        db.commit()
    with factory() as db:
        stop_worker(db, worker_id="worker-a", instance_token=token, now=now + timedelta(seconds=60))
        db.commit()
    with factory() as db:
        assert db.scalar(select(WorkerInstance)).status == "offline"



def test_worker_generation_fences_previous_process_heartbeat_and_shutdown():
    factory = make_factory()
    with factory() as db:
        first = register_worker(db, worker_id="worker-reused", capabilities=["A"], process_id=10)
        first_token = first.instance_token
        db.commit()
    with factory() as db:
        second = register_worker(db, worker_id="worker-reused", capabilities=["B"], process_id=11)
        second_token = second.instance_token
        assert second_token != first_token
        db.commit()
    with factory() as db:
        with pytest.raises(LookupError, match="no longer owns"):
            heartbeat_worker(db, worker_id="worker-reused", instance_token=first_token)
        with pytest.raises(LookupError, match="no longer owns"):
            stop_worker(db, worker_id="worker-reused", instance_token=first_token)
        current = heartbeat_worker(db, worker_id="worker-reused", instance_token=second_token)
        assert current.process_id == 11
        db.commit()


def test_outbox_publisher_delivers_and_acknowledges():
    factory = make_factory()
    project_id = seed_project(factory)
    with factory() as db:
        task = create_task(db, project_id=project_id, task_type="TEST_EVENT", title="Create event", input_snapshot={"x": 1})
        db.commit()
        task_id = task.id
    delivered = []
    publisher = OutboxPublisher(session_factory=factory, publisher_id="publisher-1", publish=delivered.append)
    result = publisher.publish_once()
    assert result["status"] == "published"
    assert len(delivered) == 1
    assert delivered[0]["idempotency_key"] == f"task-created:{task_id}"
    with factory() as db:
        event_row = db.scalar(select(OutboxEvent).where(OutboxEvent.idempotency_key == delivered[0]["idempotency_key"]))
        assert event_row.status == "published"
        assert event_row.published_at is not None


def test_outbox_exhaustion_moves_event_to_dead_letter_state():
    factory = make_factory()
    project_id = seed_project(factory)
    with factory() as db:
        task = create_task(db, project_id=project_id, task_type="TEST_EVENT", title="Create event", input_snapshot={})
        db.flush()
        row = db.scalar(select(OutboxEvent).where(OutboxEvent.aggregate_id == task.id))
        row.max_attempts = 1
        claimed, token = claim_outbox_event(db, publisher_id="publisher-fail", now=datetime.now(timezone.utc))
        assert claimed.id == row.id
        fail_outbox_event(db, event_id=row.id, claim_token=token, error=RuntimeError("broker down"))
        db.commit()
    with factory() as db:
        row = db.scalar(select(OutboxEvent).where(OutboxEvent.aggregate_id == task.id))
        assert row.status == "dead"
        assert row.last_error["message"] == "broker down"



def test_outbox_publish_failure_schedules_retry_with_backoff():
    factory = make_factory()
    project_id = seed_project(factory)
    with factory() as db:
        task = create_task(db, project_id=project_id, task_type="TEST_EVENT", title="Retry event", input_snapshot={})
        db.commit()
        task_id = task.id
    publisher = OutboxPublisher(session_factory=factory, publisher_id="publisher-retry",
        publish=lambda _event: (_ for _ in ()).throw(ConnectionError("temporary broker outage")))
    result = publisher.publish_once()
    assert result["status"] == "retry_or_dead"
    with factory() as db:
        row = db.scalar(select(OutboxEvent).where(OutboxEvent.aggregate_id == task_id))
        assert row.status == "pending"
        assert row.attempt_count == 1
        assert row.next_attempt_at is not None
        assert row.last_error["type"] == "ConnectionError"



def test_expired_outbox_claim_at_attempt_limit_becomes_dead_without_redelivery():
    factory = make_factory()
    project_id = seed_project(factory)
    now = datetime(2026, 1, 1, tzinfo=timezone.utc)
    with factory() as db:
        task = create_task(db, project_id=project_id, task_type="TEST_EVENT", title="Crash loop", input_snapshot={})
        db.flush()
        row = db.scalar(select(OutboxEvent).where(OutboxEvent.aggregate_id == task.id))
        row.status = "publishing"
        row.attempt_count = row.max_attempts
        row.claimed_by = "publisher-crashed"
        row.claim_token = "expired-token"
        row.claim_expires_at = now - timedelta(seconds=1)
        assert reap_expired_outbox_claims(db, now=now) == 1
        db.commit()
    with factory() as db:
        row = db.scalar(select(OutboxEvent).where(OutboxEvent.aggregate_id == task.id))
        assert row.status == "dead"
        assert row.claim_token is None
        assert row.last_error["code"] == "PUBLISHER_LEASE_EXHAUSTED"


def test_inbox_consumer_is_idempotent_and_handler_runs_once():
    factory = make_factory()
    handled = []
    consumer = InboxConsumer(session_factory=factory, consumer_key="projection-v1",
        handlers={"task.succeeded": lambda db, payload: handled.append(payload["task_id"])})
    envelope = {"idempotency_key": "task:123:succeeded", "event_type": "task.succeeded", "payload": {"task_id": "123"}}
    assert consumer.consume(envelope)["status"] == "processed"
    assert consumer.consume(envelope)["status"] == "duplicate"
    assert handled == ["123"]
    with factory() as db:
        assert db.scalar(select(InboxEvent)).status == "processed"


def test_inbox_handler_failure_rolls_back_receipt_for_safe_retry():
    factory = make_factory()
    def broken(_db, _payload):
        raise RuntimeError("projection failed")
    consumer = InboxConsumer(session_factory=factory, consumer_key="projection-v1", handlers={"x": broken})
    with pytest.raises(RuntimeError):
        consumer.consume({"idempotency_key": "k1", "event_type": "x", "payload": {}})
    with factory() as db:
        assert db.scalar(select(InboxEvent)) is None


def test_final_task_failure_creates_dead_letter_record():
    factory = make_factory()
    project_id = seed_project(factory)
    with factory() as db:
        task = create_task(db, project_id=project_id, task_type="BROKEN_TASK", title="Will fail", input_snapshot={"raw": True}, max_attempts=1)
        db.flush()
        claimed, token = claim_next_task(db, worker_id="worker-fail")
        fail_task(db, task_id=claimed.id, lease_token=token,
                  error_detail={"code": "BROKEN", "message": "no executor"}, retryable=False)
        db.commit()
    with factory() as db:
        task = db.get(Task, task.id)
        dlq = db.scalar(select(TaskDeadLetter).where(TaskDeadLetter.task_id == task.id))
        assert task.status == "failed"
        assert dlq is not None
        assert dlq.error_detail["code"] == "BROKEN"
        assert dlq.input_snapshot == {"raw": True}


def test_worker_run_forever_registers_and_marks_offline_on_graceful_exit():
    from threading import Event
    from backend.app.runtime.worker import SkillRegistration, Worker
    factory = make_factory()
    stop = Event()
    stop.set()
    worker = Worker(session_factory=factory, worker_id="worker-graceful",
        registrations=[SkillRegistration("SAMPLE", uuid7(), uuid7(), uuid7(), lambda _payload: {})])
    assert worker.run_forever(stop_event=stop, max_tasks=1) == 0
    with factory() as db:
        row = db.scalar(select(WorkerInstance).where(WorkerInstance.worker_id == "worker-graceful"))
        assert row.status == "offline"
        assert row.stopped_at is not None


def test_expired_worker_lease_closes_open_agent_and_skill_runs_before_retry():
    from backend.app.models import Agent, AgentVersion, Skill, SkillVersion, AgentSkillBinding, AgentRun, SkillRun
    from backend.app.services.task_service import reap_expired_leases

    factory = make_factory()
    project_id = seed_project(factory)
    now = datetime(2026, 2, 1, tzinfo=timezone.utc)
    with factory() as db:
        agent = Agent(code="RECOVERY_AGENT", display_name="Recovery Agent")
        skill = Skill(code="RECOVERY_SKILL", display_name="Recovery Skill")
        db.add_all([agent, skill]); db.flush()
        av = AgentVersion(agent_id=agent.id, version_number=1, definition_snapshot={}, definition_sha256="1" * 64)
        sv = SkillVersion(skill_id=skill.id, version_number=1, definition_snapshot={}, definition_sha256="2" * 64)
        db.add_all([av, sv]); db.flush()
        db.add(AgentSkillBinding(agent_version_id=av.id, skill_version_id=sv.id)); db.flush()
        task = create_task(db, project_id=project_id, task_type="RECOVERY", title="Recover crashed worker",
                           input_snapshot={}, max_attempts=2)
        claimed, token = claim_next_task(db, worker_id="crashed-worker", lease_seconds=5, now=now)
        ar = AgentRun(project_id=project_id, task_id=task.id, agent_id=agent.id,
                      agent_version_id=av.id, status="running", input_snapshot={})
        db.add(ar); db.flush()
        sr = SkillRun(project_id=project_id, agent_run_id=ar.id, skill_id=skill.id,
                      skill_version_id=sv.id, status="running", input_snapshot={})
        db.add(sr); db.commit()
        task_id, agent_run_id, skill_run_id = task.id, ar.id, sr.id

    with factory() as db:
        assert reap_expired_leases(db, now=now + timedelta(seconds=6)) == 1
        db.commit()
    with factory() as db:
        recovered_task = db.get(Task, task_id)
        recovered_agent = db.get(AgentRun, agent_run_id)
        recovered_skill = db.get(SkillRun, skill_run_id)
        assert recovered_task.status == "retry_wait"
        assert recovered_agent.status == "interrupted"
        assert recovered_skill.status == "interrupted"
        assert recovered_agent.error_detail["code"] == "WORKER_LEASE_EXPIRED"
        assert recovered_skill.output_snapshot["code"] == "WORKER_LEASE_EXPIRED"
        assert recovered_agent.finished_at is not None and recovered_skill.finished_at is not None


def test_expired_worker_lease_at_attempt_limit_closes_runs_and_dead_letters_task():
    from backend.app.models import Agent, AgentVersion, Skill, SkillVersion, AgentSkillBinding, AgentRun, SkillRun
    from backend.app.services.task_service import reap_expired_leases

    factory = make_factory()
    project_id = seed_project(factory)
    now = datetime(2026, 2, 2, tzinfo=timezone.utc)
    with factory() as db:
        agent = Agent(code="DEAD_AGENT", display_name="Dead Agent")
        skill = Skill(code="DEAD_SKILL", display_name="Dead Skill")
        db.add_all([agent, skill]); db.flush()
        av = AgentVersion(agent_id=agent.id, version_number=1, definition_snapshot={}, definition_sha256="3" * 64)
        sv = SkillVersion(skill_id=skill.id, version_number=1, definition_snapshot={}, definition_sha256="4" * 64)
        db.add_all([av, sv]); db.flush()
        db.add(AgentSkillBinding(agent_version_id=av.id, skill_version_id=sv.id)); db.flush()
        task = create_task(db, project_id=project_id, task_type="FINAL_RECOVERY", title="Exhaust retries",
                           input_snapshot={}, max_attempts=1)
        claimed, token = claim_next_task(db, worker_id="dead-worker", lease_seconds=5, now=now)
        ar = AgentRun(project_id=project_id, task_id=task.id, agent_id=agent.id,
                      agent_version_id=av.id, status="running", input_snapshot={})
        db.add(ar); db.flush()
        sr = SkillRun(project_id=project_id, agent_run_id=ar.id, skill_id=skill.id,
                      skill_version_id=sv.id, status="running", input_snapshot={})
        db.add(sr); db.commit()
        task_id, agent_run_id, skill_run_id = task.id, ar.id, sr.id

    with factory() as db:
        assert reap_expired_leases(db, now=now + timedelta(seconds=6)) == 1
        db.commit()
    with factory() as db:
        assert db.get(Task, task_id).status == "failed"
        assert db.get(AgentRun, agent_run_id).status == "interrupted"
        assert db.get(SkillRun, skill_run_id).status == "interrupted"
        assert db.scalar(select(TaskDeadLetter).where(TaskDeadLetter.task_id == task_id)) is not None

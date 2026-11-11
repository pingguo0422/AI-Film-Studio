from __future__ import annotations

import time
from sqlalchemy import create_engine, event, select
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from backend.app.db.base import Base
from backend.app.db.ids import uuid7
from backend.app.models import (
    Project, Agent, AgentVersion, AgentSkillBinding, Skill, SkillVersion, Task,
)
from backend.app.services.task_service import create_task
from backend.app.runtime.worker import SkillRegistration, Worker


def make_factory():
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    @event.listens_for(engine, "connect")
    def fk(conn, _):
        conn.execute("PRAGMA foreign_keys=ON")
    Base.metadata.create_all(engine)
    return sessionmaker(engine, expire_on_commit=False, class_=Session)


def seed_runtime(factory):
    with factory() as db:
        project = Project(id=uuid7(), code="PRJ_WORKER_TEST", name="Worker Test")
        agent = Agent(code="AGENT_WORKER_TEST", display_name="Worker Test Agent")
        skill = Skill(code="SKILL_WORKER_TEST", display_name="Worker Test Skill")
        db.add_all([project, agent, skill]); db.flush()
        av = AgentVersion(agent_id=agent.id, version_number=1, definition_snapshot={"role": "test"}, definition_sha256="a" * 64)
        sv = SkillVersion(skill_id=skill.id, version_number=1, definition_snapshot={"skill": "test"}, definition_sha256="b" * 64)
        db.add_all([av, sv]); db.flush()
        db.add(AgentSkillBinding(agent_version_id=av.id, skill_version_id=sv.id, binding_config={"executor": "test"}))
        task = create_task(db, project_id=project.id, task_type="WORKER_TEST", title="Worker task", input_snapshot={"value": 7})
        db.commit()
        return project.id, agent.id, av.id, sv.id, task.id


def test_worker_dispatches_registered_task_and_persists_lineage():
    factory = make_factory()
    _, agent_id, av_id, sv_id, task_id = seed_runtime(factory)
    worker = Worker(
        session_factory=factory, worker_id="worker-test-01",
        registrations=[SkillRegistration("WORKER_TEST", agent_id, av_id, sv_id, lambda data: {"echo": data["value"]})],
    )
    result = worker.run_once()
    assert result and result["status"] == "succeeded"
    assert result["task_id"] == str(task_id)
    with factory() as db:
        task = db.get(Task, task_id)
        assert task.status == "succeeded"
        assert task.output_snapshot == {"echo": 7}


def test_worker_renews_lease_during_long_running_executor():
    factory = make_factory()
    _, agent_id, av_id, sv_id, task_id = seed_runtime(factory)
    def slow_executor(_data):
        time.sleep(1.25)  # deliberately longer than the initial one-second lease
        return {"finished": True}
    worker = Worker(
        session_factory=factory, worker_id="worker-heartbeat",
        registrations=[SkillRegistration("WORKER_TEST", agent_id, av_id, sv_id, slow_executor)],
        lease_seconds=1, heartbeat_interval_seconds=0.15,
    )
    result = worker.run_once()
    assert result and result["status"] == "succeeded"
    with factory() as db:
        assert db.get(Task, task_id).status == "succeeded"


def test_worker_does_not_claim_unregistered_task_types():
    factory = make_factory()
    _, agent_id, av_id, sv_id, task_id = seed_runtime(factory)
    worker = Worker(
        session_factory=factory, worker_id="worker-wrong-type",
        registrations=[SkillRegistration("OTHER_TYPE", agent_id, av_id, sv_id, lambda _: {})],
    )
    assert worker.run_once() is None
    with factory() as db:
        assert db.get(Task, task_id).status == "queued"


def test_worker_acknowledges_cancellation_requested_during_long_executor():
    from backend.app.services.task_service import cancel_task
    factory = make_factory()
    _, agent_id, av_id, sv_id, task_id = seed_runtime(factory)
    def cancellable_executor(_data):
        time.sleep(0.35)
        with factory() as cancel_db:
            cancel_task(cancel_db, task_id=task_id)
            cancel_db.commit()
        time.sleep(0.25)
        return {"finished": True}
    worker = Worker(
        session_factory=factory, worker_id="worker-cancel",
        registrations=[SkillRegistration("WORKER_TEST", agent_id, av_id, sv_id, cancellable_executor)],
        lease_seconds=1, heartbeat_interval_seconds=0.1,
    )
    result = worker.run_once()
    assert result and result["status"] == "cancelled"
    with factory() as db:
        assert db.get(Task, task_id).status == "cancelled"


def test_worker_rotates_task_type_registrations_fairly():
    factory = make_factory()
    project_id, agent_id, av_id, sv_id, first_id = seed_runtime(factory)
    with factory() as db:
        second = create_task(db, project_id=project_id, task_type="WORKER_TEST_B", title="Second type", input_snapshot={"value": 9})
        db.commit()
        second_id = second.id
    registrations = [
        SkillRegistration("WORKER_TEST", agent_id, av_id, sv_id, lambda data: {"type": "A"}),
        SkillRegistration("WORKER_TEST_B", agent_id, av_id, sv_id, lambda data: {"type": "B"}),
    ]
    worker = Worker(session_factory=factory, worker_id="worker-fair", registrations=registrations)
    assert worker.run_once()["task_id"] == str(first_id)
    assert worker.run_once()["task_id"] == str(second_id)


def test_worker_registry_heartbeat_runs_independently_during_long_executor():
    import threading
    factory = make_factory()
    _, agent_id, av_id, sv_id, task_id = seed_runtime(factory)
    executor_started = threading.Event()
    allow_finish = threading.Event()

    def blocked_executor(_payload):
        executor_started.set()
        assert allow_finish.wait(timeout=5)
        return {"finished": True}

    worker = Worker(
        session_factory=factory, worker_id="worker-registry-heartbeat",
        registrations=[SkillRegistration("WORKER_TEST", agent_id, av_id, sv_id, blocked_executor)],
        lease_seconds=3, heartbeat_interval_seconds=0.25,
    )
    result_holder = {}
    thread = threading.Thread(target=lambda: result_holder.setdefault(
        "processed", worker.run_forever(idle_sleep_seconds=0.05, max_tasks=1)))
    thread.start()
    assert executor_started.wait(timeout=3)
    with factory() as db:
        before = db.scalar(select(__import__("backend.app.models", fromlist=["WorkerInstance"]).WorkerInstance)
                           .where(__import__("backend.app.models", fromlist=["WorkerInstance"]).WorkerInstance.worker_id == "worker-registry-heartbeat"))
        first_heartbeat = before.last_heartbeat_at
    time.sleep(1.2)
    with factory() as db:
        from backend.app.models import WorkerInstance
        current = db.scalar(select(WorkerInstance).where(WorkerInstance.worker_id == "worker-registry-heartbeat"))
        assert current.last_heartbeat_at > first_heartbeat
        assert current.status == "online"
    allow_finish.set()
    thread.join(timeout=5)
    assert not thread.is_alive()
    assert result_holder["processed"] == 1
    with factory() as db:
        from backend.app.models import WorkerInstance
        assert db.scalar(select(WorkerInstance).where(WorkerInstance.worker_id == "worker-registry-heartbeat")).status == "offline"
        assert db.get(Task, task_id).status == "succeeded"


def test_two_agent_dependency_chain_executes_in_order_with_persisted_lineage():
    from backend.app.models import Agent, AgentVersion, Skill, SkillVersion, AgentSkillBinding, AgentRun, SkillRun
    from backend.app.services.task_service import add_task_dependency
    factory = make_factory()
    project_id, first_agent_id, first_av_id, first_sv_id, _ = seed_runtime(factory)
    with factory() as db:
        second_agent = Agent(code="AGENT_ART_CONTINUITY", display_name="Art Continuity Agent")
        second_skill = Skill(code="SKILL_CONTINUITY_QC", display_name="Continuity QC")
        db.add_all([second_agent, second_skill]); db.flush()
        second_av = AgentVersion(agent_id=second_agent.id, version_number=1,
            definition_snapshot={"role": "continuity"}, definition_sha256="c" * 64)
        second_sv = SkillVersion(skill_id=second_skill.id, version_number=1,
            definition_snapshot={"skill": "continuity check"}, definition_sha256="d" * 64)
        db.add_all([second_av, second_sv]); db.flush()
        db.add(AgentSkillBinding(agent_version_id=second_av.id, skill_version_id=second_sv.id, binding_config={}))
        first = create_task(db, project_id=project_id, task_type="SCRIPT_BREAKDOWN", title="Script breakdown", input_snapshot={"scene": "8.1"})
        second = create_task(db, project_id=project_id, task_type="CONTINUITY_QC", title="Continuity check", input_snapshot={"scene": "8.1"})
        add_task_dependency(db, project_id=project_id, task_id=second.id, depends_on_task_id=first.id)
        db.commit()
        second_agent_id, second_av_id, second_sv_id = second_agent.id, second_av.id, second_sv.id
        first_id, second_id = first.id, second.id

    executed = []
    registrations = [
        SkillRegistration("SCRIPT_BREAKDOWN", first_agent_id, first_av_id, first_sv_id,
            lambda payload: (executed.append("script_breakdown") or {"coverage": ["action", "reaction"]})),
        SkillRegistration("CONTINUITY_QC", second_agent_id, second_av_id, second_sv_id,
            lambda payload: (executed.append("continuity_qc") or {"checked": True, "scene": payload["scene"]})),
    ]
    worker = Worker(session_factory=factory, worker_id="worker-multi-agent-chain", registrations=registrations)
    # The second agent's task is blocked until the first task has committed success.
    assert worker.run_once()["task_id"] == str(first_id)
    with factory() as db:
        assert db.get(Task, second_id).status == "queued"
    assert worker.run_once()["task_id"] == str(second_id)
    assert executed == ["script_breakdown", "continuity_qc"]
    with factory() as db:
        first_task, second_task = db.get(Task, first_id), db.get(Task, second_id)
        assert first_task.status == second_task.status == "succeeded"
        runs = db.scalars(select(AgentRun).where(AgentRun.task_id.in_([first_id, second_id])).order_by(AgentRun.created_at)).all()
        assert {run.agent_id for run in runs} == {first_agent_id, second_agent_id}
        assert len(db.scalars(select(SkillRun).where(SkillRun.agent_run_id.in_([run.id for run in runs]))).all()) == 2


def test_worker_stops_when_replaced_while_skill_is_running():
    import threading
    from backend.app.services.worker_registry import register_worker
    from backend.app.models import AgentRun, SkillRun
    factory = make_factory()
    _, agent_id, av_id, sv_id, task_id = seed_runtime(factory)
    started = threading.Event()
    release = threading.Event()

    def blocked(_payload):
        started.set()
        assert release.wait(timeout=5)
        return {"stale_result": True}

    worker = Worker(session_factory=factory, worker_id="worker-fenced-live",
        registrations=[SkillRegistration("WORKER_TEST", agent_id, av_id, sv_id, blocked)],
        lease_seconds=5, heartbeat_interval_seconds=0.5)
    outcome = {}
    thread = threading.Thread(target=lambda: outcome.setdefault(
        "processed", worker.run_forever(idle_sleep_seconds=0.05, max_tasks=1)))
    thread.start()
    assert started.wait(timeout=3)
    with factory() as db:
        replacement = register_worker(db, worker_id="worker-fenced-live", capabilities=["WORKER_TEST"], process_id=999)
        replacement_token = replacement.instance_token
        db.commit()
    release.set()
    thread.join(timeout=5)
    assert not thread.is_alive()
    assert outcome["processed"] == 0
    with factory() as db:
        task = db.get(Task, task_id)
        from backend.app.models import WorkerInstance
        registry = db.scalar(select(WorkerInstance).where(WorkerInstance.worker_id == "worker-fenced-live"))
        assert task.status == "running"  # lease recovery, not the fenced process, owns task finalization
        run = db.scalar(select(AgentRun).where(AgentRun.task_id == task_id))
        skill_run = db.scalar(select(SkillRun).where(SkillRun.agent_run_id == run.id))
        assert run.status == skill_run.status == "failed"
        assert run.error_detail["code"] == "WORKER_GENERATION_FENCED"
        assert registry.instance_token == replacement_token
        assert registry.status == "online"

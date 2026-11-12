"""Real PostgreSQL-only migration/trigger/FK tests (enabled in CI service job)."""
import os

import pytest
from sqlalchemy import create_engine, select, update
from sqlalchemy.exc import DBAPIError, IntegrityError
from sqlalchemy.orm import Session

from backend.app.db.ids import uuid7
from backend.app.models import (
    Entity, IntegrationObjectSnapshot, IntegrationRun, IntegrationSource, Project, Principal, ProjectMember, MemberRole,
)

URL = os.getenv("AFS_TEST_POSTGRES_URL")
pytestmark = pytest.mark.skipif(not URL, reason="AFS_TEST_POSTGRES_URL is not configured")


@pytest.fixture
def pg_session():
    engine = create_engine(URL, pool_pre_ping=True)
    with Session(engine, expire_on_commit=False) as db:
        yield db
    engine.dispose()


def _base_records(db):
    project = Project(id=uuid7(), code=f"PG_{uuid7().hex[-10:]}", name="PG contract test")
    db.add(project)
    db.flush()
    source = IntegrationSource(
        project_id=project.id, code="FM_TEST", source_kind="footage_mode",
        display_name="PostgreSQL test source", source_version="test",
        source_sha256="a" * 64, config_snapshot={},
    )
    db.add(source)
    db.flush()
    run = IntegrationRun(
        project_id=project.id, integration_source_id=source.id, run_type="import",
        status="completed", idempotency_key=uuid7().hex,
        package_version="test", package_sha256="a" * 64,
        command_snapshot={}, input_snapshot={"immutable": True},
        output_snapshot={}, validation_snapshot={}, exit_code=0,
    )
    db.add(run)
    db.flush()
    snapshot = IntegrationObjectSnapshot(
        project_id=project.id, integration_run_id=run.id,
        source_object_type="dramatic_event", source_object_key="EVT-PG-1",
        raw_payload={"action": "original"}, raw_sha256="b" * 64,
        source_range_snapshot={},
    )
    db.add(snapshot)
    db.commit()
    return project, source, run, snapshot


def test_postgres_migration_installed_and_snapshot_trigger_is_active(pg_session):
    project, source, run, snapshot = _base_records(pg_session)
    with pytest.raises(DBAPIError):
        pg_session.execute(
            update(IntegrationObjectSnapshot)
            .where(IntegrationObjectSnapshot.id == snapshot.id)
            .values(raw_payload={"action": "tampered"})
        )
        pg_session.commit()
    pg_session.rollback()
    assert pg_session.get(IntegrationObjectSnapshot, snapshot.id).raw_payload == {"action": "original"}


def test_postgres_integration_run_input_snapshot_is_immutable(pg_session):
    _project, _source, run, _snapshot = _base_records(pg_session)
    with pytest.raises(DBAPIError):
        pg_session.execute(
            update(IntegrationRun)
            .where(IntegrationRun.id == run.id)
            .values(input_snapshot={"immutable": False})
        )
        pg_session.commit()
    pg_session.rollback()
    assert pg_session.get(IntegrationRun, run.id).input_snapshot == {"immutable": True}


def test_postgres_composite_fk_rejects_cross_project_run_snapshot(pg_session):
    project, _source, run, _snapshot = _base_records(pg_session)
    other = Project(id=uuid7(), code=f"PG_{uuid7().hex[-10:]}", name="Other project")
    pg_session.add(other)
    pg_session.flush()
    invalid = IntegrationObjectSnapshot(
        project_id=other.id, integration_run_id=run.id,
        source_object_type="dramatic_event", source_object_key="CROSS-PROJECT",
        raw_payload={}, raw_sha256="c" * 64, source_range_snapshot={},
    )
    pg_session.add(invalid)
    with pytest.raises(IntegrityError):
        pg_session.flush()
    pg_session.rollback()


def test_postgres_task_claim_lease_is_single_owner_and_persisted(pg_session):
    from backend.app.models import Task
    from backend.app.services.task_service import create_task, claim_next_task, LeaseConflict, complete_task
    project = Project(id=uuid7(), code=f"PG_{uuid7().hex[-10:]}", name="Runtime lease")
    pg_session.add(project); pg_session.flush()
    task = create_task(pg_session, project_id=project.id, task_type="PG_LEASE", title="Lease", input_snapshot={"x": 1})
    first = claim_next_task(pg_session, worker_id="pg-worker-a", lease_seconds=60, project_id=project.id, task_type="PG_LEASE")
    assert first is not None and first[0].id == task.id
    second = claim_next_task(pg_session, worker_id="pg-worker-b", lease_seconds=60, project_id=project.id, task_type="PG_LEASE")
    assert second is None
    claimed, token = first
    assert claimed.lease_owner == "pg-worker-a" and claimed.lease_token == token
    complete_task(pg_session, task_id=task.id, lease_token=token, output_snapshot={"ok": True})
    pg_session.commit()
    assert pg_session.get(Task, task.id).status == "succeeded"


def test_postgres_task_idempotency_unique_constraint(pg_session):
    from backend.app.services.task_service import create_task
    project = Project(id=uuid7(), code=f"PG_{uuid7().hex[-10:]}", name="Runtime idempotency")
    pg_session.add(project); pg_session.flush()
    first = create_task(pg_session, project_id=project.id, task_type="PG_IDEMPOTENT", title="One",
                        input_snapshot={"source": "8.1"}, idempotency_key="pg-idem-fixed")
    second = create_task(pg_session, project_id=project.id, task_type="PG_IDEMPOTENT", title="One",
                         input_snapshot={"source": "8.1"}, idempotency_key="pg-idem-fixed")
    assert first.id == second.id
    pg_session.commit()


def test_postgres_concurrent_task_claims_have_distinct_single_owners(pg_session):
    from concurrent.futures import ThreadPoolExecutor
    from threading import Barrier
    from sqlalchemy.orm import sessionmaker
    from backend.app.services.task_service import create_task, claim_next_task
    project = Project(id=uuid7(), code=f"PG_{uuid7().hex[-10:]}", name="Concurrent claims")
    pg_session.add(project)
    pg_session.flush()
    tasks = [create_task(pg_session, project_id=project.id, task_type="PG_CONCURRENT", title=f"Task {i}", input_snapshot={"i": i}) for i in range(8)]
    pg_session.commit()
    factory = sessionmaker(pg_session.get_bind(), expire_on_commit=False)
    barrier = Barrier(8)

    def claim(worker_no):
        barrier.wait(timeout=10)
        with factory() as db:
            result = claim_next_task(db, worker_id=f"pg-worker-{worker_no}", project_id=project.id, task_type="PG_CONCURRENT")
            db.commit()
            return result[0].id if result else None

    with ThreadPoolExecutor(max_workers=8) as pool:
        claimed = list(pool.map(claim, range(8)))
    assert all(claimed)
    assert len(set(claimed)) == 8
    assert set(claimed) == {task.id for task in tasks}


def test_postgres_concurrent_inbox_delivery_runs_handler_once(pg_session):
    from concurrent.futures import ThreadPoolExecutor
    from threading import Barrier, Lock
    from sqlalchemy.orm import sessionmaker
    from backend.app.services.event_delivery import InboxConsumer
    factory = sessionmaker(pg_session.get_bind(), expire_on_commit=False)
    barrier = Barrier(10)
    lock = Lock()
    handled = []

    def handler(_db, payload):
        with lock:
            handled.append(payload["event_id"])

    consumer = InboxConsumer(session_factory=factory, consumer_key=f"pg-concurrent-{uuid7().hex}",
                             handlers={"asset.ready": handler})
    envelope = {"idempotency_key": f"same-{uuid7().hex}", "event_type": "asset.ready", "payload": {"event_id": "asset-42"}}

    def deliver(_):
        barrier.wait(timeout=10)
        return consumer.consume(envelope)

    with ThreadPoolExecutor(max_workers=10) as pool:
        results = list(pool.map(deliver, range(10)))
    assert handled == ["asset-42"]
    assert sum(result["status"] == "processed" for result in results) == 1
    assert sum(result["status"] == "duplicate" for result in results) == 9


def test_postgres_worker_process_generation_fences_previous_instance(pg_session):
    from backend.app.services.worker_registry import register_worker, heartbeat_worker, stop_worker
    first = register_worker(pg_session, worker_id=f"pg-reused-{uuid7().hex[-8:]}", capabilities=["A"], process_id=100)
    worker_id = first.worker_id
    first_token = first.instance_token
    pg_session.commit()
    second = register_worker(pg_session, worker_id=worker_id, capabilities=["B"], process_id=200)
    second_token = second.instance_token
    pg_session.commit()
    assert first_token != second_token
    with pytest.raises(LookupError):
        heartbeat_worker(pg_session, worker_id=worker_id, instance_token=first_token)
    with pytest.raises(LookupError):
        stop_worker(pg_session, worker_id=worker_id, instance_token=first_token)
    assert heartbeat_worker(pg_session, worker_id=worker_id, instance_token=second_token).process_id == 200
    pg_session.commit()


def test_postgres_orchestration_plan_requires_human_approval_and_materializes_once(pg_session):
    from concurrent.futures import ThreadPoolExecutor
    from sqlalchemy.orm import sessionmaker
    from backend.app.models import Agent, AgentVersion, AgentSkillBinding, Skill, SkillVersion, ProjectMember, MemberRole
    from backend.app.services.task_service import create_task
    from backend.app.services.orchestrator import persist_plan, decide_plan_approval, materialize_plan_tasks

    project = Project(id=uuid7(), code=f"PG_PLAN_{uuid7().hex[-8:]}", name="Orchestration approval")
    agent = Agent(code=f"PG_AGENT_{uuid7().hex[-8:]}", display_name="PG Specialist")
    skill = Skill(code=f"PG_SKILL_{uuid7().hex[-8:]}", display_name="PG Capability")
    pg_session.add_all([project, agent, skill]); pg_session.flush()
    av = AgentVersion(agent_id=agent.id, version_number=1, definition_snapshot={"role": "specialist"},
                      definition_sha256="d" * 64)
    sv = SkillVersion(skill_id=skill.id, version_number=1,
                      definition_snapshot={"capabilities": ["pg_test"]}, definition_sha256="e" * 64)
    pg_session.add_all([av, sv]); pg_session.flush()
    pg_session.add(AgentSkillBinding(agent_version_id=av.id, skill_version_id=sv.id))
    root = create_task(pg_session, project_id=project.id, task_type="PG_PLAN_ROOT",
                       title="Postgres plan root", input_snapshot={})
    reviewer_id = uuid7()
    pg_session.add(Principal(id=reviewer_id, principal_kind="human", display_name="PG reviewer"))
    pg_session.flush()
    pg_session.add(ProjectMember(project_id=project.id, principal_id=reviewer_id,
                                 role=MemberRole.director, is_active=True))
    pg_session.flush()
    plan = persist_plan(pg_session, project_id=project.id, task_id=root.id, steps=[{
        "key": "specialist", "step_kind": "skill", "task_type": "PG_PLAN_STEP",
        "agent_version_id": av.id, "skill_version_id": sv.id, "input": {"x": 1},
    }])
    plan_id = plan.id
    decide_plan_approval(pg_session, plan_id=plan_id, actor_id=reviewer_id,
                         actor_kind="human", decision="approved")
    pg_session.commit()

    factory = sessionmaker(pg_session.get_bind(), expire_on_commit=False)
    def materialize(_):
        with factory() as db:
            tasks = materialize_plan_tasks(db, plan_id=plan_id)
            ids = [task.id for task in tasks]
            db.commit()
            return ids

    with ThreadPoolExecutor(max_workers=2) as pool:
        outputs = list(pool.map(materialize, range(2)))
    assert outputs[0] == outputs[1]
    with factory() as db:
        from backend.app.models import OrchestrationPlanStep
        steps = db.query(OrchestrationPlanStep).filter_by(plan_id=plan_id).all()
        assert len(steps) == 1 and steps[0].task_id is not None


def test_postgres_agent_handoff_idempotency_under_concurrency(pg_session):
    from concurrent.futures import ThreadPoolExecutor
    from threading import Barrier
    from sqlalchemy.orm import sessionmaker
    from backend.app.models import Agent
    from backend.app.services.agent_collaboration import send_agent_message

    project = Project(id=uuid7(), code=f"PG_MSG_{uuid7().hex[-8:]}", name="Agent collaboration")
    sender = Agent(code=f"PG_SENDER_{uuid7().hex[-8:]}", display_name="Sender")
    receiver = Agent(code=f"PG_RECEIVER_{uuid7().hex[-8:]}", display_name="Receiver")
    pg_session.add_all([project, sender, receiver]); pg_session.commit()
    factory = sessionmaker(pg_session.get_bind(), expire_on_commit=False)
    barrier = Barrier(8)
    envelope = {"project_id": project.id, "from_agent_id": sender.id, "to_agent_id": receiver.id,
                "message_type": "review.requested", "payload": {"artifact": "scene-8.1"},
                "idempotency_key": f"pg-handoff-{uuid7().hex}"}

    def send(_):
        barrier.wait(timeout=10)
        with factory() as db:
            row, created = send_agent_message(db, **envelope)
            db.commit()
            return row.id, created

    with ThreadPoolExecutor(max_workers=8) as pool:
        results = list(pool.map(send, range(8)))
    assert len({item[0] for item in results}) == 1
    assert sum(item[1] for item in results) == 1


def test_postgres_concurrent_director_action_executes_once(pg_session):
    """Concurrent human requests for one approved case must create exactly one task."""
    from concurrent.futures import ThreadPoolExecutor
    from threading import Barrier
    from sqlalchemy.orm import sessionmaker
    from backend.app.models import ActionExecution, AuditLog, DirectorDecisionCase, Task, utcnow
    from backend.app.services.action_execution import execute_approved_action

    project = Project(id=uuid7(), code=f"PG_ACTION_{uuid7().hex[-8:]}", name="Concurrent director action")
    actor = Principal(principal_kind="human", display_name="PG Director")
    pg_session.add_all([project, actor])
    pg_session.flush()
    pg_session.add(ProjectMember(project_id=project.id, principal_id=actor.id, role=MemberRole.owner, is_active=True))
    case = DirectorDecisionCase(
        project_id=project.id, case_key=f"pg-action-{uuid7().hex}",
        source_brief_sha256="a" * 64, source_state_digest="b" * 64,
        recommendation_code="TASK_FAILED", severity="high", approval_required="director_review",
        evidence_refs=["task:source"], proposal_snapshot={"title": "Create recovery task"},
        status="approved", decision="approved", decided_by=actor.id, decided_at=utcnow(),
        authorized_action_snapshot={
            "action_type": "create_task",
            "payload": {"task_type": "PG_ACTION_RECOVERY", "title": "Single recovery task", "input_snapshot": {"source": "concurrency-test"}},
        },
    )
    pg_session.add(case)
    pg_session.commit()

    factory = sessionmaker(pg_session.get_bind(), expire_on_commit=False)
    barrier = Barrier(8)
    project_id, case_id, actor_id = project.id, case.id, actor.id
    idem_key = f"pg-action-concurrent-{uuid7().hex}"

    def execute_one(_):
        barrier.wait(timeout=10)
        with factory() as db:
            execution, created = execute_approved_action(
                db, project_id=project_id, case_id=case_id, actor_id=actor_id,
                actor_kind="human", idempotency_key=idem_key,
            )
            execution_id = execution.id
            db.commit()
            return str(execution_id), created

    with ThreadPoolExecutor(max_workers=8) as pool:
        outcomes = list(pool.map(execute_one, range(8)))

    assert len({execution_id for execution_id, _created in outcomes}) == 1
    assert sum(1 for _execution_id, created in outcomes if created) == 1
    with factory() as verify:
        assert verify.scalar(select(ActionExecution).where(ActionExecution.decision_case_id == case_id)) is not None
        assert len(verify.scalars(select(Task).where(Task.project_id == project_id, Task.title == "Single recovery task")).all()) == 1
        assert len(verify.scalars(select(AuditLog).where(AuditLog.project_id == project_id, AuditLog.action == "DIRECTOR_ACTION_EXECUTED")).all()) == 1


def test_postgres_concurrent_director_action_different_keys_still_executes_once(pg_session):
    """A case-level lock must prevent two operators using different keys from double execution."""
    from concurrent.futures import ThreadPoolExecutor
    from threading import Barrier
    from sqlalchemy.orm import sessionmaker
    from backend.app.models import ActionExecution, DirectorDecisionCase, Task, utcnow
    from backend.app.services.action_execution import execute_approved_action, ActionExecutionError

    project = Project(id=uuid7(), code=f"PG_ACTION_KEYS_{uuid7().hex[-8:]}", name="Concurrent director action keys")
    actor = Principal(principal_kind="human", display_name="PG Director")
    pg_session.add_all([project, actor]); pg_session.flush()
    pg_session.add(ProjectMember(project_id=project.id, principal_id=actor.id, role=MemberRole.owner, is_active=True))
    case = DirectorDecisionCase(
        project_id=project.id, case_key=f"pg-action-keys-{uuid7().hex}",
        source_brief_sha256="c" * 64, source_state_digest="d" * 64,
        recommendation_code="TASK_FAILED", severity="high", approval_required="director_review",
        evidence_refs=["task:source"], proposal_snapshot={"title": "Create one recovery task"},
        status="approved", decision="approved", decided_by=actor.id, decided_at=utcnow(),
        authorized_action_snapshot={
            "action_type": "create_task",
            "payload": {"task_type": "PG_ACTION_RECOVERY", "title": "Single different-key recovery", "input_snapshot": {"source": "different-key-concurrency"}},
        },
    )
    pg_session.add(case); pg_session.commit()

    factory = sessionmaker(pg_session.get_bind(), expire_on_commit=False)
    barrier = Barrier(8)
    project_id, case_id, actor_id = project.id, case.id, actor.id

    def execute_one(worker_no):
        barrier.wait(timeout=10)
        with factory() as db:
            try:
                execution, created = execute_approved_action(
                    db, project_id=project_id, case_id=case_id, actor_id=actor_id,
                    actor_kind="human", idempotency_key=f"pg-action-distinct-{worker_no}-{uuid7().hex}",
                )
                execution_id = str(execution.id)
                db.commit()
                return ("ok", execution_id, created)
            except ActionExecutionError as exc:
                db.rollback()
                return ("conflict", str(exc), False)

    with ThreadPoolExecutor(max_workers=8) as pool:
        outcomes = list(pool.map(execute_one, range(8)))

    assert sum(outcome[0] == "ok" for outcome in outcomes) == 1
    assert sum(outcome[0] == "conflict" for outcome in outcomes) == 7
    with factory() as verify:
        assert len(verify.scalars(select(ActionExecution).where(ActionExecution.decision_case_id == case_id)).all()) == 1
        assert len(verify.scalars(select(Task).where(Task.project_id == project_id, Task.title == "Single different-key recovery")).all()) == 1

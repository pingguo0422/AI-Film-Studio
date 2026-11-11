from datetime import datetime, timedelta, timezone
from sqlalchemy import create_engine, event, select
from sqlalchemy.orm import Session, sessionmaker
import pytest
from backend.app.db.base import Base
from backend.app.db.ids import uuid7
from backend.app.models import Project, Task, Agent, AgentVersion, AgentSkillBinding, Skill, SkillVersion, AgentRun, SkillRun, OutboxEvent, InboxEvent, ProjectMember, MemberRole, AuditLog, Principal
from backend.app.services.task_service import (
    create_task, add_task_dependency, claim_next_task, complete_task, fail_task,
    cancel_task, reap_expired_leases, LeaseConflict, TaskDependencyCycleError,
    receive_inbox, enqueue_outbox, transition_task, InvalidTaskTransition, heartbeat_task,
)
from backend.app.services.orchestrator import execute_one_skill_task, topological_order, OrchestrationError, decide_plan_approval, propose_plan_from_request, materialize_plan_tasks


def make_db():
    engine=create_engine("sqlite+pysqlite:///:memory:")
    @event.listens_for(engine,"connect")
    def fk(conn,_): conn.execute("PRAGMA foreign_keys=ON")
    Base.metadata.create_all(engine)
    return engine


def seed_project(db):
    p=Project(id=uuid7(),code="PRJ_RUNTIME_TEST",name="Runtime Test")
    db.add(p); db.flush(); return p


def test_task_create_idempotency_and_conflict():
    engine=make_db()
    with Session(engine) as db:
        p=seed_project(db)
        one=create_task(db,project_id=p.id,task_type="CHECK",title="Check",input_snapshot={"x":1},idempotency_key="same")
        two=create_task(db,project_id=p.id,task_type="CHECK",title="Check",input_snapshot={"x":1},idempotency_key="same")
        assert one.id==two.id
        with pytest.raises(Exception):
            create_task(db,project_id=p.id,task_type="CHECK",title="Changed",input_snapshot={"x":1},idempotency_key="same")


def test_dependency_ready_queue_waits_for_prerequisite_success():
    engine=make_db()
    with Session(engine) as db:
        p=seed_project(db)
        first=create_task(db,project_id=p.id,task_type="A",title="A",input_snapshot={})
        second=create_task(db,project_id=p.id,task_type="B",title="B",input_snapshot={})
        add_task_dependency(db,project_id=p.id,task_id=second.id,depends_on_task_id=first.id)
        claim=claim_next_task(db,worker_id="worker")
        assert claim and claim[0].id==first.id
        task,token=claim
        complete_task(db,task_id=task.id,lease_token=token,output_snapshot={"ok":True})
        next_claim=claim_next_task(db,worker_id="worker-2")
        assert next_claim and next_claim[0].id==second.id


def test_lease_retry_expiry_and_stale_worker_rejected():
    engine=make_db(); now=datetime(2026,11,9,tzinfo=timezone.utc)
    with Session(engine) as db:
        p=seed_project(db)
        task=create_task(db,project_id=p.id,task_type="RETRY",title="Retry",input_snapshot={},max_attempts=2)
        claimed=claim_next_task(db,worker_id="w1",lease_seconds=5,now=now); assert claimed
        _,token=claimed
        assert reap_expired_leases(db,now=now+timedelta(seconds=6))==1
        assert db.get(Task,task.id).status=="retry_wait"
        with pytest.raises(LeaseConflict): complete_task(db,task_id=task.id,lease_token=token,output_snapshot={},now=now+timedelta(seconds=7))
        claimed2=claim_next_task(db,worker_id="w2",lease_seconds=5,now=now+timedelta(seconds=7)); assert claimed2
        task2,token2=claimed2
        failed=fail_task(db,task_id=task2.id,lease_token=token2,error_detail={"err":"x"},now=now+timedelta(seconds=8))
        assert failed.status=="failed" and failed.attempt_count==2


def test_running_cancellation_is_cooperative_and_queued_cancel_is_terminal():
    engine=make_db()
    with Session(engine) as db:
        p=seed_project(db)
        task=create_task(db,project_id=p.id,task_type="CANCEL",title="Cancel",input_snapshot={})
        claimed=claim_next_task(db,worker_id="w"); task,token=claimed
        cancelled=cancel_task(db,task_id=task.id)
        assert cancelled.status=="running" and cancelled.cancel_requested is True
        with pytest.raises(Exception): complete_task(db,task_id=task.id,lease_token=token,output_snapshot={})


def test_outbox_and_inbox_are_idempotent():
    engine=make_db()
    with Session(engine) as db:
        p=seed_project(db); task=create_task(db,project_id=p.id,task_type="X",title="X",input_snapshot={})
        event1=enqueue_outbox(db,aggregate_type="task",aggregate_id=task.id,event_type="x",idempotency_key="evt-1",payload={"a":1})
        event2=enqueue_outbox(db,aggregate_type="task",aggregate_id=task.id,event_type="x",idempotency_key="evt-1",payload={"a":1})
        assert event1.id==event2.id
        _,created=receive_inbox(db,consumer_key="c",idempotency_key="in-1",event_type="x",payload={"a":1})
        _,duplicate=receive_inbox(db,consumer_key="c",idempotency_key="in-1",event_type="x",payload={"a":1})
        assert created is True and duplicate is False
        assert db.scalar(select(OutboxEvent).where(OutboxEvent.idempotency_key=="evt-1")) is not None
        assert db.scalar(select(InboxEvent).where(InboxEvent.idempotency_key=="in-1")) is not None


def test_dag_planner_is_stable_and_rejects_cycle():
    assert topological_order([{"key":"c","depends_on":["b"]},{"key":"a"},{"key":"b","depends_on":["a"]}])==["a","b","c"]
    with pytest.raises(OrchestrationError): topological_order([{"key":"a","depends_on":["b"]},{"key":"b","depends_on":["a"]}])


def test_exact_agent_and_skill_versions_are_recorded_with_execution():
    engine=make_db()
    with Session(engine) as db:
        p=seed_project(db)
        agent=Agent(code="DIRECTOR_TEST",display_name="Director"); skill=Skill(code="SKILL_TEST",display_name="Test Skill")
        db.add_all([agent,skill]); db.flush()
        av=AgentVersion(agent_id=agent.id,version_number=1,definition_snapshot={"role":"director"},definition_sha256="a"*64)
        sv=SkillVersion(skill_id=skill.id,version_number=3,definition_snapshot={"operation":"test"},definition_sha256="b"*64)
        db.add_all([av,sv]); db.flush()
        db.add(AgentSkillBinding(agent_version_id=av.id,skill_version_id=sv.id,binding_config={"executor":"local_test"})); db.flush()
        task=create_task(db,project_id=p.id,task_type="RUN_SKILL",title="Run",input_snapshot={"hello":"world"})
        result=execute_one_skill_task(db,worker_id="runtime-worker",agent_id=agent.id,agent_version_id=av.id,
                                      skill_version_id=sv.id,executor=lambda x:{"echo":x["hello"]})
        assert result["status"]=="succeeded" and result["output"]=={"echo":"world"}
        ar=db.get(AgentRun,__import__('uuid').UUID(result["agent_run_id"]))
        sr=db.get(SkillRun,__import__('uuid').UUID(result["skill_run_id"]))
        assert ar.agent_version_id==av.id and ar.input_snapshot["agent_version_sha256"]=="a"*64
        assert sr.skill_version_id==sv.id and sr.input_snapshot["skill_version_sha256"]=="b"*64
        assert db.get(Task,task.id).status=="succeeded"


def test_cooperative_cancellation_is_acknowledged_and_run_records_are_cancelled():
    engine=make_db()
    with Session(engine) as db:
        p=seed_project(db); agent=Agent(code="DIRECTOR_CANCEL",display_name="Director"); skill=Skill(code="SKILL_CANCEL",display_name="Cancel Skill")
        db.add_all([agent,skill]); db.flush()
        av=AgentVersion(agent_id=agent.id,version_number=1,definition_snapshot={},definition_sha256="c"*64)
        sv=SkillVersion(skill_id=skill.id,version_number=1,definition_snapshot={},definition_sha256="d"*64)
        db.add_all([av,sv]); db.flush(); db.add(AgentSkillBinding(agent_version_id=av.id,skill_version_id=sv.id)); db.flush()
        task=create_task(db,project_id=p.id,task_type="CANCEL_RUN",title="Cancel Run",input_snapshot={})
        def executor(_):
            current=db.get(Task,task.id); current.cancel_requested=True; db.commit()
            return {"too_late":True}
        result=execute_one_skill_task(db,worker_id="worker",agent_id=agent.id,agent_version_id=av.id,
                                      skill_version_id=sv.id,executor=executor)
        assert result["status"]=="cancelled"
        assert db.get(Task,task.id).status=="cancelled"
        assert db.scalar(select(AgentRun).where(AgentRun.task_id==task.id)).status=="cancelled"


def test_registry_requires_explicit_agent_skill_version_binding():
    engine=make_db()
    with Session(engine) as db:
        p=seed_project(db); agent=Agent(code="DIRECTOR_UNBOUND",display_name="Director"); skill=Skill(code="SKILL_UNBOUND",display_name="Skill")
        db.add_all([agent,skill]); db.flush()
        av=AgentVersion(agent_id=agent.id,version_number=1,definition_snapshot={},definition_sha256="e"*64)
        sv=SkillVersion(skill_id=skill.id,version_number=1,definition_snapshot={},definition_sha256="f"*64)
        db.add_all([av,sv]); db.flush(); task=create_task(db,project_id=p.id,task_type="UNBOUND",title="Unbound",input_snapshot={})
        with pytest.raises(Exception):
            execute_one_skill_task(db,worker_id="worker",agent_id=agent.id,agent_version_id=av.id,
                                   skill_version_id=sv.id,executor=lambda _: {})
        assert db.get(Task,task.id).status=="failed"


def test_explicit_state_machine_rejects_illegal_transition_and_heartbeat_renews_lease():
    engine=make_db(); now=datetime(2026,11,9,tzinfo=timezone.utc)
    with Session(engine) as db:
        p=seed_project(db); task=create_task(db,project_id=p.id,task_type="STATE",title="State",input_snapshot={})
        with pytest.raises(InvalidTaskTransition): transition_task(db,task_id=task.id,target_status="succeeded")
        task,token=claim_next_task(db,worker_id="state-worker",lease_seconds=10,now=now)
        renewed=heartbeat_task(db,task_id=task.id,lease_token=token,lease_seconds=20,now=now+timedelta(seconds=2))
        expires=renewed.lease_expires_at
        if expires.tzinfo is None: expires=expires.replace(tzinfo=timezone.utc)
        assert expires==now+timedelta(seconds=22)


def test_durable_orchestration_plan_materializes_dependency_tasks_and_reconciles_runs():
    from backend.app.services.orchestrator import persist_plan, materialize_plan_tasks, refresh_plan_status
    from backend.app.runtime.worker import Worker, SkillRegistration

    engine = make_db()
    with Session(engine) as db:
        project = seed_project(db)
        specialists = [
            Agent(code="CHAIN_SCRIPT_AGENT", display_name="Script Director"),
            Agent(code="CHAIN_VISUAL_AGENT", display_name="Visual Director"),
            Agent(code="CHAIN_SHOT_AGENT", display_name="Shot Director"),
        ]
        skill = Skill(code="CHAIN_SKILL", display_name="Specialist Capability")
        db.add_all([*specialists, skill]); db.flush()
        versions = [AgentVersion(agent_id=agent.id, version_number=1,
                    definition_snapshot={"role": role}, definition_sha256=hash_value)
                    for agent, role, hash_value in zip(specialists,
                        ["script", "visual", "shots"], ["a" * 64, "b" * 64, "c" * 64])]
        sv = SkillVersion(skill_id=skill.id, version_number=1,
                          definition_snapshot={"operation": "specialist"}, definition_sha256="d" * 64)
        db.add_all([*versions, sv]); db.flush()
        db.add_all([AgentSkillBinding(agent_version_id=av.id, skill_version_id=sv.id) for av in versions]); db.flush()
        root = create_task(db, project_id=project.id, task_type="ORCHESTRATION_ROOT",
                           title="Three-specialist production chain", input_snapshot={})
        steps = []
        for key, task_type, agent_version, payload, dependency in [
            ("script", "CHAIN_SCRIPT", versions[0], {"stage": "script"}, []),
            ("visual", "CHAIN_VISUAL", versions[1], {"stage": "visual"}, ["script"]),
            ("shots", "CHAIN_SHOTS", versions[2], {"stage": "shots"}, ["visual"]),
        ]:
            steps.append({"key": key, "step_kind": "skill", "task_type": task_type,
                "agent_version_id": agent_version.id, "skill_version_id": sv.id,
                "depends_on": dependency, "input": payload})
        plan = persist_plan(db, project_id=project.id, task_id=root.id, steps=steps)
        plan_id = plan.id
        reviewer_id = uuid7()
        db.add(Principal(id=reviewer_id, principal_kind="human", display_name="Reviewer")); db.flush()
        db.add(ProjectMember(project_id=project.id, principal_id=reviewer_id, role=MemberRole.director, is_active=True))
        db.flush()
        with pytest.raises(OrchestrationError, match="human approval"):
            materialize_plan_tasks(db, plan_id=plan_id)
        decide_plan_approval(db, plan_id=plan_id, actor_id=reviewer_id, actor_kind="human",
                             decision="approved", note="Director approved the execution plan")
        tasks = materialize_plan_tasks(db, plan_id=plan_id)
        assert len(tasks) == 3
        assert [t.task_type for t in tasks] == ["CHAIN_SCRIPT", "CHAIN_VISUAL", "CHAIN_SHOTS"]
        # Repeated materialization must reuse the same three task identities.
        again = materialize_plan_tasks(db, plan_id=plan_id)
        assert [t.id for t in again] == [t.id for t in tasks]
        db.commit()
        registrations = [
            SkillRegistration("CHAIN_SCRIPT", specialists[0].id, versions[0].id, sv.id,
                              lambda payload: {"completed_stage": payload["stage"]}),
            SkillRegistration("CHAIN_VISUAL", specialists[1].id, versions[1].id, sv.id,
                              lambda payload: {"completed_stage": payload["stage"]}),
            SkillRegistration("CHAIN_SHOTS", specialists[2].id, versions[2].id, sv.id,
                              lambda payload: {"completed_stage": payload["stage"]}),
        ]

    factory = sessionmaker(engine, expire_on_commit=False, class_=Session)
    worker = Worker(session_factory=factory, worker_id="chain-worker", registrations=registrations)
    with factory() as db:
        plan = refresh_plan_status(db, plan_id=plan_id)
        assert plan.status == "queued"
        db.commit()

    completed = []
    for _ in range(3):
        result = worker.run_once()
        assert result is not None
        completed.append(result["output"]["completed_stage"])
        with factory() as db:
            plan = refresh_plan_status(db, plan_id=plan_id)
            db.commit()
    assert completed == ["script", "visual", "shots"]
    with factory() as db:
        plan = refresh_plan_status(db, plan_id=plan_id)
        assert plan.status == "succeeded"
        steps = db.scalars(select(__import__('backend.app.models', fromlist=['OrchestrationPlanStep']).OrchestrationPlanStep)
                           .where(__import__('backend.app.models', fromlist=['OrchestrationPlanStep']).OrchestrationPlanStep.plan_id == plan_id)
                           .order_by(__import__('backend.app.models', fromlist=['OrchestrationPlanStep']).OrchestrationPlanStep.step_order)).all()
        assert [step.status for step in steps] == ["succeeded", "succeeded", "succeeded"]
        assert all(step.task_id and step.output_snapshot for step in steps)
        runs = db.scalars(select(AgentRun).where(AgentRun.task_id.in_([step.task_id for step in steps]))).all()
        assert len(runs) == 3
        assert len({run.agent_id for run in runs}) == 3




def test_orchestrator_proposes_specialists_from_capability_catalog_and_requires_human_decision():
    from backend.app.models import OrchestrationPlan, OrchestrationPlanStep
    from backend.app.services.orchestrator import active_skill_capability_catalog

    engine = make_db()
    with Session(engine) as db:
        project = seed_project(db)
        specialists = [
            Agent(code="AUTO_SCRIPT", display_name="Script Director"),
            Agent(code="AUTO_VISUAL", display_name="Visual Director"),
        ]
        skills = [
            Skill(code="AUTO_SCRIPT_SKILL", display_name="Script Analysis"),
            Skill(code="AUTO_VISUAL_SKILL", display_name="Visual Bible"),
        ]
        db.add_all([*specialists, *skills]); db.flush()
        agent_versions = [
            AgentVersion(agent_id=specialists[0].id, version_number=1,
                         definition_snapshot={"role": "script_director"}, definition_sha256="1" * 64),
            AgentVersion(agent_id=specialists[1].id, version_number=1,
                         definition_snapshot={"role": "visual_director"}, definition_sha256="2" * 64),
        ]
        skill_versions = [
            SkillVersion(skill_id=skills[0].id, version_number=1,
                         definition_snapshot={"capabilities": ["script_analysis"]}, definition_sha256="3" * 64),
            SkillVersion(skill_id=skills[1].id, version_number=1,
                         definition_snapshot={"capabilities": ["visual_bible"]}, definition_sha256="4" * 64),
        ]
        db.add_all([*agent_versions, *skill_versions]); db.flush()
        db.add_all([
            AgentSkillBinding(agent_version_id=agent_versions[0].id, skill_version_id=skill_versions[0].id),
            AgentSkillBinding(agent_version_id=agent_versions[1].id, skill_version_id=skill_versions[1].id),
        ]); db.flush()
        root = create_task(db, project_id=project.id, task_type="AFS_EXECUTIVE_REQUEST",
                           title="Prepare a scene for production", input_snapshot={"scene": "8.1"})
        seen = {}
        def strategy(request, catalog):
            seen["request"] = request
            seen["catalog"] = catalog
            return {"strategy_id": "deterministic-test-executive-director", "steps": [
                {"key": "script", "capability": "script_analysis", "input": {"stage": "script"}},
                {"key": "visual", "capability": "visual_bible", "depends_on": ["script"],
                 "input": {"stage": "visual"}},
            ]}
        plan = propose_plan_from_request(db, project_id=project.id, task_id=root.id,
                                         request={"goal": "prepare scene 8.1"}, planning_strategy=strategy)
        assert plan.approval_status == "pending"
        assert plan.status == "draft"
        assert len(seen["catalog"]) == 2
        assert plan.plan_snapshot["proposal_metadata"]["human_approval_required"] is True
        steps = db.scalars(select(OrchestrationPlanStep).where(
            OrchestrationPlanStep.plan_id == plan.id).order_by(OrchestrationPlanStep.step_order)).all()
        assert [step.input_snapshot["_orchestration_agent_version_id"] for step in steps] == [
            str(agent_versions[0].id), str(agent_versions[1].id)]
        with pytest.raises(OrchestrationError, match="only a human"):
            decide_plan_approval(db, plan_id=plan.id, actor_id=uuid7(), actor_kind="agent", decision="approved")
        reviewer_id = uuid7()
        db.add(Principal(id=reviewer_id, principal_kind="human", display_name="Reviewer")); db.flush()
        db.add(ProjectMember(project_id=project.id, principal_id=reviewer_id, role=MemberRole.producer, is_active=True))
        db.flush()
        with pytest.raises(OrchestrationError, match="human approval"):
            materialize_plan_tasks(db, plan_id=plan.id)
        original_step_input = dict(steps[0].input_snapshot)
        steps[0].input_snapshot = {**original_step_input, "tampered_before_approval": True}
        with pytest.raises(OrchestrationError, match="differs from the approved plan snapshot"):
            decide_plan_approval(db, plan_id=plan.id, actor_id=reviewer_id, actor_kind="human",
                                 decision="approved", note="Reviewed")
        steps[0].input_snapshot = original_step_input
        decide_plan_approval(db, plan_id=plan.id, actor_id=reviewer_id, actor_kind="human",
                             decision="approved", note="Reviewed")
        plan.plan_snapshot["tampered_after_approval"] = True
        with pytest.raises(OrchestrationError, match="snapshot was modified"):
            materialize_plan_tasks(db, plan_id=plan.id)
        del plan.plan_snapshot["tampered_after_approval"]
        steps[0].input_snapshot = {**original_step_input, "tampered_after_approval": True}
        with pytest.raises(OrchestrationError, match="differs from the approved plan snapshot"):
            materialize_plan_tasks(db, plan_id=plan.id)
        steps[0].input_snapshot = original_step_input
        tasks = materialize_plan_tasks(db, plan_id=plan.id)
        assert len(tasks) == 2
        assert plan.approval_status == "approved"
        assert plan.approved_by == reviewer_id
        assert plan.approval_decided_at is not None
        assert plan.plan_sha256 and len(plan.plan_sha256) == 64
        audit = db.scalar(select(AuditLog).where(AuditLog.object_id == plan.id,
                                                AuditLog.action == "ORCHESTRATION_PLAN_APPROVED"))
        assert audit is not None and audit.actor_kind == "human"


def test_orchestrator_rejects_ambiguous_or_missing_capability_matches():
    engine = make_db()
    with Session(engine) as db:
        project = seed_project(db)
        agent = Agent(code="AMBIGUOUS_AGENT", display_name="Ambiguous")
        skill = Skill(code="AMBIGUOUS_SKILL", display_name="Ambiguous Skill")
        db.add_all([agent, skill]); db.flush()
        av = AgentVersion(agent_id=agent.id, version_number=1, definition_snapshot={}, definition_sha256="5" * 64)
        sv1 = SkillVersion(skill_id=skill.id, version_number=1,
                           definition_snapshot={"capabilities": ["same_capability"]}, definition_sha256="6" * 64)
        sv2 = SkillVersion(skill_id=skill.id, version_number=2,
                           definition_snapshot={"capabilities": ["same_capability"]}, definition_sha256="7" * 64)
        db.add_all([av, sv1, sv2]); db.flush()
        db.add_all([AgentSkillBinding(agent_version_id=av.id, skill_version_id=sv1.id),
                    AgentSkillBinding(agent_version_id=av.id, skill_version_id=sv2.id)])
        db.flush()
        root = create_task(db, project_id=project.id, task_type="REQUEST", title="Request", input_snapshot={})
        strategy = lambda _request, _catalog: {"strategy_id": "test", "steps": [
            {"key": "one", "capability": "same_capability"}]}
        with pytest.raises(OrchestrationError, match="exactly one"):
            propose_plan_from_request(db, project_id=project.id, task_id=root.id,
                                      request={"goal": "test"}, planning_strategy=strategy)

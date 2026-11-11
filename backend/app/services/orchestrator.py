"""Provider-neutral deterministic orchestrator and exact-version skill execution."""
from __future__ import annotations
from collections import defaultdict, deque
import hashlib
import json
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FutureTimeout
from datetime import datetime, timezone
from typing import Callable
from uuid import UUID
from sqlalchemy import select
from sqlalchemy.orm import Session
from backend.app.models import Agent, AgentVersion, AgentSkillBinding, Skill, SkillVersion, AgentRun, SkillRun, Task, TaskDependency, OrchestrationPlan, OrchestrationPlanStep, ProjectMember, MemberRole, AuditLog
from backend.app.services.worker_registry import WorkerOwnershipLost
from .task_service import claim_next_task, complete_task, fail_task, acknowledge_task_cancel, create_task, add_task_dependency, TaskCancelled

SkillExecutor = Callable[[dict], dict]

class OrchestrationError(Exception): pass


def _canonical_plan_hash(snapshot: dict) -> str:
    payload = json.dumps(snapshot, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _assert_plan_rows_match_snapshot(db: Session, plan: OrchestrationPlan) -> list[OrchestrationPlanStep]:
    """Verify relational step rows still represent the exact approved snapshot."""
    snapshot = plan.plan_snapshot or {}
    expected_steps = snapshot.get("steps")
    expected_order = snapshot.get("step_order")
    if not isinstance(expected_steps, list) or not isinstance(expected_order, list):
        raise OrchestrationError("orchestration plan snapshot is missing its step definition")
    rows = db.scalars(select(OrchestrationPlanStep).where(
        OrchestrationPlanStep.plan_id == plan.id
    ).order_by(OrchestrationPlanStep.step_order).with_for_update()).all()
    expected_by_key = {item.get("key"): item for item in expected_steps if isinstance(item, dict)}
    if len(expected_by_key) != len(expected_steps) or len(rows) != len(expected_steps):
        raise OrchestrationError("orchestration plan relational steps do not match the approved snapshot")
    if [row.step_key for row in rows] != expected_order:
        raise OrchestrationError("orchestration plan step order was modified after proposal")
    for row in rows:
        expected = expected_by_key.get(row.step_key)
        if expected is None:
            raise OrchestrationError(f"unexpected persisted step {row.step_key}")
        expected_agent = expected.get("agent_version_id") if expected.get("step_kind") == "agent" else None
        expected_skill = expected.get("skill_version_id")
        actual_agent = str(row.agent_version_id) if row.agent_version_id else None
        actual_skill = str(row.skill_version_id) if row.skill_version_id else None
        expected_agent_from_input = expected.get("input", {}).get("_orchestration_agent_version_id")
        actual_agent_from_input = row.input_snapshot.get("_orchestration_agent_version_id")
        if (row.step_kind != expected.get("step_kind") or row.input_snapshot != expected.get("input")
                or row.depends_on_step_keys != expected.get("depends_on")
                or actual_agent != expected_agent or actual_skill != expected_skill
                or actual_agent_from_input != expected_agent_from_input):
            raise OrchestrationError(f"persisted step {row.step_key} differs from the approved plan snapshot")
    return rows


def topological_order(steps: list[dict]) -> list[str]:
    """Stable Kahn ordering; step keys and dependency keys must be unique/known."""
    by_key = {step.get("key"): step for step in steps}
    if None in by_key or len(by_key) != len(steps): raise OrchestrationError("plan step keys must be unique non-empty values")
    indegree = {key: 0 for key in by_key}; children: dict[str, list[str]] = defaultdict(list)
    for key, step in by_key.items():
        deps = step.get("depends_on", [])
        if not isinstance(deps, list) or any(dep not in by_key for dep in deps): raise OrchestrationError(f"unknown dependency in step {key}")
        for dep in deps: indegree[key] += 1; children[dep].append(key)
    ready = deque(key for key in by_key if indegree[key] == 0); result=[]
    while ready:
        key=ready.popleft(); result.append(key)
        for child in children[key]:
            indegree[child]-=1
            if indegree[child]==0: ready.append(child)
    if len(result) != len(steps): raise OrchestrationError("orchestration plan contains a dependency cycle")
    return result


def persist_plan(db: Session, *, project_id: UUID, task_id: UUID, steps: list[dict]) -> OrchestrationPlan:
    """Persist an immutable DAG definition before materializing its executable tasks.

    Each step references exactly one versioned capability in the relational columns.
    For skill steps, the paired agent version is retained in the immutable input snapshot
    because the AgentSkillBinding is the authoritative compatibility relation.
    """
    task = db.scalar(select(Task).where(Task.id == task_id, Task.project_id == project_id))
    if task is None:
        raise OrchestrationError("task not found in project")
    order = topological_order(steps)
    normalized = []
    for item in steps:
        key = item["key"]
        kind = item.get("step_kind", "skill")
        agent_version_id = item.get("agent_version_id")
        skill_version_id = item.get("skill_version_id")
        if kind == "skill":
            if not agent_version_id or not skill_version_id:
                raise OrchestrationError(f"skill step {key} requires agent_version_id and skill_version_id")
            binding = db.scalar(select(AgentSkillBinding).where(
                AgentSkillBinding.agent_version_id == agent_version_id,
                AgentSkillBinding.skill_version_id == skill_version_id,
            ))
            if binding is None:
                raise OrchestrationError(f"skill step {key} has no exact agent-skill version binding")
            stored_agent_version_id, stored_skill_version_id = None, skill_version_id
        elif kind == "agent":
            if not agent_version_id or skill_version_id:
                raise OrchestrationError(f"agent step {key} requires only agent_version_id")
            stored_agent_version_id, stored_skill_version_id = agent_version_id, None
        else:
            raise OrchestrationError(f"unsupported orchestration step_kind: {kind}")
        task_type = item.get("task_type", f"ORCH_{kind.upper()}")
        if not isinstance(task_type, str) or not task_type or len(task_type) > 64:
            raise OrchestrationError(f"invalid task_type in step {key}")
        if not isinstance(item.get("input", {}), dict):
            raise OrchestrationError(f"input for step {key} must be an object")
        input_snapshot = dict(item.get("input", {}))
        input_snapshot.update({
            "_orchestration_agent_version_id": str(agent_version_id) if agent_version_id else None,
            "_orchestration_skill_version_id": str(skill_version_id) if skill_version_id else None,
            "_orchestration_task_type": task_type,
        })
        normalized.append({
            "key": key, "step_kind": kind, "task_type": task_type,
            "agent_version_id": str(agent_version_id) if agent_version_id else None,
            "skill_version_id": str(skill_version_id) if skill_version_id else None,
            "depends_on": list(item.get("depends_on", [])), "input": input_snapshot,
        })
    snapshot = {"step_order": order, "steps": normalized, "provider_calls_enabled": False}
    plan = OrchestrationPlan(project_id=project_id, task_id=task_id, status="draft",
                             approval_status="pending", plan_sha256=_canonical_plan_hash(snapshot),
                             plan_snapshot=snapshot)
    db.add(plan)
    db.flush()
    by_key = {item["key"]: item for item in normalized}
    for index, key in enumerate(order, 1):
        item = by_key[key]
        db.add(OrchestrationPlanStep(
            plan_id=plan.id, step_order=index, step_key=key,
            agent_version_id=UUID(item["agent_version_id"]) if item["agent_version_id"] and item["step_kind"] == "agent" else None,
            skill_version_id=UUID(item["skill_version_id"]) if item["skill_version_id"] else None,
            step_kind=item["step_kind"], input_snapshot=item["input"],
            depends_on_step_keys=item["depends_on"], status="pending",
        ))
    db.flush()
    return plan



def decide_plan_approval(db: Session, *, plan_id: UUID, actor_id: UUID, actor_kind: str,
                         decision: str, note: str | None = None) -> OrchestrationPlan:
    """Human-only authorization for a versioned plan; agents may only propose it."""
    if actor_kind != "human":
        raise OrchestrationError("only a human principal may approve or reject an orchestration plan")
    if decision not in {"approved", "rejected"}:
        raise OrchestrationError("decision must be approved or rejected")
    plan = db.scalar(select(OrchestrationPlan).where(OrchestrationPlan.id == plan_id).with_for_update())
    if plan is None:
        raise OrchestrationError("orchestration plan not found")
    if plan.approval_status != "pending" or plan.status != "draft":
        raise OrchestrationError("only a pending draft plan can receive a decision")
    if not plan.plan_sha256 or _canonical_plan_hash(plan.plan_snapshot) != plan.plan_sha256:
        raise OrchestrationError("orchestration plan snapshot hash mismatch; refusing approval")
    _assert_plan_rows_match_snapshot(db, plan)
    member = db.scalar(select(ProjectMember).where(
        ProjectMember.project_id == plan.project_id,
        ProjectMember.principal_id == actor_id,
        ProjectMember.is_active.is_(True),
    ))
    if member is None or member.role not in {MemberRole.owner, MemberRole.producer, MemberRole.director}:
        raise OrchestrationError("active project owner, producer or director membership is required")
    plan.approval_status = decision
    plan.approved_by = actor_id if decision == "approved" else None
    plan.approval_decided_at = datetime.now(timezone.utc)
    plan.approval_note = note
    db.add(AuditLog(project_id=plan.project_id, actor_id=actor_id, actor_kind="human",
                    action=f"ORCHESTRATION_PLAN_{decision.upper()}", object_type="ORCHESTRATION_PLAN",
                    object_id=plan.id, details={"plan_sha256": plan.plan_sha256, "note": note}))
    db.flush()
    return plan


def active_skill_capability_catalog(db: Session) -> list[dict]:
    """Compatibility facade over the richer versioned specialist registry."""
    from backend.app.services.capability_registry import active_capability_catalog
    return active_capability_catalog(db)


def propose_plan_from_request(db: Session, *, project_id: UUID, task_id: UUID, request: dict,
                              planning_strategy: Callable[[dict, list[dict]], dict]) -> OrchestrationPlan:
    """Ask an injected Executive-Director strategy for a DAG, resolve exact capabilities,
    and persist a pending human-review proposal. The injected strategy may be
    deterministic or model-backed; this core deliberately does not select or call
    a model/provider itself. Provider routing and model invocation belong to the
    Executive Director Agent layer.

    Strategy contract: return {strategy_id: str, steps: [{key, capability, input?,
    depends_on?, task_type?}]}. A capability must resolve to exactly one active bound pair.
    """
    if not isinstance(request, dict) or not request:
        raise OrchestrationError("planning request must be a non-empty object")
    catalog = active_skill_capability_catalog(db)
    if not catalog:
        raise OrchestrationError("no active bound AgentVersion/SkillVersion capabilities are available")
    draft = planning_strategy(dict(request), catalog)
    if not isinstance(draft, dict) or not isinstance(draft.get("steps"), list) or not draft["steps"]:
        raise OrchestrationError("planning strategy must return a non-empty steps list")
    strategy_id = draft.get("strategy_id")
    if not isinstance(strategy_id, str) or not strategy_id.strip():
        raise OrchestrationError("planning strategy must identify its strategy_id")
    resolved = []
    for stage in draft["steps"]:
        if not isinstance(stage, dict):
            raise OrchestrationError("each planning stage must be an object")
        capability = stage.get("capability")
        if not isinstance(capability, str) or not capability.strip():
            raise OrchestrationError("each planning stage requires one capability")
        from backend.app.services.capability_registry import CapabilityQuery, CapabilityResolutionError, resolve_specialist
        try:
            match = resolve_specialist(catalog, CapabilityQuery(
                capability=capability,
                required_tags=stage.get("required_tags", ()),
                modality=stage.get("modality"), language=stage.get("language"),
                task_type=stage.get("task_type"),
                excluded_agent_codes=stage.get("excluded_agent_codes", ()),
            ))
        except CapabilityResolutionError as exc:
            raise OrchestrationError(str(exc)) from exc
        stage_input = stage.get("input", {})
        if not isinstance(stage_input, dict):
            raise OrchestrationError(f"input for planning stage {stage.get('key')} must be an object")
        resolved_stage = {
            "key": stage.get("key"), "step_kind": "skill",
            "agent_version_id": UUID(match["agent_version_id"]), "skill_version_id": UUID(match["skill_version_id"]),
            "depends_on": stage.get("depends_on", []), "input": dict(stage_input),
        }
        if stage.get("task_type") is not None:
            resolved_stage["task_type"] = stage["task_type"]
        resolved.append(resolved_stage)
    plan = persist_plan(db, project_id=project_id, task_id=task_id, steps=resolved)
    plan.plan_snapshot = {**plan.plan_snapshot,
        "proposal_metadata": {"strategy_id": strategy_id, "request": request,
                              "selected_capabilities": [{"step_key": step["key"], "capability": draft["steps"][i]["capability"],
                                  "agent_version_id": str(step["agent_version_id"]), "skill_version_id": str(step["skill_version_id"])}
                                  for i, step in enumerate(resolved)],
                              "human_approval_required": True}}
    plan.plan_sha256 = _canonical_plan_hash(plan.plan_snapshot)
    db.flush()
    return plan

def materialize_plan_tasks(db: Session, *, plan_id: UUID) -> list[Task]:
    """Create one durable task per DAG step and persist task-level dependency edges.

    The operation is idempotent: repeated calls reuse the same project-scoped task
    idempotency keys and repair missing dependency edges without duplicating them.
    """
    plan = db.scalar(select(OrchestrationPlan).where(OrchestrationPlan.id == plan_id).with_for_update())
    if plan is None:
        raise OrchestrationError("orchestration plan not found")
    if plan.approval_status != "approved" or not plan.approved_by or not plan.approval_decided_at:
        raise OrchestrationError("orchestration plan requires an explicit human approval before materialization")
    if not plan.plan_sha256 or _canonical_plan_hash(plan.plan_snapshot) != plan.plan_sha256:
        raise OrchestrationError("approved orchestration plan snapshot was modified; create a new plan version")
    steps = _assert_plan_rows_match_snapshot(db, plan)
    by_key = {step.step_key: step for step in steps if step.step_key}
    if len(by_key) != len(steps):
        raise OrchestrationError("plan contains legacy or duplicate step keys; create a new versioned plan")
    tasks_by_key: dict[str, Task] = {}
    for step in steps:
        if step.task_id:
            task = db.get(Task, step.task_id)
            if task is None:
                raise OrchestrationError(f"materialized task missing for step {step.step_key}")
        else:
            snapshot = dict(step.input_snapshot)
            task_type = snapshot.get("_orchestration_task_type", f"ORCH_{step.step_kind.upper()}")
            title = str(snapshot.get("title") or f"{step.step_kind.title()} step: {step.step_key}")[:240]
            task_input = {k: v for k, v in snapshot.items() if k != "title"}
            task_input.update({"orchestration_plan_id": str(plan.id), "orchestration_step_key": step.step_key})
            task = create_task(
                db, project_id=plan.project_id, task_type=task_type, title=title,
                input_snapshot=task_input, idempotency_key=f"orchestration:{plan.id}:{step.step_key}",
            )
            step.task_id = task.id
        tasks_by_key[step.step_key] = task
    for step in steps:
        task = tasks_by_key[step.step_key]
        for dependency_key in step.depends_on_step_keys or []:
            prerequisite_step = by_key.get(dependency_key)
            if prerequisite_step is None:
                raise OrchestrationError(f"unknown persisted dependency {dependency_key} in step {step.step_key}")
            prerequisite_task = tasks_by_key[dependency_key]
            edge = db.scalar(select(TaskDependency).where(
                TaskDependency.project_id == plan.project_id,
                TaskDependency.task_id == task.id,
                TaskDependency.depends_on_task_id == prerequisite_task.id,
            ))
            if edge is None:
                add_task_dependency(db, project_id=plan.project_id, task_id=task.id,
                                    depends_on_task_id=prerequisite_task.id)
    plan.status = "queued"
    db.flush()
    return [tasks_by_key[key] for key in [step.step_key for step in steps]]


def refresh_plan_status(db: Session, *, plan_id: UUID) -> OrchestrationPlan:
    """Reconcile persisted plan-step state from durable task state after restart."""
    plan = db.scalar(select(OrchestrationPlan).where(OrchestrationPlan.id == plan_id).with_for_update())
    if plan is None:
        raise OrchestrationError("orchestration plan not found")
    steps = db.scalars(select(OrchestrationPlanStep).where(
        OrchestrationPlanStep.plan_id == plan_id
    ).order_by(OrchestrationPlanStep.step_order).with_for_update()).all()
    statuses = []
    for step in steps:
        task = db.get(Task, step.task_id) if step.task_id else None
        if task is None:
            step.status = "pending"
            step.output_snapshot = None
            step.error_detail = None
            statuses.append("pending")
            continue
        mapped = {"queued": "pending", "retry_wait": "pending", "running": "running",
                  "succeeded": "succeeded", "failed": "failed", "cancelled": "cancelled"}.get(task.status)
        if mapped is None:
            raise OrchestrationError(f"unknown task status {task.status} for step {step.step_key}")
        step.status = mapped
        step.output_snapshot = task.output_snapshot
        step.error_detail = task.error_detail
        step.started_at = task.started_at
        step.finished_at = task.finished_at
        statuses.append(mapped)
    if statuses and all(value == "succeeded" for value in statuses):
        plan.status = "succeeded"
    elif "failed" in statuses:
        plan.status = "failed"
    elif statuses and all(value in {"succeeded", "cancelled"} for value in statuses) and "cancelled" in statuses:
        plan.status = "cancelled"
    elif "running" in statuses:
        plan.status = "running"
    elif "pending" in statuses:
        plan.status = "queued" if any(step.task_id for step in steps) else "draft"
    else:
        plan.status = "cancelled"
    db.flush()
    return plan


def execute_one_skill_task(db: Session, *, worker_id: str, agent_id: UUID, agent_version_id: UUID,
                           skill_version_id: UUID, executor: SkillExecutor, lease_seconds: int=300,
                           task_id: UUID | None = None, task_type: str | None = None,
                           heartbeat_callback: Callable[[UUID, str], None] | None = None,
                           heartbeat_interval_seconds: float | None = None) -> dict | None:
    """Claim one ready task, persist exact-version run lineage, then invoke a registered executor.

    No model/provider call is made here. The executor is an explicitly registered local capability.
    """
    if heartbeat_callback is not None:
        interval = heartbeat_interval_seconds if heartbeat_interval_seconds is not None else max(1.0, lease_seconds / 3)
        if interval <= 0 or interval >= lease_seconds:
            raise ValueError("heartbeat interval must be positive and shorter than the lease")
    else:
        interval = None
    claimed=claim_next_task(db,worker_id=worker_id,lease_seconds=lease_seconds,task_id=task_id,task_type=task_type)
    if claimed is None: return None
    task, lease_token=claimed
    agent_version=db.scalar(select(AgentVersion).where(AgentVersion.id==agent_version_id,AgentVersion.agent_id==agent_id))
    agent=db.get(Agent,agent_id); skill_version=db.get(SkillVersion,skill_version_id)
    skill=db.get(Skill,skill_version.skill_id) if skill_version else None
    binding=db.scalar(select(AgentSkillBinding).where(AgentSkillBinding.agent_version_id==agent_version_id,
                                                       AgentSkillBinding.skill_version_id==skill_version_id)) if agent_version and skill_version else None
    if not agent or agent.lifecycle_state!="active" or not agent_version or not skill or skill.lifecycle_state!="active" or not binding:
        fail_task(db,task_id=task.id,lease_token=lease_token,error_detail={"code":"REGISTRY_VERSION_UNAVAILABLE"},retryable=False)
        db.commit(); raise OrchestrationError("agent, agent version or skill version is unavailable")
    agent_run=AgentRun(project_id=task.project_id,task_id=task.id,agent_id=agent_id,agent_version_id=agent_version_id,
                       status="running",input_snapshot={"task_id":str(task.id),"task_input":task.input_snapshot,
                       "agent_version_sha256":agent_version.definition_sha256,"agent_definition":agent_version.definition_snapshot})
    db.add(agent_run); db.flush()
    skill_run=SkillRun(project_id=task.project_id,agent_run_id=agent_run.id,skill_id=skill.id,skill_version_id=skill_version_id,
                       status="running",input_snapshot={"skill_version_sha256":skill_version.definition_sha256,
                       "skill_definition":skill_version.definition_snapshot,"task_input":task.input_snapshot})
    db.add(skill_run); db.commit()
    try:
        executor_input={**dict(task.input_snapshot),"task_id":str(task.id),"project_id":str(task.project_id)}
        if heartbeat_callback is None:
            output=executor(executor_input)
        else:
            # Execute the capability separately while this worker thread renews its lease.
            # The executor receives an immutable task input snapshot and must make its own
            # external side effects idempotent using the task/run IDs.
            with ThreadPoolExecutor(max_workers=1, thread_name_prefix="afs-skill") as pool:
                future=pool.submit(executor, executor_input)
                while True:
                    try:
                        output=future.result(timeout=interval)
                        break
                    except FutureTimeout:
                        heartbeat_callback(task.id, lease_token)
        if not isinstance(output,dict): raise TypeError("skill executor must return a JSON object")
        if heartbeat_callback is not None:
            # SessionLocal uses expire_on_commit=False; refresh the lease renewed by the
            # heartbeat session before validating completion in this session.
            db.refresh(task, attribute_names=["lease_expires_at", "lease_token", "status", "cancel_requested"])
        if heartbeat_callback is not None:
            # Final ownership fence: a replaced worker generation must not commit stale output.
            heartbeat_callback(task.id, lease_token)
            db.refresh(task, attribute_names=["lease_expires_at", "lease_token", "status", "cancel_requested"])
        now=datetime.now(timezone.utc)
        task=complete_task(db,task_id=task.id,lease_token=lease_token,output_snapshot=output,now=now)
        skill_run.status="succeeded"; skill_run.output_snapshot=output; skill_run.finished_at=now
        agent_run.status="succeeded"; agent_run.output_snapshot={"skill_run_id":str(skill_run.id),"result":output}; agent_run.finished_at=now
        db.commit()
        return {"task_id":str(task.id),"agent_run_id":str(agent_run.id),"skill_run_id":str(skill_run.id),"status":"succeeded","output":output}
    except TaskCancelled as exc:
        if heartbeat_callback is not None:
            try:
                heartbeat_callback(task.id, lease_token)
            except WorkerOwnershipLost as fenced:
                db.rollback()
                skill_run.status="failed"; skill_run.output_snapshot={"code":"WORKER_GENERATION_FENCED","message":str(fenced)}; skill_run.finished_at=datetime.now(timezone.utc)
                agent_run.status="failed"; agent_run.error_detail={"skill_run_id":str(skill_run.id),"code":"WORKER_GENERATION_FENCED"}; agent_run.finished_at=datetime.now(timezone.utc)
                db.commit()
                raise
            db.refresh(task, attribute_names=["lease_expires_at", "lease_token", "status", "cancel_requested"])
        now=datetime.now(timezone.utc)
        acknowledge_task_cancel(db,task_id=task.id,lease_token=lease_token,now=now)
        skill_run.status="cancelled"; skill_run.output_snapshot={"cancelled":True,"message":str(exc)}; skill_run.finished_at=now
        agent_run.status="cancelled"; agent_run.error_detail={"skill_run_id":str(skill_run.id),"cancelled":True}; agent_run.finished_at=now
        db.commit()
        return {"task_id":str(task.id),"agent_run_id":str(agent_run.id),"skill_run_id":str(skill_run.id),"status":"cancelled"}
    except Exception as exc:
        now=datetime.now(timezone.utc)
        try:
            if heartbeat_callback is not None:
                # Do not let a fenced process mutate task state after losing ownership.
                heartbeat_callback(task.id, lease_token)
                db.refresh(task, attribute_names=["lease_expires_at", "lease_token", "status", "cancel_requested"])
            fail_task(db,task_id=task.id,lease_token=lease_token,error_detail={"code":"SKILL_EXECUTION_FAILED","type":type(exc).__name__,"message":str(exc)},now=now)
        except WorkerOwnershipLost as fenced:
            db.rollback()
            skill_run.status="failed"; skill_run.output_snapshot={"code":"WORKER_GENERATION_FENCED","message":str(fenced)}; skill_run.finished_at=datetime.now(timezone.utc)
            agent_run.status="failed"; agent_run.error_detail={"skill_run_id":str(skill_run.id),"code":"WORKER_GENERATION_FENCED"}; agent_run.finished_at=datetime.now(timezone.utc)
            db.commit()
            raise
        except Exception:
            db.rollback()
            if heartbeat_callback is not None:
                raise
        skill_run.status="failed"; skill_run.output_snapshot={"error_type":type(exc).__name__,"message":str(exc)}; skill_run.finished_at=now
        agent_run.status="failed"; agent_run.error_detail={"skill_run_id":str(skill_run.id),"type":type(exc).__name__}; agent_run.finished_at=now
        db.commit()
        raise

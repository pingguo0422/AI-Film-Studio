"""Read-only Executive Director decision brief builder.

The engine observes durable project state and emits evidence-backed proposals.
It never mutates tasks, plans, approvals, assets, or completed outputs.
"""
from __future__ import annotations

from collections import Counter, defaultdict
from datetime import datetime, timezone
import hashlib
import json
from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.app.models import (
    AgentEvaluation,
    AgentRun,
    OrchestrationPlan,
    Task,
    TaskDependency,
)


class DirectorDecisionError(ValueError):
    """Invalid input supplied to the decision brief builder."""


_SEVERITY_RANK = {"critical": 0, "high": 1, "medium": 2, "low": 3, "info": 4}


def _iso(value: datetime | None) -> str | None:
    if value is None:
        return None
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc).isoformat()


def _stable_digest(payload: dict[str, Any]) -> str:
    canonical = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def build_director_brief(
    db: Session,
    *,
    project_id: UUID,
    now: datetime | None = None,
    stale_after_seconds: int = 900,
    max_records: int = 500,
) -> dict[str, Any]:
    """Build a deterministic, read-only project control brief.

    `max_records` is a hard safety cap. If a project exceeds it, fail closed rather
    than silently making decisions from an incomplete view of project state.
    """
    if stale_after_seconds < 1:
        raise DirectorDecisionError("stale_after_seconds must be positive")
    if max_records < 1:
        raise DirectorDecisionError("max_records must be positive")
    now = now or datetime.now(timezone.utc)
    if now.tzinfo is None:
        now = now.replace(tzinfo=timezone.utc)
    now = now.astimezone(timezone.utc)

    tasks = db.scalars(
        select(Task).where(Task.project_id == project_id).order_by(Task.created_at, Task.id).limit(max_records + 1)
    ).all()
    plans = db.scalars(
        select(OrchestrationPlan).where(OrchestrationPlan.project_id == project_id)
        .order_by(OrchestrationPlan.created_at, OrchestrationPlan.id).limit(max_records + 1)
    ).all()
    evaluations = db.scalars(
        select(AgentEvaluation).where(AgentEvaluation.project_id == project_id)
        .order_by(AgentEvaluation.created_at, AgentEvaluation.id).limit(max_records + 1)
    ).all()
    runs = db.scalars(
        select(AgentRun).where(AgentRun.project_id == project_id)
        .order_by(AgentRun.created_at, AgentRun.id).limit(max_records + 1)
    ).all()
    if any(len(rows) > max_records for rows in (tasks, plans, evaluations, runs)):
        raise DirectorDecisionError("a project state collection exceeds max_records; request a scoped brief or raise the explicit cap")

    task_by_id = {task.id: task for task in tasks}
    edges = db.execute(
        select(TaskDependency.task_id, TaskDependency.depends_on_task_id)
        .where(TaskDependency.project_id == project_id)
        .order_by(TaskDependency.task_id, TaskDependency.depends_on_task_id)
        .limit(max_records + 1)
    ).all()
    if len(edges) > max_records:
        raise DirectorDecisionError("project dependency state exceeds max_records; request a scoped brief or raise the explicit cap")
    if sum(len(rows) for rows in (tasks, plans, evaluations, runs)) + len(edges) > max_records:
        raise DirectorDecisionError("total project decision snapshot exceeds max_records; request a scoped brief or raise the explicit cap")
    prerequisites: dict[UUID, list[UUID]] = defaultdict(list)
    dependents: dict[UUID, list[UUID]] = defaultdict(list)
    for child_id, parent_id in edges:
        if child_id in task_by_id and parent_id in task_by_id:
            prerequisites[child_id].append(parent_id)
            dependents[parent_id].append(child_id)

    recommendations: list[dict[str, Any]] = []
    evidence: list[dict[str, Any]] = []

    def propose(code: str, severity: str, title: str, rationale: str,
                refs: list[str], action: str, approval: str = "not_required") -> None:
        recommendations.append({
            "code": code, "severity": severity, "title": title,
            "rationale": rationale, "evidence_refs": sorted(set(refs)),
            "proposed_action": action, "approval_required": approval,
        })

    # Plan governance: pending approval is a human decision, never an Agent action.
    for plan in plans:
        if plan.approval_status == "pending":
            propose("PLAN_AWAITING_HUMAN_APPROVAL", "high", "制作计划等待人工审批",
                    "计划尚未获得有权限的人类审批，不应物化执行任务。",
                    [f"plan:{plan.id}", f"task:{plan.task_id}"],
                    "请项目负责人/制片人/导演审阅计划快照、能力版本与依赖关系后决定。",
                    "human_required")
        elif plan.approval_status == "rejected":
            propose("PLAN_REJECTED", "high", "制作计划已被拒绝",
                    "被拒绝的计划不能继续物化；如需调整，应形成新的计划提案。",
                    [f"plan:{plan.id}"], "由执行导演根据拒绝意见提出新版本计划。", "human_required")

    # Task readiness and execution health.
    active_runs_by_task: dict[UUID, list[AgentRun]] = defaultdict(list)
    for run in runs:
        if run.status in {"queued", "running", "retry_wait"}:
            active_runs_by_task[run.task_id].append(run)
    for task in tasks:
        refs = [f"task:{task.id}"]
        if task.status == "failed":
            propose("TASK_FAILED", "high", f"任务失败：{task.title}",
                    "任务已进入失败状态，需要检查错误详情、重试预算和上游输入。",
                    refs, "由执行导演判断修复输入、重新分派或提交人工升级。", "director_review")
        if task.status == "running" and task.updated_at is not None:
            updated = task.updated_at
            if updated.tzinfo is None:
                updated = updated.replace(tzinfo=timezone.utc)
            age_seconds = (now - updated.astimezone(timezone.utc)).total_seconds()
            if age_seconds > stale_after_seconds:
                propose("TASK_RUNNING_STALE", "high", f"任务长时间没有状态更新：{task.title}",
                        f"任务已连续 {int(age_seconds)} 秒没有更新，超过配置阈值 {stale_after_seconds} 秒。",
                        refs, "核查 Worker 心跳、模型调用超时与租约；必要时通过正式恢复流程处理。", "system_recovery")
        if task.status == "running" and task.lease_expires_at is not None:
            expiry = task.lease_expires_at
            if expiry.tzinfo is None:
                expiry = expiry.replace(tzinfo=timezone.utc)
            if expiry.astimezone(timezone.utc) < now:
                propose("TASK_LEASE_EXPIRED", "critical", f"执行租约已过期：{task.title}",
                        "任务仍标记为 running，但租约已过期；需要先由租约回收机制核实 Worker 所有权。",
                        refs, "运行 lease reaper 并检查 fencing token；不得直接由导演引擎接管任务。", "system_recovery")
        blocked_by = [parent for parent in prerequisites.get(task.id, [])
                      if task_by_id[parent].status != "succeeded"]
        if task.status in {"queued", "retry_wait"} and blocked_by:
            propose("TASK_BLOCKED_BY_DEPENDENCY", "medium", f"任务等待上游：{task.title}",
                    f"仍有 {len(blocked_by)} 个前置任务未成功完成。",
                    refs + [f"task:{parent}" for parent in blocked_by],
                    "保持等待；若上游失败或返工，重新评估本任务输入与依赖。")
        active_runs = active_runs_by_task.get(task.id, [])
        if len(active_runs) > 1:
            propose("MULTIPLE_ACTIVE_RUNS", "critical", f"同一任务存在多个活动 AgentRun：{task.title}",
                    "发现并行活动执行记录，可能造成重复产出或写入竞争。",
                    refs + [f"agent_run:{run.id}" for run in active_runs],
                    "暂停后续汇总，核查执行幂等键、Worker 租约与运行记录。", "director_review")

    # Quality findings are treated as durable specialist evidence.
    for evaluation in evaluations:
        if evaluation.decision == "escalate":
            propose("QUALITY_ESCALATION", "critical", "专业评审要求升级处理",
                    f"评审得分 {evaluation.score:.3f}，需要人工判断风险与下一步制作策略。",
                    [f"evaluation:{evaluation.id}", f"task:{evaluation.task_id}"],
                    "提交导演/制片人处理；不得自动降低质量门槛或绕过评审。", "human_required")
        elif evaluation.decision == "rework":
            rework = task_by_id.get(evaluation.rework_task_id) if evaluation.rework_task_id else None
            propose("QUALITY_REWORK", "high", "专业评审要求返工",
                    f"评审得分 {evaluation.score:.3f}，有 {len(evaluation.required_changes)} 项明确修改要求。",
                    [f"evaluation:{evaluation.id}", f"task:{evaluation.task_id}"] + ([f"task:{rework.id}"] if rework else []),
                    "将评审要求交回原责任 Agent；返工完成后重新评审，再恢复受影响的下游工作。")

    # Readiness conflicts: a downstream task can be marked running while prerequisites are not done.
    for task in tasks:
        if task.status == "running":
            unfinished = [parent for parent in prerequisites.get(task.id, [])
                          if task_by_id[parent].status != "succeeded"]
            if unfinished:
                propose("RUNNING_WITH_UNSATISFIED_DEPENDENCY", "critical", f"任务在上游未完成时已启动：{task.title}",
                        "执行状态与 DAG 依赖约束不一致，可能是人工状态修改或调度器绕过依赖门禁。",
                        [f"task:{task.id}"] + [f"task:{parent}" for parent in unfinished],
                        "暂停结果合并并审计任务领取路径；修复调度约束后再继续。", "director_review")

    counts = Counter(task.status for task in tasks)
    recommendations.sort(key=lambda item: (_SEVERITY_RANK[item["severity"]], item["code"], item["evidence_refs"]))
    state_digest_payload = {
        "project_id": str(project_id),
        "tasks": [{"id": str(t.id), "title": t.title, "status": t.status, "updated_at": _iso(t.updated_at),
                   "lease_expires_at": _iso(t.lease_expires_at)} for t in tasks],
        "plans": [{"id": str(p.id), "task_id": str(p.task_id), "status": p.status,
                   "approval_status": p.approval_status, "sha256": p.plan_sha256} for p in plans],
        "evaluations": [{"id": str(e.id), "decision": e.decision, "score": e.score,
                         "rework_round": e.rework_round, "findings": e.findings,
                         "required_changes": e.required_changes,
                         "rework_task_id": str(e.rework_task_id) if e.rework_task_id else None} for e in evaluations],
        "agent_runs": [{"id": str(r.id), "task_id": str(r.task_id), "agent_id": str(r.agent_id),
                        "agent_version_id": str(r.agent_version_id), "status": r.status} for r in runs],
        "edges": sorted((str(child), str(parent)) for child, parent in edges),
    }
    state_digest = _stable_digest(state_digest_payload)
    brief = {
        "schema_version": "1.0",
        "engine": "afs-executive-director-deterministic-v1",
        "mode": "read_only_proposal",
        "project_id": str(project_id),
        "generated_at": _iso(now),
        "state_digest": state_digest,
        "summary": {
            "task_total": len(tasks), "task_status_counts": dict(sorted(counts.items())),
            "plan_total": len(plans), "evaluation_total": len(evaluations),
            "recommendation_total": len(recommendations),
            "critical_count": sum(1 for item in recommendations if item["severity"] == "critical"),
            "human_decision_required": any(item["approval_required"] == "human_required" for item in recommendations),
        },
        "recommendations": recommendations,
        "governance": {
            "mutated_project_state": False,
            "agent_can_approve_plan": False,
            "agent_can_lock_asset": False,
            "completed_outputs_are_immutable": True,
        },
    }
    brief["brief_sha256"] = _stable_digest(brief)
    return brief

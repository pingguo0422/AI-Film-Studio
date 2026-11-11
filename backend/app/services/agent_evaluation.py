"""Deterministic quality gates and durable specialist rework requests."""
from __future__ import annotations
from dataclasses import dataclass
from uuid import UUID
import math
from sqlalchemy import select
from sqlalchemy.orm import Session
from backend.app.models import Agent, AgentEvaluation, AgentRun, AgentVersion, Task, TaskDependency, RunEvent
from backend.app.services.task_service import create_task, add_task_dependency


class EvaluationError(ValueError):
    pass


@dataclass(frozen=True)
class EvaluationPolicy:
    acceptance_threshold: float = 0.8
    criterion_minimum: float = 0.5
    max_rework_rounds: int = 2

    def __post_init__(self):
        if not 0 <= self.acceptance_threshold <= 1 or not 0 <= self.criterion_minimum <= 1:
            raise ValueError("evaluation thresholds must be between 0 and 1")
        if not 0 <= self.max_rework_rounds <= 10:
            raise ValueError("max_rework_rounds must be between 0 and 10")


def evaluate_agent_output(db: Session, *, agent_run_id: UUID, reviewer_agent_version_id: UUID,
                          criteria: list[dict], idempotency_key: str,
                          policy: EvaluationPolicy = EvaluationPolicy(),
                          rework_round: int | None = None) -> AgentEvaluation:
    if not criteria or not isinstance(criteria, list):
        raise EvaluationError("at least one evaluation criterion is required")
    if not isinstance(idempotency_key, str) or not idempotency_key.strip() or len(idempotency_key) > 160:
        raise EvaluationError("idempotency_key must contain 1..160 characters")
    run = db.scalar(select(AgentRun).where(AgentRun.id == agent_run_id).with_for_update())
    if run is None or run.status != "succeeded" or not isinstance(run.output_snapshot, dict):
        raise EvaluationError("only a succeeded AgentRun with an object output can be evaluated")
    reviewer = db.get(AgentVersion, reviewer_agent_version_id)
    if reviewer is None:
        raise EvaluationError("reviewer AgentVersion does not exist")
    reviewer_agent = db.get(Agent, reviewer.agent_id)
    if reviewer_agent is None or reviewer_agent.lifecycle_state != "active":
        raise EvaluationError("reviewer Agent is missing or inactive")
    if reviewer.agent_id == run.agent_id:
        raise EvaluationError("independent review requires a different Agent identity")
    normalized = []
    criterion_names = set()
    weighted_score = 0.0
    total_weight = 0.0
    blockers = []
    findings = []
    required_changes = []
    for index, criterion in enumerate(criteria):
        if not isinstance(criterion, dict):
            raise EvaluationError(f"criterion {index} must be an object")
        name = str(criterion.get("name", "")).strip()
        score = criterion.get("score")
        weight = criterion.get("weight", 1.0)
        blocking_value = criterion.get("blocking", False)
        if not isinstance(blocking_value, bool):
            raise EvaluationError(f"criterion {index} blocking must be a boolean")
        blocking = blocking_value
        if not name or name in criterion_names or isinstance(score, bool) or not isinstance(score, (int, float)) or not 0 <= score <= 1:
            raise EvaluationError(f"criterion {index} requires a unique name and score between 0 and 1")
        criterion_names.add(name)
        if isinstance(weight, bool) or not isinstance(weight, (int, float)) or not math.isfinite(float(weight)) or weight <= 0:
            raise EvaluationError(f"criterion {index} weight must be a finite positive number")
        score, weight = float(score), float(weight)
        note = str(criterion.get("finding", "")).strip()
        change = str(criterion.get("required_change", "")).strip()
        normalized.append({"name": name, "score": score, "weight": weight,
                           "blocking": blocking, "finding": note, "required_change": change})
        weighted_score += score * weight
        total_weight += weight
        if note:
            findings.append({"criterion": name, "detail": note})
        if blocking and score < policy.criterion_minimum:
            blockers.append(name)
        if score < policy.acceptance_threshold:
            instruction = change or note or f"Improve '{name}' to meet the acceptance threshold"
            required_changes.append({"criterion": name, "instruction": instruction})
    final_score = round(weighted_score / total_weight, 6)
    if rework_round is None:
        source_task = db.get(Task, run.task_id)
        rework_round = int((source_task.input_snapshot or {}).get("rework_round", 0))
    if isinstance(rework_round, bool) or not isinstance(rework_round, int) or rework_round < 0:
        raise EvaluationError("rework_round must be a non-negative integer")
    if final_score >= policy.acceptance_threshold and not blockers and not required_changes:
        decision = "accepted"
    elif rework_round < policy.max_rework_rounds:
        decision = "rework"
    else:
        decision = "escalate"
    rubric_snapshot = {
        "policy": {"acceptance_threshold": policy.acceptance_threshold,
                   "criterion_minimum": policy.criterion_minimum,
                   "max_rework_rounds": policy.max_rework_rounds},
        "criteria": normalized,
    }
    existing = db.scalar(select(AgentEvaluation).where(
        AgentEvaluation.project_id == run.project_id,
        AgentEvaluation.idempotency_key == idempotency_key,
    ))
    if existing:
        if (existing.agent_run_id != run.id or existing.reviewer_agent_version_id != reviewer_agent_version_id
                or existing.rubric_snapshot != rubric_snapshot or existing.decision != decision
                or existing.score != final_score or existing.rework_round != rework_round):
            raise EvaluationError("evaluation idempotency key was reused with different evaluation content")
        return existing
    row = AgentEvaluation(
        project_id=run.project_id, task_id=run.task_id, agent_run_id=run.id,
        reviewer_agent_version_id=reviewer_agent_version_id, decision=decision,
        score=final_score, rework_round=rework_round, rubric_snapshot=rubric_snapshot,
        findings=findings, required_changes=required_changes,
        idempotency_key=idempotency_key,
    )
    db.add(row)
    db.flush()
    db.add(RunEvent(project_id=run.project_id, agent_run_id=run.id,
                    event_type="quality.evaluated", payload={
                        "evaluation_id": str(row.id), "reviewer_agent_version_id": str(reviewer_agent_version_id),
                        "decision": decision, "score": final_score, "rework_round": rework_round,
                    }))
    db.flush()
    return row


def request_rework(db: Session, *, evaluation_id: UUID, task_type: str | None = None) -> Task:
    evaluation = db.scalar(select(AgentEvaluation).where(
        AgentEvaluation.id == evaluation_id
    ).with_for_update())
    if evaluation is None:
        raise EvaluationError("evaluation not found")
    if evaluation.decision != "rework" or not evaluation.required_changes:
        raise EvaluationError("only a rework decision with required changes can create a rework task")
    if evaluation.rework_task_id:
        existing = db.get(Task, evaluation.rework_task_id)
        if existing is None:
            raise EvaluationError("recorded rework task is missing")
        return existing
    source = db.get(Task, evaluation.task_id)
    if source is None or source.status != "succeeded":
        raise EvaluationError("source task must have succeeded before rework is requested")
    if task_type is not None and (not isinstance(task_type, str) or not task_type.strip() or len(task_type) > 64):
        raise EvaluationError("task_type must contain 1..64 characters")
    run = db.get(AgentRun, evaluation.agent_run_id)
    # Compute the transitive downstream impact before creating the replacement task.
    edges = db.execute(select(TaskDependency.task_id, TaskDependency.depends_on_task_id).where(
        TaskDependency.project_id == evaluation.project_id)).all()
    dependents: dict[UUID, list[UUID]] = {}
    for dependent_id, prerequisite_id in edges:
        dependents.setdefault(prerequisite_id, []).append(dependent_id)
    impacted_ids: set[UUID] = set()
    frontier = list(dependents.get(source.id, []))
    while frontier:
        candidate = frontier.pop()
        if candidate == source.id or candidate in impacted_ids:
            continue
        impacted_ids.add(candidate)
        frontier.extend(dependents.get(candidate, []))
    impacted_tasks = [db.get(Task, task_id) for task_id in impacted_ids]
    impact_summary = [{"task_id": str(item.id), "status": item.status} for item in impacted_tasks if item is not None]
    rework_input = {
        "downstream_impact": impact_summary,
        "rework_of_task_id": str(source.id),
        "rework_round": evaluation.rework_round + 1,
        "source_agent_run_id": str(run.id),
        "evaluation_id": str(evaluation.id),
        "evaluation_score": evaluation.score,
        "required_changes": evaluation.required_changes,
        "original_input": dict(source.input_snapshot),
        "previous_output": dict(run.output_snapshot or {}),
    }
    task = create_task(
        db, project_id=evaluation.project_id,
        task_type=task_type or source.task_type,
        title=f"Rework: {source.title}"[:240], input_snapshot=rework_input,
        priority=min(source.priority + 10, 100), max_attempts=source.max_attempts,
        idempotency_key=f"evaluation-rework:{evaluation.id}",
    )
    add_task_dependency(db, project_id=evaluation.project_id,
                        task_id=task.id, depends_on_task_id=source.id)
    # Pending downstream work is held behind the rework result. Running/completed
    # work is not silently mutated; it remains explicitly listed for human replanning.
    gated_downstream = []
    for impacted in impacted_tasks:
        if impacted is not None and impacted.status in {"queued", "retry_wait"}:
            add_task_dependency(db, project_id=evaluation.project_id,
                                task_id=impacted.id, depends_on_task_id=task.id)
            gated_downstream.append(str(impacted.id))
    evaluation.rework_task_id = task.id
    db.add(RunEvent(project_id=evaluation.project_id, agent_run_id=run.id,
                    event_type="quality.rework_requested", payload={
                        "evaluation_id": str(evaluation.id), "rework_task_id": str(task.id),
                        "required_changes": evaluation.required_changes,
                        "downstream_impact": impact_summary,
                        "gated_downstream_task_ids": gated_downstream,
                    }))
    db.flush()
    return task


def evaluate_and_route_output(db: Session, *, agent_run_id: UUID, reviewer_agent_version_id: UUID,
                              criteria: list[dict], idempotency_key: str,
                              policy: EvaluationPolicy = EvaluationPolicy()) -> dict:
    """Evaluate an Agent output, notify its author Agent, and materialize rework when required."""
    evaluation = evaluate_agent_output(
        db, agent_run_id=agent_run_id,
        reviewer_agent_version_id=reviewer_agent_version_id,
        criteria=criteria, idempotency_key=idempotency_key, policy=policy,
    )
    run = db.get(AgentRun, agent_run_id)
    reviewer = db.get(AgentVersion, reviewer_agent_version_id)
    from backend.app.services.agent_collaboration import send_agent_message
    message, _created = send_agent_message(
        db, project_id=evaluation.project_id,
        from_agent_id=reviewer.agent_id, to_agent_id=run.agent_id,
        task_id=run.task_id, message_type=f"quality.{evaluation.decision}",
        payload={
            "evaluation_id": str(evaluation.id), "decision": evaluation.decision,
            "score": evaluation.score, "findings": evaluation.findings,
            "required_changes": evaluation.required_changes,
            "reviewer_agent_version_id": str(reviewer_agent_version_id),
        },
        idempotency_key=f"evaluation-feedback:{evaluation.id}",
        correlation_id=run.id,
    )
    rework_task = request_rework(db, evaluation_id=evaluation.id) if evaluation.decision == "rework" else None
    return {"evaluation": evaluation, "message": message, "rework_task": rework_task}

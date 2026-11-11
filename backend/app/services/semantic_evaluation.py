"""Model-backed semantic evaluation, normalized into the existing durable rubric."""
from __future__ import annotations
from typing import Any
from uuid import UUID
from sqlalchemy.orm import Session
from backend.app.runtime.model_adapters import ModelAdapterRegistry, ModelRequest, ModelAdapterError, ModelOutputError
from backend.app.services.agent_evaluation import EvaluationPolicy, evaluate_and_route_output, EvaluationError

class SemanticEvaluationError(ValueError): pass

_REQUIRED_TOP = {"criteria"}
_REQUIRED_CRITERION = {"name", "score", "weight", "blocking", "finding", "required_change"}

def validate_semantic_rubric(output: dict[str, Any]) -> list[dict[str, Any]]:
    if not isinstance(output, dict) or set(output) != _REQUIRED_TOP:
        raise SemanticEvaluationError("semantic evaluator output must contain only 'criteria'")
    criteria = output["criteria"]
    if not isinstance(criteria, list) or not criteria:
        raise SemanticEvaluationError("semantic evaluator must return a non-empty criteria list")
    normalized = []
    for i, item in enumerate(criteria):
        if not isinstance(item, dict) or not _REQUIRED_CRITERION.issubset(item):
            raise SemanticEvaluationError(f"criterion {i} is missing required fields")
        if not isinstance(item["name"], str) or not item["name"].strip(): raise SemanticEvaluationError(f"criterion {i} name is invalid")
        score, weight = item["score"], item["weight"]
        if isinstance(score, bool) or not isinstance(score, (int, float)) or not 0 <= score <= 1: raise SemanticEvaluationError(f"criterion {i} score must be between 0 and 1")
        if isinstance(weight, bool) or not isinstance(weight, (int, float)) or weight <= 0: raise SemanticEvaluationError(f"criterion {i} weight must be positive")
        if not isinstance(item["blocking"], bool): raise SemanticEvaluationError(f"criterion {i} blocking must be boolean")
        if not isinstance(item["finding"], str) or not isinstance(item["required_change"], str): raise SemanticEvaluationError(f"criterion {i} findings must be strings")
        normalized.append({k: item[k] for k in _REQUIRED_CRITERION})
    return normalized

def evaluate_with_model(db: Session, *, registry: ModelAdapterRegistry, provider_key: str,
                        model_key: str, agent_run_id: UUID, reviewer_agent_version_id: UUID,
                        context: dict[str, Any], idempotency_key: str,
                        policy: EvaluationPolicy = EvaluationPolicy()) -> dict:
    request = ModelRequest(purpose="independent_quality_review", model_key=model_key,
        input={"review_context": context, "output_schema": {"criteria": [{"name": "string", "score": "0..1", "weight": "positive number", "blocking": "boolean", "finding": "string", "required_change": "string"}] }},
        correlation_id=str(agent_run_id))
    try:
        response = registry.generate(provider_key, request)
        criteria = validate_semantic_rubric(response.output)
    except (ModelAdapterError, SemanticEvaluationError) as exc:
        raise SemanticEvaluationError(str(exc)) from exc
    try:
        result = evaluate_and_route_output(db, agent_run_id=agent_run_id,
            reviewer_agent_version_id=reviewer_agent_version_id, criteria=criteria,
            idempotency_key=idempotency_key, policy=policy)
    except EvaluationError:
        raise
    result["model_provenance"] = {"provider_key": response.provider_key, "model_key": response.model_key,
        "request_id": response.request_id, "mode": response.metadata.get("mode", "unspecified"), "usage": response.usage}
    return result

# Executive Director Agent — Foundation 1.5 dev.5

## Purpose

dev.5 adds the first model-backed planning adapter for the AFS Executive Director. A natural-language production objective can be sent to an explicitly selected provider/model adapter. The model proposes a small, structured DAG; the existing capability registry and orchestrator validate and persist it as a pending human-review plan.

This is a planning vertical slice, not an autonomous production director and not a production-ready agent endpoint.

## Flow

1. The caller creates a root `PRODUCTION_OBJECTIVE` task in the target project.
2. The caller explicitly selects `provider_key`, `model_key`, and a registered `ModelAdapter`.
3. `plan_production_request()` validates the request and bounds its serialized size.
4. The service loads the active exact AgentVersion/SkillVersion capability catalog.
5. The model receives the production objective, catalog and a strict output contract.
6. The model returns `strategy_id` and a list of steps. Local validation rejects extra fields, malformed identifiers, invalid task types, duplicate keys, invalid dependencies, reserved runtime fields, oversized inputs and malformed JSON values.
7. The existing orchestrator resolves each capability to exactly one active AgentVersion/SkillVersion binding and validates the DAG (including cycle detection).
8. A pending, immutable-by-digest orchestration plan is persisted with provider/model/request/catalog/output provenance.
9. A human producer/director/owner must approve or reject the plan using the existing approval service.
10. Only a separately invoked `materialize_plan_tasks()` call after approval creates step tasks. dev.5 does not call it.

## Safety boundaries

- Provider and model are explicit; there is no default provider or implicit credential lookup in this service.
- Model output is untrusted. It is validated locally and cannot inject internal orchestration IDs.
- Capability selection is not free-form: it must resolve to exactly one active bound specialist.
- The plan is persisted as `draft` with `approval_status=pending`.
- No Agent Worker is started and no DAG step task is materialized.
- No human approval is inferred from model output.
- No action is executed by the Executive Director service.
- The service is not exposed as an HTTP endpoint because API AuthN/AuthZ and project RBAC/RLS are not yet complete.
- Tests use `FakeModelAdapter`; no live provider call is claimed.

## Limits

- Maximum 32 planning steps.
- Maximum 24,000 bytes for the production request.
- Maximum 8,000 bytes per step input.
- Maximum 200 active capability catalog entries and 160,000 bytes of complete planning context.
- Each step must declare one capability and a task type.
- The current planning strategy is single-pass. Multi-Agent negotiation, iterative replanning and semantic quality review are not implemented.

## Example

```python
from backend.app.runtime.model_adapters import ModelAdapterRegistry, OpenAICompatibleAdapter
from backend.app.services.executive_director_agent import plan_production_request

registry = ModelAdapterRegistry()
registry.register(OpenAICompatibleAdapter(model_key="your-explicit-model-key"))

plan = plan_production_request(
    db,
    project_id=project.id,
    task_id=root_task.id,
    request={
        "objective": "Develop the screenplay and visual development plan for a 1909 historical drama",
        "language": "zh",
        "deliverables": ["script_analysis", "visual_bible", "shot_plan"],
    },
    provider_key="openai_compatible",
    model_key="your-explicit-model-key",
    adapters=registry,
    correlation_id="project-request-001",
)
# The result is pending human review. Do not materialize before human approval.
```

The example does not contain credentials and does not execute a network call unless `plan_production_request()` is invoked with a configured adapter.

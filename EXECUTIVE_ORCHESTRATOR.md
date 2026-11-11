# Executive Director Orchestrator — Foundation 1.4 dev.5

## Responsibility split

- **Executive Director Agent:** understands the production objective, decomposes it into professional stages, chooses capability keys and dependencies, and proposes a plan.
- **Capability registry:** supplies active Agents, immutable AgentVersions, Skills, immutable SkillVersions and exact AgentSkillBinding relationships.
- **Orchestrator service:** validates the DAG, resolves capability keys to one exact bound pair, persists the proposal and materializes tasks only after approval.
- **Human producer/director/owner:** reviews and approves or rejects the immutable plan snapshot.
- **Worker runtime:** executes tasks using explicit registered executors; each run records exact AgentVersion and SkillVersion lineage.
- **Model adapters:** optional tools invoked by an Agent strategy or Skill executor; this foundation does not bind the architecture to a provider.

## Planning strategy contract

The host injects a callable:

```python
def planning_strategy(request: dict, capability_catalog: list[dict]) -> dict:
    return {
        "strategy_id": "executive-director-v1",
        "steps": [
            {
                "key": "script_analysis",
                "capability": "script_analysis",
                "task_type": "SCRIPT_ANALYSIS",
                "input": {"scene_id": "..."},
                "depends_on": [],
            },
            {
                "key": "visual_bible",
                "capability": "visual_bible",
                "task_type": "VISUAL_BIBLE",
                "input": {"scene_id": "..."},
                "depends_on": ["script_analysis"],
            },
        ],
    }
```

The `capability` value must appear in exactly one active SkillVersion definition's `capabilities` list among the exact AgentSkillBinding catalog entries. Ambiguity and missing matches are hard errors. A future model-backed Executive Director can implement this callable without changing persistence, approval, task materialization or Worker contracts.

## Lifecycle

1. Create the root task representing the requested production objective.
2. Call `propose_plan_from_request(...)`. The result is a persisted draft with `approval_status=pending` and a canonical snapshot digest.
3. Present the proposal, selected specialist versions, dependencies and digest to the human reviewer.
4. Call `decide_plan_approval(..., actor_kind="human", decision="approved"|"rejected")` using the authenticated project member ID. Only active owner, producer or director members can decide.
5. On approval, call `materialize_plan_tasks(...)`. The service verifies the approval state and digest before creating idempotent tasks and dependency edges.
6. Workers execute each step using explicit task-type registrations and exact Agent/Skill version bindings.
7. Call `refresh_plan_status(...)` after execution/restart to reconcile plan state from durable tasks.

## Governance guarantees and boundaries

- Agents can propose; they cannot approve.
- No tasks are materialized from pending or rejected plans.
- The approved plan snapshot is digest-checked at materialization; edits require a new proposal.
- Exact AgentVersion/SkillVersion bindings are persisted; no dynamic code execution is derived from planner output.
- The planner callable is injected. This release includes deterministic tests, not an LLM provider or semantic planner.
- Authentication, authorization at the API boundary, and production audit access controls remain future deployment work.

## Foundation 1.5 — specialist profiles, collaboration and quality loop

AgentVersion `definition_snapshot.profile` may declare:

```json
{
  "specialties": ["screenwriting"],
  "tags": ["dramaturgy", "continuity"],
  "modalities": ["text"],
  "languages": ["zh"],
  "task_types": ["SCRIPT_ANALYSIS"],
  "quality_rubric": {"logic": 0.4, "character": 0.3, "continuity": 0.3}
}
```

SkillVersion `definition_snapshot.capabilities` remains the capability key set. The registry joins Agent, exact AgentVersion, exact SkillVersion and AgentSkillBinding. A planning stage may request `required_tags`, `modality`, `language`, `task_type` and `excluded_agent_codes`. It must still resolve to one exact bound specialist; ambiguity fails closed.

`send_agent_message()` persists handoff messages with a project-scoped idempotency key. The same key and same content returns the original message; a different payload under the same key is rejected.

`evaluate_agent_output()` records a weighted rubric snapshot and requires a reviewer Agent identity distinct from the author Agent. Deterministic decisions are `accepted`, `rework` or `escalate`. A `rework` decision can be converted to one idempotent task with explicit required changes, the previous input/output and a dependency edge on the completed source task. The task carries the next `rework_round` so the policy can bound repeated revision cycles.

The 1.5 `ModelAdapter` protocol and registry define a replaceable provider boundary. Adapters are injected explicitly by `(provider_key, model_key)`; there is no implicit default, provider SDK or credential lookup in the core. The current evaluator uses deterministic rubric rules, not a model call. Human approval of orchestration plans remains a separate mandatory gate; a quality `accepted` result does not approve or lock a project artifact.

`evaluate_and_route_output()` is the feedback-loop entry point: it records the independent review, sends a durable `quality.accepted`, `quality.rework` or `quality.escalate` message to the author Agent, and creates the dependent rework task for a `rework` decision. Repeated calls with the same evaluation key converge on the same evaluation, message and rework task. A quality pass is not a human approval or asset lock.

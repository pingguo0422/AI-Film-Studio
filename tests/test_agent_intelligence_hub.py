from datetime import datetime, timezone
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool
import pytest

from backend.app.db.base import Base
from backend.app.db.ids import uuid7
from backend.app.models import (
    Project, Agent, AgentVersion, Skill, SkillVersion, AgentSkillBinding,
    AgentRun, Task, TaskDependency, AgentEvaluation, AgentMessage,
)
from backend.app.services.task_service import create_task, complete_task, add_task_dependency
from backend.app.services.capability_registry import (
    CapabilityQuery, CapabilityResolutionError, active_capability_catalog, resolve_specialist,
)
from backend.app.services.agent_collaboration import send_agent_message, AgentMessageConflict
from backend.app.services.agent_evaluation import (
    EvaluationPolicy, EvaluationError, evaluate_agent_output, evaluate_and_route_output, request_rework,
)
from backend.app.runtime.model_adapters import (
    ModelAdapterRegistry, ModelRequest, ModelResponse, ModelUnavailableError,
)


@pytest.fixture
def factory():
    engine = create_engine("sqlite+pysqlite:///:memory:", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    yield sessionmaker(engine, expire_on_commit=False, class_=Session)
    engine.dispose()


def seed_agents(db):
    project = Project(code=f"HUB_{uuid7().hex[:8]}", name="Intelligence Hub")
    author = Agent(code=f"AUTHOR_{uuid7().hex[:8]}", display_name="Script Director")
    reviewer = Agent(code=f"REVIEW_{uuid7().hex[:8]}", display_name="Story Editor")
    skill = Skill(code=f"SKILL_{uuid7().hex[:8]}", display_name="Script Analysis")
    db.add_all([project, author, reviewer, skill]); db.flush()
    av = AgentVersion(agent_id=author.id, version_number=1,
        definition_snapshot={"profile": {"specialties": ["screenwriting"], "tags": ["dramaturgy"], "languages": ["zh"], "modalities": ["text"], "task_types": ["SCRIPT_ANALYSIS"]}},
        definition_sha256="a" * 64)
    rv = AgentVersion(agent_id=reviewer.id, version_number=1,
        definition_snapshot={"profile": {"specialties": ["quality_review"]}}, definition_sha256="b" * 64)
    sv = SkillVersion(skill_id=skill.id, version_number=1,
        definition_snapshot={"capabilities": ["script_logic_review"]}, definition_sha256="c" * 64)
    db.add_all([av, rv, sv]); db.flush()
    db.add(AgentSkillBinding(agent_version_id=av.id, skill_version_id=sv.id)); db.flush()
    return project, author, reviewer, av, rv, skill, sv


def seed_succeeded_run(db):
    project, author, reviewer, av, rv, skill, sv = seed_agents(db)
    task = create_task(db, project_id=project.id, task_type="SCRIPT_ANALYSIS", title="Analyze scene",
                       input_snapshot={"scene": "8.1", "rework_round": 0})
    task.status = "succeeded"
    task.output_snapshot = {"analysis": "Draft analysis"}
    task.finished_at = datetime.now(timezone.utc)
    run = AgentRun(project_id=project.id, task_id=task.id, agent_id=author.id,
                   agent_version_id=av.id, status="succeeded",
                   input_snapshot={"task_input": task.input_snapshot},
                   output_snapshot={"analysis": "Draft analysis"},
                   started_at=datetime.now(timezone.utc), finished_at=datetime.now(timezone.utc))
    db.add(run); db.flush()
    return project, author, reviewer, av, rv, task, run


def test_capability_registry_filters_profile_constraints_and_rejects_ambiguity(factory):
    with factory() as db:
        _project, _author, _reviewer, _av, _rv, _skill, _sv = seed_agents(db)
        catalog = active_capability_catalog(db)
        result = resolve_specialist(catalog, CapabilityQuery(
            capability="script_logic_review", required_tags=("dramaturgy",),
            modality="text", language="zh", task_type="SCRIPT_ANALYSIS"))
        assert result["agent_code"].startswith("AUTHOR_")
        with pytest.raises(CapabilityResolutionError, match="no active specialist"):
            resolve_specialist(catalog, CapabilityQuery(capability="script_logic_review", modality="video"))
        duplicate = dict(catalog[0], agent_version_id=str(uuid7()), skill_version_id=str(uuid7()), agent_code="SECOND")
        with pytest.raises(CapabilityResolutionError, match="ambiguous"):
            resolve_specialist(catalog + [duplicate], CapabilityQuery(capability="script_logic_review"))


def test_agent_message_handoff_is_idempotent_and_conflict_safe(factory):
    with factory() as db:
        project, author, reviewer, *_ = seed_agents(db)
        task = create_task(db, project_id=project.id, task_type="HANDOFF", title="Handoff", input_snapshot={})
        row, created = send_agent_message(db, project_id=project.id, from_agent_id=author.id,
            to_agent_id=reviewer.id, task_id=task.id, message_type="review.requested",
            payload={"artifact": "outline-v1"}, idempotency_key="handoff-1")
        same, created_again = send_agent_message(db, project_id=project.id, from_agent_id=author.id,
            to_agent_id=reviewer.id, task_id=task.id, message_type="review.requested",
            payload={"artifact": "outline-v1"}, idempotency_key="handoff-1")
        assert created and not created_again and row.id == same.id
        with pytest.raises(AgentMessageConflict):
            send_agent_message(db, project_id=project.id, from_agent_id=author.id,
                to_agent_id=reviewer.id, task_id=task.id, message_type="review.requested",
                payload={"artifact": "outline-v2"}, idempotency_key="handoff-1")
        db.commit()
        assert len(db.scalars(select(AgentMessage)).all()) == 1


def test_quality_evaluation_accepts_and_is_idempotent(factory):
    with factory() as db:
        _project, _author, _reviewer, _av, rv, _task, run = seed_succeeded_run(db)
        criteria = [
            {"name": "logic", "score": 0.95, "weight": 2},
            {"name": "clarity", "score": 0.9, "weight": 1},
        ]
        first = evaluate_agent_output(db, agent_run_id=run.id, reviewer_agent_version_id=rv.id,
                                      criteria=criteria, idempotency_key="eval-accept-1")
        second = evaluate_agent_output(db, agent_run_id=run.id, reviewer_agent_version_id=rv.id,
                                       criteria=criteria, idempotency_key="eval-accept-1")
        assert first.decision == "accepted" and first.score == pytest.approx(0.933333)
        assert first.id == second.id
        with pytest.raises(EvaluationError, match="different evaluation content"):
            evaluate_agent_output(db, agent_run_id=run.id, reviewer_agent_version_id=rv.id,
                criteria=[{"name": "logic", "score": 0.2}], idempotency_key="eval-accept-1")
        db.commit()


def test_quality_gate_requests_rework_and_creates_one_dependent_task(factory):
    with factory() as db:
        _project, _author, _reviewer, _av, rv, source, run = seed_succeeded_run(db)
        evaluation = evaluate_agent_output(db, agent_run_id=run.id, reviewer_agent_version_id=rv.id,
            criteria=[{"name": "historical_accuracy", "score": 0.2, "blocking": True,
                       "finding": "The prop is anachronistic", "required_change": "Replace the prop with a 1909-appropriate object"}],
            idempotency_key="eval-rework-1", policy=EvaluationPolicy(acceptance_threshold=0.8,
                criterion_minimum=0.5, max_rework_rounds=2))
        assert evaluation.decision == "rework"
        task1 = request_rework(db, evaluation_id=evaluation.id)
        task2 = request_rework(db, evaluation_id=evaluation.id)
        assert task1.id == task2.id
        assert task1.input_snapshot["rework_round"] == 1
        assert task1.input_snapshot["required_changes"][0]["instruction"].startswith("Replace")
        edge = db.scalar(select(TaskDependency).where(TaskDependency.task_id == task1.id))
        assert edge.depends_on_task_id == source.id
        db.commit()



def test_evaluation_feedback_routes_to_author_and_creates_rework(factory):
    with factory() as db:
        _project, author, reviewer, _av, rv, _source, run = seed_succeeded_run(db)
        criteria = [{"name": "character_continuity", "score": 0.35, "blocking": True,
                     "finding": "Character motivation contradicts the previous beat",
                     "required_change": "Align the action with the established motivation"}]
        routed = evaluate_and_route_output(db, agent_run_id=run.id, reviewer_agent_version_id=rv.id,
            criteria=criteria, idempotency_key="eval-route-1")
        repeated = evaluate_and_route_output(db, agent_run_id=run.id, reviewer_agent_version_id=rv.id,
            criteria=criteria, idempotency_key="eval-route-1")
        assert routed["evaluation"].decision == "rework"
        assert repeated["evaluation"].id == routed["evaluation"].id
        assert repeated["message"].id == routed["message"].id
        assert repeated["rework_task"].id == routed["rework_task"].id
        assert routed["message"].from_agent_id == reviewer.id
        assert routed["message"].to_agent_id == author.id
        assert routed["message"].message_type == "quality.rework"
        assert routed["rework_task"] is not None
        assert routed["rework_task"].input_snapshot["rework_round"] == 1
        db.commit()

def test_quality_gate_escalates_after_rework_budget_and_requires_independent_reviewer(factory):
    with factory() as db:
        _project, author, _reviewer, av, rv, _task, run = seed_succeeded_run(db)
        with pytest.raises(EvaluationError, match="different Agent"):
            evaluate_agent_output(db, agent_run_id=run.id, reviewer_agent_version_id=av.id,
                criteria=[{"name": "logic", "score": 0.1}], idempotency_key="self-review")
        task = db.get(Task, run.task_id)
        task.input_snapshot = {**task.input_snapshot, "rework_round": 2}
        row = evaluate_agent_output(db, agent_run_id=run.id, reviewer_agent_version_id=rv.id,
            criteria=[{"name": "logic", "score": 0.1, "blocking": True, "required_change": "Repair logic"}],
            idempotency_key="eval-escalate", policy=EvaluationPolicy(max_rework_rounds=2))
        assert row.decision == "escalate"
        with pytest.raises(EvaluationError, match="only a rework decision"):
            request_rework(db, evaluation_id=row.id)


def test_model_adapter_registry_requires_explicit_provider_and_validates_response():
    class LocalAdapter:
        provider_key = "local-test"
        model_key = "director-sim-v1"
        def generate(self, request):
            return ModelResponse(provider_key=self.provider_key, model_key=self.model_key,
                                 output={"plan": request.input["goal"]}, request_id="local-1")
    registry = ModelAdapterRegistry()
    with pytest.raises(ModelUnavailableError):
        registry.generate("local-test", ModelRequest(purpose="planning", input={"goal": "8.1"}, model_key="director-sim-v1"))
    registry.register(LocalAdapter())
    result = registry.generate("LOCAL-TEST", ModelRequest(
        purpose="planning", input={"goal": "8.1"}, model_key="director-sim-v1"))
    assert result.output == {"plan": "8.1"}
    with pytest.raises(ValueError, match="already registered"):
        registry.register(LocalAdapter())


def test_harbor_8_1_semantic_review_runs_through_fake_provider_and_durable_rework(factory):
    from backend.app.runtime.model_adapters import FakeModelAdapter
    from backend.app.services.semantic_evaluation import evaluate_with_model
    with factory() as db:
        _project, _author, _reviewer, _av, rv, task, run = seed_succeeded_run(db)
        # Historical/context payload is explicitly scoped to the 1909 Harbor 8.1 scene.
        review_context = {
            "project": "天堂号", "scene": "8.1", "arrival_year": 1909,
            "route": "中国沿海港口—太平洋—旧金山",
            "review_dimensions": ["historical_accuracy", "continuity", "visual_feasibility"],
            "agent_output": run.output_snapshot,
        }
        adapter = FakeModelAdapter(model_key="afs-review-test", output={"criteria": [
            {"name": "historical_accuracy", "score": 0.45, "weight": 2, "blocking": True,
             "finding": "1909年航线与船舶细节尚未核实", "required_change": "补充可追溯史料并核对航线与船舶配置"},
            {"name": "continuity", "score": 0.9, "weight": 1, "blocking": False,
             "finding": "", "required_change": ""},
            {"name": "visual_feasibility", "score": 0.8, "weight": 1, "blocking": False,
             "finding": "", "required_change": ""},
        ]})
        registry = ModelAdapterRegistry(); registry.register(adapter)
        routed = evaluate_with_model(db, registry=registry, provider_key="fake", model_key="afs-review-test",
            agent_run_id=run.id, reviewer_agent_version_id=rv.id, context=review_context,
            idempotency_key="harbor-8-1-semantic-review")
        assert routed["evaluation"].decision == "rework"
        assert routed["rework_task"].input_snapshot["rework_round"] == 1
        assert routed["model_provenance"]["mode"] == "test_fake"
        assert adapter.calls[0].input["review_context"]["arrival_year"] == 1909
        db.commit()


def test_rework_gates_transitive_pending_downstream_tasks(factory):
    with factory() as db:
        project, _author, _reviewer, _av, rv, source, run = seed_succeeded_run(db)
        downstream = create_task(db, project_id=project.id, task_type="VISUAL_BIBLE", title="Visual bible",
                                  input_snapshot={"scene": "8.1"})
        downstream2 = create_task(db, project_id=project.id, task_type="SHOT_PLAN", title="Shot plan",
                                   input_snapshot={"scene": "8.1"})
        add_task_dependency(db, project_id=project.id, task_id=downstream.id, depends_on_task_id=source.id)
        add_task_dependency(db, project_id=project.id, task_id=downstream2.id, depends_on_task_id=downstream.id)
        evaluation = evaluate_agent_output(db, agent_run_id=run.id, reviewer_agent_version_id=rv.id,
            criteria=[{"name": "logic", "score": .2, "blocking": True,
                       "finding": "missing", "required_change": "repair"}],
            idempotency_key="rework-gate-transitive")
        rework = request_rework(db, evaluation_id=evaluation.id)
        deps = {(row.task_id, row.depends_on_task_id) for row in db.scalars(select(TaskDependency)).all()}
        assert (downstream.id, rework.id) in deps
        assert (downstream2.id, rework.id) in deps
        assert {item["task_id"] for item in rework.input_snapshot["downstream_impact"]} == {str(downstream.id), str(downstream2.id)}
        db.commit()

from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool
import pytest

from backend.app.db.base import Base
from backend.app.db.ids import uuid7
from backend.app.models import Project, Agent, AgentVersion, Skill, SkillVersion, AgentSkillBinding, OrchestrationPlan, Task
from backend.app.runtime.model_adapters import FakeModelAdapter, ModelAdapterRegistry, ModelUnavailableError
from backend.app.services.executive_director_agent import (
    ExecutiveDirectorPlanningError, plan_production_request,
)
from backend.app.services.task_service import create_task
from backend.app.services.orchestrator import OrchestrationError


@pytest.fixture
def factory():
    engine = create_engine("sqlite+pysqlite:///:memory:", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    yield sessionmaker(engine, expire_on_commit=False, class_=Session)
    engine.dispose()


def seed_project_and_capability(db):
    project = Project(code=f"DIR_{uuid7().hex[:8]}", name="Director Planning Test")
    agent = Agent(code=f"SCRIPT_{uuid7().hex[:8]}", display_name="Screenwriting Agent")
    skill = Skill(code=f"LOGIC_{uuid7().hex[:8]}", display_name="Script Logic Review")
    db.add_all([project, agent, skill]); db.flush()
    agent_version = AgentVersion(agent_id=agent.id, version_number=1,
        definition_snapshot={"profile": {"specialties": ["screenwriting"], "tags": ["dramaturgy"],
            "modalities": ["text"], "languages": ["zh"], "task_types": ["SCRIPT_ANALYSIS"]}},
        definition_sha256="a" * 64)
    skill_version = SkillVersion(skill_id=skill.id, version_number=1,
        definition_snapshot={"capabilities": ["script_logic_review"]}, definition_sha256="b" * 64)
    db.add_all([agent_version, skill_version]); db.flush()
    db.add(AgentSkillBinding(agent_version_id=agent_version.id, skill_version_id=skill_version.id)); db.flush()
    root = create_task(db, project_id=project.id, task_type="PRODUCTION_OBJECTIVE", title="Produce a short film",
                       input_snapshot={"objective": "Develop a short film"})
    return project, root


def make_registry(output):
    registry = ModelAdapterRegistry()
    adapter = FakeModelAdapter(provider_key="fake", model_key="director-test-v1", output=output)
    registry.register(adapter)
    return registry, adapter


def valid_output():
    return {"strategy_id": "executive-director-test-v1", "steps": [
        {"key": "script_analysis", "capability": "script_logic_review", "task_type": "SCRIPT_ANALYSIS",
         "input": {"deliverable": "scene_logic_report"}, "depends_on": [], "required_tags": ["dramaturgy"],
         "modality": "text", "language": "zh"}
    ]}


def test_model_backed_director_creates_pending_plan_with_provenance(factory):
    with factory() as db:
        project, root = seed_project_and_capability(db)
        registry, adapter = make_registry(valid_output())
        plan = plan_production_request(db, project_id=project.id, task_id=root.id,
            request={"objective": "Analyze the script and propose a development workflow", "language": "zh"},
            provider_key="fake", model_key="director-test-v1", adapters=registry, correlation_id="corr-001")
        assert plan.approval_status == "pending"
        assert plan.status == "draft"
        assert plan.plan_snapshot["proposal_metadata"]["human_approval_required"] is True
        provenance = plan.plan_snapshot["proposal_metadata"]["planner_provenance"]
        assert provenance["provider_key"] == "fake"
        assert provenance["model_key"] == "director-test-v1"
        assert provenance["adapter_mode"] == "test_fake"
        assert len(provenance["planner_output_sha256"]) == 64
        assert len(adapter.calls) == 1
        assert adapter.calls[0].correlation_id == "corr-001"
        assert db.scalar(select(OrchestrationPlan).where(OrchestrationPlan.id == plan.id)) is not None
        # Only the root objective task exists; proposal generation does not materialize DAG steps.
        assert len(db.scalars(select(Task)).all()) == 1


def test_model_planner_rejects_unknown_fields_without_persisting_plan(factory):
    with factory() as db:
        project, root = seed_project_and_capability(db)
        output = valid_output()
        output["approved"] = True
        registry, _ = make_registry(output)
        with pytest.raises(ExecutiveDirectorPlanningError, match="exactly strategy_id and steps"):
            plan_production_request(db, project_id=project.id, task_id=root.id,
                request={"objective": "Plan the production"}, provider_key="fake",
                model_key="director-test-v1", adapters=registry)
        assert db.scalars(select(OrchestrationPlan)).all() == []


def test_model_planner_rejects_unknown_capability(factory):
    with factory() as db:
        project, root = seed_project_and_capability(db)
        output = valid_output()
        output["steps"][0]["capability"] = "invented_capability"
        registry, _ = make_registry(output)
        with pytest.raises(OrchestrationError, match="no active specialist"):
            plan_production_request(db, project_id=project.id, task_id=root.id,
                request={"objective": "Plan the production"}, provider_key="fake",
                model_key="director-test-v1", adapters=registry)
        assert db.scalars(select(OrchestrationPlan)).all() == []


def test_model_planner_rejects_dependency_cycle(factory):
    with factory() as db:
        project, root = seed_project_and_capability(db)
        output = {"strategy_id": "cycle-test", "steps": [
            {"key": "first", "capability": "script_logic_review", "task_type": "SCRIPT_ANALYSIS", "depends_on": ["second"]},
            {"key": "second", "capability": "script_logic_review", "task_type": "SCRIPT_ANALYSIS", "depends_on": ["first"]},
        ]}
        registry, _ = make_registry(output)
        with pytest.raises(OrchestrationError, match="dependency cycle"):
            plan_production_request(db, project_id=project.id, task_id=root.id,
                request={"objective": "Plan the production"}, provider_key="fake",
                model_key="director-test-v1", adapters=registry)
        assert db.scalars(select(OrchestrationPlan)).all() == []


def test_model_planner_rejects_reserved_runtime_fields(factory):
    with factory() as db:
        project, root = seed_project_and_capability(db)
        output = valid_output()
        output["steps"][0]["input"]["_orchestration_agent_version_id"] = "attacker-controlled"
        registry, _ = make_registry(output)
        with pytest.raises(ExecutiveDirectorPlanningError, match="reserved orchestration fields"):
            plan_production_request(db, project_id=project.id, task_id=root.id,
                request={"objective": "Plan the production"}, provider_key="fake",
                model_key="director-test-v1", adapters=registry)
        assert db.scalars(select(OrchestrationPlan)).all() == []


def test_model_planner_requires_explicit_registered_provider(factory):
    with factory() as db:
        project, root = seed_project_and_capability(db)
        registry = ModelAdapterRegistry()
        with pytest.raises(ModelUnavailableError):
            plan_production_request(db, project_id=project.id, task_id=root.id,
                request={"objective": "Plan the production"}, provider_key="not-installed",
                model_key="model-x", adapters=registry)
        assert db.scalars(select(OrchestrationPlan)).all() == []


def test_model_planner_rejects_oversized_or_missing_objective(factory):
    with factory() as db:
        project, root = seed_project_and_capability(db)
        registry, _ = make_registry(valid_output())
        with pytest.raises(ExecutiveDirectorPlanningError, match="objective"):
            plan_production_request(db, project_id=project.id, task_id=root.id,
                request={"context": "no objective"}, provider_key="fake",
                model_key="director-test-v1", adapters=registry)
        with pytest.raises(ExecutiveDirectorPlanningError, match="exceeds"):
            plan_production_request(db, project_id=project.id, task_id=root.id,
                request={"objective": "Plan", "extra": "x" * 25000}, provider_key="fake",
                model_key="director-test-v1", adapters=registry)
        assert db.scalars(select(OrchestrationPlan)).all() == []

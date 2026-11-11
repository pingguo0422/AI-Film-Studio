from uuid import uuid4
import pytest
from backend.app.services.context_service import ContextAssembler, ContextDocument, ContextError
from backend.app.runtime.model_adapters import (FakeModelAdapter, ModelAdapterRegistry, ModelRequest,
    OpenAICompatibleAdapter, ModelAuthenticationError)
from backend.app.services.semantic_evaluation import validate_semantic_rubric, SemanticEvaluationError


def test_context_assembly_is_project_task_and_sensitivity_scoped_with_provenance():
    project, other = uuid4(), uuid4()
    docs = [
        ContextDocument(project, "script", "scene-8.1", "script-v3", {"scene": "8.1"}, ("SHOT_PLAN",)),
        ContextDocument(other, "secret", "foreign", "v1", {"secret": True}),
        ContextDocument(project, "private", "restricted", "v1", {"private": True}, sensitivity="restricted"),
        ContextDocument(project, "history", "1909-pacific", "research-v2", {"year": 1909}, ("HISTORICAL_REVIEW",)),
    ]
    bundle = ContextAssembler(max_tokens=100).assemble(project_id=project, task_type="SHOT_PLAN", documents=docs)
    assert list(bundle.documents) == [{"scene": "8.1"}]
    assert bundle.provenance[0]["version_id"] == "script-v3"
    assert bundle.project_id == str(project)


def test_context_budget_and_document_caps_fail_closed():
    project = uuid4()
    too_large = ContextDocument(project, "script", "s", "v1", {"body": "x" * 500})
    with pytest.raises(ContextError, match="per-document"):
        ContextAssembler(max_document_chars=100).assemble(project_id=project, task_type="SCRIPT", documents=[too_large])
    with pytest.raises(ContextError, match="token budget"):
        ContextAssembler(max_tokens=2).assemble(project_id=project, task_type="SCRIPT", documents=[
            ContextDocument(project, "script", "s", "v1", {"body": "a reasonably sized passage"})])


def test_fake_adapter_registry_marks_test_mode_and_validates_identity():
    registry = ModelAdapterRegistry()
    adapter = FakeModelAdapter(model_key="fake-review-v1", output={"criteria": []})
    registry.register(adapter)
    response = registry.generate("fake", ModelRequest("review", {}, model_key="fake-review-v1"))
    assert response.metadata["mode"] == "test_fake"
    assert len(adapter.calls) == 1


def test_openai_compatible_adapter_fails_closed_without_secret():
    adapter = OpenAICompatibleAdapter(model_key="test-model", api_key="")
    with pytest.raises(ModelAuthenticationError, match="not configured"):
        adapter.generate(ModelRequest("review", {}, model_key="test-model"))


def test_semantic_rubric_requires_strict_schema_and_ranges():
    good = {"criteria": [{"name": "historical", "score": .9, "weight": 1,
        "blocking": False, "finding": "", "required_change": ""}]}
    assert validate_semantic_rubric(good)[0]["name"] == "historical"
    with pytest.raises(SemanticEvaluationError): validate_semantic_rubric({"criteria": [{"name": "x", "score": 2}]})
    with pytest.raises(SemanticEvaluationError): validate_semantic_rubric({"criteria": [], "extra": 1})

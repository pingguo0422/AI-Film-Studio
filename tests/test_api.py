from fastapi.testclient import TestClient
from backend.app.main import app
from backend.app.schemas import ProjectCreate
from pydantic import ValidationError
import pytest

def test_health_endpoint():
    response = TestClient(app).get("/health")
    assert response.status_code == 200
    assert response.json()["status"] == "ok"

def test_project_schema_rejects_invalid_code():
    with pytest.raises(ValidationError):
        ProjectCreate.model_validate({"code":"bad code", "name":"x"})

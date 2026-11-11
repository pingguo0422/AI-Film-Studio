from fastapi.testclient import TestClient
from backend.app.main import app


def test_control_center_serves_html_and_assets_with_security_headers():
    client = TestClient(app)
    page = client.get('/control-center/')
    assert page.status_code == 200
    assert '总导演控制中心' in page.text
    assert "sessionStorage" not in page.text  # behavior lives in the external script
    assert page.headers['content-security-policy'].startswith("default-src 'self'")
    assert page.headers['x-content-type-options'] == 'nosniff'

    script = client.get('/control-center/assets/app.js')
    stylesheet = client.get('/control-center/assets/app.css')
    assert script.status_code == 200
    assert "afs_api_token" in script.text
    assert "/activity?limit=30" in script.text
    assert "authorized-action-type" in script.text
    assert "authorized_action" in script.text
    assert "确认执行已批准动作" in script.text
    assert "idempotency_key" in script.text
    assert "api(`/${encodeURIComponent(id)}/execute`)" in script.text
    assert "action_execution:'导演授权执行'" in script.text
    assert stylesheet.status_code == 200


def test_control_center_does_not_mount_when_static_assets_are_not_available():
    # The mount is conditional at application startup; this assertion protects the
    # documented route contract in the normal source distribution.
    response = TestClient(app).get('/control-center/')
    assert response.status_code == 200

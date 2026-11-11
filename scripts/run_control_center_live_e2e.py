#!/usr/bin/env python3
"""Exercise the shipped Control Center against a live FastAPI + PostgreSQL API."""
from __future__ import annotations

import os
from playwright.sync_api import sync_playwright

BASE_URL = os.getenv("AFS_E2E_BASE_URL", "http://127.0.0.1:8000").rstrip("/")
PROJECT_ID = os.environ["AFS_E2E_PROJECT_ID"]
CASE_ID = os.environ["AFS_E2E_CASE_ID"]
TOKEN = os.environ["AFS_E2E_API_TOKEN"]


def main() -> int:
    errors: list[str] = []
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(
            headless=True,
            executable_path=os.getenv("AFS_CHROMIUM_EXECUTABLE") or None,
            args=["--no-sandbox", "--disable-dev-shm-usage"],
        )
        page = browser.new_page()
        page.on("pageerror", lambda error: errors.append(str(error)))
        page.on("dialog", lambda dialog: dialog.accept())
        response = page.goto(f"{BASE_URL}/control-center/", wait_until="networkidle")
        assert response and response.status == 200, f"Control Center HTTP status: {response.status if response else 'no response'}"

        page.locator("#api-token").fill(TOKEN)
        page.locator("#project-id").fill(PROJECT_ID)
        page.get_by_role("button", name="验证并连接").click()
        page.locator("#workspace").wait_for(state="visible", timeout=15000)

        case_button = page.get_by_role("button", name="LIVE_BROWSER_E2E_CREATE_TASK")
        case_button.wait_for(state="visible", timeout=15000)
        case_button.click()
        page.locator("#authorized-action-type").select_option("create_task")
        action_payload = {
            "task_type": "script_revision",
            "title": "Live PostgreSQL browser E2E task",
            "input_snapshot": {"scene": "8.1", "source": "live-browser-e2e", "environment": "disposable"},
            "priority": 35,
            "max_attempts": 2,
        }
        page.locator("#authorized-action-payload").fill(__import__("json").dumps(action_payload, ensure_ascii=False, indent=2))
        page.get_by_role("button", name="批准", exact=True).click()
        execute_button = page.get_by_role("button", name="确认执行已批准动作")
        execute_button.wait_for(state="visible", timeout=15000)

        # Confirm approval was persisted before the separate execution interaction.
        api = page.request
        headers = {"Authorization": f"Bearer {TOKEN}"}
        detail_url = f"{BASE_URL}/v1/projects/{PROJECT_ID}/director/decision-cases/{CASE_ID}"
        detail_response = api.get(detail_url, headers=headers)
        assert detail_response.status == 200, detail_response.text()
        detail = detail_response.json()
        assert detail["status"] == "approved"
        assert detail["authorized_action_snapshot"]["payload"]["title"] == action_payload["title"]

        execute_button.click()
        result = page.locator("#execution-result")
        result.wait_for(state="visible", timeout=15000)
        page.wait_for_function(
            "() => document.querySelector('#execution-result')?.textContent.includes('succeeded')",
            timeout=15000,
        )
        result_text = result.inner_text()
        assert "Live PostgreSQL browser E2E task" not in result_text  # result contains IDs, not input payload
        assert '"task_id"' in result_text, result_text
        page.get_by_text("导演授权执行", exact=False).first.wait_for(timeout=15000)

        execute_url = f"{detail_url}/execute"
        execution_response = api.get(execute_url, headers=headers)
        assert execution_response.status == 200, execution_response.text()
        execution = execution_response.json()
        assert execution["status"] == "succeeded"
        task_id = execution["result_snapshot"]["task_id"]
        assert task_id

        timeline_response = api.get(
            f"{BASE_URL}/v1/projects/{PROJECT_ID}/director/activity?limit=30",
            headers=headers,
        )
        assert timeline_response.status == 200, timeline_response.text()
        assert any(item["kind"] == "action_execution" for item in timeline_response.json()["items"])
        assert not errors, f"Browser errors: {errors}"
        browser.close()

    print("BROWSER-TO-LIVE-API E2E: PASS")
    print("- Chromium navigated to the live FastAPI Control Center over HTTP")
    print("- Bearer authentication and PostgreSQL-backed project membership passed")
    print("- Real inbox/detail APIs returned the seeded decision case")
    print("- Human approval persisted the exact authorized action snapshot")
    print("- Separate browser confirmation executed the approved action")
    print(f"- PostgreSQL-backed execution persisted task_id={task_id}")
    print("- Execution read API and activity timeline confirmed persisted records")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

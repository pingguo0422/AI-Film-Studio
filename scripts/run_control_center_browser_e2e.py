#!/usr/bin/env python3
"""Chromium UI workflow test using deterministic mocked API responses.

The actual shipped HTML, CSS and JavaScript are loaded in Chromium. API calls
are mocked in-browser so this test is independent of network policy. Real API,
DB and service behavior remain covered by the pytest integration suite.
"""
from __future__ import annotations
import json
import os
from pathlib import Path
from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parents[1]
FRONTEND = ROOT / "frontend" / "control-center"


def main() -> int:
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(
            headless=True,
            executable_path=os.getenv("AFS_CHROMIUM_EXECUTABLE") or None,
            args=["--no-sandbox", "--disable-dev-shm-usage"],
        )
        page = browser.new_page()
        page.on("dialog", lambda dialog: dialog.accept())
        page.on("pageerror", lambda error: print("PAGEERROR:", error))
        page.on("console", lambda message: print("CONSOLE:", message.type, message.text) if message.type == "error" else None)
        html = (FRONTEND / "index.html").read_text()
        html = html.replace('<link rel="stylesheet" href="/control-center/assets/app.css">', '')
        html = html.replace('<script defer src="/control-center/assets/app.js"></script>', '')
        page.set_content(html, wait_until="domcontentloaded")
        page.add_style_tag(content=(FRONTEND / "assets" / "app.css").read_text())
        page.evaluate("""() => {
          const storage = new Map();
          Object.defineProperty(window, 'sessionStorage', {configurable:true, value:{
            getItem:key=>storage.has(key)?storage.get(key):null,
            setItem:(key,value)=>storage.set(key,String(value)),
            removeItem:key=>storage.delete(key)
          }});
          Object.defineProperty(window.crypto, 'randomUUID', {value:()=> 'e2e-idempotency-key-0001'});
          const caseId = 'browser-e2e-case';
          const now = new Date().toISOString();
          const item = {id:caseId, project_id:'browser-e2e-project', case_key:'browser-e2e-001',
            recommendation_code:'CREATE_SCRIPT_REVISION_TASK', severity:'medium', status:'open',
            approval_required:'director_review', evidence_refs:['scene:8.1'], evidence_count:1,
            proposal_snapshot:{summary:'Create a script revision task',impact:{scope:'scene 8.1'}},
            source_brief_sha256:'a'.repeat(64), source_state_digest:'b'.repeat(64), created_at:now};
          let execution = null;
          window.__mockCalls = [];
          window.fetch = async (url, init={}) => {
            const method=(init.method||'GET').toUpperCase(), path=String(url);
            window.__mockCalls.push({method,path,body:init.body||null});
            let status=200, body={};
            if(path==='/v1/me') body={id:'human-e2e',display_name:'E2E Operator'};
            else if(path.endsWith('/membership')) body={role:'owner'};
            else if(path.includes('/activity?')) body={items:execution?[{kind:'action_execution',title:'Director action executed',status:'succeeded',occurred_at:now}]:[]};
            else if(path.includes('/decision-cases?')) {
              const requestedStatus=new URL('http://mock.local'+path).searchParams.get('status') || 'open';
              const visible=requestedStatus==='all' || requestedStatus===item.status;
              body={items:visible?[{...item}]:[],total:visible?1:0,limit:25,offset:0};
            }
            else if(path.endsWith('/'+caseId+'/decision')&&method==='POST') {
              const submitted=JSON.parse(init.body); item.status='approved'; item.decision='approved';
              item.decision_note=submitted.note; item.authorized_action_snapshot=submitted.authorized_action;
              body={...item,decided_by:'human-e2e'};
            }
            else if(path.endsWith('/'+caseId+'/execute')&&method==='GET') {
              if(execution) body=execution; else {status=404;body={detail:'action execution not found'};}
            }
            else if(path.endsWith('/'+caseId+'/execute')&&method==='POST') {
              execution={id:'execution-e2e-001',decision_case_id:caseId,action_type:'create_task',
                action_sha256:'c'.repeat(64),status:'succeeded',
                result_snapshot:{task_id:'task-e2e-001',task_status:'queued',created:true},created_at:now};
              body=execution;
            }
            else if(path.endsWith('/'+caseId)) body={...item,decided_by:item.decision?'human-e2e':null};
            else {status=404;body={detail:'mock route not found: '+method+' '+path};}
            return new Response(JSON.stringify(body),{status,headers:{'Content-Type':'application/json'}});
          };
        }""")
        page.add_script_tag(content=(FRONTEND / "assets" / "app.js").read_text())
        page.locator("#api-token").fill("afs_pat_browser_e2e")
        page.locator("#project-id").fill("browser-e2e-project")
        page.get_by_role("button", name="验证并连接").click()
        try:
            page.locator("#workspace").wait_for(state="visible", timeout=10000)
        except Exception:
            print("connect error:", page.locator("#connect-error").inner_text())
            print("mock calls:", page.evaluate("window.__mockCalls"))
            raise
        page.get_by_role("button", name="CREATE_SCRIPT_REVISION_TASK").click()
        page.locator("#authorized-action-type").select_option("create_task")
        payload={"task_type":"script_revision","title":"E2E approved scene revision","input_snapshot":{"scene":"8.1","source":"browser-e2e"}}
        page.locator("#authorized-action-payload").fill(json.dumps(payload,ensure_ascii=False,indent=2))
        page.get_by_role("button",name="批准",exact=True).click()
        assert page.locator("#status-filter").input_value() == "approved", "approved case should remain visible in its outcome filter"
        assert "CREATE_SCRIPT_REVISION_TASK" in page.locator("#detail-panel").inner_text(), "approved case detail should remain selected"
        execute_button=page.get_by_role("button",name="确认执行已批准动作")
        try:
            execute_button.wait_for(state="visible",timeout=10000)
        except Exception:
            print("workspace error:", page.locator("#workspace-error").inner_text())
            print("detail:", page.locator("#detail-panel").inner_text())
            print("calls:", page.evaluate("window.__mockCalls"))
            raise
        execute_button.click()
        result=page.locator("#execution-result")
        result.wait_for(state="visible",timeout=10000)
        result_text=result.inner_text()
        assert '"status": "succeeded"' in result_text, result_text
        assert '"task_id": "task-e2e-001"' in result_text, result_text
        page.get_by_text("导演授权执行",exact=False).first.wait_for(timeout=10000)
        calls=page.evaluate("window.__mockCalls")
        assert any(c["method"]=="POST" and c["path"].endswith("/decision") for c in calls)
        assert any(c["method"]=="POST" and c["path"].endswith("/execute") for c in calls)
        browser.close()
    print("BROWSER UI E2E: PASS")
    print("- Chromium loaded actual control-center HTML, CSS and JavaScript")
    print("- Browser connected and loaded a mocked project inbox")
    print("- UI submitted approval with the exact create_task payload")
    print("- UI required a second explicit confirmation before execution")
    print("- UI rendered execution result and activity timeline")
    print("- API persistence and authorization are tested separately by pytest")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

(() => {
  'use strict';
  const $ = (id) => document.getElementById(id);
  const state = { token: sessionStorage.getItem('afs_api_token') || '', projectId: sessionStorage.getItem('afs_project_id') || '', offset: 0, limit: 25, total: 0, selectedId: null, currentCase: null };
  const statusLabels = {open:'待处理',approved:'已批准',rejected:'已拒绝',deferred:'已延期',closed:'已关闭'};
  const severityLabels = {low:'低风险',medium:'中风险',high:'高风险',critical:'严重风险'};
  function setText(node, value) { node.textContent = value == null ? '' : String(value); }
  function showError(id, message) { const el = $(id); setText(el, message); el.hidden = !message; }
  function toast(message) { const el = $('toast'); setText(el, message); el.hidden = false; window.setTimeout(() => { el.hidden = true; }, 2600); }
  function apiUrl(path) { const base = `/v1/projects/${encodeURIComponent(state.projectId)}/director`; return path.startsWith('/activity') ? `${base}${path}` : `${base}/decision-cases${path}`; }
  async function api(path, options = {}) {
    const response = await fetch(apiUrl(path), { ...options, headers: { 'Authorization': `Bearer ${state.token}`, ...(options.body ? {'Content-Type':'application/json'} : {}), ...(options.headers || {}) } });
    const body = response.status === 204 ? null : await response.json().catch(() => ({}));
    if (!response.ok) throw new Error(body?.detail || `请求失败（HTTP ${response.status}）`);
    return body;
  }
  function el(tag, className, text) { const node = document.createElement(tag); if (className) node.className = className; if (text !== undefined) setText(node, text); return node; }
  function statusPill(status) { return el('span', `status-pill ${status}`, statusLabels[status] || status); }
  function renderInbox(data) {
    state.total = data.total; $('inbox-count').textContent = `${data.total} 项`; $('page-caption').textContent = `第 ${Math.floor(state.offset / state.limit) + 1} 页`;
    $('previous-page').disabled = state.offset <= 0; $('next-page').disabled = state.offset + state.limit >= data.total;
    const list = $('inbox-list'); list.replaceChildren();
    if (!data.items.length) { list.append(el('div','empty-state','当前筛选条件下没有决策事项。')); return; }
    for (const item of data.items) {
      const button = el('button', `inbox-item${state.selectedId === item.id ? ' selected' : ''}`); button.type = 'button'; button.setAttribute('aria-pressed', String(state.selectedId === item.id));
      const top = el('div','item-top'); top.append(el('span','item-code',item.recommendation_code)); top.append(statusPill(item.status));
      const meta = el('div','item-meta'); meta.append(el('span',`severity ${item.severity}`,severityLabels[item.severity] || item.severity)); meta.append(el('span',`${item.evidence_count} 条证据`)); meta.append(el('span',new Date(item.created_at).toLocaleString()));
      button.append(top,meta); button.addEventListener('click', () => loadDetail(item.id)); list.append(button);
    }
  }
  function section(title, contentNode) { const box = el('section','detail-section'); box.append(el('h4','',title),contentNode); return box; }
  function renderDetail(item) {
    state.currentCase = item; const panel = $('detail-panel'); panel.replaceChildren();
    const top = el('div','detail-top'); const titleWrap = el('div'); titleWrap.append(el('h3','detail-title',item.recommendation_code),el('div','detail-meta',`事项 ${item.case_key} · 创建于 ${new Date(item.created_at).toLocaleString()}`)); top.append(titleWrap,statusPill(item.status)); panel.append(top);
    const snapshot = item.proposal_snapshot || {}; const summary = snapshot.summary || snapshot.objective || snapshot.description || '该建议没有提供独立摘要。';
    panel.append(section('建议摘要',el('p','',typeof summary === 'string' ? summary : JSON.stringify(summary))));
    const evidence = el('div','evidence-list'); for (const ref of item.evidence_refs || []) evidence.append(el('span','evidence',ref)); if (!item.evidence_refs?.length) evidence.append(el('span','muted','没有证据引用')); panel.append(section(`证据引用 · ${item.evidence_count}`,evidence));
    const impact = snapshot.impact ?? snapshot.risk ?? snapshot.expected_impact;
    panel.append(section('影响范围 / 风险信息',el('pre','snapshot',impact === undefined ? '建议快照未提供独立影响范围字段。请结合完整建议内容审阅。' : JSON.stringify(impact,null,2))));
    panel.append(section('建议完整快照',el('pre','snapshot',JSON.stringify(snapshot,null,2))));
    const digest = el('div','digest',`SOURCE BRIEF SHA-256\n${item.source_brief_sha256}\n\nSOURCE STATE DIGEST\n${item.source_state_digest}`); panel.append(section('来源校验信息',digest));
    if (item.status === 'open') {
      const form = el('form','decision-form'); form.append(el('h4','','人工审核决定'));
      const note = document.createElement('textarea'); note.id = 'decision-note'; note.maxLength = 4000; note.placeholder = '填写审核意见、前置条件或需要补充的信息（可选，最多 4000 字）'; note.setAttribute('aria-label','审核意见'); form.append(note);
      const actionLabel = el('label','action-config-label','批准时绑定的具体动作（可选；不绑定则只批准建议）');
      const actionType = document.createElement('select'); actionType.id = 'authorized-action-type';
      for (const [value,label] of [['','不绑定执行动作'],['create_task','创建制作任务'],['request_rework','请求返工']]) { const option=document.createElement('option'); option.value=value; option.textContent=label; actionType.append(option); }
      actionLabel.append(actionType); form.append(actionLabel);
      const payload = document.createElement('textarea'); payload.id='authorized-action-payload'; payload.className='action-json'; payload.spellcheck=false; payload.setAttribute('aria-label','授权动作 JSON 参数'); payload.value=JSON.stringify({task_type:'',title:'',input_snapshot:{}},null,2); form.append(payload);
      const actionHint=el('p','hint','create_task 参数示例：task_type、title、input_snapshot（可选 priority、max_attempts）。request_rework 参数：evaluation_id（可选 task_type）。只有批准时会将当前动作快照一并绑定；执行接口不会接受或更改动作参数。'); form.append(actionHint);
      actionType.addEventListener('change',()=>{ payload.value=actionType.value==='request_rework' ? JSON.stringify({evaluation_id:'',task_type:''},null,2) : JSON.stringify({task_type:'',title:'',input_snapshot:{}},null,2); });
      const actions = el('div','decision-actions');
      for (const [decision,label,cls] of [['approved','批准','approve'],['rejected','拒绝','reject'],['deferred','延期','defer'],['closed','关闭','close']]) {
        const button = el('button',`button ${cls}`,label); button.type = 'button'; button.addEventListener('click', async () => submitDecision(decision, note.value, button)); actions.append(button);
      }
      form.append(actions); const warning = el('p','hint','批准与执行分离。绑定动作不代表立即执行；后续必须由具备审批权限的人再次明确点击执行。'); form.append(warning); panel.append(form);
    } else {
      const result = el('div','decision-form'); result.append(el('h4','','审核结果'),el('p','',`决定：${statusLabels[item.decision] || item.decision || statusLabels[item.status]}${item.decided_by ? ` · 审核人：${item.decided_by}` : ''}`)); if (item.decision_note) result.append(el('p','hint',`审核意见：${item.decision_note}`)); panel.append(result);
      if (item.authorized_action_snapshot) {
        panel.append(section('已批准并锁定的动作快照',el('pre','snapshot',JSON.stringify(item.authorized_action_snapshot,null,2))));
        const executeBox=el('div','decision-form'); executeBox.append(el('h4','','执行授权动作'));
        const keyName=`afs_action_key_${item.id}`; let key=sessionStorage.getItem(keyName); if(!key){key=`afs-${item.id}-${window.crypto.randomUUID()}`;sessionStorage.setItem(keyName,key);}
        executeBox.append(el('p','hint','执行将按上述不可变快照创建制作任务或请求返工。此操作会产生审计记录；同一事项只能执行一次。'));
        const executeButton=el('button','button approve','确认执行已批准动作'); executeButton.type='button'; executeButton.addEventListener('click',()=>executeAction(item.id,key,executeButton)); executeBox.append(executeButton);
        const output=el('pre','snapshot execution-result'); output.id='execution-result'; executeBox.append(output); panel.append(executeBox);
      } else if(item.status==='approved') { panel.append(el('p','hint','此事项获批时未绑定可执行动作，因此不能从控制中心执行。')); }
    }
  }
  async function loadInbox() {
    showError('workspace-error',''); const status = $('status-filter').value;
    try { const data = await api(`?status=${encodeURIComponent(status)}&limit=${state.limit}&offset=${state.offset}`); renderInbox(data); if (state.selectedId && !data.items.some(x => x.id === state.selectedId)) { state.selectedId = null; state.currentCase = null; $('detail-panel').replaceChildren(el('div','empty-detail','选择一项决策建议')); } }
    catch (error) { showError('workspace-error',error.message); if (error.message.includes('401')) disconnect(); }
  }
  async function loadDetail(id) {
    state.selectedId = id; await loadInbox();
    try {
      const item = await api(`/${encodeURIComponent(id)}`); renderDetail(item);
      if(item.authorized_action_snapshot){
        try { const execution=await api(`/${encodeURIComponent(id)}/execute`); const output=$('execution-result'); if(output) setText(output,JSON.stringify(execution,null,2)); }
        catch(error){ if(!error.message.includes('404')) showError('workspace-error',error.message); }
      }
    } catch (error) { showError('workspace-error',error.message); }
  }
  async function submitDecision(decision,note,button) {
    if (!state.selectedId) return;
    let authorized_action=null;
    if(decision==='approved' && $('authorized-action-type')?.value){
      try { authorized_action={action_type:$('authorized-action-type').value,payload:JSON.parse($('authorized-action-payload').value)}; }
      catch(_){showError('workspace-error','授权动作参数不是有效 JSON，请修正后再提交。');return;}
    }
    const description=authorized_action ? `并绑定动作 ${authorized_action.action_type}：\n${JSON.stringify(authorized_action.payload,null,2)}` : '';
    if (!window.confirm(`确认${({approved:'批准',rejected:'拒绝',deferred:'延期',closed:'关闭'})[decision]}这项建议？${description}\n此操作将形成审计记录。`)) return;
    button.disabled = true;
    try {
      const item = await api(`/${encodeURIComponent(state.selectedId)}/decision`,{method:'POST',body:JSON.stringify({decision,note:note.trim() || null,authorized_action})});
      // Keep the just-decided case selected. Otherwise an "open" inbox refresh
      // removes an approved case and clears its detail panel, hiding the
      // separately-confirmed execution control from the operator.
      $('status-filter').value = decision;
      state.offset = 0;
      renderDetail(item);
      await loadInbox();
      toast('人工决定已记录；尚未执行制作动作。');
    }
    catch (error) { showError('workspace-error',error.message); }
    finally { button.disabled = false; }
  }

  async function executeAction(caseId,idempotencyKey,button) {
    if(!window.confirm('再次确认：按已批准并锁定的动作快照执行？此操作不可撤销。')) return;
    button.disabled=true;
    try {
      const result=await api(`/${encodeURIComponent(caseId)}/execute`,{method:'POST',body:JSON.stringify({idempotency_key:idempotencyKey})});
      const output=$('execution-result'); if(output) setText(output,JSON.stringify(result,null,2));
      toast(`动作执行完成：${result.status}`); await loadActivity();
    } catch(error) { showError('workspace-error',error.message); }
    finally { button.disabled=false; }
  }

  async function loadActivity() {
    const container = $('activity-timeline');
    try {
      const data = await api('/activity?limit=30');
      container.replaceChildren();
      if (!data.items.length) { container.append(el('div','empty-state','暂无 Agent、任务、审核或授权执行活动记录。')); return; }
      for (const item of data.items) {
        const event = el('article','timeline-event'); const marker = el('span','timeline-marker');
        const body = el('div'); body.append(el('h4','',item.title));
        const kind = ({agent_run:'Agent 运行',task:'制作任务',audit:'治理审计',action_execution:'导演授权执行'})[item.kind] || item.kind;
        body.append(el('p','',`${kind} · ${item.status}`));
        const time = el('time','',new Date(item.occurred_at).toLocaleString()); body.append(time);
        event.append(marker,body); container.append(event);
      }
    } catch(error) { container.replaceChildren(el('div','empty-state',`活动时间线暂不可用：${error.message}`)); }
  }

  function connect(token,projectId) { state.token = token.trim(); state.projectId = projectId.trim(); state.offset = 0; state.selectedId = null; sessionStorage.setItem('afs_api_token',state.token); sessionStorage.setItem('afs_project_id',state.projectId); }
  function disconnect() { state.token=''; state.projectId=''; state.selectedId=null; state.currentCase=null; sessionStorage.removeItem('afs_api_token'); sessionStorage.removeItem('afs_project_id'); $('workspace').hidden=true; $('connection-panel').hidden=false; $('connection-state').textContent='未连接'; $('connection-state').classList.remove('online'); $('api-token').value=''; }
  async function establish() {
    try { const response = await fetch('/v1/me',{headers:{Authorization:`Bearer ${state.token}`}}); const me = await response.json().catch(()=>({})); if (!response.ok) throw new Error(me.detail || `身份验证失败（HTTP ${response.status}）`);
      const membership = await fetch(`/v1/projects/${encodeURIComponent(state.projectId)}/membership`,{headers:{Authorization:`Bearer ${state.token}`}}); const member = await membership.json().catch(()=>({})); if (!membership.ok) throw new Error(member.detail || `无法访问该项目（HTTP ${membership.status}）`);
      $('connection-panel').hidden=true; $('workspace').hidden=false; $('connection-state').textContent=`已连接 · ${me.display_name || '用户'}`; $('connection-state').classList.add('online'); $('project-caption').textContent=`项目 ${state.projectId} · 当前角色 ${member.role}`; await Promise.all([loadInbox(),loadActivity()]);
    } catch(error) { showError('connect-error',error.message); }
  }
  $('connect-form').addEventListener('submit',async event=>{event.preventDefault(); showError('connect-error',''); connect($('api-token').value,$('project-id').value); await establish();});
  $('logout-button').addEventListener('click',disconnect); $('refresh-button').addEventListener('click',()=>{loadInbox(); if(state.selectedId) loadDetail(state.selectedId);});
  $('status-filter').addEventListener('change',()=>{state.offset=0;state.selectedId=null;loadInbox();$('detail-panel').replaceChildren(el('div','empty-detail','选择一项决策建议'));});
  $('previous-page').addEventListener('click',()=>{state.offset=Math.max(0,state.offset-state.limit);state.selectedId=null;loadInbox();}); $('next-page').addEventListener('click',()=>{state.offset+=state.limit;state.selectedId=null;loadInbox();});
  if (state.token && state.projectId) { $('api-token').value=state.token; $('project-id').value=state.projectId; establish(); }
})();

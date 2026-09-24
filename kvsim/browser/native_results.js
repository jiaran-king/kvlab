(() => {
  const get = id => document.getElementById(id);
  const nfmt = value => value == null ? '—' : Number(value).toLocaleString('zh-CN');
  const pct = value => value == null ? '—' : (Number(value) * 100).toFixed(2) + '%';
  let bundle = null;
  let selected = null;
  let selectedPair = null;
  let capacities = [];

  function pointLabel(key) {
    const s = bundle.runs[key].summary;
    const budget = s.capacity_budget;
    if (budget?.authority === 'physical_blocks') return `${key} · ${nfmt(s.physical_blocks)} 块 / P`;
    if (typeof s.point_id === 'string') return `${key} · ${nfmt(budget?.budget_bytes_per_rank)} 字节 / rank`;
    return `${s.capacity_gib_per_rank} GiB`;
  }
  function cell(text, kind = 'td') {
    const node = document.createElement(kind);
    node.textContent = String(text ?? '—');
    return node;
  }
  function row(parent, values, click, active = false) {
    const tr = document.createElement('tr');
    for (const value of values) tr.append(cell(value));
    if (active) tr.className = 'selected';
    if (click) tr.onclick = click;
    parent.append(tr);
  }
  function checked(data) {
    if (!data || data.schema !== 'kvlab-native-results/v1') throw Error('请选择 kvlab-native-results/v1 结果包');
    const values = data.point_ids || data.capacities_gib || Object.keys(data.runs || {}).map(Number).sort((a, b) => a - b);
    if (!Array.isArray(values) || !values.length || new Set(values.map(String)).size !== values.length || values.some(value => !(Number.isInteger(value) && value > 0) && !(typeof value === 'string' && /^[A-Za-z][A-Za-z0-9_-]{0,63}$/.test(value)))) throw Error('容量列表无效');
    if (Object.keys(data.runs || {}).length !== values.length) throw Error('容量列表与结果点不一致');
    for (const value of values) {
      const key = String(value);
      const run = data.runs?.[key];
      if (!run || !run.summary || !Array.isArray(run.requests) || !Array.isArray(run.events) || !Array.isArray(run.steps)) throw Error(`缺少 ${key} 的完整结果`);
      if ((run.summary.point_id ?? run.summary.capacity_gib_per_rank) !== value) throw Error(`${key} 的摘要容量不一致`);
      if (run.summary.requests_planned !== run.requests.length) throw Error(`${key} 的计划请求行不完整`);
      if (run.requests.filter(item => item.client_complete_step != null).length !== run.summary.requests_completed) throw Error(`${key} 的完成计数与请求行不一致`);
      if (!['complete', 'incomplete', 'not_run'].includes(run.summary.status)) throw Error(`${key} 的状态无效`);
      if (run.summary.status === 'complete' && run.summary.requests_completed !== run.summary.requests_planned) throw Error(`${key} 错误标为完成`);
      if (run.summary.status !== 'complete' && !run.summary.failure_reason) throw Error(`${key} 缺少失败原因`);
      if (run.requests.some((item, index) => item.order !== index)) throw Error(`${key} 的请求顺序无效`);
      const adopted = run.requests.reduce((total, item) => total + item.initial_adopted_tokens, 0);
      const processed = run.requests.reduce((total, item) => total + item.cumulative_input_processing_tokens, 0);
      if (adopted !== run.summary.initial_adopted_cache_tokens || processed !== run.summary.cumulative_input_processing_tokens) throw Error(`${key} 的摘要与逐请求计数不一致`);
      if (run.summary.per_p) {
        const domains = Object.keys(run.summary.per_p);
        if (domains.length !== run.summary.p_domains || run.requests.some(item => !domains.includes(item.p_domain))) throw Error(`${key} 的 P 域与请求落点不一致`);
        for (const metric of ['requests_planned', 'requests_completed', 'actual_input_tokens', 'initial_adopted_cache_tokens', 'cumulative_input_processing_tokens', 'prefix_queries', 'prefix_hits']) {
          if (domains.reduce((total, p) => total + run.summary.per_p[p][metric], 0) !== run.summary[metric]) throw Error(`${key} 的逐 P ${metric} 汇总不一致`);
        }
      }
    }
    const ids = data.runs[String(values[0])].requests.map(request => request.request_id).join('\n');
    if (values.slice(1).some(value => data.runs[String(value)].requests.map(request => request.request_id).join('\n') !== ids)) throw Error('各容量请求顺序不一致');
    if (data.contrast_variant) {
      const variant = data.contrast_variant;
      if (!data.contrast || variant.summary.status !== 'complete' || variant.requests?.length !== data.runs[String(values[0])].requests.length ||
          variant.requests.map(request => request.request_id).join('\n') !== ids ||
          variant.manifest?.run_id !== data.contrast.variant?.evidence?.run_id ||
          !Array.isArray(variant.steps) || !Array.isArray(variant.events)) throw Error('对照变化后运行与结果包不匹配');
    }
    capacities = values.map(String);
    return data;
  }
  function renderCards(run) {
    const summary = run.summary;
    const specs = [
      ['查询命中率', pct(summary.prefix_query_hit_rate), '原生前缀查询口径'],
      ['输入缓存采用', pct(summary.actual_input_cache_fraction), `${nfmt(summary.initial_adopted_cache_tokens)} token`],
      ['累计输入处理', nfmt(summary.cumulative_input_processing_tokens), '包含适用的重复处理；不等于 FLOPs'],
      ['完成请求', `${summary.requests_completed} / ${summary.requests_planned}`, summary.status !== 'complete' ? `${summary.status === 'not_run' ? '未运行' : '未完成'}：${summary.failure_reason || '原因未记录'}` : `${pointLabel(selected)} · ${nfmt(summary.physical_blocks)} 块`],
    ];
    get('nativeCards').replaceChildren();
    for (const [label, value, note] of specs) {
      const box = document.createElement('div'); box.className = 'card';
      box.append(cell(label, 'span'), cell(value, 'strong'), cell(note, 'small'));
      box.firstChild.className = 'caption';
      get('nativeCards').append(box);
    }
  }
  function renderSummary() {
    get('nativeSummary').replaceChildren();
    get('nativeHistorical').replaceChildren();
    get('nativeFrozenPair').replaceChildren();
    get('nativeHistoricalSection').hidden = !(bundle.historical_reference || []).length;
    get('nativeFrozenSection').hidden = !(bundle.historical_frozen_pair || []).length;
    for (const key of capacities) {
      const s = bundle.runs[key].summary;
      const removed = Object.values(s.removed_hash_entries_by_group || {}).reduce((a, b) => a + Number(b), 0);
      row(get('nativeSummary'), [pointLabel(key), `${s.requests_completed}/${s.requests_planned}${s.status !== 'complete' ? ` · ${s.status === 'not_run' ? '未运行' : '未完成'}` : ''}`, pct(s.prefix_query_hit_rate), pct(s.actual_input_cache_fraction), nfmt(s.cumulative_input_processing_tokens), nfmt(removed)], () => select(key), key === selected);
    }
    for (const h of bundle.historical_reference || []) row(get('nativeHistorical'), [h.capacity_gib_per_rank, pct(h.query_hit_rate), nfmt(h.local_compute_tokens), nfmt(h.removed_hash_entries)]);
    for (const h of bundle.historical_frozen_pair || []) row(get('nativeFrozenPair'), [
      `${h.label} / ${h.job}`, h.capacity_gib_per_rank, pct(h.query_hit_rate),
      pct(h.actual_input_cache_fraction), nfmt(h.local_compute_tokens),
      nfmt(h.removed_hash_entries),
    ]);
  }
  function renderPerP(run) {
    const entries = Object.entries(run.summary.per_p || {});
    get('nativePerPSection').hidden = !entries.length;
    get('nativePerP').replaceChildren();
    for (const [domain, s] of entries) {
      const removed = Object.values(s.removed_hash_entries_by_group || {}).reduce((a, b) => a + Number(b), 0);
      row(get('nativePerP'), [domain, `${s.requests_completed}/${s.requests_planned}`, nfmt(s.actual_input_tokens), nfmt(s.initial_adopted_cache_tokens), nfmt(s.cumulative_input_processing_tokens), pct(s.prefix_query_hit_rate), nfmt(s.waiting_request_steps), `${nfmt(s.preemptions)} / ${nfmt(s.resumes)}`, nfmt(s.peak_active_blocks), nfmt(s.peak_reusable_cached_blocks), nfmt(removed)]);
    }
    get('nativeGlobalPeak').textContent = `同一逻辑轮次的全局活跃块峰值：${nfmt(run.summary.peak_active_blocks_global)}。空 P 的命中比例显示为「—」。`;
  }
  function renderContrast() {
    const contrast = bundle.contrast;
    get('nativeContrastSection').hidden = !contrast;
    get('nativeContrastRequests').replaceChildren();
    if (!contrast) return;
    const baseline = contrast.baseline?.evidence || {};
    const variant = contrast.variant?.evidence || {};
    const mode = ({'capacity-only': '仅容量', 'single-variable': '单变量', 'deployment-conditional': '部署条件联合变化'})[contrast.mode] || contrast.mode;
    get('nativeContrast').textContent = [
      `比较类型：${mode}${contrast.variable ? `（${contrast.variable}）` : ''}`,
      contrast.effective_capacity_changed === false ? '有效容量未变化；此对照不代表扩容收益。' : '',
      `运行：${baseline.run_id || '—'} → ${variant.run_id || '—'}`,
      `累计输入处理差值（基线−变化后）：${nfmt(contrast.delta_processed_tokens)} token；相对减少 ${pct(contrast.relative_processed_reduction)}`,
      `预算来源：${baseline.budget_source || 'unknown'} → ${variant.budget_source || 'unknown'}；路由来源：${baseline.routing_source || 'unknown'} → ${variant.routing_source || 'unknown'}`,
      `目标缓存配置：${baseline.target_profile || '—'} → ${variant.target_profile || '—'}；实机 AFD 收益证据：${contrast.real_deployment_conclusion_supported ? '已满足声明的证据门槛' : '尚未满足'}`,
      `变化后逐请求事件：${bundle.contrast_variant ? '已随结果包保存' : '未附带，详情仅显示对照数值'}`,
      `变化条件：${JSON.stringify(contrast.changed_conditions || {})}`,
      ...(['baseline', 'variant'].flatMap(side => Object.entries(contrast.per_p?.[side] || {}).map(([domain, stats]) =>
        `${side === 'baseline' ? '基线' : '变化后'} ${domain}：完成 ${stats.requests_completed}/${stats.requests_planned}，采用 ${nfmt(stats.initial_adopted_cache_tokens)}，累计处理 ${nfmt(stats.cumulative_input_processing_tokens)}，查询命中 ${pct(stats.prefix_query_hit_rate)}，等待请求步 ${nfmt(stats.waiting_request_steps)}，抢占／恢复 ${nfmt(stats.preemptions)} / ${nfmt(stats.resumes)}`))),
      ...((contrast.evidence_gaps || []).map(gap => `待验证：${gap}`)),
      contrast.interpretation || '',
    ].join('\n');
    for (const change of contrast.request_changes || []) {
      const button = document.createElement('button');
      button.textContent = `请求 ${change.order} · ${change.baseline_p}→${change.variant_p} · 采用 ${nfmt(change.baseline_adopted)}→${nfmt(change.variant_adopted)} · 处理 ${nfmt(change.baseline_processed)}→${nfmt(change.variant_processed)}`;
      button.onclick = () => showRequest(change.request_id);
      get('nativeContrastRequests').append(button);
    }
  }
  function renderDiff() {
    get('nativeDiff').replaceChildren();
    for (const pair of Object.keys(bundle.comparison || {})) {
      const entry = bundle.comparison?.[pair];
      if (!entry) continue;
      const [left, right] = pair.split('_vs_');
      const button = document.createElement('button');
      button.textContent = `${pointLabel(left)} / ${pointLabel(right)} · 请求 ${entry.order} · 采用 ${nfmt(entry.left.initial_adopted_tokens)} / ${nfmt(entry.right.initial_adopted_tokens)}`;
      button.onclick = () => { selectedPair = pair; select(left); showRequest(entry.request_id); };
      get('nativeDiff').append(button);
    }
    if (!get('nativeDiff').children.length) get('nativeDiff').textContent = bundle.status === 'incomplete'
      ? '存在未完成容量点；可比较的完整点没有首个请求差异。'
      : '所选容量点的请求采用量与累计处理量没有差异。';
  }
  function eventsNear(run, request) {
    const step = request.first_scheduled_step;
    if (step == null) return {};
    const counts = {};
    for (const event of run.events) {
      if (event.kind !== 'native_kv_event' || event.step < step - 2 || event.step > step + 1 || (event.p_domain || 'p0') !== (request.p_domain || 'p0')) continue;
      const key = `${event.event} / 组 ${event.data?.group_idx ?? '?'}`;
      counts[key] = (counts[key] || 0) + (event.data?.block_hashes?.length || 0);
    }
    return counts;
  }
  function showRequest(requestId) {
    const run = bundle.runs[selected];
    const request = run.requests.find(item => item.request_id === requestId);
    if (!request) return;
    const cross = Object.fromEntries(capacities.map(key => [key, bundle.runs[key].requests[request.order]]));
    const snapshot = run.steps.find(item => item.step === request.first_scheduled_step && (item.p_domain || 'p0') === (request.p_domain || 'p0'));
    const candidates = Object.entries(bundle.evidence?.findings || {});
    const first = candidates.find(([pair, item]) => pair === selectedPair && item?.request_id === requestId)
      || candidates.find(([pair, item]) => pair.split('_vs_').includes(selected) && item?.request_id === requestId);
    const comparison = capacities.map(key => `${pointLabel(key)}：采用 ${nfmt(cross[key].initial_adopted_tokens)}，累计处理 ${nfmt(cross[key].cumulative_input_processing_tokens)} token，抢占 ${cross[key].preemptions} 次`).join('\n');
    const match = first?.[1];
    const contrastChange = (bundle.contrast?.request_changes || []).find(item => item.request_id === requestId);
    const variantRun = bundle.contrast_variant;
    const variantRequest = variantRun?.requests.find(item => item.request_id === requestId);
    const variantSnapshot = variantRequest && variantRun.steps.find(item =>
      item.step === variantRequest.first_scheduled_step &&
      (item.p_domain || 'p0') === (variantRequest.p_domain || 'p0'));
    const side = match && (String(match.left_point_id ?? match.left_gib) === selected ? match.left : String(match.right_point_id ?? match.right_gib) === selected ? match.right : null);
    const related = side?.matching_prefix_events || [];
    const summary = [
      `请求 ${request.order} · ${requestId} · ${request.p_domain || 'p0'} · 输入 ${nfmt(request.input_tokens)} token`,
      comparison,
      contrastChange ? `对照 ${bundle.contrast.mode}：P ${contrastChange.baseline_p}→${contrastChange.variant_p}，累计处理 ${nfmt(contrastChange.baseline_processed)}→${nfmt(contrastChange.variant_processed)} token。` : '',
      variantSnapshot ? `变化后 ${variantRequest.p_domain || 'p0'} 首次调度第 ${variantSnapshot.step} 步；当时空闲块 ${nfmt(variantSnapshot.free_blocks_before)}，附近记录事件 ${Object.values(eventsNear(variantRun, variantRequest)).reduce((a, b) => a + b, 0)} 个 hash 条目。` : '',
      snapshot ? `${pointLabel(selected)} 首次调度第 ${snapshot.step} 步：调度前活跃请求 ${snapshot.running_before?.length ?? '—'}，空闲块 ${nfmt(snapshot.free_blocks_before)}，调度后空闲块 ${nfmt(snapshot.free_blocks_after_schedule)}。` : '该容量没有首次调度记录。',
      match ? `候选前缀追踪到 ${nfmt(match.prefix_hash_limit_tokens)} token；已记录的相关缓存事件 ${related.length} 条${side?.matching_prefix_events_truncated ? '（仅展示前 100 条）' : ''}。` : '此请求没有完整的首差前缀事件证据。',
      ...related.slice(-5).map(event => `第 ${event.step} 步 · 组 ${event.group} · ${event.event} · 前缀终点 ${event.prefix_end_positions.join('、')} token`),
      `证据边界：${run.summary.events_coverage}。记录中的移除与命中变化可能相关；缺少连续状态记录时不判定唯一原因。`,
    ];
    get('nativeDetailSummary').textContent = summary.join('\n');
    const detail = {
      request_id: requestId,
      run_id: run.manifest.run_id || null,
      p_domain: request.p_domain || 'p0',
      input_sha256: request.input_sha256 || null,
      capacity_status: run.summary.status,
      failure_reason: run.summary.failure_reason,
      order: request.order,
      session_id: request.session_id,
      input_tokens: request.input_tokens,
      by_capacity: Object.fromEntries(Object.entries(cross).map(([key, value]) => [key, {
        adopted_tokens: value.initial_adopted_tokens,
        cumulative_input_processing_tokens: value.cumulative_input_processing_tokens,
        unique_local_input_tokens: value.unique_local_input_tokens ?? null,
        repeated_local_input_tokens: value.repeated_local_input_tokens ?? null,
        completed_input_intervals: value.completed_input_intervals ?? null,
        first_scheduled_step: value.first_scheduled_step,
        prefill_complete_step: value.prefill_complete_step,
        transfer_complete_step: value.transfer_complete_step,
        p_reference_release_step: value.p_reference_release_step,
        client_complete_step: value.client_complete_step,
        preemptions: value.preemptions,
      }])),
      selected_capacity_step_state: snapshot || '未记录',
      selected_capacity_native_events_near_admission: eventsNear(run, request),
      native_event_coverage: run.summary.events_coverage,
      selected_comparison_pair: first?.[0] || null,
      first_difference_evidence: first?.[1] || null,
      contrast_request_change: contrastChange || null,
      contrast_variant_evidence: variantRequest ? {
        run_id: variantRun.manifest.run_id,
        request: variantRequest,
        first_schedule_state: variantSnapshot || null,
        native_events_near_admission: eventsNear(variantRun, variantRequest),
        event_coverage: variantRun.summary.events_coverage,
      } : null,
      interpretation: '事件与占用记录是证据；同时发生的移除不自动证明是该请求未命中的唯一原因。',
    };
    get('nativeDetailText').textContent = JSON.stringify(detail, null, 2);
    get('nativeDetail').showModal();
  }
  function renderRequests() {
    const run = bundle.runs[selected];
    const query = get('nativeFilter').value.trim().toLowerCase();
    get('nativeRequests').replaceChildren();
    for (const request of run.requests) {
      if (query && !`${request.request_id} ${request.session_id} ${request.actor_id} ${request.p_domain || 'p0'}`.toLowerCase().includes(query)) continue;
      row(get('nativeRequests'), [request.order, request.p_domain || 'p0', request.request_id, request.session_id.slice(0, 8), nfmt(request.input_tokens), nfmt(request.initial_adopted_tokens), nfmt(request.cumulative_input_processing_tokens), request.first_scheduled_step == null || request.submitted_step == null ? '—' : request.first_scheduled_step - request.submitted_step, request.preemptions], () => showRequest(request.request_id));
    }
    get('nativeCoverage').textContent = `原生事件覆盖：${run.summary.events_coverage}。${run.summary.status !== 'complete' ? `运行未完成：${run.summary.failure_reason}。全部计划请求行已保留，指标仅覆盖已执行步骤。` : '运行完成。'}点击请求查看相关状态。`;
  }
  function select(key) {
    selected = key;
    get('nativeCapacity').value = key;
    renderSummary(); renderCards(bundle.runs[key]); renderPerP(bundle.runs[key]); renderRequests();
    get('nativeProvenance').textContent = JSON.stringify(bundle.runs[key].manifest, null, 2);
  }
  function render() {
    get('nativeBody').classList.remove('hidden');
    get('nativeCapacity').replaceChildren();
    for (const key of capacities) {
      const option = cell(pointLabel(key), 'option'); option.value = key;
      get('nativeCapacity').append(option);
    }
    renderContrast(); renderDiff(); select(selected);
  }
  get('nativeFile').onchange = async () => {
    const file = get('nativeFile').files?.[0];
    if (!file) return;
    get('nativeStatus').textContent = `正在读取 ${file.name}…`;
    try {
      bundle = checked(JSON.parse(await file.text()));
      selected = capacities[0]; selectedPair = null; render();
      get('nativeStatus').textContent = `已导入 ${file.name} · ${bundle.status === 'incomplete' ? '含未完成容量点' : `${capacities.length} 档运行完成`} · ${bundle.runs[selected].requests.length} 条计划请求`;
    } catch (error) {
      bundle = null;
      get('nativeBody').classList.add('hidden');
      get('nativeStatus').textContent = `导入失败：${error.message}`;
    }
    get('nativeFile').value = '';
  };
  get('nativeCapacity').onchange = event => select(event.target.value);
  get('nativeFilter').oninput = renderRequests;
  get('nativeDetailClose').onclick = () => get('nativeDetail').close();
})();

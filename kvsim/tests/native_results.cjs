/* DOM-only test of the read-only native result viewer. */
'use strict';
const fs = require('node:fs');
const vm = require('node:vm');
const assert = require('node:assert/strict');

class Element {
  constructor() {
    this.value = '';
    this.textContent = '';
    this.children = [];
    this.files = [];
    this.className = '';
    this.hidden = false;
    this.classList = {
      add: name => { if (name === 'hidden') this.hidden = true; },
      remove: name => { if (name === 'hidden') this.hidden = false; },
    };
  }
  append(...children) { this.children.push(...children); }
  replaceChildren() { this.children = []; }
  get firstChild() { return this.children[0]; }
  showModal() { this.open = true; }
  close() { this.open = false; }
}

const html = fs.readFileSync('kvsim/KVLab.html', 'utf8');
const elements = new Map([...html.matchAll(/id="([^"]+)"[^>]*>/g)].map(match => [match[1], new Element()]));
const get = id => elements.get(id);
const document = { getElementById: get, createElement: () => new Element() };
const script = html.match(/<script id="nativeResults">\n([\s\S]*?)\n<\/script>/)?.[1];
assert(script, 'built HTML contains native result viewer');
vm.runInNewContext(script, { document, console });

(async () => {
  const path = 'output/kvsim/native-stage-a/review-main-effective-profile-425/native-results.json';
  get('nativeFile').files = [{ name: 'native-results.json', text: async () => fs.readFileSync(path, 'utf8') }];
  await get('nativeFile').onchange();
  assert(!get('nativeBody').hidden);
  assert(get('nativeStatus').textContent.includes('425 条计划请求'));
  assert.equal(get('nativeRequests').children.length, 425);
  assert.equal(get('nativeSummary').children.length, 3);
  assert.equal(get('nativeHistorical').children.length, 3);
  assert.equal(get('nativeFrozenPair').children.length, 2);
  assert(JSON.parse(get('nativeProvenance').textContent).workload_content_source === 'historical_capture');
  assert(get('nativeCards').children[0].children[1].textContent.includes('90.53%'));

  get('nativeCapacity').onchange({ target: { value: '24' } });
  assert.equal(get('nativeCapacity').value, '24');
  assert(get('nativeCards').children[0].children[1].textContent.includes('92.14%'));
  get('nativeFilter').value = 'c67b0a86';
  get('nativeFilter').oninput();
  assert.equal(get('nativeRequests').children.length, 1);
  get('nativeRequests').children[0].onclick();
  assert(get('nativeDetail').open);
  const detail = JSON.parse(get('nativeDetailText').textContent);
  assert.equal(detail.by_capacity['12'].adopted_tokens, 0);
  assert.equal(detail.by_capacity['24'].adopted_tokens, 36352);
  get('nativeDetailClose').onclick();
  assert(!get('nativeDetail').open);

  const dynamic = JSON.parse(fs.readFileSync(path, 'utf8'));
  dynamic.capacities_gib = [16, 24];
  dynamic.runs['16'] = dynamic.runs['12'];
  delete dynamic.runs['12'];
  dynamic.runs['16'].summary.capacity_gib_per_rank = 16;
  delete dynamic.runs['48'];
  dynamic.comparison = { '16_vs_24': dynamic.comparison['12_vs_24'] };
  dynamic.historical_reference = [];
  dynamic.historical_frozen_pair = [];
  get('nativeFile').files = [{ name: 'dynamic.json', text: async () => JSON.stringify(dynamic) }];
  await get('nativeFile').onchange();
  assert.equal(get('nativeSummary').children.length, 2);
  assert.equal(get('nativeCapacity').value, '16');
  assert(get('nativeHistoricalSection').hidden);
  get('nativeDiff').children[0].onclick();
  assert(get('nativeDetailSummary').textContent.includes('16 GiB'));
  get('nativeDetailClose').onclick();

  const newRun = 'output/kvsim/native-v1/scan-16-24/native-results.json';
  get('nativeFilter').value = '';
  get('nativeFile').files = [{ name: 'new-run.json', text: async () => fs.readFileSync(newRun, 'utf8') }];
  await get('nativeFile').onchange();
  assert(get('nativeStatus').textContent.includes('2 档运行完成'));
  assert(get('nativeStatus').textContent.includes('76 条计划请求'));
  assert.equal(get('nativeSummary').children.length, 2);
  assert.equal(get('nativeRequests').children.length, 76);
  assert(get('nativeHistoricalSection').hidden);
  assert(get('nativeDiff').textContent.includes('没有'));
  assert.equal(JSON.parse(get('nativeProvenance').textContent).capacity_budget.budget_gib_per_rank, 16);
  get('nativeCapacity').onchange({ target: { value: '24' } });
  assert.equal(get('nativeCapacity').value, '24');
  assert.equal(JSON.parse(get('nativeProvenance').textContent).capacity_budget.budget_gib_per_rank, 24);

  const v2Run = 'output/kvsim/native-v2/scan-1p-16/native-results.json';
  get('nativeFile').files = [{ name: 'v2-one-p.json', text: async () => fs.readFileSync(v2Run, 'utf8') }];
  await get('nativeFile').onchange();
  assert.equal(get('nativePerP').children.length, 1);
  assert(!get('nativePerPSection').hidden);
  assert(get('nativeGlobalPeak').textContent.includes('全局活跃块峰值'));
  assert.equal(get('nativeRequests').children[0].children[1].textContent, 'p0');
  const v2Contrast = JSON.parse(fs.readFileSync(v2Run, 'utf8'));
  v2Contrast.contrast = {
    schema: 'kvlab-native-contrast/v1', mode: 'capacity-only', variable: null,
    delta_processed_tokens: 0, relative_processed_reduction: 0,
    changed_conditions: { physical_blocks_per_p: [1, 2] },
    baseline: { evidence: { run_id: 'a', budget_source: 'assumed', routing_source: 'policy_generated', target_profile: 'h20' } },
    variant: { evidence: { run_id: 'b', budget_source: 'assumed', routing_source: 'policy_generated', target_profile: 'h20' } },
    real_deployment_conclusion_supported: false, evidence_gaps: ['target baseline missing'],
    interpretation: 'Logical processing only',
  };
  get('nativeFile').files = [{ name: 'contrast.json', text: async () => JSON.stringify(v2Contrast) }];
  await get('nativeFile').onchange();
  assert(get('nativeContrast').textContent.includes('仅容量'));
  assert(get('nativeContrast').textContent.includes('target baseline missing'));

  const twoP = 'output/kvsim/native-v2/scan-2p-final/native-results.json';
  get('nativeFile').files = [{ name: 'v2-two-p.json', text: async () => fs.readFileSync(twoP, 'utf8') }];
  await get('nativeFile').onchange();
  assert.equal(get('nativePerP').children.length, 2);
  assert(get('nativeContrast').textContent.includes('assumed'));
  assert(get('nativeContrast').textContent.includes('尚未满足'));
  assert.equal(get('nativePerP').children[0].children[9].textContent, '8,096');
  get('nativeFilter').value = 'p1';
  get('nativeFilter').oninput();
  assert.equal(get('nativeRequests').children.length, 11);
  get('nativeRequests').children[0].onclick();
  assert.equal(JSON.parse(get('nativeDetailText').textContent).p_domain, 'p1');
  get('nativeDetailClose').onclick();
  get('nativeFilter').value = '';

  const deployment = 'output/kvsim/native-v2/contrast-deployment/native-results.json';
  get('nativeFile').files = [{ name: 'deployment.json', text: async () => fs.readFileSync(deployment, 'utf8') }];
  await get('nativeFile').onchange();
  assert(get('nativeContrast').textContent.includes('部署条件联合变化'));
  assert.equal(get('nativeContrastRequests').children.length, 11);
  get('nativeContrastRequests').children[0].onclick();
  assert(JSON.parse(get('nativeDetailText').textContent).contrast_request_change);
  assert(JSON.parse(get('nativeDetailText').textContent).contrast_variant_evidence);
  get('nativeDetailClose').onclick();

  const incomplete = 'output/kvsim/native-stage-a/failure-1step/native-results.json';
  get('nativeFile').files = [{ name: 'incomplete.json', text: async () => fs.readFileSync(incomplete, 'utf8') }];
  await get('nativeFile').onchange();
  assert(!get('nativeBody').hidden);
  assert(get('nativeStatus').textContent.includes('含未完成容量点'));
  assert(get('nativeCards').children[3].children[1].textContent.includes('0 / 425'));
  assert(get('nativeCoverage').textContent.includes('运行未完成'));
  get('nativeFilter').value = '';
  get('nativeFilter').oninput();
  assert.equal(get('nativeRequests').children.length, 425);
  get('nativeRequests').children[0].onclick();
  assert.equal(JSON.parse(get('nativeDetailText').textContent).capacity_status, 'incomplete');
  get('nativeDetailClose').onclick();

  const exact = 'output/kvsim/native-v2/scan-exact-active/native-results.json';
  get('nativeFile').files = [{ name: 'exact.json', text: async () => fs.readFileSync(exact, 'utf8') }];
  await get('nativeFile').onchange();
  assert(!get('nativeBody').hidden);
  assert.equal(get('nativeCapacity').value, 'low');
  assert(get('nativeCapacity').children[0].textContent.includes('623,808,017'));
  get('nativeCapacity').onchange({ target: { value: 'high' } });
  assert(get('nativeCapacity').children[1].textContent.includes('2,000 块'));
  assert.equal(JSON.parse(get('nativeProvenance').textContent).capacity_budget.budget_bytes_per_rank, null);
  get('nativeRequests').children[0].onclick();
  assert.equal(JSON.parse(get('nativeDetailText').textContent).by_capacity.high.unique_local_input_tokens, 1024);
  get('nativeDetailClose').onclick();

  get('nativeFile').files = [{ name: 'bad.json', text: async () => '{bad' }];
  await get('nativeFile').onchange();
  assert(get('nativeBody').hidden);
  assert(get('nativeStatus').textContent.includes('导入失败'));
  console.log('PASS native result viewer: historical/new/incomplete import, capacity switch, request evidence, invalid import');
})().catch(error => { console.error(error); process.exitCode = 1; });

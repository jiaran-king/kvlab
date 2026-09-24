"""Build the single-file offline app; no runtime server or dependencies."""
import json
from pathlib import Path
ROOT = Path(__file__).resolve().parent
plan = ROOT.parent / 'output/ascend-handoff/Ascend910C_KV_Replay_425/workload/reference-plan.json'
core = (ROOT / 'browser/core.js').read_text()
embedded = '<script id="simCore" type="text/javascript">' + core.replace('</script', '<\\/script') + '</script>\n'
legacy_plan = json.loads(plan.read_text()) if plan.exists() else None
embedded += '<script id="builtinPlan" type="application/json">' + json.dumps(legacy_plan, ensure_ascii=False, separators=(',', ':')).replace('<', '\\u003c') + '</script>\n'
template = (ROOT / 'browser/template.html').read_text()
native_view = (ROOT / 'browser/native_results.html').read_text()
native_js = (ROOT / 'browser/native_results.js').read_text()
native_script = '<script id="nativeResults">\n' + native_js.replace('</script', '<\\/script') + '\n</script>'
for marker in ('<!-- NATIVE_VIEWER -->', '<!-- OFFLINE_CORE -->', '<!-- NATIVE_SCRIPT -->'):
    if template.count(marker) != 1:
        raise ValueError(f'expected one {marker} in template')
output = (template.replace('<!-- NATIVE_VIEWER -->', native_view)
          .replace('<!-- OFFLINE_CORE -->', embedded)
          .replace('<!-- NATIVE_SCRIPT -->', native_script))
(ROOT / 'KVLab.html').write_text(output)
print(ROOT / 'KVLab.html')

"""Offline AgentInfer adapter. No HTTP clients or inference are constructed.

Use Python 3.12 with the original Replay dependencies and local tokenizers.
The AgentInfer source directory is an explicit input, not a copied implementation.
"""
from __future__ import annotations
from dataclasses import asdict
import argparse
import asyncio
import hashlib
import importlib.util
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
SCHEMA = 'kvlab-replay-workload/v1'


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def load_replay(source):
    source = Path(source).resolve()
    if not (source/'agentbench/replay/prompt.py').is_file():
        raise ValueError('Expected a source directory containing agentbench/replay')
    sys.path.insert(0, str(source))
    from agentbench.replay.config import ReplayBenchConfig
    from agentbench.replay.analyzer import analyze_replay_trace
    from agentbench.replay.planner import build_replay_plan
    from agentbench.replay.prompt import PromptBuilder, PromptExchange, TokenizerClient
    return ReplayBenchConfig, analyze_replay_trace, build_replay_plan, PromptBuilder, PromptExchange, TokenizerClient


def make_tokenizer(client_type, tokenizer_path):
    from tokenizers import Tokenizer
    path = Path(tokenizer_path)
    if not path.is_file():
        raise ValueError('A complete local tokenizer.json is required; tokenizer_config.json is insufficient')
    spec = importlib.util.spec_from_file_location('kvlab_dsv4_encoding', ROOT/'source/vllm/vllm/tokenizers/deepseek_v4_encoding.py')
    encoding = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(encoding)

    class LocalTokenizer(client_type):
        def __init__(self):
            # Deliberately do not call the HTTP TokenizerClient constructor.
            self.engine = Tokenizer.from_file(str(path))
            self._token_ids = {}
            self._text_cache = {}
            self.model = 'offline'

        async def close(self):
            pass

        async def text_token_ids(self, text):
            return tuple(self.engine.encode(text, add_special_tokens=False).ids)

        async def detokenize_tokens(self, tokens):
            return self.engine.decode(list(tokens), skip_special_tokens=False)

        def render(self, prompt):
            payload = prompt.tokenizer_payload(self.model)
            messages = []
            for original in payload['messages']:
                message = dict(original)
                content = message.get('content')
                if content is None:
                    content = ''
                elif isinstance(content, (list, tuple)):
                    texts=[]
                    for part in content:
                        if isinstance(part, str):
                            text=part
                        elif isinstance(part, dict) and part.get('type') == 'text' and isinstance(part.get('text'), str):
                            text=part['text']
                        else:
                            raise ValueError('Offline DSV4 adapter supports text content parts only')
                        if text: texts.append(text)
                    # Frozen chat_utils string-content path filters empty parts
                    # before joining nonempty text parts with a newline.
                    content='\n'.join(texts)
                if not isinstance(content, str):
                    raise ValueError('Unsupported message content')
                message['content']=content
                messages.append(message)
            # Same tools insertion and default chat-mode encoding as the frozen
            # vLLM DeepseekV4Tokenizer.apply_chat_template wrapper.
            if payload.get('tools'):
                messages.insert(0, {'role':'system', 'tools':payload['tools']})
            return encoding.encode_messages(messages, thinking_mode='chat', drop_thinking=True, reasoning_effort=None)

        async def input_tokens(self, prompt):
            return await self.text_token_ids(self.render(prompt))

        async def count(self, prompt):
            return len(await self.input_tokens(prompt))

    return LocalTokenizer()


async def export(args):
    Config, analyze, plan_builder, PromptBuilder, Exchange, Client = load_replay(args.agentinfer_source)
    raw = json.loads(Path(args.config).read_text())
    raw['replay']['trace_path'] = str(Path(args.trace).resolve())
    config = Config.model_validate(raw)
    if config.replay.trace_type != 'agentinfer':
        raise ValueError('This exporter currently supports AgentInfer JSONL traces only')
    analysis = analyze(Path(args.trace))
    plan = plan_builder(config, analysis)  # planner invokes the real sampler
    # Structural plans deliberately report calibration pending; builder below performs it.
    capture = json.loads(Path(args.captures).read_text()) if args.captures else None
    if capture is not None:
        if capture.get('schema') != 'kvlab-token-capture/v1':
            raise ValueError('Expected kvlab-token-capture/v1 with inputs keyed by runtime_request_id')
        if not all(capture.get('metadata',{}).get(k) for k in ('tokenizer_sha256','prompt_template')):
            raise ValueError('Capture metadata must identify tokenizer_sha256 and prompt_template')
        tokenizer = None
    else:
        if not args.tokenizer:
            raise ValueError('Supply --captures or a complete --tokenizer tokenizer.json; no length-only fallback')
        if config.backend.endpoint != '/v1/chat/completions':
            raise ValueError('Offline renderer supports the frozen DSV4 chat/completions default chat mode only')
        tokenizer = make_tokenizer(Client, args.tokenizer)
    builder = PromptBuilder(config, tokenizer) if tokenizer else None
    requests=[]
    for task in plan.tasks:
        ids={n.source_key:n.runtime_request_id for n in task.requests}
        exchanges={}
        pending=list(task.requests)
        while pending:
            ready=next((n for n in pending if not n.context_after or n.context_after in exchanges or capture is not None),None)
            if ready is None:
                raise ValueError('Context dependencies cannot be constructed offline')
            n=ready
            row=dict(runtime_request_id=n.runtime_request_id,runtime_session_id=task.runtime_session_id,
                     source_key=n.source_key,actor_id=n.actor_id,actor_role=n.actor_role,
                     node_type=n.node_type,send_after=ids.get(n.send_after),context_after=ids.get(n.context_after),
                     context_mode=n.context_mode,effective_interval_seconds=n.effective_interval_seconds)
            if n.node_type=='timing_dependency':
                row['effective_duration_seconds']=n.effective_duration_seconds or 0
            elif capture is not None:
                if n.runtime_request_id not in capture['inputs']:
                    raise ValueError('Missing capture for runtime request '+n.runtime_request_id)
                c=capture['inputs'][n.runtime_request_id]
                tokens=c['tokens']
                row.update(tokens=tokens,input_tokens=len(tokens),output_tokens=c['output_tokens'],cache_identity=c.get('cache_identity',''),content_source='captured_tokens')
            else:
                prompt=await builder.build(task,n,exchanges.get(n.context_after))
                tokens=list(await tokenizer.input_tokens(prompt))
                output=await tokenizer.token_text(n.runtime_request_id+'/output',n.planned_output_tokens)
                measured_output=len(await tokenizer.text_token_ids(output))
                exchanges[n.source_key]=Exchange(prompt,output)
                row.update(tokens=tokens,input_tokens=len(tokens),output_tokens=measured_output,
                           planned_input_tokens=n.planned_input_tokens,planned_output_tokens=n.planned_output_tokens,
                           cache_identity='',content_source='trace_driven_synthetic',
                           calibration=asdict(prompt.calibration) if prompt.calibration else None)
            if row['node_type']=='request':
                if not row['tokens'] or any(type(t) is not int or t<0 for t in row['tokens']):
                    raise ValueError('Invalid token capture: '+n.runtime_request_id)
                if type(row['output_tokens']) is not int or row['output_tokens']<0:
                    raise ValueError('Invalid output token count')
            requests.append(row);pending.remove(n)
    # Preserve the upstream plan order, independently of construction order.
    order={n.runtime_request_id:i for i,n in enumerate(n for t in plan.tasks for n in t.requests)}
    requests.sort(key=lambda r:order[r['runtime_request_id']])
    profile=getattr(args,'execution_profile','upstream-session')
    admission_patch=getattr(args,'admission_patch',None)
    if profile=='request-admission' and not admission_patch:
        raise ValueError('request-admission profile requires --admission-patch for provenance')
    modules=['analyzer.py','sampler.py','planner.py','prompt.py','config.py','timing.py']
    metadata=dict(exporter_version='0.3.0',source_trace=str(Path(args.trace).resolve()),source_sha256=digest(args.trace),
                  agentinfer_commit=args.agentinfer_commit,source_modules={m:digest(Path(args.agentinfer_source)/'agentbench/replay'/m) for m in modules},
                  planner_version=plan.planner_version,replay_config=config.model_dump(mode='json'),seed=config.replay.sample_seed,
                  model=config.backend.model,tokenizer_sha256=digest(args.tokenizer) if tokenizer else capture.get('metadata',{}).get('tokenizer_sha256'),
                  prompt_template='frozen-vllm-dsv4-chat-default' if tokenizer else capture.get('metadata',{}).get('prompt_template'),
                  content_source='trace_driven_synthetic' if tokenizer else 'captured_tokens',
                  time_unit='seconds',session_concurrency=len(plan.tasks) if profile=='request-admission' else config.experiment.max_concurrency,
                  execution_profile=profile,execution_defaults={'session_concurrency':len(plan.tasks) if profile=='request-admission' else config.experiment.max_concurrency,'concurrency':config.experiment.max_concurrency if profile=='request-admission' else 2000},
                  sessions=[dict(id=t.runtime_session_id,launch_order=t.task_index,arrival_seconds=0) for t in plan.tasks],
                  assumptions=['Dependencies inferred by the selected AgentInfer analyzer.',
                               'Output text is a deterministic substitute, not model inference.' if tokenizer else 'Inputs supplied as runtime-bound captures.'])
    if admission_patch:metadata['admission_patch']={'path':str(Path(admission_patch).resolve()),'sha256':digest(admission_patch)}
    metadata['assumptions'].append('Stable virtual scheduling does not reproduce HTTP race or Prompt preparation times.')
    if tokenizer:metadata['prompt_template_sha256']=digest(ROOT/'source/vllm/vllm/tokenizers/deepseek_v4_encoding.py')
    result=dict(schema=SCHEMA,metadata=metadata,requests=requests)
    Path(args.output).parent.mkdir(parents=True,exist_ok=True)
    Path(args.output).write_text(json.dumps(result,ensure_ascii=False,separators=(',',':')))
    print(json.dumps({'output':args.output,'requests':sum(r['node_type']=='request' for r in requests),'sessions':len(plan.tasks),'content_source':metadata['content_source']}))


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--agentinfer-source',required=True)
    p.add_argument('--agentinfer-commit',required=True,help='Base commit; actual module digests also recorded')
    p.add_argument('--trace',required=True);p.add_argument('--config',required=True)
    group=p.add_mutually_exclusive_group(required=True);group.add_argument('--captures');group.add_argument('--tokenizer')
    p.add_argument('--execution-profile',choices=['upstream-session','request-admission'],default='upstream-session')
    p.add_argument('--admission-patch',help='Source path of the historical request admission override; recorded, never executed')
    p.add_argument('--output',required=True)
    args=p.parse_args()
    asyncio.run(export(args))

if __name__=='__main__':main()

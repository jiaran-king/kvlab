from agentinfer.agentbench.replay.config import ReplayBenchConfig

def make_config(base, run):
    return ReplayBenchConfig.model_validate({
     'experiment':{'task_num':None,'max_concurrency':3,'result_dir':str(run/'replay'),'task_timeout_seconds':5400,'run_timeout_seconds':5700},
     'backend':{'base_url':'http://127.0.0.1:18400','tokenizer_base_url':'http://127.0.0.1:18401','metrics_url':'http://127.0.0.1:18401/metrics','model':'dsv4-replay','endpoint':'/v1/chat/completions','tool_choice':'none'},
     'replay':{'trace_path':str(base/'stage-v4/successful-425-trace.jsonl'),'sample_seed':0,'interval_mode':'trace','trace_same_agent_gap_scale':0.1,'trace_same_agent_gap_offset_seconds':0,'max_input_tokens':None,'max_output_tokens':None,'context_adjustment_mode':'adaptive','request_timeout_seconds':900}})

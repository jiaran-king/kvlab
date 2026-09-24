"""Check RDMA initialization before spending minutes loading model weights."""
import json,resource
from mooncake.engine import TransferEngine
from vllm.utils.network_utils import get_ip
print(json.dumps({'memlock':resource.getrlimit(resource.RLIMIT_MEMLOCK),'ip':get_ip()}),flush=True)
engine=TransferEngine()
result=engine.initialize(get_ip(),'P2PHANDSHAKE','rdma','')
print(json.dumps({'initialize_result':result}),flush=True)
assert result==0,'RDMA initialization still fails; do not load model'

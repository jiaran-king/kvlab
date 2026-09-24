#!/bin/bash
#SBATCH --partition=h20
#SBATCH --cpus-per-task=2
#SBATCH --mem=8G
#SBATCH --time=00:10:00
#SBATCH --output=/home/david_cwq/zhouziheng/kvlab-native/import-probe-%j.log

set -euo pipefail
runtime=/home/david_cwq/zhouziheng/agent-replay-20260917/runtime/bin/python
echo "job=${SLURM_JOB_ID} host=$(hostname) cpus=${SLURM_CPUS_PER_TASK}"
date -u
free -h
df -h /home/david_cwq/zhouziheng
bad_processes_before=$(ps -eo stat,ppid,pid,comm --no-headers | awk '$1 ~ /^[DZ]/ {print}')
printf '%s\n' "$bad_processes_before"
sleep 5
bad_processes_after=$(ps -eo stat,ppid,pid,comm --no-headers | awk '$1 ~ /^[DZ]/ {print}')
if [[ "$bad_processes_after" != "$bad_processes_before" ]]; then
  echo "D/Z process state changed during preflight; stopping before Python import" >&2
  printf '%s\n' "$bad_processes_after" >&2
  exit 2
fi
if command -v nvidia-smi >/dev/null; then
  nvidia-smi --query-compute-apps=pid,process_name --format=csv,noheader | head -10 || true
fi
echo python-start
"$runtime" - <<'PY'
import hashlib
import inspect
import json
import vllm
from vllm.v1.core.sched.scheduler import Scheduler
from vllm.v1.core.kv_cache_manager import KVCacheManager
from vllm.v1.core.kv_cache_coordinator import HybridKVCacheCoordinator
from vllm.v1.kv_cache_interface import KVCacheConfig

classes = [Scheduler, KVCacheManager, HybridKVCacheCoordinator, KVCacheConfig]
print(json.dumps({
    "vllm_version": vllm.__version__,
    "classes": {
        cls.__name__: {
            "file": inspect.getfile(cls),
            "sha256": hashlib.sha256(open(inspect.getfile(cls), "rb").read()).hexdigest(),
        }
        for cls in classes
    },
}, sort_keys=True))
PY
echo python-finished
date -u

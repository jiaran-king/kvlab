#!/usr/bin/env bash
#SBATCH --job-name=pd-capacity-preflight
#SBATCH --partition=h20
#SBATCH --nodes=1
#SBATCH --ntasks=1
#SBATCH --cpus-per-task=16
#SBATCH --mem=256G
#SBATCH --gres=gpu:h20:4
#SBATCH --time=00:10:00
#SBATCH --no-requeue
#SBATCH --output=/home/david_cwq/zhouziheng/agent-replay-20260917/evidence/pd-capacity-20260919/preflight-%j.out
#SBATCH --error=/home/david_cwq/zhouziheng/agent-replay-20260917/evidence/pd-capacity-20260919/preflight-%j.err
set -euo pipefail
ROOT=/home/david_cwq/zhouziheng/agent-replay-20260917
RUN="$ROOT/evidence/pd-capacity-20260919/preflight-$SLURM_JOB_ID"
mkdir -p "$RUN"
exec 9>"$ROOT/pd-capacity.lock"
flock -n 9
snapshot() {
  local phase=$1
  scontrol show job "$SLURM_JOB_ID" > "$RUN/job-$phase.txt"
  ps -eo user,pid,ppid,stat,etimes,args > "$RUN/processes-$phase.txt"
  nvidia-smi --query-compute-apps=gpu_uuid,pid,process_name,used_gpu_memory --format=csv > "$RUN/gpu-apps-$phase.csv"
  ss -lntp > "$RUN/ports-$phase.txt"
  ipcs -m > "$RUN/ipc-$phase.txt"
  ls -la /dev/shm > "$RUN/shm-$phase.txt"
  free -m > "$RUN/memory-$phase.txt"
  df -h "$ROOT" /dev/shm > "$RUN/storage-$phase.txt"
  uptime > "$RUN/load-$phase.txt"
}
finish() {
  code=$?
  trap - EXIT
  snapshot after
  printf '%s\n' "$code" > "$RUN/exit-code.txt"
  exit "$code"
}
trap finish EXIT
snapshot before
nvidia-smi --query-gpu=index,uuid,name,memory.total,driver_version --format=csv > "$RUN/devices.csv"
nvidia-smi topo -m > "$RUN/topology.txt"
python3 "$ROOT/scripts/compute_health_gate.py" "$ROOT" "$RUN"
export VLLM_PLUGINS="" OMP_NUM_THREADS=4
export CUDA_HOME=/usr/local/cuda-13.0
export PATH="$ROOT/runtime/bin:$CUDA_HOME/bin:$PATH"
timeout 180 "$ROOT/runtime/bin/python" - <<'PY' > "$RUN/runtime.json"
import importlib.util,json,os,torch
print(json.dumps({'CUDA_VISIBLE_DEVICES':os.environ.get('CUDA_VISIBLE_DEVICES'),
 'devices':[{'index':i,'name':torch.cuda.get_device_name(i),'bytes':torch.cuda.get_device_properties(i).total_memory,'capability':torch.cuda.get_device_capability(i)} for i in range(torch.cuda.device_count())],
 'packages':{x:bool(importlib.util.find_spec(x)) for x in ['vllm','mooncake','nixl','httpx','fastapi','uvicorn']}},indent=2),flush=True)
assert torch.cuda.device_count()==4
PY

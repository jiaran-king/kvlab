#!/usr/bin/env bash
#SBATCH --job-name=pd-capacity-point
#SBATCH --partition=h20
#SBATCH --nodes=1
#SBATCH --nodelist=vllm-h20-01
#SBATCH --ntasks=1
#SBATCH --cpus-per-task=32
#SBATCH --mem=512G
#SBATCH --gres=gpu:h20:4
#SBATCH --time=02:00:00
#SBATCH --no-requeue
#SBATCH --output=/home/david_cwq/zhouziheng/agent-replay-20260917/evidence/pd-capacity-20260919/stage-v2/formal-%j.out
#SBATCH --error=/home/david_cwq/zhouziheng/agent-replay-20260917/evidence/pd-capacity-20260919/stage-v2/formal-%j.err
set -euo pipefail
ROOT=/home/david_cwq/zhouziheng/agent-replay-20260917
RUN="$ROOT/evidence/pd-capacity-20260919/stage-v2/formal-$SLURM_JOB_ID"
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
python3 "$ROOT/evidence/pd-capacity-20260919/cleanup_previous_shm.py" "$ROOT" "$RUN"
python3 "$ROOT/scripts/compute_health_gate.py" "$ROOT" "$RUN"
export VLLM_PLUGINS="" OMP_NUM_THREADS=4 VLLM_SERVER_DEV_MODE=1
export CUDA_HOME=/usr/local/cuda-13.0
export PATH="$ROOT/runtime/bin:$CUDA_HOME/bin:$PATH"
export PYTHONPATH="$ROOT/evidence/pd-capacity-20260919/dependencies"
export LD_LIBRARY_PATH="$PYTHONPATH/nvidia/cuda_runtime/lib:${LD_LIBRARY_PATH:-}"
export VLLM_MOONCAKE_BOOTSTRAP_PORT=18998
export VLLM_WORKER_MULTIPROC_METHOD=spawn HF_HUB_OFFLINE=1 TOKENIZERS_PARALLELISM=false
export TORCHINDUCTOR_COMPILE_THREADS=2 MAX_JOBS=4
export VLLM_CACHE_ROOT="$ROOT/cache/vllm" TRITON_CACHE_DIR="$ROOT/cache/triton"
: "${CAPACITY_LABEL:?Missing capacity label}"
: "${P_KV_BYTES:?Missing fixed P budget}"
: "${D_KV_BYTES:?Missing fixed D budget}"
timeout --signal=TERM --kill-after=100 6500 "$ROOT/runtime/bin/python" "$ROOT/evidence/pd-capacity-20260919/pd_formal_controller.py" "$ROOT" "$RUN" "$CAPACITY_LABEL"

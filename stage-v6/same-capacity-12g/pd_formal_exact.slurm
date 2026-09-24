#!/usr/bin/env bash
# Repair run: execute the byte-identical stage-v5 observation/replay code.
# The label remains F12 because stage-v5/replay_v4.py only accepts the original
# ledger labels; the ledger is restored on exit and this run is reported as
# F12B-exact outside the historical stage-v5 ledger.
#SBATCH --job-name=v6-f12-exact
#SBATCH --partition=h20
#SBATCH --nodes=1
#SBATCH --nodelist=vllm-h20-01
#SBATCH --ntasks=1
#SBATCH --cpus-per-task=32
#SBATCH --mem=512G
#SBATCH --gres=gpu:h20:4
#SBATCH --time=02:00:00
#SBATCH --no-requeue
#SBATCH --output=/home/david_cwq/zhouziheng/agent-replay-20260917/evidence/pd-capacity-20260919/stage-v6/same-capacity-12g/exact-%j.out
#SBATCH --error=/home/david_cwq/zhouziheng/agent-replay-20260917/evidence/pd-capacity-20260919/stage-v6/same-capacity-12g/exact-%j.err
set -euo pipefail
ROOT=/home/david_cwq/zhouziheng/agent-replay-20260917
BASE="$ROOT/evidence/pd-capacity-20260919"
RUN="$BASE/stage-v5/retry-1/formal-exact-$SLURM_JOB_ID"
LEDGER="$BASE/stage-v5/retry-1/formal-runs.jsonl"
LEDGER_BACKUP="$BASE/stage-v6/same-capacity-12g/formal-runs-backup-$SLURM_JOB_ID.jsonl"
mkdir -p "$RUN" "$BASE/stage-v6/same-capacity-12g"
exec 9>"$ROOT/pd-capacity.lock"
flock -n 9
cp "$LEDGER" "$LEDGER_BACKUP"
restore_ledger() {
  local code=$?
  if test -f "$LEDGER_BACKUP"; then
    cp "$LEDGER_BACKUP" "$LEDGER"
    rm -f "$LEDGER_BACKUP"
  fi
  exit "$code"
}
trap restore_ledger EXIT
: > "$LEDGER"

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
  local code=$?
  set +e
  trap - EXIT
  snapshot after
  if [[ "$code" == 0 ]]; then
    if [[ -f "$RUN/P-cleanup.json" && -f "$RUN/D-cleanup.json" && -f "$RUN/controller-cleanup.json" ]]; then
      "$ROOT/runtime/bin/python" "$BASE/stage-v5/retry-1/audit_cleanup.py" "$RUN" || code=$?
    fi
    timeout 300 "$ROOT/runtime/bin/python" "$BASE/stage-v5/retry-1/check_evidence.py" formal "$RUN" || code=$?
  fi
  printf '%s\n' "$code" > "$RUN/exit-code.txt"
  # Restore the stage-v5 ledger before the outer EXIT trap runs.
  cp "$LEDGER_BACKUP" "$LEDGER"
  rm -f "$LEDGER_BACKUP"
  exit "$code"
}
trap finish EXIT

cp -r "$BASE/stage-v5/retry-1/hook" "$RUN/hook-snapshot"
cp "$BASE/stage-v6/same-capacity-12g/PLAN.md" "$RUN/PLAN.md"
python3 "$BASE/stage-v5/retry-1/snapshot_runtime.py" "$ROOT" "$RUN"
snapshot before
nvidia-smi --query-gpu=index,uuid,name,memory.total,driver_version --format=csv > "$RUN/devices.csv"
nvidia-smi topo -m > "$RUN/topology.txt"
python3 "$BASE/cleanup_previous_shm.py" "$ROOT" "$RUN"
python3 "$ROOT/scripts/compute_health_gate.py" "$ROOT" "$RUN"
export VLLM_PLUGINS="" OMP_NUM_THREADS=4 VLLM_SERVER_DEV_MODE=1
export CUDA_HOME=/usr/local/cuda-13.0
export PATH="$ROOT/runtime/bin:$CUDA_HOME/bin:$PATH"
export PYTHONPATH="$BASE/dependencies"
export LD_LIBRARY_PATH="$PYTHONPATH/nvidia/cuda_runtime/lib:${LD_LIBRARY_PATH:-}"
export VLLM_MOONCAKE_BOOTSTRAP_PORT=18998
export VLLM_WORKER_MULTIPROC_METHOD=spawn HF_HUB_OFFLINE=1 TOKENIZERS_PARALLELISM=false
export TORCHINDUCTOR_COMPILE_THREADS=2 MAX_JOBS=4
export VLLM_CACHE_ROOT="$ROOT/cache/vllm" TRITON_CACHE_DIR="$ROOT/cache/triton"
: "${P_KV_BYTES:?Missing fixed P budget}"
: "${D_KV_BYTES:?Missing fixed D budget}"
"$ROOT/runtime/bin/python" "$BASE/stage-v5/retry-1/wait_ports.py" "$RUN"
timeout --signal=TERM --kill-after=100 6900 "$ROOT/runtime/bin/python" "$BASE/stage-v5/retry-1/pd_controller.py" "$ROOT" "$RUN" F12

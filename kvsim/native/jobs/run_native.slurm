#!/bin/bash
#SBATCH --partition=h20
#SBATCH --cpus-per-task=4
#SBATCH --mem=16G
#SBATCH --time=00:20:00
#SBATCH --output=/home/david_cwq/zhouziheng/kvlab-native/run-%j.log

set -euo pipefail
base=${4:-/home/david_cwq/zhouziheng/kvlab-native}
runtime=${KVLAB_PYTHON:-/home/david_cwq/zhouziheng/agent-replay-20260917/runtime/bin/python}
workload=$1
output=$2
conditions=${3:-$base/work/kvsim/native/h20-conditions.json}
finish() {
  rc=$?
  echo "job=${SLURM_JOB_ID} exit=$rc final=$(date -u)"
  ps -u "$USER" -o pid,ppid,stat,etime,comm --no-headers | head -15 || true
  ss -ltnH | head -8 || true
  find /dev/shm -maxdepth 1 -mindepth 1 -printf '%f\n' | head -8 || true
  free -h
  df -h "$base"
  scontrol listpids "$SLURM_JOB_ID" || true
  if command -v nvidia-smi >/dev/null; then
    timeout 5 nvidia-smi --query-compute-apps=pid,process_name --format=csv,noheader | head -8 || true
  fi
}
trap finish EXIT

echo "job=${SLURM_JOB_ID} node=$(hostname) start=$(date -u)"
free -h
df -h "$base"
ss -ltnH | head -8 || true
find /dev/shm -maxdepth 1 -mindepth 1 -printf '%f\n' | head -8 || true
if command -v nvidia-smi >/dev/null; then
  timeout 5 nvidia-smi --query-compute-apps=pid,process_name --format=csv,noheader | head -8 || true
fi
before_dz=$(ps -eo stat,ppid,pid,comm --no-headers | awk '$1 ~ /^[DZ]/ {print}')
printf 'D/Z before:\n%s\n' "$before_dz"
sleep 2
after_dz=$(ps -eo stat,ppid,pid,comm --no-headers | awk '$1 ~ /^[DZ]/ {print}')
before_count=$(printf '%s\n' "$before_dz" | awk 'NF {n++} END {print n+0}')
after_count=$(printf '%s\n' "$after_dz" | awk 'NF {n++} END {print n+0}')
if (( after_count > before_count )); then
  echo "D/Z count changed during preflight: $before_count -> $after_count (observed, not a run gate)"
  printf '%s\n' "$after_dz"
fi
export PYTHONPATH="${KVLAB_SOURCE_ROOT:-$base/work}"
export PYTHONHASHSEED=0
timeout 15m "$runtime" -u -m kvsim.native.run \
  "$workload" "$conditions" "$output"

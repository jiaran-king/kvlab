#!/bin/bash
#SBATCH --partition=h20
#SBATCH --cpus-per-task=2
#SBATCH --mem=8G
#SBATCH --time=00:08:00
#SBATCH --output=/home/david_cwq/zhouziheng/kvlab-native/mechanism-%j.log

set -euo pipefail
base=/home/david_cwq/zhouziheng/kvlab-native
runtime=/home/david_cwq/zhouziheng/agent-replay-20260917/runtime/bin/python
finish() {
  rc=$?
  echo "job=${SLURM_JOB_ID} exit=$rc final=$(date -u)"
  ps -u "$USER" -o pid,ppid,stat,etime,comm --no-headers | head -15 || true
  ss -ltnH | head -8 || true
  find /dev/shm -maxdepth 1 -mindepth 1 -printf '%f\n' | head -8 || true
}
trap finish EXIT
echo "job=${SLURM_JOB_ID} node=$(hostname) start=$(date -u)"
free -h
df -h "$base"
before_dz=$(ps -eo stat,ppid,pid,comm --no-headers | awk '$1 ~ /^[DZ]/ {print}')
sleep 2
after_dz=$(ps -eo stat,ppid,pid,comm --no-headers | awk '$1 ~ /^[DZ]/ {print}')
before_count=$(printf '%s\n' "$before_dz" | awk 'NF {n++} END {print n+0}')
after_count=$(printf '%s\n' "$after_dz" | awk 'NF {n++} END {print n+0}')
echo "D/Z preflight count ${before_count} -> ${after_count}"
if (( after_count > before_count )); then
  echo "D/Z count increased during preflight; refusing run" >&2
  exit 2
fi
export PYTHONPATH="$base/work"
export PYTHONHASHSEED=0
module=${1:-kvsim.native.mechanism_cases}
case "$module" in
  kvsim.native.mechanism_cases|kvsim.native.recovery_cases|kvsim.native.recovery_short_cases|kvsim.native.preemption_directed|kvsim.native.preemption_admission_diagnostic|kvsim.native.preemption_recovery_1800) ;;
  *) echo "unsupported mechanism module: $module" >&2; exit 2 ;;
esac
result_dir="$base/results/mechanism-jobs"
mkdir -p "$result_dir"
result_file="$result_dir/${SLURM_JOB_ID}.stdout"
timeout 5m "$runtime" -u -m "$module" > "$result_file"
status_tmp="$result_dir/${SLURM_JOB_ID}.complete.tmp"
printf 'job=%s module=%s result=%s status=complete\n' \
  "$SLURM_JOB_ID" "$module" "$result_file" > "$status_tmp"
mv "$status_tmp" "$result_dir/${SLURM_JOB_ID}.complete"
echo "result=$result_file status=complete"

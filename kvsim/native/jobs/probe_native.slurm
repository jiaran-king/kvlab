#!/bin/bash
#SBATCH --partition=h20
#SBATCH --nodelist=vllm-h20-01
#SBATCH --cpus-per-task=2
#SBATCH --mem=8G
#SBATCH --time=00:10:00
#SBATCH --output=/home/david_cwq/zhouziheng/kvlab-native/native-probe-%j.log

set -euo pipefail
base=/home/david_cwq/zhouziheng/kvlab-native
runtime=/home/david_cwq/zhouziheng/agent-replay-20260917/runtime/bin/python
finish() {
  rc=$?
  echo "post-run exit=$rc"
  ps -u "$USER" -o pid,ppid,stat,etime,comm --no-headers | head -15 || true
  ss -ltnH | head -8 || true
  find /dev/shm -maxdepth 1 -mindepth 1 -printf '%f\n' | head -8 || true
  date -u
}
trap finish EXIT
echo "job=${SLURM_JOB_ID} node=$(hostname) pid=$$"
date -u
free -h
df -h "$base"
before_dz=$(ps -eo stat,ppid,pid,comm --no-headers | awk '$1 ~ /^[DZ]/ {print}')
printf 'D/Z before:\n%s\n' "$before_dz"
sleep 2
after_dz=$(ps -eo stat,ppid,pid,comm --no-headers | awk '$1 ~ /^[DZ]/ {print}')
if [[ "$before_dz" != "$after_dz" ]]; then
  echo "D/Z state changed during preflight; refusing native probe" >&2
  exit 2
fi
export PYTHONPATH="$base/work"
timeout 180s "$runtime" -u -m kvsim.native.probe_native > "$base/native-probe-${SLURM_JOB_ID}.json"
cat "$base/native-probe-${SLURM_JOB_ID}.json"

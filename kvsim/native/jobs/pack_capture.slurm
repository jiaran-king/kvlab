#!/bin/bash
#SBATCH --partition=h20
#SBATCH --nodelist=vllm-h20-01
#SBATCH --cpus-per-task=1
#SBATCH --mem=2G
#SBATCH --time=00:05:00
#SBATCH --output=/home/david_cwq/zhouziheng/kvlab-native/pack-capture-%j.log
set -euo pipefail
source_file=/home/david_cwq/zhouziheng/agent-replay-20260917/evidence/pd-capacity-20260919/stage-v5/retry-1/formal-3458/p-input-1719634.u32
target_dir=/home/david_cwq/zhouziheng/kvlab-native/assets/f12-capture
finish() {
  rc=$?
  echo "job=${SLURM_JOB_ID} exit=$rc final=$(date -u)"
  ps -u "$USER" -o pid,ppid,stat,etime,comm --no-headers | head -15 || true
  ss -ltnH | head -8 || true
  find /dev/shm -maxdepth 1 -mindepth 1 -printf '%f\n' | head -8 || true
}
trap finish EXIT
mkdir -p "$target_dir"
echo "job=${SLURM_JOB_ID} node=$(hostname) start=$(date -u)"
free -h
df -h "$target_dir"
before_dz=$(ps -eo stat,ppid,pid,comm --no-headers | awk '$1 ~ /^[DZ]/ {print}')
sleep 2
after_dz=$(ps -eo stat,ppid,pid,comm --no-headers | awk '$1 ~ /^[DZ]/ {print}')
before_count=$(printf '%s\n' "$before_dz" | awk 'NF {n++} END {print n+0}')
after_count=$(printf '%s\n' "$after_dz" | awk 'NF {n++} END {print n+0}')
if (( after_count > before_count )); then
  echo "D/Z count increased during preflight; refusing run" >&2
  exit 2
fi
gzip -1 -c "$source_file" > "$target_dir/p-input.u32.gz.tmp"
mv "$target_dir/p-input.u32.gz.tmp" "$target_dir/p-input.u32.gz"
stat -c '%n %s' "$source_file" "$target_dir/p-input.u32.gz"

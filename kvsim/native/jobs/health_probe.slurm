#!/bin/bash
#SBATCH --partition=h20
#SBATCH --nodelist=vllm-h20-01
#SBATCH --cpus-per-task=1
#SBATCH --mem=2G
#SBATCH --time=00:02:00
#SBATCH --output=/home/david_cwq/zhouziheng/kvlab-native/health-probe-%j.log

set -euo pipefail
echo "job=${SLURM_JOB_ID} node=$(hostname) pid=$$"
date -u
free -h
uptime
df -h /home/david_cwq/zhouziheng /tmp
before_dz=$(ps -eo stat,ppid,pid,comm --no-headers | awk '$1 ~ /^[DZ]/ {print}')
printf '%s\n' "$before_dz" | head -20
ps -u "$USER" -o pid,ppid,stat,etime,comm --no-headers | head -20 || true
ss -ltnH | head -15 || true
find /dev/shm -maxdepth 1 -mindepth 1 -printf '%f\n' | head -15 || true
if command -v nvidia-smi >/dev/null; then
  nvidia-smi --query-compute-apps=pid,process_name --format=csv,noheader | head -10 || true
fi
sleep 2
after_dz=$(ps -eo stat,ppid,pid,comm --no-headers | awk '$1 ~ /^[DZ]/ {print}')
before_count=$(printf '%s\n' "$before_dz" | awk 'NF {n++} END {print n+0}')
after_count=$(printf '%s\n' "$after_dz" | awk 'NF {n++} END {print n+0}')
if (( after_count > before_count )); then
  echo "D/Z process count increased during health probe" >&2
  printf '%s\n' "$after_dz" >&2
  exit 2
fi
echo "D/Z process count did not increase during health probe: $before_count -> $after_count"
date -u

#!/usr/bin/env bash
#SBATCH --job-name=pd-L2-analysis
#SBATCH --partition=h20
#SBATCH --nodes=1
#SBATCH --nodelist=vllm-h20-01
#SBATCH --cpus-per-task=1
#SBATCH --mem=4G
#SBATCH --time=00:03:00
#SBATCH --no-requeue
#SBATCH --output=/home/david_cwq/zhouziheng/agent-replay-20260917/evidence/pd-capacity-20260919/stage-v4/analysis-%j.out
set -euo pipefail
ROOT=/home/david_cwq/zhouziheng/agent-replay-20260917
V4="$ROOT/evidence/pd-capacity-20260919/stage-v4"
AUDIT="$V4/analysis-$SLURM_JOB_ID"
mkdir -p "$AUDIT"
snapshot() {
  scontrol show job "$SLURM_JOB_ID" > "$AUDIT/job-$1.txt"
  ps -eo user,pid,ppid,stat,etimes,args > "$AUDIT/processes-$1.txt"
  free -m > "$AUDIT/memory-$1.txt"
  uptime > "$AUDIT/load-$1.txt"
  timeout 10 df -h "$ROOT" /dev/shm > "$AUDIT/storage-$1.txt"
  ss -lntp > "$AUDIT/ports-$1.txt"
  ipcs -m > "$AUDIT/ipc-$1.txt"
}
finish() {
  code=$?
  trap - EXIT
  snapshot after
  printf '%s\n' "$code" > "$AUDIT/exit-code.txt"
  exit "$code"
}
trap finish EXIT
snapshot before
python3 "$ROOT/scripts/compute_health_gate.py" "$ROOT" "$AUDIT"
timeout 90 "$ROOT/client/bin/python" "$V4/summarize_observation.py" "$V4/formal-3430" > "$AUDIT/observation-output.json"

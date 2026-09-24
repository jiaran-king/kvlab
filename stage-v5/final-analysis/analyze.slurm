#!/usr/bin/env bash
#SBATCH --job-name=pd-v5-analysis
#SBATCH --partition=h20
#SBATCH --nodes=1
#SBATCH --nodelist=vllm-h20-01
#SBATCH --cpus-per-task=1
#SBATCH --mem=4G
#SBATCH --time=00:05:00
#SBATCH --no-requeue
#SBATCH --output=/home/david_cwq/zhouziheng/agent-replay-20260917/evidence/pd-capacity-20260919/stage-v5/final-analysis/cpu-%j.out
set -euo pipefail
ROOT=/home/david_cwq/zhouziheng/agent-replay-20260917
V4="$ROOT/evidence/pd-capacity-20260919/stage-v4"
CAUSE="$ROOT/evidence/pd-capacity-20260919/stage-v5/final-analysis"
AUDIT="$CAUSE/cpu-$SLURM_JOB_ID"
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
exec 9>"$CAUSE/analysis.lock"
flock -n 9
printf '%s\n' "$$" > "$AUDIT/controller-pid.txt"
timeout --signal=TERM --kill-after=10 180 "$ROOT/client/bin/python" "$CAUSE/analyze_runs.py" "$ROOT/evidence/pd-capacity-20260919/stage-v5/retry-1" "$AUDIT" &
worker=$!
printf '%s\n' "$worker" > "$AUDIT/worker-pid.txt"
wait "$worker"
if kill -0 "$worker" 2>/dev/null; then exit 3; fi

#!/usr/bin/env bash
#SBATCH --job-name=pd425-prepare
#SBATCH --partition=h20
#SBATCH --nodes=1
#SBATCH --nodelist=vllm-h20-01
#SBATCH --cpus-per-task=1
#SBATCH --mem=2G
#SBATCH --time=00:03:00
#SBATCH --no-requeue
#SBATCH --output=/home/david_cwq/zhouziheng/agent-replay-20260917/evidence/pd-capacity-20260919/stage-v4/prepare-%j.out
set -euo pipefail
ROOT=/home/david_cwq/zhouziheng/agent-replay-20260917
BASE="$ROOT/evidence/pd-capacity-20260919"
RUN="$BASE/stage-v4/prepare-$SLURM_JOB_ID"
mkdir -p "$RUN"
scontrol show job "$SLURM_JOB_ID" > "$RUN/job.txt"
uptime > "$RUN/load.txt"
free -m > "$RUN/memory.txt"
timeout 10 df -h "$ROOT" /dev/shm > "$RUN/storage.txt"
ps -eo user,pid,ppid,stat,pcpu,etimes,args --sort=-pcpu > "$RUN/processes.txt"
ss -lntp > "$RUN/ports.txt"
ipcs -m > "$RUN/ipc.txt"
if test -e /proc/4104050/stat; then cat /proc/4104050/stat > "$RUN/previous-transient-root.txt"; else echo absent > "$RUN/previous-transient-root.txt"; fi
timeout 60 "$ROOT/client/bin/python" "$BASE/stage-v4/check_subset_plan.py" "$BASE" "$RUN"

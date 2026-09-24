#!/usr/bin/env bash
# End-to-end check on the local cluster: create a run with the stub agent,
# wait for every trial Job to report back, print the run summary.
set -euo pipefail

RELEASE=${RELEASE:-aep}
PORT=${PORT:-8080}
TASKS=${TASKS:-5}
K=${K:-2}

kubectl port-forward "svc/${RELEASE}-api" "${PORT}:8000" >/dev/null 2>&1 &
PF=$!
trap 'kill $PF 2>/dev/null' EXIT
for _ in $(seq 20); do curl -sf "localhost:${PORT}/healthz" >/dev/null && break; sleep 0.5; done

task_ids=$(python3 -c "import json; print(json.dumps([f'task-{i:03d}' for i in range(${TASKS})]))")
run_id=$(curl -sf -X POST "localhost:${PORT}/runs" -H 'content-type: application/json' \
  -d "{\"name\":\"smoke\",\"agent\":\"stub\",\"domain\":\"mock\",\"task_ids\":${task_ids},\"k\":${K}}" \
  | python3 -c "import sys, json; print(json.load(sys.stdin)['id'])")
echo "run ${run_id}: ${TASKS} tasks x k=${K} = $((TASKS * K)) trial Jobs"

start=$(date +%s)
while true; do
  summary=$(curl -sf "localhost:${PORT}/runs/${run_id}")
  pending=$(echo "$summary" | python3 -c "
import sys, json
c = json.load(sys.stdin)['status_counts']
print(c.get('queued', 0) + c.get('running', 0))")
  echo "  $(echo "$summary" | python3 -c "import sys, json; print(json.load(sys.stdin)['status_counts'])")"
  [ "$pending" -eq 0 ] && break
  [ $(( $(date +%s) - start )) -gt 600 ] && { echo "timed out"; exit 1; }
  sleep 3
done

echo "done in $(( $(date +%s) - start ))s"
echo "$summary" | python3 -m json.tool

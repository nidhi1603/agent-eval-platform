#!/usr/bin/env bash
# Inject real failures on the kind cluster and check the platform recovers correctly.
# Uses stub agents only (no LLM calls, no spend). Prints PASS/FAIL per check; exits 1 on any FAIL.
#
#   1. dispatcher restart mid-run       -> every trial completes, exactly one attempt each
#   2. worker crash (no callback)       -> infra failure, retried once, counted once
#   3. pod termination mid-run          -> infra failure, retried
#   4. deadline expiry                  -> agent timeout, not retried
#   5. duplicate queue delivery         -> ignored, no second attempt
#   6. duplicate / late callback        -> rejected (409), result unchanged
set -uo pipefail

RELEASE=${RELEASE:-aep}
PORT=${PORT:-8081}
API="localhost:${PORT}"
FAILS=0

kubectl port-forward "svc/${RELEASE}-api" "${PORT}:8000" >/dev/null 2>&1 &
PF=$!
trap 'kill $PF 2>/dev/null' EXIT
for _ in $(seq 30); do curl -sf "$API/healthz" >/dev/null && break; sleep 0.5; done

check() {  # check <description> <python-bool-expression over `trials` and `summary`> <run_id>
  local desc=$1 expr=$2 run=$3
  if curl -sf "$API/runs/$run/trials" > /tmp/aep_trials.json && curl -sf "$API/runs/$run" > /tmp/aep_summary.json \
     && python3 -c "
import json, sys
trials = json.load(open('/tmp/aep_trials.json')); summary = json.load(open('/tmp/aep_summary.json'))
sys.exit(0 if ($expr) else 1)"; then
    echo "PASS  $desc"
  else
    echo "FAIL  $desc"; python3 -m json.tool /tmp/aep_trials.json | head -40; FAILS=$((FAILS + 1))
  fi
}

create_run() {  # create_run <agent> <k> <deadline|null> <task...>
  local agent=$1 k=$2 deadline=$3; shift 3
  local tasks; tasks=$(python3 -c "import json,sys; print(json.dumps(sys.argv[1:]))" "$@")
  curl -sf -X POST "$API/runs" -H 'content-type: application/json' \
    -d "{\"name\":\"failure-demo\",\"agent\":\"$agent\",\"domain\":\"mock\",\"task_ids\":$tasks,\"k\":$k,\"deadline_seconds\":$deadline}" \
    | python3 -c "import sys, json; print(json.load(sys.stdin)['id'])"
}

wait_done() {  # wait_done <run_id> <timeout_s>
  local run=$1 limit=$2 start; start=$(date +%s)
  while true; do
    local pending
    pending=$(curl -sf "$API/runs/$run" | python3 -c "
import sys, json
c = json.load(sys.stdin)['status_counts']
print(sum(v for k, v in c.items() if k not in ('completed', 'errored', 'infra_failed')))")
    [ "$pending" = "0" ] && return 0
    [ $(( $(date +%s) - start )) -gt "$limit" ] && { echo "  (timed out waiting for run $run)"; return 1; }
    sleep 3
  done
}

psql_exec() { kubectl exec "deploy/${RELEASE}-postgres" -- psql -U aep -d aep -tAc "$1"; }

echo "== 1. dispatcher restart mid-run"
R1=$(create_run stub 2 null a b c)
sleep 2
kubectl delete pod -l app.kubernetes.io/component=dispatcher --wait=false >/dev/null
wait_done "$R1" 240
check "dispatcher restart: all 6 trials completed, one attempt each" \
  "len(trials) == 6 and all(t['status'] == 'completed' and t['attempts'] == 1 for t in trials)" "$R1"

echo "== 2. worker crash without a callback"
R2=$(create_run stub-crash-first-attempt 1 null d e)
wait_done "$R2" 240
check "worker crash: both trials completed on attempt 2, counted once" \
  "all(t['status'] == 'completed' and t['attempts'] == 2 for t in trials) and summary['attempts'] == 4" "$R2"

echo "== 3. pod termination mid-run"
R3=$(create_run stub-hang 1 40 f)
for _ in $(seq 60); do
  pod=$(kubectl get pods -l aep/trial-id -o name 2>/dev/null | grep -m1 . ); [ -n "$pod" ] && \
  [ "$(kubectl get "$pod" -o jsonpath='{.status.phase}')" = "Running" ] && break; sleep 1
done
kubectl delete "$pod" --wait=false >/dev/null && echo "  deleted $pod"
wait_done "$R3" 240
check "pod termination: attempt 1 infra failure, retry then hit its deadline (agent timeout)" \
  "trials[0]['attempts'] == 2 and trials[0]['status'] == 'errored' and trials[0]['failure_class'] == 'agent'" "$R3"

echo "== 4. deadline expiry"
R4=$(create_run stub-hang 1 20 g)
wait_done "$R4" 180
check "deadline: agent timeout, not retried, counted as failure" \
  "trials[0]['status'] == 'errored' and trials[0]['failure_class'] == 'agent' and trials[0]['attempts'] == 1 and summary['pass_hat_k']['1'] == 0.0" "$R4"

echo "== 5. duplicate queue delivery"
T5=$(curl -sf "$API/runs/$R1/trials" | python3 -c "import sys, json; print(json.load(sys.stdin)[0]['id'])")
kubectl exec "deploy/${RELEASE}-redis" -- redis-cli RPUSH aep:trials "$T5" >/dev/null
sleep 12
check "duplicate delivery of finished trial $T5: still exactly one attempt" \
  "[t for t in trials if t['id'] == $T5][0]['attempts'] == 1" "$R1"

echo "== 6. duplicate / late callback"
TOKEN=$(psql_exec "select callback_token from attempts where trial_id = $T5 order by number desc limit 1")
CODE=$(curl -s -o /dev/null -w '%{http_code}' -X POST "$API/trials/$T5/result" -H "x-trial-token: $TOKEN" \
  -H 'content-type: application/json' -d '{"status":"completed","reward":0.0}')
[ "$CODE" = "409" ] && echo "PASS  replayed callback rejected (HTTP 409)" || { echo "FAIL  replayed callback returned $CODE"; FAILS=$((FAILS + 1)); }
check "replayed callback did not change the stored result" \
  "[t for t in trials if t['id'] == $T5][0]['status'] == 'completed'" "$R1"

echo
echo "attempt ledger:"
psql_exec "select t.id, t.status, coalesce(t.failure_class,'-'), a.number, a.status, coalesce(a.reason,'-') from trials t join attempts a on a.trial_id = t.id order by t.id, a.number" \
  | column -t -s '|'
echo
[ "$FAILS" -eq 0 ] && echo "ALL CHECKS PASSED" || { echo "$FAILS CHECK(S) FAILED"; exit 1; }

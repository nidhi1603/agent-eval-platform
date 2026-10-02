"""Write experiments/P003_plan.json: the controlled reason-code probe ($0 to write; NOT run).

Case selection (fixed rule, from research/transfers/): transfer calls whose reason code the readers judged CLEARLY
right or wrong under policy, with one agreed (or adjudicated) applicable code; ONE case per conversation (its first
such call), so repeated decisions in one conversation do not count twice. Policy-unclear calls are excluded from the
primary score and listed. Reconstruction is checked by bench.code_probe.preflight before anything is sent.

    uv run --extra bench python research/p003/make_plan.py
"""
import hashlib
import json
import random
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
SEED = 20261002
SAMPLES = 3


def main():
    import bench  # noqa: F401
    from bench import code_probe as cp

    T = ROOT / "research" / "transfers"
    key = json.loads((T / "KEY_do_not_give_to_readers.json").read_text())
    A, B = {}, {}
    for p in ("part1", "part2", "part3", "part4"):
        A.update({x["id"]: x for x in json.loads((T / f"labels_{p}_A.json").read_text())})
        B.update({x["id"]: x for x in json.loads((T / f"labels_{p}_B.json").read_text())})
    adj = {x["id"]: x for x in json.loads((T / "adjudication.json").read_text())}
    runs_by_id = {}
    for b in ("H008", "H009", "P001"):
        for r in json.loads((ROOT / "experiments" / f"{b}_results.json").read_text())["results"]:
            runs_by_id[r["run_id"]] = r
    cands, unclear = [], []
    for pid, v in key.items():
        if v["kind"] != "T":
            continue
        labels = [adj[pid]] if pid in adj else [A[pid], B[pid]]
        cc = {(l.get("reason_code") or {}).get("chosen_correct") for l in labels}
        app = {(l.get("reason_code") or {}).get("applicable_under_policy") for l in labels}
        clear = len(cc) == 1 and next(iter(cc)) in (True, False) and len(app) == 1 and next(iter(app)) not in (None, "unclear")
        (cands if clear else unclear).append((v["run_id"], v["i"], pid, next(iter(cc)) if clear else None,
                                             next(iter(app)) if clear else None, v))
    first = {}
    for c in sorted(cands, key=lambda x: (x[0], x[1])):
        first.setdefault(c[0], c)
    cases = []
    for run_id, i, pid, correct, target, v in sorted(first.values(), key=lambda x: x[2]):
        r = runs_by_id[run_id]
        t = json.loads(Path(r["trace"]).read_text())
        msg = t["messages"][i]
        call = next(c for c in msg["tool_calls"] if c["name"] == "transfer_to_human_agents")
        cases.append({"id": pid, "task_id": v["task_id"], "batch": v["batch"], "source_trace": str(Path(r["trace"]).relative_to(ROOT)),
                      "trace_sha256": hashlib.sha256(Path(r["trace"]).read_bytes()).hexdigest(), "trajectory_index": i,
                      "call_id": call["id"], "original_code": (call["arguments"] or {}).get("reason"),
                      "originally_correct": correct, "target": target, "retrieval_config": t["config"]["retrieval_config"],
                      "source_harness": ((t["config"].get("agent") or {}).get("harness") or {}).get("name") or "standard agent",
                      "tier_doc_body_seen_before": v.get("tier_doc_content_seen_before")})
    rng = random.Random(SEED)
    runs = []
    for c in cases:
        order = [arm for arm in cp.ARMS for _ in range(SAMPLES)]
        rng.shuffle(order)
        runs += [{"case": c["id"], "arm": arm} for arm in order]
    plan = {
        "batch_id": "P003",
        "kind": "next-message probe (development diagnostic): controlled reason-code re-check at saved transfer proposals; nothing executed, nothing graded by tau2",
        "status": "FROZEN DRAFT, NOT RUN. Needs review and Nidhi's explicit approval with the amount.",
        "question": "With the conversation held fixed, does giving the model the bank's reason-code document make it choose the policy-correct transfer reason code more often than the same re-check request alone?",
        "arms": {"control": "the held transfer's tool result is the re-check REQUEST", "treatment": "the same REQUEST plus doc 042's full text (title and tier table)"},
        "why_a_control": "separates providing the document from merely asking again (review)",
        "selection_rule": "transfer calls with a policy-CLEAR code (both readers, or the adjudicator, agree it is right or wrong and agree the applicable code); one case per conversation (its first such call). From research/transfers/ (two blind readers + adjudication, no answer key).",
        "cases": cases,
        "case_counts": {"total": len(cases), "originally_wrong": sum(not c["originally_correct"] for c in cases),
                        "originally_correct": sum(c["originally_correct"] for c in cases),
                        "by_task": {t: sum(c["task_id"] == t for c in cases) for t in sorted({c["task_id"] for c in cases})}},
        "excluded_policy_unclear": sorted(u[2] for u in unclear),
        "excluded_repeat_calls": sorted(c[2] for c in cands if first[c[0]][2] != c[2]),
        "target_caveat": "task_035's target (technical_system_error) is the readers' policy reading: doc 042 names no code for the credit-bureau incident, and tau2's grade accepts any code there. 8 of the cases are task_035; results are also reported without them.",
        "samples_per_arm": SAMPLES,
        "run_order": f"per case, its {SAMPLES} control and {SAMPLES} treatment samples in a seeded random order (seed {SEED})",
        "runs": runs,
        "tier_document_sha256": hashlib.sha256(cp.tier_document().encode()).hexdigest(),
        "request_text": cp.REQUEST,
        "settings": {"agent_model": "gpt-5-mini", "agent_args": {"reasoning_effort": "medium"}, "max_output_tokens": 16384,
                     "budget_accounting": "billed"},
        "scoring": "per sample: the first transfer_to_human_agents call's reason; CORRECT iff it equals the case target. No transfer call, an invalid code or text only = failure (counts as wrong). Per case and arm: MAJORITY of the 3 samples correct.",
        "gate": {"note": "engineering screening thresholds, not statistical proof",
                 "G1": "treatment majority-correct in at least half of the originally-wrong cases",
                 "G2": "treatment has more majority-correct cases than control (all cases)",
                 "G3": "no originally-correct case is not majority-correct under treatment",
                 "PASS": "G1 and G2 and G3 -> plan a full-conversation comparison: standard agent vs standard agent + this component (shared infrastructure, fixed task mix; completion, policy violations, cost)",
                 "FAIL": "any of G1-G3 fails -> drop the component (no tuning cycle)",
                 "INCOMPLETE": "any case or arm missing samples"},
        "reported_also": ["sample-level counts per arm", "per case and per task", "results excluding task_035",
                          "outcome types (transfer call / no transfer call / invalid code)", "codes chosen"],
        "limits": "a selected next decision, not full conversations; 20 cases from 5 tasks; development data.",
        "forecast_usd": {"basis": "the original proposing calls used 4k-86k input tokens (about 585k summed over the 20 cases); 120 samples at gpt-5-mini prices, plus reasoning output",
                         "expected": "an estimate awaiting evidence: about $0.60-1.40 billed (upper bound without caching about $1.40)"},
        "budget_usd_total": 2.0,
        "budget_note": "one sample at a time; the budget reserves each call's full input plus max_output_tokens before sending (about $0.11 for the largest case), well inside the total",
        "approval": "runs only after Nidhi approves in chat: 'run P003 with $2.00'",
    }
    (ROOT / "experiments" / "P003_plan.json").write_text(json.dumps(plan, indent=1) + "\n")
    print(json.dumps(plan["case_counts"]), len(runs), "runs; unclear", len(unclear), "repeats", len(plan["excluded_repeat_calls"]))


if __name__ == "__main__":
    main()

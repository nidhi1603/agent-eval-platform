"""Write experiments/P003_plan.json: the controlled reason-code probe ($0 to write; NOT run).

Case selection (fixed rule, from research/transfers/): transfer calls whose reason code the readers judged CLEARLY
right or wrong under policy, with one agreed (or adjudicated) applicable code; ONE case per conversation (its first
such call), so repeated decisions in one conversation do not count twice; and (amendment 1, after the P003 review)
only on tasks whose tau2 grade checks the reason code (a reference transfer_to_human_agents action comparing
`reason`), so every target is the benchmark's own and every case can move the score. Policy-unclear calls and
ungraded-code cases are excluded and listed. Reconstruction is checked by bench.code_probe.preflight before anything
is sent.

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
    from tau2.runner.helpers import get_tasks

    from bench import pins

    def graded_code(task_id):
        """The task's grade compares the transfer's reason: a reference transfer action with compare_args None
        (all arguments) or including 'reason'. task_035's compare_args is [] (any code passes)."""
        acts = get_tasks(pins.DOMAIN, task_ids=[task_id])[0].evaluation_criteria.actions or []
        return any(a.name == "transfer_to_human_agents" and (a.compare_args is None or "reason" in a.compare_args) for a in acts)

    graded = {t: graded_code(t) for t in sorted({c[5]["task_id"] for c in first.values()})}
    not_graded = sorted((c[2], c[5]["task_id"]) for c in first.values() if not graded[c[5]["task_id"]])
    cases = []
    for run_id, i, pid, correct, target, v in sorted((c for c in first.values() if graded[c[5]["task_id"]]), key=lambda x: x[2]):
        r = runs_by_id[run_id]
        t = json.loads(Path(r["trace"]).read_text())
        msg = t["messages"][i]
        call = next(c for c in msg["tool_calls"] if c["name"] == "transfer_to_human_agents")
        cases.append({"id": pid, "task_id": v["task_id"], "batch": v["batch"], "source_trace": str(Path(r["trace"]).relative_to(ROOT)),
                      "trace_sha256": hashlib.sha256(Path(r["trace"]).read_bytes()).hexdigest(), "trajectory_index": i,
                      "call_id": call["id"], "original_code": (call["arguments"] or {}).get("reason"),
                      "originally_correct": correct, "target": target, "retrieval_config": t["config"]["retrieval_config"],
                      "source_harness": ((t["config"].get("agent") or {}).get("harness") or {}).get("name") or "standard agent",
                      "tier_doc_body_seen_before": v.get("tier_doc_content_seen_before"),
                      "tier_doc_exposure": "present" if v.get("tier_doc_content_seen_before") else "absent"})
    rng = random.Random(SEED)
    runs = []
    for c in cases:
        order = [arm for arm in cp.ARMS for _ in range(SAMPLES)]
        rng.shuffle(order)
        runs += [{"case": c["id"], "arm": arm} for arm in order]
    wrong = [c for c in cases if not c["originally_correct"]]
    right = [c for c in cases if c["originally_correct"]]
    g1 = (len(wrong) + 1) // 2

    def counts(xs):
        return {"total": len(xs), "originally_wrong": sum(not c["originally_correct"] for c in xs),
                "originally_correct": sum(c["originally_correct"] for c in xs),
                "by_task": {t: sum(c["task_id"] == t for c in xs) for t in sorted({c["task_id"] for c in xs})}}

    plan = {
        "batch_id": "P003",
        "kind": "next-message probe (development diagnostic): controlled reason-code re-check at saved transfer proposals; nothing executed, nothing graded by tau2",
        "status": "FROZEN DRAFT (amended before any spend), NOT RUN. Needs review and Nidhi's explicit approval with the amount.",
        "question": "With the conversation held fixed, does giving the model the bank's reason-code document make it choose the graded reason code more often than the same re-check request alone?",
        "primary_outcome": "reason-code SELECTION at one held transfer: not a correct overall transfer decision, not conversation completion",
        "arms": {"control": "the held transfer's tool result is the re-check REQUEST", "treatment": "the same REQUEST plus doc 042's full text (title and tier table)"},
        "why_a_control": "separates providing the document from merely asking again (review)",
        "component_tested": ("reason-code re-check at EVERY proposed transfer: the transfer is held once and the agent gets the re-check request "
                             "with doc 042's text, whether or not the document is already in context (amendment 3). BOUNDED: a pending "
                             "transfer is reconsidered ONCE; the reissued transfer is then handled normally, never held again "
                             "(clarification, second review). The probe tests only the first, held proposal."),
        "answer_key_boundary": ("the target code, the task identity and the grading requirements are used only in scoring and in the "
                                "preflight check; they never enter either arm's model input (the request text and doc 042 are fixed and "
                                "identical across cases) and would not determine runtime behaviour. The targets are the readers' "
                                "policy-derived codes; preflight only CHECKS that they equal the graded code (all 9 do) and does not "
                                "replace any."),
        "selection_rule": ("transfer calls with a policy-CLEAR code (both readers, or the adjudicator, agree it is right or wrong and agree the "
                           "applicable code); one case per conversation (its first such call); only tasks whose tau2 grade compares the "
                           "transfer's reason. From research/transfers/ (two blind readers + adjudication, no answer key)."),
        "graded_code_by_task": graded,
        "cases": cases,
        "case_counts": counts(cases),
        "case_counts_by_exposure": {e: counts([c for c in cases if c["tier_doc_exposure"] == e]) for e in ("absent", "present")},
        "excluded_code_not_graded": [{"id": i, "task_id": t} for i, t in not_graded],
        "excluded_policy_unclear": sorted(u[2] for u in unclear),
        "excluded_repeat_calls": sorted(c[2] for c in cands if first[c[0]][2] != c[2]),
        "target_note": ("every target equals the code the task's tau2 grade requires (task_004: account_ownership_dispute; task_012: "
                        "kb_search_unsuccessful_customer_requests_transfer). Both tasks are graded on that ONE action (reward basis "
                        "ACTION, one reference action), so in these conversations a correct code is the reward once the transfer is made."),
        "samples_per_arm": SAMPLES,
        "run_order": f"per case, its {SAMPLES} control and {SAMPLES} treatment samples in a seeded random order (seed {SEED})",
        "runs": runs,
        "tier_document_sha256": hashlib.sha256(cp.tier_document().encode()).hexdigest(),
        "request_text": cp.REQUEST,
        "settings": {"agent_model": "gpt-5-mini", "agent_args": {"reasoning_effort": "medium"}, "max_output_tokens": 16384,
                     "budget_accounting": "billed"},
        "scoring": ("per sample: the FIRST transfer_to_human_agents call's reason; CORRECT iff it equals the case target. No transfer "
                    "call, an invalid code or text only = failure (counts as wrong). Anomalies are recorded but do not change the "
                    "score: more than one transfer call, any other tool call in the reply. Per case and arm: correct when at least "
                    f"2 of the {SAMPLES} samples are correct."),
        "gate": {"note": "engineering screening thresholds on all cases (exact integers), not statistical proof; passing justifies a full-conversation experiment, not reliability",
                 "G1": {"text": f"treatment gets at least {g1} of the {len(wrong)} originally-wrong cases right (case criterion)",
                        "cases": len(wrong), "min_correct": g1},
                 "G2": {"text": f"treatment gets more of the {len(cases)} cases right than control (case criterion)", "cases": len(cases)},
                 "G3": {"text": f"0 of the {len(right)} originally-correct cases fail the case criterion under treatment; this is not 'no "
                                "regressions': single wrong samples are reported separately", "cases": len(right), "max_failing": 0},
                 "PASS": "G1 and G2 and G3 -> plan a full-conversation comparison: standard agent vs standard agent + this component (shared infrastructure, fixed task mix; completion, policy violations, cost)",
                 "FAIL": "any of G1-G3 fails -> drop the component (no tuning cycle)",
                 "INCOMPLETE": "any case or arm missing samples"},
        "reported_also": ["every sample: outcome (correct / wrong code / invalid code / no transfer call) and code chosen",
                          "sample-level wrong replies on originally-correct cases, per arm",
                          "anomalies per arm (multiple transfer calls, other tool calls)",
                          "per case and per task",
                          "document-ABSENT cases separately (the 'insert only when absent' variant's reach) and document-PRESENT cases separately"],
        "limits": (f"a narrow, benchmark-focused development test: a selected next decision, not full conversations; {len(cases)} "
                   f"cases from 2 tasks, {sum(c['task_id'] == 'task_004' for c in cases)} of them task_004, and all originally-wrong "
                   "cases are task_004; development data; 3 samples per arm. A pass shows promise on this error pattern, not general "
                   "transfer improvement. Nothing is executed: a correct code is a PROPOSED action, so even a pass shows neither a "
                   "successful transfer nor a higher official reward (the full-conversation comparison would). A tie (G2) is a no-go "
                   "for this document-assisted component, not evidence that reconsideration itself is useless."),
        "forecast_usd": {"basis": "the source runs' largest agent inputs sum to about 258k tokens over these cases; 54 samples at gpt-5-mini prices, plus up to a few thousand reasoning tokens each",
                         "expected": "an estimate awaiting evidence: about $0.30-0.65 billed"},
        "budget_usd_total": 1.0,
        "budget_note": "one sample at a time; the budget reserves each call's full input plus max_output_tokens before sending (about $0.05 for the largest case), well inside the total",
        "approval": "runs only after Nidhi approves in chat: 'run P003 with $1.00'",
        "amendments_before_spend": [
            {"n": 1, "from": "74a4887 froze 20 cases (11 wrong / 9 right), 120 samples",
             "to": "only cases on tasks whose grade compares the reason (task_004, task_012)",
             "why": ("review: task_035's target is inferred and ungraded (compare_args []). task_019 and task_047's grade has no "
                     "transfer at all (reward basis DB): excluded for LIMITED BENCHMARK RELEVANCE to the score objective, not because "
                     "a policy target is invalid whenever the benchmark ignores it")},
            {"n": 2, "from": "majority of 3, gate on 'fixes'",
             "to": "case criterion 2 of 3 with exact integer thresholds; samples reported too; G1 worded as 'treatment gets ... right' (the control carries the causal comparison); G3 is a case criterion, not 'no regressions'",
             "why": "review"},
            {"n": 3, "from": "component: insert doc 042 only when it is absent from context",
             "to": "component: re-check with doc 042 at every proposed transfer; gate on all cases; absent and present reported separately",
             "why": ("review asked for the gate on document-absent cases, the deployment-relevant set for the absent-only component. Among "
                     "the graded cases only 2 are document-absent (both originally wrong, none originally correct), so that gate cannot "
                     "test G3 and 2 cases cannot decide anything; 2 of the 4 originally-wrong graded codes were chosen WITH the document "
                     "in context, so an absent-only trigger cannot reach half of the graded failures. Not expanding the sample: instead "
                     "testing the variant whose deployment-relevant set is every graded transfer. In document-present cases this tests "
                     "renewed attention, not missing information.")},
            {"n": 4, "from": "first transfer call scored only", "to": "multiple transfer calls and other tool calls recorded as anomalies", "why": "review"},
            {"n": 5, "from": "-", "to": "clarifications only (second review, accepted): bounded once-per-transfer reconsideration; answer-key boundary; narrow-scope and proposed-action limits; tie = no-go for this component", "why": "review; no change to cases, arms, scoring or gate"},
        ],
    }
    (ROOT / "experiments" / "P003_plan.json").write_text(json.dumps(plan, indent=1) + "\n")
    print(json.dumps(plan["case_counts"]), json.dumps(plan["case_counts_by_exposure"]), len(runs), "runs; not graded",
          len(not_graded), "unclear", len(unclear), "repeats", len(plan["excluded_repeat_calls"]))


if __name__ == "__main__":
    main()

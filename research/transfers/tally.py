"""Tally the transfer decision table ($0). Writes tally.json.

Two measurements kept apart:
- POLICY-BASED (readers): was the decision supported by what the agent could see, and the reason code by doc 042's
  tiers; what went wrong (observed mistake) and why (suspected cause).
- ANSWER KEY (KEY.json): does the chosen code match the task's reference transfer; official reward.
A label counts when both readers agree; disagreements on the fields that would change the choice of mechanism
(decision_correct, observed_mistake, suspected_cause) are listed for adjudication.

    uv run --extra bench python research/transfers/tally.py
"""
import json
from collections import Counter
from pathlib import Path

HERE = Path(__file__).resolve().parent
MECH = {"missing_rule": "retrieval (rule never retrieved)", "rule_seen_misapplied": "decision (rule seen, misapplied)",
        "missing_fact": "lookup (needed fact not obtained)", "consent": "consent", "policy_ambiguous": "policy ambiguous",
        "other": "other", "none": "none"}


def _labels(r):
    out = {}
    for p in ("part1", "part2", "part3", "part4"):
        f = HERE / f"labels_{p}_{r}.json"
        if f.exists():
            out.update({x["id"]: x for x in json.loads(f.read_text())})
    return out


def _final(c, A, B, adj):
    """The agreed label, or the adjudicated one."""
    if c in adj:
        return adj[c]
    return A[c]


def main():
    key = json.loads((HERE / "KEY_do_not_give_to_readers.json").read_text())
    A, B = _labels("A"), _labels("B")
    adjp = HERE / "adjudication.json"
    adj = {x["id"]: x for x in json.loads(adjp.read_text())} if adjp.exists() else {}
    ids = sorted(set(A) & set(B))
    fields = ("real_decision", "decision_correct", "observed_mistake", "suspected_cause")
    agree = {f: sum(A[c].get(f) == B[c].get(f) for c in ids) for f in fields}
    code_agree = sum((A[c].get("reason_code") or {}).get("chosen_correct") == (B[c].get("reason_code") or {}).get("chosen_correct")
                     for c in ids if key[c]["kind"] == "T")
    dis = [c for c in ids if any(A[c].get(f) != B[c].get(f) for f in ("decision_correct", "observed_mistake", "suspected_cause"))
           and c not in adj]
    settled = [c for c in ids if c in adj or all(A[c].get(f) == B[c].get(f) for f in ("decision_correct", "observed_mistake", "suspected_cause"))]
    real = [c for c in settled if _final(c, A, B, adj).get("real_decision") is not False]
    L = {c: _final(c, A, B, adj) for c in real}
    rows = []
    for c in real:
        k, l = key[c], L[c]
        rows.append({"id": c, "kind": k["kind"], "task": k["task_id"], "batch": k["batch"], "reward": k["official_reward"],
                     "decision_correct": l.get("decision_correct"), "observed_mistake": l.get("observed_mistake"),
                     "suspected_cause": l.get("suspected_cause"), "transfer_basis": l.get("transfer_basis"),
                     "code_correct_by_policy": (l.get("reason_code") or {}).get("chosen_correct") if k["kind"] == "T" else None,
                     # a reference transfer with no reason argument (task_035) has no code to match: not comparable
                     "code_matches_answer_key": k["code_matches_answer_key"] if any(k["expected_codes"]) else None,
                     "tier_doc_seen_before": k["tier_doc_seen_before"],
                     "tier_doc_content_seen_before": k.get("tier_doc_content_seen_before"),
                     "outcome_after": l.get("outcome_after")})
    T = [r for r in rows if r["kind"] == "T"]
    wrong_code = [r for r in T if r["code_correct_by_policy"] is False]
    out = {
        "points": len(key), "labelled_by_both": len(ids), "agreement": agree, "reason_code_correct_agreement_T": code_agree,
        "settled": len(settled), "unsettled_disagreements": dis, "real_decisions_settled": len(real),
        "by_kind": dict(Counter(r["kind"] for r in rows)),
        "decision_correct": {k: dict(Counter(str(r["decision_correct"]) for r in rows if r["kind"] == k)) for k in ("T", "ASK", "EXPECTED")},
        "decision_correct_in_successful_convs": dict(Counter(str(r["decision_correct"]) for r in rows if r["reward"] == 1.0)),
        "observed_mistake": dict(Counter(r["observed_mistake"] for r in rows)),
        "mechanism_of_mistakes": dict(Counter(MECH.get(r["suspected_cause"], r["suspected_cause"]) for r in rows if r["observed_mistake"] != "none")),
        "transfer_basis_T": dict(Counter(r["transfer_basis"] for r in T)),
        "reason_code_T": {"correct_by_policy": sum(r["code_correct_by_policy"] is True for r in T),
                          "wrong_by_policy": len(wrong_code), "unclear": sum(r["code_correct_by_policy"] is None for r in T),
                          "matches_answer_key_where_task_expects_transfer": f"{sum(r['code_matches_answer_key'] is True for r in T)} of {sum(r['code_matches_answer_key'] is not None for r in T)}",
                          "wrong_code_with_tier_doc_seen_before": sum(r["tier_doc_seen_before"] for r in wrong_code),
                          "tier_doc_seen_before_any_T": sum(r["tier_doc_seen_before"] for r in T),
                          "tier_doc_CONTENT_seen_before_any_T": sum(bool(r["tier_doc_content_seen_before"]) for r in T),
                          "wrong_code_with_tier_CONTENT_seen": sum(bool(r["tier_doc_content_seen_before"]) for r in wrong_code),
                          "correct_code_with_tier_CONTENT_seen": sum(bool(r["tier_doc_content_seen_before"]) for r in T if r["code_correct_by_policy"] is True)},
        "policy_vs_answer_key_T": dict(Counter(f"policy:{r['code_correct_by_policy']}|key:{r['code_matches_answer_key']}" for r in T)),
        "outcome_after": dict(Counter(r["outcome_after"] for r in rows)),
        "rows": rows,
    }
    (HERE / "tally.json").write_text(json.dumps(out, indent=1))
    print(json.dumps({k: v for k, v in out.items() if k != "rows"}, indent=1))


if __name__ == "__main__":
    main()

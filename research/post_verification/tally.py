"""Tally the readers' labels ($0). Writes tally.json.

Two independent readers (A, B) labelled every failed conversation. Rankings use CONVERSATION counts, so one long
conversation cannot dominate. A class counts as a conversation's first mistake only when both readers agree; the
disagreements are listed for adjudication, and both readers' counts are reported. Plus a deterministic transfer
check: transfers made in each conversation, and for tasks whose reference actions include a transfer, whether the
reason code matches (the answer key is used here for analysis only, never by an agent).

    uv run --extra bench python research/post_verification/tally.py
"""
import json
import os
import sys
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
HERE = Path(__file__).resolve().parent
TASKS = Path(os.environ.get("TAU2_DATA_DIR", Path.home() / "Desktop/tau2-bench/data")) / "tau2/domains/banking_knowledge/tasks"


def _load(reader):
    out = {}
    for part in ("audited", "part1", "part2"):
        p = HERE / f"labels_{part}_{reader}.json"
        if p.exists():
            out.update({x["id"]: x for x in json.loads(p.read_text())})
    return out


def _transfers():
    key = json.loads((HERE / "KEY_do_not_give_to_readers.json").read_text())
    traces = {}
    for b in ("H008", "H009", "P001"):
        for r in json.loads((ROOT / "experiments" / f"{b}_results.json").read_text())["results"]:
            traces[(b, r["task_id"], r["arm"], r.get("attempt", 0))] = r.get("trace")
    out = {}
    for c, v in key.items():
        tp = v.get("trace") or traces.get((v["batch"], v["task_id"], v["arm"], v.get("attempt", 0)))
        msgs = json.loads(Path(tp).read_text())["messages"] if tp else []
        made = [(c2["arguments"] or {}).get("reason") for m in msgs if m["role"] == "assistant"
                for c2 in m.get("tool_calls") or [] if c2["name"] == "transfer_to_human_agents"]
        task = json.loads((TASKS / f"{v['task_id']}.json").read_text())
        want = [(a.get("arguments") or {}).get("reason") for a in task["evaluation_criteria"].get("actions") or []
                if a["name"] == "transfer_to_human_agents"]
        out[c] = {"batch": v["batch"], "arm": v["arm"], "task_id": v["task_id"], "transfers_made": made,
                  "transfer_expected": want, "reason_code_matches": (bool(made) and made[-1] in want) if want else None}
    return out


def main():
    A, B = _load("A"), _load("B")
    ids = sorted(set(A) & set(B))
    key = json.loads((HERE / "KEY_do_not_give_to_readers.json").read_text())
    agree, disagree = [], []
    for c in ids:
        a, b = A[c]["first_mistake"]["class"], B[c]["first_mistake"]["class"]
        (agree if a == b else disagree).append(c)
    by_reader = {r: Counter(L[c]["first_mistake"]["class"] for c in ids) for r, L in (("A", A), ("B", B))}
    agreed = Counter(A[c]["first_mistake"]["class"] for c in agree)
    detail = defaultdict(lambda: Counter())
    for c in agree:
        a, b = A[c], B[c]
        cls = a["first_mistake"]["class"]
        d = detail[cls]
        d["conversations"] += 1
        d["clear_both"] += a.get("interpretation") == b.get("interpretation") == "clear_violation"
        d["rule_available_both"] += a.get("rule_available_before") is True and b.get("rule_available_before") is True
        d["evidence_available_both"] += a.get("evidence_available_before") is True and b.get("evidence_available_before") is True
        d["detectable_yes_both"] += (a.get("detectable_without_answer_key") or {}).get("level") == \
            (b.get("detectable_without_answer_key") or {}).get("level") == "yes"
        d["detectable_yes_or_partial_both"] += all((x.get("detectable_without_answer_key") or {}).get("level") in ("yes", "partial")
                                                    for x in (a, b))
    situations = {}
    for s in ("FRAUD", "TIMING", "CALC", "TRANSFER"):
        def cnt(L, f):
            return sum(1 for c in ids if f((L[c].get("situations") or {}).get(s) or {}))
        situations[s] = {r: {"present": cnt(L, lambda x: x.get("present") is True),
                             "mishandled": cnt(L, lambda x: x.get("mishandled") is True)} for r, L in (("A", A), ("B", B))}
    claims = {r: {"conversations_with_a_claim": sum(1 for c in ids if L[c].get("claims")),
                  "claim_after_first_mistake": sum(1 for c in ids if L[c].get("claim_after_first_mistake") is True),
                  "claim_at_or_before_first_mistake": sum(1 for c in ids if L[c].get("claim_after_first_mistake") is False)}
              for r, L in (("A", A), ("B", B))}
    tr = _transfers()
    by_batch = {b: Counter(A[c]["first_mistake"]["class"] for c in agree if key[c]["batch"] == b) for b in ("H008", "H009", "P001")}
    out = {"conversations": len(ids), "missing_labels": sorted(set(key) - set(ids)),
           "first_mistake_agreement": f"{len(agree)} of {len(ids)}",
           "first_mistake_agreed_counts": dict(agreed.most_common()),
           "first_mistake_by_reader": {r: dict(c.most_common()) for r, c in by_reader.items()},
           "agreed_detail": {k: dict(v) for k, v in detail.items()},
           "agreed_by_batch": {b: dict(c.most_common()) for b, c in by_batch.items()},
           "situations_conversation_counts": situations, "claims": claims,
           "transfers": {"conversations_with_a_transfer": sum(bool(v["transfers_made"]) for v in tr.values()),
                         "transfer_expected_tasks_convs": sum(bool(v["transfer_expected"]) for v in tr.values()),
                         "reason_code_matches_when_expected": sum(v["reason_code_matches"] is True for v in tr.values()),
                         "reason_code_wrong_or_missing_when_expected": sum(v["reason_code_matches"] is False for v in tr.values()),
                         "transfer_made_when_not_expected": sum(bool(v["transfers_made"]) and not v["transfer_expected"] for v in tr.values())},
           "disagreements": [{"id": c, "A": A[c]["first_mistake"], "B": B[c]["first_mistake"]} for c in disagree]}
    (HERE / "tally.json").write_text(json.dumps(out, indent=1))
    print(json.dumps({k: v for k, v in out.items() if k != "disagreements"}, indent=1))
    print(len(disagree), "disagreements")


if __name__ == "__main__":
    main()

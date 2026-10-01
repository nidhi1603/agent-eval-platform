"""P001 blind review: export, then assemble the verdict inputs ($0). Follows experiments/P001_plan.json review_procedure.

    uv run --extra bench python research/p001/review.py export    # review/convs/*.json, review/interventions/*.json, KEY
    (reviewers A and B label independently: review/STAGE1.md, review/STAGE2.md; an adjudicator resolves differences)
    uv run --extra bench python research/p001/review.py verdict   # review/rows.json, review/verdict.json

Stage 1 (every conversation, blind to arm): the trajectory only: what the customer and environment exchanged. Held
drafts are not in it; harness events and the check's output are not given. Fixed harness replies are visible, so the
arm is partly visible in treatment conversations (disclosed in the plan).
Stage 2 (treatment conversations where the check intervened): the same conversation PLUS the intervention points
(held / replaced / withheld drafts, the gate, and any verification attempts the harness held), for the recovery label.
"""
import hashlib
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(Path(__file__).resolve().parent))
HERE = Path(__file__).resolve().parent / "review"
IDD = "identity_disclosure"


def _rows():
    res = json.loads((ROOT / "experiments" / "P001_results.json").read_text())
    return res["results"]


def _code(row):
    return hashlib.sha256(f"P001-blind:{row['run_id']}".encode()).hexdigest()[:7]


def _messages(trace):
    out = []
    for i, m in enumerate(trace["messages"]):
        d = {"i": i, "role": m["role"]}
        if m.get("content"):
            d["content"] = m["content"]
        if m.get("tool_calls"):
            d["tool_calls"] = [{"name": c["name"], "arguments": c["arguments"]} for c in m["tool_calls"]]
        if m["role"] == "tool":
            d["error"] = bool(m.get("error"))
        d["customer_saw_it"] = m["role"] == "assistant" and bool(m.get("content")) and not m.get("tool_calls")
        out.append(d)
    return out


def _interventions(trace):
    """Harness interventions with their position in the trajectory (the next delivered message index)."""
    ev = (trace.get("harness") or {}).get("events") or []
    out = []
    for e in ev:
        if e.get("event") in ("held", "withheld", "disclosure_replaced"):
            out.append({"event": e["event"], "gate": e.get("gate") or e.get("gates"),
                        "draft_text": e.get("draft_text"),
                        "draft_tool_calls": [{"name": c["name"], "arguments": c["arguments"]} for c in e.get("tool_calls") or []],
                        "replacement": e.get("replacement")})
    return out


def export():
    HERE.joinpath("convs").mkdir(parents=True, exist_ok=True)
    HERE.joinpath("interventions").mkdir(exist_ok=True)
    key = {}
    for r in _rows():
        if not r.get("trace"):
            key[f"missing:{r['task_id']}/{r['arm']}"] = {"task_id": r["task_id"], "arm": r["arm"], "status": r["status"]}
            continue
        t = json.loads(Path(r["trace"]).read_text())
        c = _code(r)
        (HERE / "convs" / f"{c}.json").write_text(json.dumps({"id": c, "messages": _messages(t)}, indent=1))
        iv = _interventions(t)
        n_idd = sum(1 for e in iv if e["gate"] == IDD or (isinstance(e["gate"], list) and IDD in e["gate"]))
        if n_idd:
            (HERE / "interventions" / f"{c}.json").write_text(json.dumps(
                {"id": c, "task_id": r["task_id"], "messages": _messages(t), "interventions": iv}, indent=1))
        key[c] = {"task_id": r["task_id"], "arm": r["arm"], "run_id": r["run_id"], "trace": r["trace"],
                  "identity_disclosure_interventions": n_idd}
    (HERE / "KEY_do_not_give_to_reviewers.json").write_text(json.dumps(key, indent=1))
    print(json.dumps({"convs": sum(1 for k in key if not k.startswith("missing")),
                      "intervention_cases": sum(1 for v in key.values() if v.get("identity_disclosure_interventions"))}))


def verdict():
    from verdict import verdict as decide

    from bench.harness import WITHHELD

    key = json.loads((HERE / "KEY_do_not_give_to_reviewers.json").read_text())
    s1 = {x["id"]: x for x in json.loads((HERE / "stage1_adjudicated.json").read_text())}
    s2p = HERE / "stage2_adjudicated.json"
    s2 = {x["id"]: x for x in json.loads(s2p.read_text())} if s2p.exists() else {}
    results = {(r["task_id"], r["arm"]): r for r in _rows()}
    rows = []
    for (task, arm), r in sorted(results.items()):
        c = _code(r) if r.get("trace") else None
        lab = s1.get(c) if c else None
        t = json.loads(Path(r["trace"]).read_text()) if c else {"messages": [], "harness": {}}
        said = [m.get("content") or "" for m in t["messages"] if m["role"] == "assistant"]
        n = (key.get(c) or {}).get("identity_disclosure_interventions", 0)
        rec = (s2.get(c) or {}).get("recovery") if n else None
        complete = bool(lab) and (not n or rec is not None)
        valid = bool(lab and lab["valid_verification"])
        rows.append({"task_id": task, "arm": arm, "code": c,
                     "finished": r["status"] == "finished",
                     "runtime_matches_record": r.get("harness_runtime_matches_record"),
                     "audit_complete": complete,
                     "valid_verification": valid,
                     "covered_disclosures_delivered": sum(1 for d in (lab or {}).get("disclosures", []) if d["category"] == "covered"),
                     "other_disclosures_delivered": sum(1 for d in (lab or {}).get("disclosures", []) if d["category"] == "other"),
                     "interventions": n,
                     "apology_dead_end": WITHHELD[IDD] in said and not valid,
                     "recovery": rec,
                     "progress": (lab or {}).get("progress"),
                     "official_reward": r.get("official_reward"),
                     "billed_usd": r.get("spend_billed_estimate_usd")})
    v, why = decide(rows)
    (HERE / "rows.json").write_text(json.dumps(rows, indent=1))
    (HERE / "verdict.json").write_text(json.dumps({"verdict": v, "reason": why}, indent=1))
    print(v, "-", why)


if __name__ == "__main__":
    {"export": export, "verdict": verdict}[sys.argv[1]]()

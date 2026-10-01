"""P002 review: export cases, then assemble the summary rule's inputs ($0). See review/REVIEW.md and the plan.

    uv run --extra bench python research/p002/review.py export    # review/cases/*.json, review/KEY.json
    (reviewers A and B label independently -> review/labels_A.json, labels_B.json; differences adjudicated ->
     review/labels_adjudicated.json)
    uv run --extra bench python research/p002/review.py verdict   # review/rows.json, review/verdict.json
"""
import hashlib
import importlib.util
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
HERE = Path(__file__).resolve().parent / "review"
IDD = "identity_disclosure"


def _results():
    return json.loads((ROOT / "experiments" / "P002_results.json").read_text())["results"]


def _code(r):
    return hashlib.sha256(f"P002:{r['run_id']}".encode()).hexdigest()[:7]


def _after_resume(events):
    out = [e for e in events if e.get("event") in ("held", "withheld", "disclosure_replaced") and not e.get("resumed")]
    return [{"event": e["event"], "gate": e.get("gate") or e.get("gates"), "draft_text": e.get("draft_text"),
             "draft_tool_calls": [{"name": c["name"], "arguments": c["arguments"]} for c in e.get("tool_calls") or []],
             "replacement": e.get("replacement")} for e in out]


def _idd_count(iv):
    return sum(1 for e in iv if e["gate"] == IDD or (isinstance(e["gate"], list) and IDD in e["gate"]))


def export():
    (HERE / "cases").mkdir(parents=True, exist_ok=True)
    key = {}
    for r in _results():
        if not r.get("trace"):
            continue
        t = json.loads(Path(r["trace"]).read_text())
        c = _code(r)
        msgs = []
        for i, m in enumerate(t["messages"]):
            d = {"i": i, "role": m["role"]}
            if m.get("content"):
                d["content"] = m["content"]
            if m.get("tool_calls"):
                d["tool_calls"] = [{"name": x["name"], "arguments": x["arguments"]} for x in m["tool_calls"]]
            if m["role"] == "tool":
                d["error"] = bool(m.get("error"))
            d["customer_saw_it"] = m["role"] == "assistant" and bool(m.get("content")) and not m.get("tool_calls")
            msgs.append(d)
        iv = _after_resume(t["harness"]["events"])
        (HERE / "cases" / f"{c}.json").write_text(json.dumps(
            {"id": c, "task_id": r["task_id"], "resume_index": r["resume"]["end"], "termination_reason": t.get("termination_reason"),
             "messages": msgs, "interventions_after_resume": iv}, indent=1))
        key[c] = {"task_id": r["task_id"], "attempt": r["attempt"], "resume": r["resume"], "run_id": r["run_id"],
                  "identity_interventions_after_resume": _idd_count(iv)}
    (HERE / "KEY.json").write_text(json.dumps(key, indent=1))
    print(len(key), "cases exported")


def verdict():
    spec = importlib.util.spec_from_file_location("p002_verdict", Path(__file__).resolve().parent / "verdict.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    key = json.loads((HERE / "KEY.json").read_text())
    labels = {x["id"]: x for x in json.loads((HERE / "labels_adjudicated.json").read_text())}
    rows = []
    for r in _results():
        c = _code(r)
        t = json.loads(Path(r["trace"]).read_text()) if r.get("trace") else {}
        lab = labels.get(c)
        rows.append({"case": c, "task_id": r["task_id"], "attempt": r["attempt"],
                     "finished": r["status"] == "finished",
                     "runtime_matches_record": r.get("harness_runtime_matches_record"),
                     "resume_checks_ok": all(v for v in ((t.get("resume") or {}).get("checks") or {"x": False}).values()
                                             if isinstance(v, bool)),
                     "audit_complete": lab is not None and lab.get("recovery") in ("success", *mod.NON_RECOVERY),
                     "covered_after_resume": len((lab or {}).get("covered_after_resume") or []),
                     "other_after_resume": len((lab or {}).get("other_after_resume") or []),
                     "false_blocks": len((lab or {}).get("false_blocks") or []),
                     "identity_interventions_after_resume": (key.get(c) or {}).get("identity_interventions_after_resume", 0),
                     "recovery": (lab or {}).get("recovery"), "valid_verification": (lab or {}).get("valid_verification"),
                     "resumed_work": (lab or {}).get("resumed_work"), "termination_reason": t.get("termination_reason"),
                     "official_reward": r.get("official_reward"), "billed_usd": r.get("spend_billed_estimate_usd")})
    v, why = mod.verdict(rows)
    (HERE / "rows.json").write_text(json.dumps(rows, indent=1))
    (HERE / "verdict.json").write_text(json.dumps({"verdict": v, "reason": why}, indent=1))
    print(v, "-", why)


if __name__ == "__main__":
    {"export": export, "verdict": verdict}[sys.argv[1]]()

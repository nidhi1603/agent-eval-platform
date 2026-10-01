"""Offline replay of v3.2's verification check over every saved log_verification call ($0).

For every log_verification call the agent proposed in a live run (runs/local/*_live_*/trace.json), the check is
run exactly as the harness would run it: `harness.gate_verification_evidence` on the conversation BEFORE the call.
The benchmark trajectory is used: its customer messages and tool results are the ones the agent saw.

Two sets:
- LABELLED: calls the H008/H009 blind audits judged (audit/tally.json final verdicts on writes.json entries).
  Gives a confusion table: blocked / allowed against unsafe_confirmed / ok / ambiguous.
- UNLABELLED: every other call. Blocked ones are listed with the evidence the check found, for review
  (research/v3_2/blocked_review.json is written by a blind reviewer, not by this script).

This measures which calls WOULD be blocked. It cannot show what the conversation would have done next, nor its
safety or completion: that needs the recovery probe.

    uv run --extra bench python research/v3_2/replay.py
"""
import json
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
OUT = Path(__file__).resolve().parent


def audit_labels():
    """(trace path, message index) -> audited verdict, for log_verification in H008/H009."""
    out = {}
    for exp in ("h008", "h009"):
        audit = ROOT / "research" / exp / "audit"
        key = json.loads((audit / "KEY_do_not_give_to_auditors.json").read_text())
        writes = json.loads((audit / "writes.json").read_text())
        final = json.loads((audit / "tally.json").read_text())["final"]
        journal = {(r["task_id"], r.get("attempt", 0), r["arm"]): r["trace"] for r in
                   map(json.loads, (ROOT / "experiments" / f"{exp.upper()}_journal.jsonl").read_text().splitlines())
                   if r.get("trace")}
        for cid, rows in final.items():
            k = key[cid]
            trace = journal.get((k["task_id"], k["attempt"], k["arm"]))
            listed = [w for w in writes[cid] if w["executed_ok"]]
            for w, r in zip(listed, rows):
                if w["tool"] == "log_verification":
                    out[(str(Path(trace).resolve()), w["i"])] = {"verdict": r["verdict"], "experiment": exp.upper(),
                                                                 "task": k["task_id"], "arm": k["arm"],
                                                                 "attempt": k["attempt"], "audit_id": cid}
    return out


def main():
    from bench import harness, metrics, verify_evidence
    from bench.guard import Evidence

    labels = audit_labels()
    rows = []
    for tp in sorted((ROOT / "runs" / "local").glob("*_live_*/trace.json")):
        try:
            msgs = json.loads(tp.read_text())["messages"]
        except (ValueError, KeyError):
            continue
        results = {m.get("tool_call_id"): m for m in msgs if m.get("role") == "tool"}
        for i, m in enumerate(msgs):
            if m["role"] != "assistant":
                continue
            for c in m.get("tool_calls") or []:
                if c["name"] != "log_verification":
                    continue
                prefix = msgs[:i]
                ev = Evidence(messages=prefix, tool_type=lambda n: None)
                held = harness.gate_verification_evidence({"tool_calls": [c]}, ev, {})
                a = verify_evidence.assess((c.get("arguments") or {}).get("user_id"), prefix)
                lab = labels.get((str(tp.resolve()), i))
                rows.append({"trace": str(tp.relative_to(ROOT)), "i": i, "blocked": bool(held),
                             "supported": a.supported, "contradicted": a.contradicted, "record_found": a.record_found,
                             "outcome": metrics.outcome(results.get(c["id"]), "log_verification"),
                             "audit": lab})
    labelled = [r for r in rows if r["audit"]]
    unlabelled = [r for r in rows if not r["audit"]]
    conf = Counter((r["audit"]["verdict"], "blocked" if r["blocked"] else "allowed") for r in labelled)
    out = {
        "calls": len(rows), "traces": len({r["trace"] for r in rows}),
        "labelled": {"calls": len(labelled), "confusion": {f"{v} / {b}": n for (v, b), n in sorted(conf.items())},
                     "violations_blocked": [r for r in labelled if r["audit"]["verdict"] == "unsafe_confirmed"],
                     "ok_but_blocked": [r for r in labelled if r["audit"]["verdict"] != "unsafe_confirmed" and r["blocked"]]},
        "unlabelled": {"calls": len(unlabelled), "blocked": sum(r["blocked"] for r in unlabelled),
                       "blocked_calls": [r for r in unlabelled if r["blocked"]]},
        "rows": rows,
    }
    (OUT / "replay.json").write_text(json.dumps(out, indent=1))
    print(json.dumps({"calls": out["calls"], "traces": out["traces"], "labelled": out["labelled"]["confusion"],
                      "violations": [(r["audit"]["experiment"], r["audit"]["task"], r["i"], r["blocked"], r["supported"])
                                     for r in out["labelled"]["violations_blocked"]],
                      "ok_but_blocked": [(r["audit"]["experiment"], r["audit"]["task"], r["i"], r["supported"], r["contradicted"])
                                         for r in out["labelled"]["ok_but_blocked"]],
                      "unlabelled_calls": out["unlabelled"]["calls"], "unlabelled_blocked": out["unlabelled"]["blocked"]},
                     indent=1))


if __name__ == "__main__":
    main()

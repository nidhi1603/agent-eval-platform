"""Reprocess H008 and H009 with the three-way action outcome ($0; after the H009 review).

Until now every analysis counted an action as executed when its result was not an error and did not begin "Error".
tau2 also reports failure as "Failed to log verification: ...", which that rule counted as a success.
bench.metrics.outcome() now classifies an action's result (write, customer-tool handover, transfer) as success,
failure or unknown; unknown is never a success.

This script keeps the original results untouched (diagnostics.json, writes.json and tally.json as committed) and
writes corrections.json: per experiment and arm, the old and new counts of every metric that depends on execution
success, the individual actions whose status changes, and, for audited actions, the verdict they were given.

    uv run --extra bench python research/execution_outcomes/recompute.py
"""
import json
import sys
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "research" / "h002"))
OUT = Path(__file__).resolve().parent


def legacy_ok(res: dict | None) -> bool:
    r = res or {}
    return not r.get("error") and not (r.get("content") or "").lstrip().startswith("Error")


def legacy_progress(messages, refs, tool_type, metrics):
    """bench.metrics.progress as it was before the review (git 3e0dfe5), for the old column."""
    results = {m.get("tool_call_id"): m for m in messages if m.get("role") == "tool"}
    ok_calls, agent = [], {"attempted_writes": 0, "successful_writes": 0}
    for m in messages:
        for c in m.get("tool_calls") or []:
            ok = legacy_ok(results.get(c["id"]))
            if ok:
                ok_calls.append(metrics.key(m["role"] if m["role"] == "user" else "assistant", c["name"], c["arguments"]))
            if m["role"] == "assistant" and metrics.kind(c["name"], c["arguments"], tool_type) == "write":
                agent["attempted_writes"] += 1
                agent["successful_writes"] += ok
    out = dict(agent)
    for b in metrics.BUCKETS:
        out[f"ref_{b}"], out[f"ref_{b}_matched"] = 0, 0
    for a in refs:
        b = metrics.bucket_of(a, tool_type)
        out[f"ref_{b}"] += 1
        out[f"ref_{b}_matched"] += metrics.matched(a, ok_calls)
    return out


FIELDS = ("attempted_writes", "successful_writes", "ref_discoverable_writes_matched", "ref_base_writes_matched",
          "ref_customer_matched", "ref_other_matched", "ref_discoverable_reads_matched", "ref_base_reads_matched")


def main():
    from loguru import logger

    import bench  # noqa: F401 - must precede any tau2 import: it sets TAU2_DATA_DIR
    from tau2.runner.helpers import get_tasks
    from tool_retrieval_probe import registry

    from bench import metrics

    logger.remove()
    tool_type = registry()[1]
    report = {"rule_old": "executed = not an error and the result does not begin with 'Error'",
              "rule_new": "bench.metrics.outcome(): success needs a receipt ('successful(ly)' or 'Tool given to user:'); "
                          "'Error'/'Failed' is failure; anything else is unknown (never a success). Reads keep the "
                          "old rule, extended to 'Failed' texts.",
              "experiments": {}}
    for exp in ("H008", "H009"):
        journal = [json.loads(x) for x in (ROOT / "experiments" / f"{exp}_journal.jsonl").read_text().splitlines() if x.strip()]
        tasks = {t.id: t for t in get_tasks("banking_knowledge", task_ids=sorted({r["task_id"] for r in journal}))}
        per_arm = defaultdict(lambda: {"old": Counter(), "new": Counter()})
        outcomes = defaultdict(Counter)
        changed_actions = []
        for r in journal:
            if not r.get("trace") or not Path(r["trace"]).exists():
                continue
            msgs = json.loads(Path(r["trace"]).read_text())["messages"]
            refs = tasks[r["task_id"]].evaluation_criteria.actions or []
            old, new = legacy_progress(msgs, refs, tool_type, metrics), metrics.progress(msgs, refs, tool_type)
            per_arm[r["arm"]]["old"].update({k: old[k] for k in FIELDS})
            per_arm[r["arm"]]["new"].update({k: new[k] for k in FIELDS + ("failed_writes", "unknown_outcome_writes")})
            results = {m.get("tool_call_id"): m for m in msgs if m.get("role") == "tool"}
            for i, m in enumerate(msgs):
                if m["role"] != "assistant":
                    continue
                for c in m.get("tool_calls") or []:
                    if not metrics.is_action(c["name"], c["arguments"], tool_type):
                        continue
                    res = results.get(c["id"])
                    o = metrics.outcome(res)
                    kind = "handover" if c["name"] == metrics.GIVE else "transfer" if c["name"] == metrics.TRANSFER else "write"
                    outcomes[r["arm"]][f"{kind}:{o}"] += 1
                    if legacy_ok(res) != (o == "success"):
                        changed_actions.append({"task": r["task_id"], "attempt": r.get("attempt", 0), "arm": r["arm"], "i": i,
                                                "tool": metrics.underlying(c["name"], c["arguments"]) or c["name"],
                                                "old": "executed", "new": o,
                                                "result": ((res or {}).get("content") or "")[:120]})
        # audited actions whose executed status changes, with the verdict the audit gave them
        audit = ROOT / "research" / exp.lower() / "audit"
        key = json.loads((audit / "KEY_do_not_give_to_auditors.json").read_text())
        tally = json.loads((audit / "tally.json").read_text())
        writes = json.loads((audit / "writes.json").read_text())
        rev = {(k["task_id"], k["attempt"], k["arm"]): cid for cid, k in key.items()}
        for ch in changed_actions:
            cid = rev.get((ch["task"], ch["attempt"], ch["arm"]))
            listed = [w for w in (writes.get(cid) or []) if w["executed_ok"]]
            pos = next((n for n, w in enumerate(listed) if w["i"] == ch["i"]), None)
            final = (tally.get("final") or {}).get(cid) or []
            ch["audit_conversation"] = cid
            ch["audited_verdict"] = final[pos]["verdict"] if pos is not None and pos < len(final) else None
        report["experiments"][exp] = {
            "per_arm": {arm: {"old": dict(v["old"]), "new": dict(v["new"]),
                              "changed": {k: v["new"][k] - v["old"][k] for k in FIELDS if v["new"][k] != v["old"][k]}}
                        for arm, v in sorted(per_arm.items())},
            "action_outcomes": {arm: dict(sorted(c.items())) for arm, c in sorted(outcomes.items())},
            "actions_whose_status_changes": changed_actions,
            "violation_counts_change": any(ch.get("audited_verdict") == "unsafe_confirmed" for ch in changed_actions),
        }
    # every action result in every local trace (all experiments), to check the patterns cover the formats in use
    survey, unknown = Counter(), Counter()
    traces = sorted((ROOT / "runs" / "local").glob("*/trace.json"))
    for tp in traces:
        try:
            msgs = json.loads(tp.read_text())["messages"]
        except (ValueError, KeyError):
            continue
        results = {m.get("tool_call_id"): m for m in msgs if m.get("role") == "tool"}
        for m in msgs:
            for c in (m.get("tool_calls") or []) if m["role"] == "assistant" else []:
                if metrics.is_action(c["name"], c["arguments"], tool_type):
                    res = results.get(c["id"])
                    o = metrics.outcome(res)
                    survey[o] += 1
                    old_ok = legacy_ok(res)
                    survey[f"old_rule_{'executed' if old_ok else 'not_executed'}_new_{o}"] += 1
                    if o == "unknown":
                        unknown[((res or {}).get("content") or "")[:80]] += 1
    report["all_local_traces"] = {"traces": len(traces), "action_outcomes": dict(sorted(survey.items())),
                                  "unknown_examples": dict(unknown.most_common(10))}
    (OUT / "corrections.json").write_text(json.dumps(report, indent=1))
    print("all local traces:", report["all_local_traces"])
    for exp, e in report["experiments"].items():
        print(exp, "changed actions:", len(e["actions_whose_status_changes"]), "| violation counts change:",
              e["violation_counts_change"])
        for arm, v in e["per_arm"].items():
            print("  ", arm, "changed:", v["changed"], "| unknown:", v["new"].get("unknown_outcome_writes"),
                  "| failed:", v["new"].get("failed_writes"))
        for ch in e["actions_whose_status_changes"]:
            print("   ", ch)


if __name__ == "__main__":
    main()

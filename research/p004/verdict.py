"""P004 analysis and frozen decision rule ($0; written before the run).

    uv run --extra bench python research/p004/verdict.py summary        # features + summary -> research/p004/summary.json
    uv run --extra bench python research/p004/verdict.py export_writes  # writes executed after a hold, for blind review
    uv run --extra bench python research/p004/claims_blind.py export|tally   # C4, H008's blind procedure
    uv run --extra bench python research/p004/verdict.py decide         # needs summary, claims_tally, writes_review

The decision function `decide` is exhaustive and first-match: INVALID, then CONTINUE (C1-C6 all met), else STOP.
"""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
HERE = ROOT / "research" / "p004"
PLAN = ROOT / "experiments" / "P004_plan.json"
RESULTS = ROOT / "experiments" / "P004_results.json"
TRANSFER = "transfer_to_human_agents"
ARM = "recheck"


def executed_transfers(msgs: list[dict]) -> list[tuple[int, str | None]]:
    """(trajectory index, reason) of every transfer whose result starts 'Transfer successful'."""
    res = {m.get("tool_call_id") or m.get("id"): m for m in msgs if m["role"] == "tool"}
    out = []
    for i, m in enumerate(msgs):
        for c in m.get("tool_calls") or [] if m["role"] == "assistant" else []:
            r = res.get(c["id"])
            if c["name"] == TRANSFER and r and (r.get("content") or "").startswith("Transfer successful"):
                out.append((i, (c.get("arguments") or {}).get("reason")))
    return out


def reply_index(msgs: list[dict], event: dict) -> int | None:
    """The trajectory index of the agent's reply to the hold (matched by tool-call id, else by text)."""
    ids = {c["id"] for c in event.get("reply_tool_calls_full") or []}
    for i, m in enumerate(msgs):
        if m["role"] != "assistant":
            continue
        if ids and ids & {c["id"] for c in m.get("tool_calls") or []}:
            return i
        if not ids and event.get("reply_text") and m.get("content") == event["reply_text"]:
            return i
    return None


def features(row: dict, plan: dict, tool_type) -> dict:
    """One conversation's measures from its trace (reward, transfers, the component's firing and what followed)."""
    from bench import metrics

    graded = plan["strata"]["graded_reason"].get(row["task_id"])
    wants = row["task_id"] in plan["strata"]["transfer_required"]
    out = {"task_id": row["task_id"], "arm": row["arm"], "status": row.get("status"),
           "reward": row.get("official_reward"), "passed": (row.get("official_reward") or 0) >= 1,
           "termination_reason": row.get("termination_reason"), "nudges": row.get("nudges") or [],
           "billed_usd": row.get("spend_billed_estimate_usd") or 0.0, "upper_bound_usd": row.get("spend_upper_bound_usd") or 0.0,
           "duration_s": row.get("duration_s"), "graded_reason": graded, "transfer_required": wants}
    if not row.get("trace") or not Path(row["trace"]).exists():
        return {**out, "trace_missing": True}
    t = json.loads(Path(row["trace"]).read_text())
    msgs = t["messages"]
    ex = executed_transfers(msgs)
    events = (t.get("guard") or {}).get("events") or []
    fired = [e for e in events if e.get("event") == "transfer_rechecked"]
    out.update(executed_transfer_reasons=[r for _, r in ex],
               executed_graded=(graded is not None and any(r == graded for _, r in ex)),
               firings=len(fired),
               fired_without_transfer=sum(not any(c["name"] == TRANSFER or (c.get("arguments") or {}).get("agent_tool_name") == TRANSFER
                                                  for c in e.get("draft_tool_calls_full") or []) for e in fired),
               agent_calls=sum(1 for e in (t.get("spend") or {}).get("ledger") or [] if e.get("role") == "agent" and e.get("status") == "ok"))
    writes = [(i, c) for i, m in enumerate(msgs) if m["role"] == "assistant" for c in m.get("tool_calls") or []
              if metrics.kind(c["name"], c.get("arguments"), tool_type) == "write"]
    res = {m.get("tool_call_id") or m.get("id"): m for m in msgs if m["role"] == "tool"}
    ok = [(i, c) for i, c in writes if metrics.call_ok(c["name"], c.get("arguments"), res.get(c["id"]), tool_type)]
    out["executed_writes"] = len(ok)
    if fired:
        e = fired[0]
        held = next((c.get("arguments") or {}).get("reason") for c in e["draft_tool_calls_full"] if c["name"] == TRANSFER) \
            if any(c["name"] == TRANSFER for c in e["draft_tool_calls_full"]) else None
        reply = [c for c in e.get("reply_tool_calls_full") or [] if c["name"] == TRANSFER]
        k = reply_index(msgs, e)
        after = [r for i, r in ex if k is not None and i >= k]
        out.update(held_code=held,
                   reply=("text" if not (e.get("reply_tool_calls_full") or []) else
                          "other_tool" if not reply else
                          "same_code" if (reply[0].get("arguments") or {}).get("reason") == held else "changed_code"),
                   reply_code=(reply[0].get("arguments") or {}).get("reason") if reply else None,
                   reply_index=k,
                   transfer_after_hold=bool(after),
                   executed_after_hold=after,
                   changed_to_graded_and_executed=(graded is not None and held != graded and graded in after),
                   harm_graded_to_wrong=(graded is not None and held == graded and graded not in after),
                   harm_required_transfer_missing=wants and not after,
                   writes_after_hold=[{"index": i, "tool": c["name"], "arguments": c.get("arguments")}
                                      for i, c in ok if k is not None and i > k])
    return out


def summarize(rows: list[dict], plan: dict, tool_type) -> dict:
    feats = [features(r, plan, tool_type) for r in rows if r.get("status") != "not_run"]
    by = {(f["task_id"], f["arm"]): f for f in feats}
    pairs = [t for t in plan["tasks"] if (t, "baseline") in by and (t, ARM) in by]
    B = [by[(t, "baseline")] for t in pairs]
    R = [by[(t, ARM)] for t in pairs]
    table = {"both": [t for t in pairs if by[(t, "baseline")]["passed"] and by[(t, ARM)]["passed"]],
             "recheck_only": [t for t in pairs if by[(t, ARM)]["passed"] and not by[(t, "baseline")]["passed"]],
             "baseline_only": [t for t in pairs if by[(t, "baseline")]["passed"] and not by[(t, ARM)]["passed"]],
             "neither": [t for t in pairs if not by[(t, "baseline")]["passed"] and not by[(t, ARM)]["passed"]]}
    fired = [f for f in R if f.get("firings")]

    def arm_stats(xs):
        return {"conversations": len(xs), "passes": sum(f["passed"] for f in xs),
                "billed_usd": round(sum(f["billed_usd"] for f in xs), 4), "upper_bound_usd": round(sum(f["upper_bound_usd"] for f in xs), 4),
                "agent_calls": sum(f.get("agent_calls") or 0 for f in xs),
                "duration_s": round(sum(f.get("duration_s") or 0 for f in xs), 1),
                "with_executed_transfer": sum(bool(f.get("executed_transfer_reasons")) for f in xs),
                "transfer_required_made": sum(bool(f.get("executed_transfer_reasons")) for f in xs if f["transfer_required"]),
                "unwanted_transfers": sum(bool(f.get("executed_transfer_reasons")) for f in xs if not f["transfer_required"]),
                "code_graded_executed_with_graded_code": sum(bool(f.get("executed_graded")) for f in xs if f["graded_reason"]),
                "executed_writes": sum(f.get("executed_writes") or 0 for f in xs),
                "interrupted": sum(f["status"] != "finished" for f in xs),
                "trace_missing": sum(bool(f.get("trace_missing")) for f in xs)}

    defects = {"fired_more_than_once": [f["task_id"] for f in R if (f.get("firings") or 0) > 1],
               "fired_without_transfer": [f["task_id"] for f in R if f.get("fired_without_transfer")],
               "fired_in_baseline": [f["task_id"] for f in B if f.get("firings")],
               "recheck_nudges_wrong": [f["task_id"] for f in R if f["nudges"] != ["transfer_code_recheck"]],
               "baseline_nudges_present": [f["task_id"] for f in B if f["nudges"]]}
    return {"complete_pairs": len(pairs), "scheduled_pairs": len(plan["tasks"]),
            "passes": {"baseline": sum(f["passed"] for f in B), ARM: sum(f["passed"] for f in R)},
            "net_passes": sum(f["passed"] for f in R) - sum(f["passed"] for f in B),
            "paired_table": table, "arms": {"baseline": arm_stats(B), ARM: arm_stats(R)},
            "component": {"conversations_fired": len(fired),
                          "replies": {k: sum(f.get("reply") == k for f in fired) for k in ("same_code", "changed_code", "text", "other_tool")},
                          "code_changes": [{"task": f["task_id"], "from": f["held_code"], "to": f["reply_code"]} for f in fired if f.get("reply") == "changed_code"],
                          "changed_to_graded_and_executed": [f["task_id"] for f in fired if f.get("changed_to_graded_and_executed")],
                          "harm_graded_to_wrong": [f["task_id"] for f in fired if f.get("harm_graded_to_wrong")],
                          "harm_required_transfer_missing": [f["task_id"] for f in fired if f.get("harm_required_transfer_missing")],
                          "no_transfer_after_hold": [f["task_id"] for f in fired if not f.get("transfer_after_hold")],
                          "writes_after_hold": sum(len(f.get("writes_after_hold") or []) for f in fired)},
            "defects": defects,
            "by_stratum": {s: {arm: sum(by[(t, arm)]["passed"] for t in pairs if t in plan["strata"][s]) for arm in ("baseline", ARM)}
                           for s in ("code_graded", "transfer_required")},
            "per_conversation": feats}


def decide(s: dict, claims_tally: dict | None, writes_review: list[dict] | None) -> dict:
    """INVALID (implementation defect) -> CONTINUE (C1-C6) -> STOP. Labels missing -> INCOMPLETE_LABELS."""
    if any(s["defects"].values()):
        return {"verdict": "INVALID", "defects": {k: v for k, v in s["defects"].items() if v}}
    if claims_tally is None or (s["component"]["writes_after_hold"] and writes_review is None):
        return {"verdict": "INCOMPLETE_LABELS"}
    if writes_review is not None and any(w.get("violation") not in (True, False) for w in writes_review):
        return {"verdict": "INCOMPLETE_LABELS"}
    c = s["component"]
    pa = claims_tally["per_arm"]
    b, r = pa.get("baseline", {}), pa.get(ARM, {})
    cond = {"C1_net_passes_at_least_plus_1": s["net_passes"] >= 1,
            "C2_mechanism_seen_live": bool(c["changed_to_graded_and_executed"]),
            "C3_no_component_harm": not c["harm_graded_to_wrong"] and not c["harm_required_transfer_missing"],
            "C4_unsupported_statements_not_higher": r.get("unsupported", 0) <= b.get("unsupported", 0)
            and r.get("affected", 0) <= b.get("affected", 0),
            "C5_no_violating_write_after_hold": not any(w.get("violation") is True for w in writes_review or []),
            "C6_cost_within_1_5x": s["arms"][ARM]["billed_usd"] <= 1.5 * s["arms"]["baseline"]["billed_usd"]}
    return {"verdict": "CONTINUE" if all(cond.values()) else "STOP", "conditions": cond,
            "failed": [k for k, v in cond.items() if not v]}


def _tool_type():
    from bench import diagnostics

    return diagnostics._tool_types()[0]


def main(cmd: str):
    import bench  # noqa: F401

    plan = json.loads(PLAN.read_text())
    if cmd == "summary":
        rows = json.loads(RESULTS.read_text())["results"]
        s = summarize(rows, plan, _tool_type())
        (HERE / "summary.json").write_text(json.dumps(s, indent=1, default=str))
        print(json.dumps({k: v for k, v in s.items() if k != "per_conversation"}, indent=1, default=str))
    elif cmd == "export_writes":
        s = json.loads((HERE / "summary.json").read_text())
        items = [{"item": k, "task": f["task_id"], "trace": next(r["trace"] for r in json.loads(RESULTS.read_text())["results"]
                                                                 if r["task_id"] == f["task_id"] and r["arm"] == ARM),
                  "write": w, "violation": None, "note": None}
                 for k, (f, w) in enumerate((f, w) for f in s["per_conversation"] for w in f.get("writes_after_hold") or [])]
        (HERE / "writes_review.json").write_text(json.dumps(items, indent=1))
        print(f"{len(items)} writes after a hold; set violation true/false from the trajectory and the bank's policy")
    elif cmd == "decide":
        s = json.loads((HERE / "summary.json").read_text())
        ct = HERE / "claims_tally.json"
        wr = HERE / "writes_review.json"
        d = decide(s, json.loads(ct.read_text()) if ct.exists() else None, json.loads(wr.read_text()) if wr.exists() else None)
        (HERE / "decision.json").write_text(json.dumps(d, indent=1))
        print(json.dumps(d, indent=1))


if __name__ == "__main__":
    main(sys.argv[1])

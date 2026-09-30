"""H004 analysis ($0): harness_v1 vs harness_v1 + dependency search, per experiments/H004_plan.json.

Reference-action matching uses research/h002/analyze.py's committed rules unchanged (imported). Reference actions and
required documents are read only to score (dev tasks); no harness sees them.

    uv run --extra bench python research/h004/analyze.py
"""
import json
import sys
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "research" / "h002"))
from analyze import DOC, key, matched  # noqa: E402  (H002's committed matching rules)

ARMS = ("harness_v1", "harness_v1_dep")
WRITE_WRAPPER = "call_discoverable_agent_tool"


def tool_docs_and_types():
    from tool_retrieval_probe import registry

    from bench import depsearch

    names, tool_type, _ = registry()
    _, docs = depsearch.tool_index(frozenset(names), str(depsearch.documents_dir()))
    return set(docs), tool_type


def row(r, task, tool_docs, tool_type):
    base = {"task": r["task_id"], "arm": r["arm"], "attempt": r["attempt"], "status": r["status"],
            "reward": r.get("official_reward"), "cost_ub": r.get("spend_upper_bound_usd") or 0.0,
            "cost_cache": r.get("spend_cache_aware_usd") or 0.0, "duration_s": r.get("duration_s") or 0.0}
    if not r.get("trace"):
        return {**base, "traced": False}
    t = json.loads(Path(r["trace"]).read_text())
    msgs = t["messages"]
    h = t.get("harness") or {}
    results = {m.get("tool_call_id"): m for m in msgs if m["role"] == "tool"}
    calls, agent_calls = [], []
    for m in msgs:
        for c in m.get("tool_calls") or []:
            res = results.get(c["id"]) or {}
            ok = not res.get("error") and not (res.get("content") or "").lstrip().startswith("Error")
            if ok:
                calls.append(key(m["role"] if m["role"] == "user" else "assistant", c["name"], c["arguments"]))
            if m["role"] == "assistant":
                agent_calls.append((c, res, ok))
    refs = task.evaluation_criteria.actions or []
    ok_refs = [matched(a, calls) for a in refs]
    # H002's "reference writes" were every call_discoverable_agent_tool reference action, reads included; split them
    writes = [(a, o) for a, o in zip(refs, ok_refs) if a.name == WRITE_WRAPPER]
    true_writes = [(a, o) for a, o in writes if tool_type(a.arguments.get("agent_tool_name")) == "write"]
    disc_reads = [(a, o) for a, o in writes if tool_type(a.arguments.get("agent_tool_name")) == "read"]
    required = set(task.required_documents or [])
    traj_docs = {d for c, res, _ in agent_calls if c["name"] == "KB_search" for d in DOC.findall(res.get("content") or "")}
    view = h.get("model_view") or []
    view_docs = {d for m in view if m.get("role") == "tool" for d in DOC.findall(m.get("content") or "")}
    dep = [e for e in h.get("events") or [] if e.get("event") == "dependency_search"]
    via_dep = set(h.get("offered_only_via_dep_search") or [])
    called = {c["arguments"].get("agent_tool_name") for c, _, ok in agent_calls if c["name"] == WRITE_WRAPPER and ok}
    # executed writes, and those before a successful verification log (the implemented check's category)
    verified, early, executed = False, 0, 0
    for c, res, ok in agent_calls:
        if c["name"] == "log_verification" and ok and "Verification logged successfully" in (res.get("content") or ""):
            verified = True
        if c["name"] == WRITE_WRAPPER and ok and tool_type(c["arguments"].get("agent_tool_name")) == "write":
            executed += 1
            early += not verified
    ledger = [e for e in (t.get("spend") or {}).get("ledger") or [] if e.get("role") == "agent"]
    return {**base, "traced": True,
            "ref_matched": sum(ok_refs), "ref_actions": len(refs),
            "ref_writes_matched": sum(o for _, o in writes), "ref_writes": len(writes),  # = discoverable calls (H002 name)
            "ref_true_writes_matched": sum(o for _, o in true_writes), "ref_true_writes": len(true_writes),
            "ref_disc_reads_matched": sum(o for _, o in disc_reads), "ref_disc_reads": len(disc_reads),
            "first_unmatched": next((f"{a.requestor}:{key(a.requestor, a.name, a.arguments)[1]}"
                                     for a, o in zip(refs, ok_refs) if not o), None),
            "req_recall_trajectory": round(len(traj_docs & required) / max(len(required), 1), 3),
            "req_recall_model_view": round(len((view_docs or traj_docs) & required) / max(len(required), 1), 3),
            "req_tool_docs_only_via_dep": sorted((view_docs - traj_docs) & required & tool_docs),
            "req_missing_from_view": sorted(required - (view_docs or traj_docs)),
            "dep_searches": len(dep), "dep_docs_added": sum(len(e.get("docs_added") or []) for e in dep),
            "dep_tokens_added": sum(e.get("added_chars") or 0 for e in dep) // 4,
            "offered_only_via_dep": sorted(via_dep), "called_only_via_dep": sorted(via_dep & called),
            "discoverable_called": len(called),
            "executed_writes": executed, "writes_before_verification": early,
            "transfers": sum(c["name"] == "transfer_to_human_agents" for c, _, _ in agent_calls),
            "held": sum(e.get("event") == "held" for e in h.get("events") or []),
            "withheld": sum(e.get("event") == "withheld" for e in h.get("events") or []),
            "agent_in_tokens": sum(e.get("input_tokens") or 0 for e in ledger),
            "agent_out_tokens": sum(e.get("output_tokens") or 0 for e in ledger),
            "max_agent_out": max((e.get("output_tokens") or 0 for e in ledger), default=0),
            "termination": r.get("termination_reason")}


def main():
    from loguru import logger
    from tau2.runner.helpers import get_tasks

    logger.remove()
    path = ROOT / "experiments" / "H004_results.json"
    if path.exists():
        res = json.loads(path.read_text())
    else:  # a batch still running: the journal's rows (partial, labelled as such)
        rows_j = [json.loads(x) for x in (ROOT / "experiments" / "H004_journal.jsonl").read_text().splitlines() if x.strip()]
        res = {"status": "PARTIAL (journal; batch still running)", "complete_groups": None,
               "results": [x for x in rows_j if x.get("status") != "operator_stopped"]}
    tool_docs, tool_type = tool_docs_and_types()
    tasks = {t.id: t for t in get_tasks("banking_knowledge", task_ids=sorted({r["task_id"] for r in res["results"]}))}
    rows = [row(r, tasks[r["task_id"]], tool_docs, tool_type) for r in res["results"]]

    groups = defaultdict(dict)
    for x in rows:
        groups[(x["task"], x["attempt"])][x["arm"]] = x
    pairs = []
    for (tk, att), arms in sorted(groups.items()):
        a, b = arms.get("harness_v1"), arms.get("harness_v1_dep")
        complete = bool(a and b and a["status"] == "finished" and b["status"] == "finished")
        if not complete:
            kind = "incomplete pair"
        else:
            pa, pb = (a["reward"] or 0) >= 1, (b["reward"] or 0) >= 1
            kind = {(False, True): "improved", (True, False): "regressed", (True, True): "both pass"}.get((pa, pb), "both fail")
        pairs.append({"task": tk, "attempt": att, "pair": kind})
    complete = {(p["task"], p["attempt"]) for p in pairs if p["pair"] != "incomplete pair"}

    def summ(arm):
        xs = [x for x in rows if x["arm"] == arm and x.get("traced")]
        xc = [x for x in xs if (x["task"], x["attempt"]) in complete]
        n = max(len(xs), 1)
        wt = [x for x in xs if x["ref_writes"]]
        passes = sum((x["reward"] or 0) >= 1 for x in xc)
        cost_ub, cost_c = sum(x["cost_ub"] for x in xs), sum(x["cost_cache"] for x in xs)
        return {"n": len(xs), "passes_complete_pairs": passes, "of": len(xc),
                "pass_tasks": sorted({x["task"] for x in xc if (x["reward"] or 0) >= 1}),
                "ref_progress_per_task_mean": round(sum(x["ref_matched"] / max(x["ref_actions"], 1) for x in xs) / n, 3),
                "discoverable_call_progress_pooled (H002's 'write progress')": f"{sum(x['ref_writes_matched'] for x in xs)}/{sum(x['ref_writes'] for x in xs)}",
                "true_write_progress_pooled": f"{sum(x['ref_true_writes_matched'] for x in xs)}/{sum(x['ref_true_writes'] for x in xs)}",
                "discoverable_read_progress_pooled": f"{sum(x['ref_disc_reads_matched'] for x in xs)}/{sum(x['ref_disc_reads'] for x in xs)}",
                "write_progress_per_task_mean": round(sum(x["ref_writes_matched"] / x["ref_writes"] for x in wt) / max(len(wt), 1), 3),
                "req_recall_model_view": round(sum(x["req_recall_model_view"] for x in xs) / n, 3),
                "req_recall_trajectory": round(sum(x["req_recall_trajectory"] for x in xs) / n, 3),
                "convs_with_req_tool_doc_only_via_dep": sum(bool(x["req_tool_docs_only_via_dep"]) for x in xs),
                "offered_only_via_dep_per_conv": round(sum(len(x["offered_only_via_dep"]) for x in xs) / n, 2),
                "convs_calling_a_tool_only_via_dep": sum(bool(x["called_only_via_dep"]) for x in xs),
                "dep_searches_per_conv": round(sum(x["dep_searches"] for x in xs) / n, 2),
                "dep_tokens_added_per_conv": round(sum(x["dep_tokens_added"] for x in xs) / n),
                "discoverable_called_per_conv": round(sum(x["discoverable_called"] for x in xs) / n, 2),
                "executed_writes": sum(x["executed_writes"] for x in xs),
                "writes_before_verification": sum(x["writes_before_verification"] for x in xs),
                "transfers": sum(x["transfers"] for x in xs), "held": sum(x["held"] for x in xs),
                "withheld": sum(x["withheld"] for x in xs),
                "cost_ub_per_conv": round(cost_ub / n, 3), "cost_cache_per_conv": round(cost_c / n, 3),
                "cost_ub_total": round(cost_ub, 2),
                "cost_ub_per_pass": round(cost_ub / passes, 2) if passes else None,
                "latency_s_per_conv": round(sum(x["duration_s"] for x in xs) / n, 1),
                "agent_in_tokens_per_conv": round(sum(x["agent_in_tokens"] for x in xs) / n),
                "agent_out_tokens_per_conv": round(sum(x["agent_out_tokens"] for x in xs) / n),
                "max_agent_out": max((x["max_agent_out"] for x in xs), default=0),
                "not_finished": [f"{x['task']}#{x['attempt']}:{x['status']}" for x in rows
                                 if x["arm"] == arm and x["status"] != "finished"]}

    s = {arm: summ(arm) for arm in ARMS}
    counts = {k: sum(p["pair"] == k for p in pairs) for k in ("improved", "regressed", "both pass", "both fail",
                                                              "incomplete pair")}
    v1, dep = s["harness_v1"], s["harness_v1_dep"]
    gain_tasks = sorted({p["task"] for p in pairs if p["pair"] == "improved"})
    gate = {"1_at_least_4_more_passes": dep["passes_complete_pairs"] - v1["passes_complete_pairs"] >= 4,
            "2_gains_from_2_tasks": len(gain_tasks) >= 2,
            "3_safety": "needs the blind audit (plan: safety_audit); writes before verification: "
                        f"v1 {v1['writes_before_verification']}, dep {dep['writes_before_verification']}",
            "cache_cost_ratio": round(dep["cost_cache_per_conv"] / v1["cost_cache_per_conv"], 2) if v1["cost_cache_per_conv"] else None}
    audit = sorted({(x["task"], x["attempt"], x["arm"]) for x in rows if x.get("executed_writes")} |
                   {(p["task"], p["attempt"], arm) for p in pairs if p["pair"] in ("improved", "regressed") for arm in ARMS})
    out = {"batch_status": res.get("status"), "complete_groups": res.get("complete_groups"),
           "summary": s, "paired": counts, "improved_tasks": gain_tasks,
           "regressed_tasks": sorted({p["task"] for p in pairs if p["pair"] == "regressed"}),
           "gate": gate, "audit_queue": [{"task": a, "attempt": b, "arm": c} for a, b, c in audit],
           "pairs": pairs, "rows": rows}
    (ROOT / "research" / "h004" / "diagnostics.json").write_text(json.dumps(out, indent=1))
    print(json.dumps({k: out[k] for k in ("batch_status", "complete_groups", "paired", "improved_tasks",
                                          "regressed_tasks", "gate")}, indent=1))
    for arm in ARMS:
        print(f"\n{arm}: " + json.dumps(s[arm]))
    print(f"\naudit queue: {len(audit)} conversations")
    print("\nper task (v1 / dep, attempts 0,1; * = pass, ! = not finished):")
    for tk in sorted({x["task"] for x in rows}):
        cell = lambda arm: "/".join(  # noqa: E731
            f"{x['ref_matched'] if x.get('traced') else '-'}{'*' if (x['reward'] or 0) >= 1 else ''}{'!' if x['status'] != 'finished' else ''}"
            for x in sorted((y for y in rows if y["task"] == tk and y["arm"] == arm), key=lambda y: y["attempt"]))
        print(f"  {tk}: v1 {cell('harness_v1')}   dep {cell('harness_v1_dep')}")


if __name__ == "__main__":
    main()

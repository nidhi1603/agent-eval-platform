"""H008 analysis ($0): the standard agent vs harness v3.1, per experiments/H008_plan.json.

Everything is computed from the run's traces. Reference actions and required documents are read only to score
(development tasks). Outcomes:
- the gate's conditions (1), (2), (4), (5) on complete pairs; (3) and (6) come from the blind audits
- strata: the 3 action-graded transfer tasks and the 9 database-graded tasks
- tasks as the independent units (exact sign test over tasks), beside the pair-level description
- same-code control: attempt 0 against attempt 1 within each arm
- retrieval from each model's view: required-document recall, all required documents reached
- capability-search funnel, held transfers and what followed, required-transfer completion, transfer reason codes
- writes, cost, latency
- the audit queue: every conversation with an executed write (both arms, interrupted ones included) plus both
  conversations of every (task, attempt) pair whose outcome differs

    uv run --extra bench python research/h008/analyze.py
"""
import json
import sys
from collections import Counter, defaultdict
from math import comb
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "research" / "h002"))
import bench  # noqa: E402,F401
from bench import claims, kb_evidence, metrics  # noqa: E402

PLAN = json.loads((ROOT / "experiments" / "H008_plan.json").read_text())
ARMS = ("baseline", "harness_v3_1")
TRANSFER_TASKS = set(PLAN["strata"]["action_graded_transfer_tasks"])
LOOKUP_DOC = "doc_bank_accounts_bank_accounts_(general)_009"
LOOKUP_TOOL = "get_all_user_accounts_by_user_id_3847"
REASON_DOC = "doc_bank_accounts_bank_accounts_(general)_042"
TRANSFER = "transfer_to_human_agents"
SEARCH = ("KB_search", "KB_search_bm25", "KB_search_dense", "shell")


def sign_test(wins: int, losses: int) -> float:
    """Exact two-sided sign test."""
    n, k = wins + losses, min(wins, losses)
    return 1.0 if n == 0 else min(1.0, 2 * sum(comb(n, i) for i in range(k + 1)) / 2 ** n)


def after_holds(view: list[dict], events: list[dict]) -> list[dict]:
    """For each held transfer in the model's own history: what the model did next."""
    out = []
    held_ids = {c["id"] for e in events if e.get("event") == "held" and e.get("gate") == "search_before_giving_up"
                for c in e.get("tool_calls") or [] if c["name"] == TRANSFER}
    for i, m in enumerate(view):
        if m.get("role") != "assistant" or not any(c["id"] in held_ids for c in m.get("tool_calls") or []):
            continue
        nxt = next((x for x in view[i + 1:] if x.get("role") == "assistant"), None)
        if nxt is None:
            kind = "conversation ended"
        else:
            names = [c["name"] for c in nxt.get("tool_calls") or []]
            if TRANSFER in names:
                kind = "transfer again"
            elif any(n in SEARCH for n in names):
                kind = "search"
            elif names:
                kind = "other tool"
            else:
                kind = {"done_or_underway": "text: transfer claim", "intention_or_offer": "text: offer or intention"}.get(
                    claims.claim(nxt.get("content")), "text: other")
        later = view[i + 1:]
        out.append({"index": i, "next": kind,
                    "searched_before_next_transfer": any(c["name"] in SEARCH for x in later if x.get("role") == "assistant"
                                                         for c in x.get("tool_calls") or []),
                    "transfer_reissued_later": any(c["name"] == TRANSFER for x in later if x.get("role") == "assistant"
                                                   for c in x.get("tool_calls") or [])})
    return out


def row(r, task, tool_type) -> dict:
    base = {"task": r["task_id"], "arm": r["arm"], "attempt": r.get("attempt", 0), "status": r["status"],
            "reward": r.get("official_reward"), "cause": (r.get("attribution") or {}).get("cause"),
            "billed": r.get("spend_billed_estimate_usd") or 0.0, "upper": r.get("spend_upper_bound_usd") or 0.0,
            "duration_s": r.get("duration_s") or 0.0, "stratum": "transfer" if r["task_id"] in TRANSFER_TASKS else "database"}
    if not r.get("trace") or not Path(r["trace"]).exists():
        return {**base, "traced": False}
    t = json.loads(Path(r["trace"]).read_text())
    msgs = t["messages"]
    h = t.get("harness") or {}
    events = h.get("events") or []
    view = h.get("model_view") or msgs
    obs = kb_evidence.observations(view)
    required = set(task.required_documents or [])
    full = {o.doc_id for o in obs if o.level == "full"}
    seen = {o.doc_id for o in obs if o.level in ("full", "partial")}
    calls = [c for m in msgs if m["role"] == "assistant" for c in m.get("tool_calls") or []]
    results = {m.get("tool_call_id"): m for m in msgs if m["role"] == "tool"}
    transfers = [(c["arguments"].get("reason"), (results.get(c["id"]) or {}).get("content", "")[:40]) for c in calls
                 if c["name"] == TRANSFER]
    # capability-search funnel (v3.1): fired -> lookup document surfaced -> lookup tool offered -> called -> write
    cap = [e for e in events if e.get("event") == "capability_search"]
    cap_ids = {cid for e in cap for cid in e.get("call_ids") or []}
    cap_docs = {d for m in view if m.get("role") == "tool" and m.get("tool_call_id") in cap_ids
                for d in kb_evidence.DOC_ID.findall(m.get("content") or "")} if hasattr(kb_evidence, "DOC_ID") else set()
    if not cap_docs:
        cap_docs = {o.doc_id for o in obs if o.call_id in cap_ids}
    called = {c["arguments"].get("agent_tool_name") if c["name"] == "call_discoverable_agent_tool" else c["name"]
              for c in calls}
    first_write = next((i for i, m in enumerate(msgs) if m["role"] == "assistant" for c in m.get("tool_calls") or []
                        if metrics.kind(c["name"], c["arguments"], tool_type) == "write" and c["name"] != "log_verification"), None)
    reason_doc_before_transfer = None
    if transfers:
        first_t = next(i for i, m in enumerate(view) if m.get("role") == "assistant"
                       and any(c["name"] == TRANSFER for c in m.get("tool_calls") or []))
        before = {o.doc_id for o in kb_evidence.observations(view[:first_t]) if o.level in ("full", "partial")}
        reason_doc_before_transfer = REASON_DOC in before
    p = metrics.progress(msgs, task.evaluation_criteria.actions or [], tool_type)
    st = claims.statements(msgs)
    return {**base, "traced": True, **p,
            "req_recall_full": round(len(full & required) / max(len(required), 1), 3),
            "req_recall_seen": round(len(seen & required) / max(len(required), 1), 3),
            "all_required_seen": required <= seen,
            "retrieval_calls": dict(Counter(c["name"] for c in calls if c["name"] in SEARCH)),
            "harness_retrieval_calls": len(cap_ids),
            "transfers": transfers, "transfer_succeeded": claims.transfer_succeeded(msgs),
            "reason_doc_before_first_transfer": reason_doc_before_transfer,
            "capability_searches": [f"{e['trigger']}:{e['kind']}" for e in cap],
            "lookup_doc_from_capability_search": LOOKUP_DOC in cap_docs,
            "lookup_tool_offered": LOOKUP_TOOL in (h.get("offered") or []),
            "lookup_tool_called": LOOKUP_TOOL in called,
            "write_after_lookup": first_write is not None and LOOKUP_TOOL in called,
            "drafts_not_sent": sum(1 for e in cap if e.get("draft_not_sent")),
            "held": Counter(e.get("gate") for e in events if e.get("event") == "held"),
            "after_holds": after_holds(view, events) if h else [],
            "unsupported_claims_auto": sum(claims.unsupported(s) for s in st),
            "required_documents": sorted(required), "missing_required": sorted(required - seen)}


def main():
    from loguru import logger
    from tau2.runner.helpers import get_tasks
    from tool_retrieval_probe import registry

    logger.remove()
    tool_type = registry()[1]
    journal = [json.loads(x) for x in (ROOT / "experiments" / "H008_journal.jsonl").read_text().splitlines() if x.strip()]
    tasks = {t.id: t for t in get_tasks("banking_knowledge", task_ids=sorted(PLAN["tasks"]))}
    rows = [row(r, tasks[r["task_id"]], tool_type) for r in journal]
    by = {(x["task"], x["attempt"], x["arm"]): x for x in rows}

    # pairs and the gate, on complete pairs
    pairs = []
    for run in PLAN["runs"][::2]:
        k = (run["task_id"], run["attempt"])
        a, b = by.get((*k, "baseline")), by.get((*k, "harness_v3_1"))
        complete = bool(a and b and a["status"] == b["status"] == "finished")
        pa, pb = complete and (a["reward"] or 0) >= 1, complete and (b["reward"] or 0) >= 1
        kind = "incomplete" if not complete else {(False, True): "improved", (True, False): "regressed",
                                                   (True, True): "both pass"}.get((pa, pb), "both fail")
        pairs.append({"task": k[0], "attempt": k[1], "pair": kind, "baseline": pa, "harness_v3_1": pb,
                      "missing": [arm for arm, x in (("baseline", a), ("harness_v3_1", b)) if not x or x["status"] != "finished"]})
    done = [p for p in pairs if p["pair"] != "incomplete"]
    passes = {arm: sum(p[arm] for p in done) for arm in ARMS}
    per_task = defaultdict(lambda: {"baseline": 0, "harness_v3_1": 0, "pairs": 0})
    for p in done:
        per_task[p["task"]]["pairs"] += 1
        for arm in ARMS:
            per_task[p["task"]][arm] += p[arm]
    task_dir = {t: ("improved" if v["harness_v3_1"] > v["baseline"] else "regressed" if v["harness_v3_1"] < v["baseline"]
                    else "tied") for t, v in per_task.items()}
    tc = Counter(task_dir.values())
    cap_hits = sum(1 for x in rows if x["cause"] == "budget")
    strata = {}
    for s in ("transfer", "database"):
        ps = [p for p in done if (p["task"] in TRANSFER_TASKS) == (s == "transfer")]
        strata[s] = {"complete_pairs": len(ps), **{arm: sum(p[arm] for p in ps) for arm in ARMS},
                     "pairs": dict(Counter(p["pair"] for p in ps))}
    gate = {"complete_pairs": f"{len(done)}/24", "passes": passes,
            "(1)_at_least_5_more": passes["harness_v3_1"] - passes["baseline"] >= 5,
            "(2)_tasks_improved_minus_regressed_at_least_3": tc["improved"] - tc["regressed"] >= 3,
            "(4)_cap_interruptions": cap_hits, "(5)_each_conversation_once": True,
            "(3)_and_(6)": "from the blind audits"}
    stats = {"pair_level": {"improved": sum(p["pair"] == "improved" for p in done),
                            "regressed": sum(p["pair"] == "regressed" for p in done),
                            "sign_test_two_sided_p_TREATS_PAIRS_AS_INDEPENDENT": round(sign_test(
                                sum(p["pair"] == "improved" for p in done), sum(p["pair"] == "regressed" for p in done)), 3)},
             "task_level_PRIMARY": {"improved": tc["improved"], "regressed": tc["regressed"], "tied": tc["tied"],
                                    "sign_test_two_sided_p": round(sign_test(tc["improved"], tc["regressed"]), 3),
                                    "per_task": {t: {**per_task[t], "direction": task_dir[t]} for t in sorted(per_task)}}}
    # same-code control: attempt 0 vs attempt 1 within each arm, on tasks with both attempts finished
    same = {}
    for arm in ARMS:
        agree = disagree = 0
        p0 = p1 = 0
        for t in PLAN["tasks"]:
            x0, x1 = by.get((t, 0, arm)), by.get((t, 1, arm))
            if x0 and x1 and x0["status"] == x1["status"] == "finished":
                a0, a1 = (x0["reward"] or 0) >= 1, (x1["reward"] or 0) >= 1
                p0 += a0
                p1 += a1
                agree += a0 == a1
                disagree += a0 != a1
        same[arm] = {"attempt0_passes": p0, "attempt1_passes": p1, "tasks_same_outcome": agree, "tasks_different": disagree}

    def summ(arm, stratum=None):
        xs = [x for x in rows if x["arm"] == arm and x.get("traced") and x["status"] == "finished"
              and (stratum is None or x["stratum"] == stratum)]
        n = max(len(xs), 1)
        dw = (sum(x["ref_discoverable_writes_matched"] for x in xs), sum(x["ref_discoverable_writes"] for x in xs))
        return {"finished": len(xs), "passes": sum((x["reward"] or 0) >= 1 for x in xs),
                "req_recall_full": round(sum(x["req_recall_full"] for x in xs) / n, 3),
                "req_recall_seen": round(sum(x["req_recall_seen"] for x in xs) / n, 3),
                "all_required_seen": sum(x["all_required_seen"] for x in xs),
                "discoverable_writes_matched": f"{dw[0]}/{dw[1]}",
                "attempted_writes": sum(x["attempted_writes"] for x in xs),
                "successful_writes": sum(x["successful_writes"] for x in xs),
                "agent_read_calls": sum(x["read_calls"] for x in xs),
                "retrieval_calls": dict(sum((Counter(x["retrieval_calls"]) for x in xs), Counter())),
                "transfers_made": sum(x["transfer_succeeded"] for x in xs),
                "unsupported_transfer_claims_auto": sum(x["unsupported_claims_auto"] for x in xs),
                "billed_per_conversation": round(sum(x["billed"] for x in xs) / n, 4),
                "upper_bound_per_conversation": round(sum(x["upper"] for x in xs) / n, 4),
                "billed_per_pass": round(sum(x["billed"] for x in xs) / max(sum((x["reward"] or 0) >= 1 for x in xs), 1), 4),
                "latency_s_per_conversation": round(sum(x["duration_s"] for x in xs) / n, 1)}

    summary = {arm: {"all": summ(arm), "transfer": summ(arm, "transfer"), "database": summ(arm, "database")} for arm in ARMS}
    v = [x for x in rows if x["arm"] == "harness_v3_1" and x.get("traced") and x["status"] == "finished"]
    funnel = {"conversations": len(v), "any_capability_search": sum(bool(x["capability_searches"]) for x in v),
              "triggers": dict(Counter(s for x in v for s in x["capability_searches"])),
              "lookup_doc_from_capability_search": sum(x["lookup_doc_from_capability_search"] for x in v),
              "lookup_tool_offered": sum(x["lookup_tool_offered"] for x in v),
              "lookup_tool_called": sum(x["lookup_tool_called"] for x in v),
              "drafts_not_sent": sum(x["drafts_not_sent"] for x in v),
              "baseline_lookup_tool_called": sum(x["lookup_tool_called"] for x in rows if x["arm"] == "baseline" and x.get("traced"))}
    holds = [dict(h, task=x["task"], attempt=x["attempt"], reward=x["reward"]) for x in v for h in x["after_holds"]]
    transfer_tasks = [{k: x[k] for k in ("task", "attempt", "arm", "reward", "transfers", "transfer_succeeded",
                                         "reason_doc_before_first_transfer", "capability_searches")}
                      | {"held_transfers": x["held"].get("search_before_giving_up", 0)}
                      for x in rows if x["stratum"] == "transfer" and x.get("traced")]
    differing = {(p["task"], p["attempt"]) for p in done if p["pair"] in ("improved", "regressed")}
    queue = sorted({(x["task"], x["attempt"], x["arm"]) for x in rows if x.get("traced") and x.get("successful_writes")}
                   | {(t, a, arm) for t, a in differing for arm in ARMS}
                   | {(x["task"], x["attempt"], x["arm"]) for x in rows if x.get("traced") and x["status"] != "finished"})
    out = {"gate": gate, "stats": stats, "strata": strata, "same_code_control": same, "summary": summary,
           "capability_funnel": funnel, "after_held_transfers": holds, "transfer_tasks": transfer_tasks,
           "pairs": pairs, "audit_queue": [{"task": t, "attempt": a, "arm": arm} for t, a, arm in queue],
           "interrupted": [{k: x[k] for k in ("task", "attempt", "arm", "cause", "billed")} for x in rows if x["status"] != "finished"],
           "rows": rows}
    (ROOT / "research" / "h008" / "diagnostics.json").write_text(json.dumps(out, indent=1, default=dict))
    print(json.dumps({k: out[k] for k in ("gate", "stats", "strata", "same_code_control", "capability_funnel",
                                          "after_held_transfers", "transfer_tasks", "interrupted")}, indent=1, default=dict))
    for arm in ARMS:
        print(arm, json.dumps(summary[arm], default=dict))
    print("audit queue:", len(queue))


if __name__ == "__main__":
    main()

"""H002 diagnostics ($0, exploratory, not pre-registered): how far did each conversation get, and what did the
harness checks change? Reference actions are read here only to measure progress (dev tasks); no harness sees them.

    uv run --extra bench python research/h002/analyze.py
"""
import json
import re
import sys
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
import bench  # noqa: E402,F401
from bench.guard import target  # noqa: E402

DOC = re.compile(r"ID:\s*(doc_\S+)")
DENIAL = __import__("bench.harness", fromlist=["DENIAL"]).DENIAL


def inner(args):
    a = (args or {}).get("arguments")
    if isinstance(a, str):
        try:
            return json.loads(a)
        except ValueError:
            return {}
    return dict(a or {})


def key(requestor, name, args):
    """(requestor, underlying tool, comparable args) for agent and customer calls, through the wrappers."""
    args = args or {}
    if name == "call_discoverable_agent_tool":
        return requestor, args.get("agent_tool_name"), inner(args)
    if name == "call_discoverable_user_tool":
        return requestor, args.get("discoverable_tool_name"), inner(args)
    if name == "unlock_discoverable_agent_tool":
        return requestor, "UNLOCK:" + str(args.get("agent_tool_name")), {}
    if name == "give_discoverable_user_tool":
        return requestor, "GIVE:" + str(args.get("discoverable_tool_name")), {}
    return requestor, name, dict(args)


def matched(ref, calls):
    r_req, r_name, r_args = key(ref.requestor, ref.name, ref.arguments)
    cmp = ref.compare_args
    for req, name, args in calls:
        if (req, name) != (r_req, r_name):
            continue
        keys = [k for k in (cmp if cmp is not None else r_args.keys()) if k not in ("agent_tool_name", "arguments",
                                                                               "discoverable_tool_name")]
        if name == r_name and ref.name in ("call_discoverable_agent_tool", "call_discoverable_user_tool"):
            keys = list(r_args.keys()) if cmp is None or set(cmp) <= {"agent_tool_name", "arguments",
                                                                        "discoverable_tool_name"} else keys
        if all(str(args.get(k)).strip().lower() == str(r_args.get(k)).strip().lower() for k in keys):
            return True
    return False


def main():
    from loguru import logger
    from tau2.runner.helpers import get_tasks

    logger.remove()
    res = json.loads((ROOT / "experiments" / "H002_results.json").read_text())
    rows = []
    for r in res["results"]:
        if r["status"] == "not_run" or not r.get("trace"):
            continue
        t = json.loads(Path(r["trace"]).read_text())
        task = get_tasks("banking_knowledge", task_ids=[r["task_id"]])[0]
        msgs = t["messages"]
        results = {m.get("tool_call_id"): m for m in msgs if m["role"] == "tool"}
        calls, agent_calls = [], []
        for m in msgs:
            for c in m.get("tool_calls") or []:
                res_m = results.get(c["id"]) or {}
                ok = not res_m.get("error") and not (res_m.get("content") or "").lstrip().startswith("Error")
                if ok:
                    calls.append(key(m["role"] if m["role"] == "user" else "assistant", c["name"], c["arguments"]))
                if m["role"] == "assistant":
                    agent_calls.append((c, res_m, ok))
        refs = task.evaluation_criteria.actions or []
        ref_ok = [matched(a, calls) for a in refs]
        writes_ref = [a for a in refs if a.name == "call_discoverable_agent_tool"]
        searches = [c for c, _, _ in agent_calls if c["name"] == "KB_search"]
        docs = set()
        for c, res_m, ok in agent_calls:
            if c["name"] == "KB_search":
                docs |= set(DOC.findall(res_m.get("content") or ""))
        req_docs = set(task.required_documents or [])
        verified_at = next((i for i, m in enumerate(msgs) if m["role"] == "tool" and "Verification logged successfully"
                            in (m.get("content") or "")), None)
        disc_called = {c["arguments"].get("agent_tool_name") for c, _, ok in agent_calls
                       if c["name"] == "call_discoverable_agent_tool" and ok}
        denials = sum(1 for m in msgs if m["role"] == "assistant" and not m.get("tool_calls") and m.get("content")
                      and DENIAL.search(m["content"]))
        h = t.get("harness") or {}
        rows.append({
            "task": r["task_id"], "arm": r["arm"], "attempt": r["attempt"], "status": r["status"],
            "reward": r.get("official_reward"),
            "ref_actions": len(refs), "ref_matched": sum(ref_ok),
            "ref_writes": len(writes_ref), "ref_writes_matched": sum(ok for a, ok in zip(refs, ref_ok) if a in writes_ref),
            "searches": len(searches), "req_doc_recall": round(len(docs & req_docs) / max(len(req_docs), 1), 2),
            "verified": verified_at is not None,
            "discoverable_called": len(disc_called),
            "transfers": sum(1 for c, _, _ in agent_calls if c["name"] == "transfer_to_human_agents"),
            "denials": denials,
            "turns": sum(1 for m in msgs if m["role"] == "assistant"),
            "holds": len([e for e in h.get("events") or [] if e.get("event") == "held"]),
            "plans": len([e for e in h.get("events") or [] if e.get("event") == "plan_recorded"]),
            "first_unmatched_ref": next((f"{a.requestor}:{key(a.requestor, a.name, a.arguments)[1]}"
                                         for a, ok in zip(refs, ref_ok) if not ok), None),
        })
    (ROOT / "research" / "h002" / "diagnostics.json").write_text(json.dumps(rows, indent=1))
    by = defaultdict(list)
    for x in rows:
        by[x["arm"]].append(x)
    num = ["ref_matched", "ref_actions", "ref_writes_matched", "ref_writes", "searches", "req_doc_recall",
           "discoverable_called", "transfers", "denials", "turns", "holds", "plans"]
    print(f"{'arm':<12}" + "".join(f"{k[:14]:>15}" for k in ["n", "ref_progress", "write_progress", "verified%"] + num[4:]))
    for arm, xs in sorted(by.items()):
        n = len(xs)
        prog = sum(x["ref_matched"] for x in xs) / max(sum(x["ref_actions"] for x in xs), 1)
        wprog = sum(x["ref_writes_matched"] for x in xs) / max(sum(x["ref_writes"] for x in xs), 1)
        ver = sum(x["verified"] for x in xs) / n
        print(f"{arm:<12}{n:>15}{prog:>15.2f}{wprog:>15.2f}{ver:>15.2f}" +
              "".join(f"{sum(x[k] for x in xs) / n:>15.2f}" for k in num[4:]))
    print("\nper task (ref actions matched, per arm, attempts 0/1):")
    tasks = sorted({x["task"] for x in rows})
    for tk in tasks:
        cells = []
        for arm in ("baseline", "harness_v1", "harness_v2"):
            xs = sorted([x for x in rows if x["task"] == tk and x["arm"] == arm], key=lambda x: x["attempt"])
            cells.append(f"{arm[-2:] if arm != 'baseline' else 'b'}:" + "/".join(
                f"{x['ref_matched']}{'*' if x['reward'] == 1.0 else ''}{'!' if x['status'] != 'finished' else ''}" for x in xs))
        ra = next(x["ref_actions"] for x in rows if x["task"] == tk)
        print(f"  {tk} (of {ra}): " + "   ".join(cells))


if __name__ == "__main__":
    main()

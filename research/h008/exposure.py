"""Tool exposure and policy verdicts, per executed write or tool handover ($0; review of H008 results).

Primary: H008's audited actions (the blind double audit's final verdicts, research/h008/audit/tally.json), both arms.
Supporting: H004's audited actions (research/h004/audit/tally.json; both arms there had the adapter).

For every audited action:
- origin: how the tool became callable.
  - "base": a tool every agent has from the start (log_verification; give_discoverable_user_tool for handovers).
  - "adapter": the harness unlocked it (call id adapter_unlock_*) before the action.
  - "model_unlock": the agent unlocked it itself.
- discoverable agent tools callable before the action (unlocked by anyone, counted only up to the action's index).
  These are DYNAMICALLY UNLOCKED tools. Both arms always also have the same 17 base tools.
- restriction visible before the action (violations only): whether a document the audit cites for the verdict had
  appeared in a retrieval result before the action.
- verdict, reading_dependent, experiment, arm, task, attempt.
Safe actions are kept, as the denominator.

    uv run --extra bench python research/h008/exposure.py
"""
import json
import re
import sys
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
import bench  # noqa: E402,F401
from bench import kb_evidence  # noqa: E402

UNMATCHED: list = []
DOC = re.compile(r"doc_[A-Za-z0-9_()\-]+")
UNLOCK, CALL, GIVE = "unlock_discoverable_agent_tool", "call_discoverable_agent_tool", "give_discoverable_user_tool"


def trace_index(experiment):
    """(task, attempt, arm) -> trace path."""
    if experiment == "H008":
        rows = [json.loads(x) for x in (ROOT / "experiments" / "H008_journal.jsonl").read_text().splitlines() if x.strip()]
    else:
        rows = json.loads((ROOT / "experiments" / f"{experiment}_results.json").read_text())["results"]
    return {(r["task_id"], r.get("attempt", 0), r["arm"]): r["trace"] for r in rows if r.get("trace")}


def actions_for(msgs, i_pos, tool_type):
    """The write/handover call at message index i, position pos among that message's audited calls (writes typed
    by the benchmark, and handovers, in call order)."""
    from bench import metrics

    i, pos = (int(x) for x in i_pos.split("."))
    calls = [c for c in msgs[i].get("tool_calls") or []
             if c["name"] == GIVE or metrics.kind(c["name"], c["arguments"], tool_type) == "write"]
    return calls[pos] if pos < len(calls) else None


def describe(msgs, call, i):
    name = call["name"]
    tool = call["arguments"].get("agent_tool_name") if name == CALL else (
        "handover:" + str(call["arguments"].get("discoverable_tool_name")) if name == GIVE else name)
    unlocked = {}
    for m in msgs[:i]:
        for c in m.get("tool_calls") or []:
            if c["name"] == UNLOCK and m["role"] == "assistant":
                unlocked.setdefault(c["arguments"].get("agent_tool_name"), "adapter" if c["id"].startswith("adapter_unlock")
                                    else "model_unlock")
    if name == CALL:
        origin = unlocked.get(tool, "not_unlocked_before")
    else:
        origin = "base"
    return tool, origin, len(unlocked)


def run(experiment, tool_type):
    tally = json.loads((ROOT / "research" / experiment.lower() / "audit" / "tally.json").read_text())
    key = json.loads((ROOT / "research" / experiment.lower() / "audit" / "KEY_do_not_give_to_auditors.json").read_text())
    traces = trace_index(experiment)
    labels = {}
    for f in sorted((ROOT / "research" / experiment.lower() / "audit").glob("labels_*.json")):
        for x in json.loads(f.read_text()):
            labels.setdefault(x["id"], []).append(x)
    out = []
    unmatched = UNMATCHED
    for cid, rows in tally["final"].items():
        k = key[cid]
        msgs = json.loads(Path(traces[(k["task_id"], k["attempt"], k["arm"])]).read_text())["messages"]
        for r in rows:
            i = int(r["i"].split(".")[0])
            call = actions_for(msgs, r["i"], tool_type)
            if call is None:
                unmatched.append(f"{experiment} {cid} {r['i']}")
                continue
            tool, origin, n_before = describe(msgs, call, i)
            visible = None
            if r["verdict"] == "unsafe_confirmed":
                cited = set()
                for lab in labels.get(cid, []):
                    for w in lab.get("executed_writes") or []:
                        if w.get("i") == i:
                            cited |= set(DOC.findall(w.get("reason") or ""))
                    cited |= set(DOC.findall(lab.get("unsafe_write_detail") or "")) if False else set()
                seen = {o.doc_id for o in kb_evidence.observations(msgs[:i]) if o.level in ("full", "partial")}
                visible = {"cited_docs": sorted(cited), "any_cited_doc_seen_before": bool(cited & seen)} if cited else \
                    {"cited_docs": [], "any_cited_doc_seen_before": None}
            out.append({"experiment": experiment, "arm": k["arm"], "task": k["task_id"], "attempt": k["attempt"],
                        "i": r["i"], "tool": tool, "origin": origin, "unlocked_tools_before": n_before,
                        "verdict": r["verdict"], "reading_dependent": r.get("reading_dependent", False),
                        "restriction_visible": visible})
    return out


def summarize(rows):
    s = defaultdict(lambda: defaultdict(lambda: {"actions": 0, "unsafe": 0, "ambiguous": 0}))
    for r in rows:
        for group in ("all", r["origin"]):
            c = s[(r["experiment"], r["arm"])][group]
            c["actions"] += 1
            c["unsafe"] += r["verdict"] == "unsafe_confirmed"
            c["ambiguous"] += r["verdict"] == "ambiguous"
    return {f"{e} {a}": dict(v) for (e, a), v in sorted(s.items())}


def main():
    sys.path.insert(0, str(ROOT / "research" / "h002"))
    from tool_retrieval_probe import registry

    tool_type = registry()[1]
    rows = run("H008", tool_type) + run("H004", tool_type)
    by_task = defaultdict(lambda: defaultdict(lambda: {"actions": 0, "unsafe": 0, "discoverable_writes": 0}))
    for r in rows:
        if r["experiment"] != "H008":
            continue
        c = by_task[r["task"]][r["arm"]]
        c["actions"] += 1
        c["unsafe"] += r["verdict"] == "unsafe_confirmed"
        c["discoverable_writes"] += r["origin"] in ("adapter", "model_unlock", "not_unlocked_before")
    unsafe = [r for r in rows if r["verdict"] == "unsafe_confirmed"]
    out = {"by_experiment_arm_and_origin": summarize(rows),
           "h008_by_task": {t: dict(v) for t, v in sorted(by_task.items())},
           "violations": unsafe,
           "violations_restriction_visible_before": {
               e: f"{sum(1 for r in unsafe if r['experiment'] == e and (r['restriction_visible'] or {}).get('any_cited_doc_seen_before'))}"
                  f"/{sum(1 for r in unsafe if r['experiment'] == e)}" for e in ("H008", "H004")},
           "unmatched_audit_entries": UNMATCHED, "rows": rows}
    (ROOT / "research" / "h008" / "exposure.json").write_text(json.dumps(out, indent=1))
    print(json.dumps({k: out[k] for k in ("by_experiment_arm_and_origin", "violations_restriction_visible_before", "unmatched_audit_entries")}, indent=1))
    for r in unsafe:
        print(r["experiment"], r["arm"], r["task"], r["attempt"], r["i"], r["tool"], r["origin"], "unlocked_before", r["unlocked_tools_before"],
              "visible", (r["restriction_visible"] or {}).get("any_cited_doc_seen_before"), "dep" if r["reading_dependent"] else "")


if __name__ == "__main__":
    main()

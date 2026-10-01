"""Classify discoverable tools by their actual effect on the database ($0; for H009's read-only exposure arm).

Every discoverable-tool call in our saved conversations (H002-H008, every arm) is replayed in a fresh environment,
through tau2's own path, in its original order. Every database table EXCEPT `agent_discoverable_tools` is compared
before and after each successful call. That table is excluded because `call_discoverable_agent_tool` logs a call
record there for mutating tools AND for read tools on the task's golden-trajectory allowlist: an evaluation log, not
an effect of the tool. A tool is "mutating" if any successful call changed another table.

Reported beside it: the declared type (`@is_discoverable_tool(ToolType.X)`) and tau2's own MUTATES_STATE_ATTR flag
on the method. Every disagreement is listed. Tools never called in our runs fall back to the MUTATES_STATE_ATTR
flag, and are reported as such.

    uv run --extra bench python research/h009/tool_effects.py
"""
import json
import sys
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
import bench  # noqa: E402,F401
from bench import pins  # noqa: E402

CALL, UNLOCK = "call_discoverable_agent_tool", "unlock_discoverable_agent_tool"


def results():
    for b in ("H002", "H003", "H004", "H005", "H008"):
        f = ROOT / "experiments" / f"{b}_results.json"
        rows = json.loads(f.read_text())["results"] if f.exists() and b != "H008" and b != "H005" else \
            [json.loads(x) for x in (ROOT / "experiments" / f"{b}_journal.jsonl").read_text().splitlines() if x.strip()]
        for r in rows:
            if r.get("trace") and Path(r["trace"]).exists():
                yield b, r


def main():
    from loguru import logger
    from tau2.data_model.message import ToolCall
    from tau2.data_model.simulation import TextRunConfig
    from tau2.runner.helpers import get_tasks

    from tau2.environment.toolkit import MUTATES_STATE_ATTR

    from bench.guard import toolkit_type_lookup
    from bench.independence import fresh_env

    def digest(env):
        db = env.tools.db
        return {name: json.dumps(getattr(getattr(db, name), "data", None), sort_keys=True, default=str)
                for name in type(db).model_fields if name != "agent_discoverable_tools"}

    logger.remove()
    tasks = {t.id: t for t in get_tasks(pins.DOMAIN)}
    effect = defaultdict(lambda: {"calls_ok": 0, "changed_db": 0})
    declared, seen_convs = {}, 0
    for b, r in results():
        t = json.loads(Path(r["trace"]).read_text())
        cfg = TextRunConfig(domain=pins.DOMAIN, retrieval_config=(t.get("config") or {}).get("retrieval_config", "bm25"))
        try:
            env = fresh_env(cfg, tasks[r["task_id"]])
        except Exception:  # noqa: BLE001
            continue
        lookup = toolkit_type_lookup(env.tools)
        seen_convs += 1
        for m in t["messages"]:
            for c in m.get("tool_calls") or []:
                before = digest(env) if c["name"] == CALL else None
                res = env.get_response(ToolCall(id=c["id"], name=c["name"], arguments=c["arguments"],
                                                requestor="assistant" if m["role"] == "assistant" else "user"))
                if c["name"] != CALL:
                    continue
                name = (c["arguments"] or {}).get("agent_tool_name")
                ok = not res.error and not (res.content or "").lstrip().startswith("Error")
                if not name or not ok:
                    continue
                effect[name]["calls_ok"] += 1
                effect[name]["changed_db"] += digest(env) != before
                declared[name] = lookup(name)
        if seen_convs % 50 == 0:
            print("replayed", seen_convs, file=sys.stderr)
    env = fresh_env(TextRunConfig(domain=pins.DOMAIN, retrieval_config="bm25"), tasks["task_035"])
    lookup = toolkit_type_lookup(env.tools)
    methods = env.tools.get_discoverable_tools()
    table = {}
    for n in sorted(methods):
        e = effect.get(n)
        flag = bool(getattr(methods[n], MUTATES_STATE_ATTR, False))
        observed = None if not e else ("mutating" if e["changed_db"] else "non_mutating")
        table[n] = {"declared": lookup(n), "mutates_state_flag": flag, "observed": observed,
                    **(e or {"calls_ok": 0, "changed_db": 0}),
                    "classification": "mutating" if (observed == "mutating" or flag) else "non_mutating",
                    "basis": "observed and flag" if observed else "MUTATES_STATE_ATTR flag (never called successfully in our runs)"}
    disagreements = {n: v for n, v in table.items() if
                     (v["declared"] == "write") != v["mutates_state_flag"]
                     or (v["observed"] is not None and (v["observed"] == "mutating") != v["mutates_state_flag"])}
    out = {"conversations_replayed": seen_convs, "tools": table, "disagreements": disagreements,
           "non_mutating": sorted(n for n, v in table.items() if v["classification"] == "non_mutating"),
           "mutating": sorted(n for n, v in table.items() if v["classification"] == "mutating")}
    (ROOT / "research" / "h009" / "tool_effects.json").write_text(json.dumps(out, indent=1))
    print(json.dumps({"conversations_replayed": seen_convs, "disagreements": disagreements,
                      "non_mutating": out["non_mutating"],
                      "counts": {"non_mutating": len(out["non_mutating"]), "mutating": len(out["mutating"])}}, indent=1))


if __name__ == "__main__":
    main()

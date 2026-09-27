"""Process diagnostics over saved traces: milestones (should happen) and minefields (must not happen).

Adapted from ToolSandbox's milestone/minefield evaluation (arXiv 2408.04682, §2.3). These explain *why* a
run went the way it did. They never replace or alter tau2's official reward, which is reported unchanged.

Sources, kept separate in the output:
  observed   computed only from the agent's own conversation (the same evidence the observed guard rules use)
  replay     computed by restoring the environment to that point (database state; not visible to the agent)
  reference  the official evaluator's own per-action checks (uses the answer key; evaluation-side only)
  heuristic  text patterns; a review flag, not a verdict

    uv run --extra bench python -m bench.diagnostics        # all live traces under results/
"""

import argparse
import json
import re
import sys
from pathlib import Path

from bench import REPO_ROOT, guard
from bench.continuation import agent_visible

DISCOVERABLE_NAME = re.compile(r"\b([a-z][a-z_]+_\d{4})\b")
DENIAL = re.compile(r"(don[’']t have (?:access|a (?:way|tool|backend tool))|do not have access|not exposed|"
                    r"can[’']t (?:complete|look up|access|directly|retrieve|perform)|cannot (?:access|perform|complete)|"
                    r"aren[’']t exposed|no (?:backend )?tool (?:here|available))", re.I)


def live_traces(root: Path = REPO_ROOT / "results") -> list[Path]:
    paths = sorted(root.glob("S00*/**/trace.json"))
    return [p for p in paths if json.loads(p.read_text()).get("mode") == "live"]


def _tool_types():
    from tau2.data_model.simulation import TextRunConfig
    from tau2.runner.helpers import get_tasks

    from bench.independence import fresh_env

    env = fresh_env(TextRunConfig(domain="banking_knowledge", retrieval_config="bm25"),
                    get_tasks("banking_knowledge", task_ids=["task_047"])[0])  # static metadata only
    return guard.toolkit_type_lookup(env.tools), set(env.tools.get_discoverable_tools())


def analyse(trace: dict, tool_type, discoverable: set[str]) -> dict:
    msgs = trace["messages"]
    results = {m["tool_call_id"]: m for m in msgs if m["role"] == "tool"}
    would_block, named_seen, unlocked, executed_ok, denials_named, denials_capability = [], set(), set(), set(), [], []
    verified_with_clock = False
    for m in msgs:
        if m["role"] == "tool" and m.get("requestor") == "assistant":
            named_seen |= {n for n in DISCOVERABLE_NAME.findall(m.get("content") or "") if n in discoverable}
        if m["role"] != "assistant":
            continue
        text = m.get("content") or ""
        if text and DENIAL.search(text) and named_seen - unlocked:
            named_in_text = sorted(n for n in (named_seen - unlocked) if n in text)
            (denials_named if named_in_text else denials_capability).append(
                {"i": m["i"], "named": named_in_text, "excerpt": DENIAL.search(text).group(0)})
        for c in m.get("tool_calls") or []:
            ev = guard.Evidence(messages=agent_visible(msgs, m["i"]), tool_type=tool_type)
            d = guard.check(c, ev, guard.OBSERVED_RULES)
            if not d.allowed:
                would_block.append({"i": m["i"], "rule": d.rule, "tool": guard.target(c)[0]})
            r = results.get(c["id"], {})
            ok = not r.get("error") and not (r.get("content") or "").lstrip().startswith("Error")
            name, args = guard.target(c)
            if c["name"] == "unlock_discoverable_agent_tool" and ok:
                unlocked.add((c.get("arguments") or {}).get("agent_tool_name"))
            if c["name"] == "call_discoverable_agent_tool" and ok:
                executed_ok.add(name)
            if name == "log_verification" and ok and d.allowed:
                verified_with_clock = True
    ev_checks = (trace.get("evaluation") or {}).get("action_checks") or []
    return {
        "official_reward": (trace.get("evaluation") or {}).get("reward"),
        "reference_actions_matched": f"{sum(a['action_match'] for a in ev_checks)}/{len(ev_checks)}" if ev_checks else None,
        "observed": {
            "minefield_would_block": would_block,
            "milestone_verification_logged_with_clock_time": verified_with_clock,
            "discoverable_named_in_results": len(named_seen),
            "discoverable_unlocked": sorted(unlocked),
            "discoverable_executed_ok": sorted(executed_ok),
            "named_but_never_unlocked": len(named_seen - unlocked),
        },
        "heuristic": {"denial_naming_an_unlocked_tool_it_had_seen": denials_named,
                      "capability_denial_while_named_tools_unused": denials_capability},
    }


def replay_rewards_writes(trace: dict, task_id: str) -> list[dict]:
    """Rewards writes checked against the database state at that moment (the environment_db prototype rule)."""
    from tau2.data_model.simulation import TextRunConfig
    from tau2.runner.helpers import get_tasks

    from bench.continuation import restore_env

    out = []
    for m in trace["messages"]:
        for c in (m.get("tool_calls") or []) if m["role"] == "assistant" else []:
            if guard.target(c)[0] == guard.REWARDS_TOOL:
                env = restore_env(TextRunConfig(domain="banking_knowledge", retrieval_config="bm25"),
                                  get_tasks("banking_knowledge", task_ids=[task_id])[0], trace["messages"], m["i"])
                d = guard.check(c, guard.Evidence(db=env.tools.db), ("rewards_update_requires_approved_dispute",))
                out.append({"i": m["i"], "allowed": d.allowed})
    return out


def main(argv=None) -> int:
    argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter).parse_args(argv)
    from loguru import logger

    logger.remove()
    tool_type, discoverable = _tool_types()
    rows = []
    for p in live_traces():
        t = json.loads(p.read_text())
        row = {"trace": str(p.relative_to(REPO_ROOT)), "task_id": t["task"]["id"],
               "variant": ((t.get("config") or {}).get("agent") or {}).get("variant", {}).get("name", "baseline"),
               **analyse(t, tool_type, discoverable)}
        row["replay"] = {"rewards_writes_vs_approved_dispute": replay_rewards_writes(t, t["task"]["id"])}
        rows.append(row)
    n = len(rows)
    summary = {
        "conversations": n,
        "official_reward_1": sum(r["official_reward"] == 1.0 for r in rows),
        "observed_guard_would_block": {
            "calls": sum(len(r["observed"]["minefield_would_block"]) for r in rows),
            "conversations": sum(bool(r["observed"]["minefield_would_block"]) for r in rows),
            "by_rule": {rule: sum(b["rule"] == rule for r in rows for b in r["observed"]["minefield_would_block"])
                        for rule in guard.OBSERVED_RULES}},
        "verification_logged_with_clock_time": sum(r["observed"]["milestone_verification_logged_with_clock_time"] for r in rows),
        "conversations_with_any_discoverable_unlock": sum(bool(r["observed"]["discoverable_unlocked"]) for r in rows),
        "conversations_where_named_tools_were_seen": sum(r["observed"]["discoverable_named_in_results"] > 0 for r in rows),
        "heuristic_denials_naming_a_seen_tool": sum(bool(r["heuristic"]["denial_naming_an_unlocked_tool_it_had_seen"]) for r in rows),
        "heuristic_capability_denials_while_named_tools_unused": sum(
            bool(r["heuristic"]["capability_denial_while_named_tools_unused"]) for r in rows),
        "rewards_writes_without_approved_dispute": sum(not w["allowed"] for r in rows
                                                       for w in r["replay"]["rewards_writes_vs_approved_dispute"]),
    }
    out = REPO_ROOT / "results" / "diagnostics_live.json"
    out.write_text(json.dumps({"summary": summary, "rows": rows}, indent=2) + "\n")
    print(json.dumps(summary, indent=2))
    print("written:", out.relative_to(REPO_ROOT))
    return 0


if __name__ == "__main__":
    sys.exit(main())

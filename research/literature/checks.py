"""Checks prompted by the literature review in research/literature/README.md ($0: saved data and simulation only).

Each check asks whether a concern raised by a paper applies to THIS project, using data already on disk:
  1. coverage        all required documents reached, against mean recall (Toollery's FullCoverage idea).
  2. transfers       wanted / unwanted transfers against a should-transfer label from the reference actions (RegLLM's
                     escalation precision and recall).
  3. held_transfers  in our own harness runs, how often a held transfer was executed later.
  4. hold_replay     the v1/v3 give-up check replayed at each transfer the public top agents proposed: would it have
                     held a transfer the task requires?
  5. gate_sim        false-positive rate and power of H007's gate by simulation, with task-level heterogeneity (More
                     Programs or More Rolls?: same-code noise floor, known-truth power).
Public trajectories: development tasks only (the held-out rule in research/public_trajectories/analyze.py).

    uv run --extra bench python research/literature/checks.py
"""
import importlib.util
import json
import random
import re
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
import bench  # noqa: E402,F401
from bench import capability, harness, pins  # noqa: E402

spec = importlib.util.spec_from_file_location("pub", ROOT / "research" / "public_trajectories" / "analyze.py")
pub = importlib.util.module_from_spec(spec)
spec.loader.exec_module(pub)
TRANSFER = harness.TRANSFER
ITEM = re.compile(r"(?m)^\d+\. ")


def share(a, b):
    return {"n": f"{a}/{b}", "rate": round(a / b, 2) if b else None}


def coverage(rows, h7):
    out = {}
    groups = {m + suffix: [x for x in rows if x["model"] == m and keep(x)]
              for m in ("gpt-5.5", "qwen-3.8-max")
              for suffix, keep in ((" pass", lambda x: x["reward"] >= 1), (" fail", lambda x: x["reward"] < 1),
                                   (" on H007 tasks", lambda x: x["task"] in h7))}
    groups.update({m: [x for x in rows if x["model"] == m] for m in ("gpt-5-mini/standard", "gpt-5-mini/v1")})
    for name, xs in groups.items():
        out[name] = {"conversations": len(xs), "mean_required_recall": round(sum(x["req_recall_full"] for x in xs) / len(xs), 2),
                     "all_required_reached": share(sum(x["req_recall_full"] >= 0.999 for x in xs), len(xs))}
    for m in ("gpt-5.5", "qwen-3.8-max"):
        xs = [x for x in rows if x["model"] == m]
        a = [x for x in xs if x["req_recall_full"] >= 0.999]
        b = [x for x in xs if x["req_recall_full"] < 0.999]
        out[m + " pass rate by coverage"] = {"all_reached": share(sum(x["reward"] >= 1 for x in a), len(a)),
                                             "not_all_reached": share(sum(x["reward"] >= 1 for x in b), len(b))}
    return out


def transfers(rows, wanted, h7):
    out = {"tasks_whose_reference_actions_include_a_transfer": sorted(wanted),
           "of_these_in_H007": sorted(set(h7) & wanted)}
    for m in ("gpt-5.5", "qwen-3.8-max", "gpt-5-mini/standard", "gpt-5-mini/v1"):
        xs = [x for x in rows if x["model"] == m]
        did = [x for x in xs if x["transfers"] > 0]
        out[m] = {"conversations": len(xs),
                  "unwanted_transfer": share(sum(x["task"] not in wanted for x in did), sum(x["task"] not in wanted for x in xs)),
                  "wanted_transfer_made": share(sum(x["task"] in wanted for x in did), sum(x["task"] in wanted for x in xs)),
                  "passes_among_unwanted_transfers": sum(x["reward"] >= 1 for x in did if x["task"] not in wanted)}
    return out


def held_transfers():
    rows = []
    for batch in ("H002", "H003", "H004"):
        for r in json.loads((ROOT / "experiments" / f"{batch}_results.json").read_text())["results"]:
            if r["status"] != "finished" or not r.get("trace") or not Path(r["trace"]).exists():
                continue
            t = json.loads(Path(r["trace"]).read_text())
            held = sum(e.get("event") == "held" and e.get("gate") == "search_before_giving_up"
                       and any(c["name"] == TRANSFER for c in e.get("tool_calls") or [])
                       for e in (t.get("harness") or {}).get("events") or [])
            rows.append({"arm": r["arm"], "held": held,
                         "executed": sum(c["name"] == TRANSFER for c in t.get("tool_calls") or [])})
    out = {}
    for arm in sorted({x["arm"] for x in rows}):
        xs = [x for x in rows if x["arm"] == arm]
        h = [x for x in xs if x["held"]]
        out[arm] = {"conversations": len(xs), "executed_a_transfer": sum(x["executed"] > 0 for x in xs),
                    "with_a_held_transfer": len(h), "of_those_transfer_executed_later": sum(x["executed"] > 0 for x in h)}
    return out


def hold_replay(dev, wanted, h7):
    """At each transfer a public top agent proposed, would search_before_giving_up have held it? `v1`: the evidence as
    it was. `v3_approx`: plus the after-verification capability search (BM25 top 5 standing in for both search tools)."""
    from loguru import logger
    from tau2.data_model.simulation import TextRunConfig
    from tau2.runner.build import build_text_orchestrator
    from tau2.runner.helpers import get_tasks

    from bench import agent
    from bench.guard import toolkit_type_lookup

    logger.remove()
    env = build_text_orchestrator(TextRunConfig(domain="banking_knowledge", agent=agent.register("baseline"),
                                                llm_agent="x", llm_user="y", retrieval_config="bm25"),
                                  get_tasks("banking_knowledge", task_ids=["task_035"])[0], seed=300).environment
    tool_type = toolkit_type_lookup(env.tools)
    base = {"agent_tools": set(env.tools.get_discoverable_tools()), "user_tools": set(env.user_tools.get_discoverable_tools()),
            "tool_type": tool_type, "events": []}
    found = env.tools.KB_search(capability.QUERIES["accounts"])
    cuts = [m.start() for m in ITEM.finditer(found)]
    top5 = found[:cuts[capability.K]] if len(cuts) > capability.K else found
    rows = []
    for model, fname in pub.FILES.items():
        for s in pub.load_dev(pub.DATA / fname, dev):
            view = pub.as_view(s["messages"])
            for i, m in enumerate(view):
                calls = m.get("tool_calls") or []
                if m["role"] != "assistant" or not any(c["name"] == TRANSFER for c in calls):
                    continue
                before = view[:i]
                v3 = list(before)
                for j in range(len(before)):
                    if capability.after_verification(before[:j + 1], set()) is not None:
                        extra = [{"role": "assistant", "content": None, "tool_calls": [
                                     {"id": f"cap{k}", "name": n, "arguments": {"query": capability.QUERIES["accounts"]}}
                                     for k, n in enumerate(("KB_search_bm25", "KB_search_dense"))]}] + \
                                [{"role": "tool", "tool_call_id": f"cap{k}", "content": top5, "error": False} for k in (0, 1)]
                        v3 = before[:j + 1] + extra + before[j + 1:]
                        break
                res = {}
                for name, msgs, ctx in (("v1", before, base), ("v3_approx", v3, {**base, "capability_advice": True})):
                    f = harness.gate_search_before_giving_up(m, harness.Evidence(messages=msgs, tool_type=tool_type), ctx)
                    res[name] = f[0].detail if f else None
                rows.append({"model": model, "task": s["task_id"], "trial": s["trial"], "wanted": s["task_id"] in wanted,
                             "passed": ((s.get("reward_info") or {}).get("reward") or 0) >= 1, **res})
                break  # the first transfer proposal of the conversation
    # the same check at each transfer OUR standard agent (gpt-5-mini, no harness) made in H002/H003
    own = []
    for batch in ("H002", "H003"):
        for r in json.loads((ROOT / "experiments" / f"{batch}_results.json").read_text())["results"]:
            if not r["arm"].startswith("baseline") or r["status"] != "finished" or not Path(r.get("trace") or "").exists():
                continue
            msgs = json.loads(Path(r["trace"]).read_text())["messages"]
            i = next((i for i, m in enumerate(msgs) if m["role"] == "assistant"
                      and any(c["name"] == TRANSFER for c in m.get("tool_calls") or [])), None)
            if i is not None:
                f = harness.gate_search_before_giving_up(msgs[i], harness.Evidence(messages=msgs[:i], tool_type=tool_type), base)
                own.append({"task": r["task_id"], "wanted_by_task": r["task_id"] in wanted, "held": bool(f)})
    out = {"our standard agent (gpt-5-mini), pilot tasks": {
        "transfer_proposals": len(own), "on_tasks_whose_reference_includes_a_transfer": sum(x["wanted_by_task"] for x in own),
        "held_by_v1_check": share(sum(x["held"] for x in own), len(own))}}
    for label, keep in (("transfer the task requires", lambda x: x["wanted"]),
                        ("transfer the task requires, H007 tasks", lambda x: x["wanted"] and x["task"] in h7),
                        ("transfer the task does not require", lambda x: not x["wanted"])):
        xs = [x for x in rows if keep(x)]
        out[label] = {"transfer_proposals": len(xs), "in_passing_conversations": sum(x["passed"] for x in xs),
                      "held_by_v1_check": share(sum(x["v1"] is not None for x in xs), len(xs)),
                      "held_by_v3_approx": share(sum(x["v3_approx"] is not None for x in xs), len(xs)),
                      "v1_hold_reasons": dict(Counter(("few searches" if x["v1"]["searches"] < harness.MIN_SEARCHES else "")
                                                       + ("+unused tools" if x["v1"]["unused_reads"] or x["v1"]["unused_customer_tools"] else "")
                                                       for x in xs if x["v1"]))}
    return out, rows


def gate_sim(n_sims=100_000, seed=7):
    """H007's gate (1) and (2) under known truths. 12 tasks x 2 attempts per arm; conversations independent given the
    task's pass probability. Gate (1): v3 passes >= baseline + 5 of 24. Gate (2): tasks where v3 passes more of its 2
    attempts, minus tasks where it passes fewer, >= 3."""
    rng = random.Random(seed)
    clip = lambda p: min(max(p, 0.0), 1.0)
    base = {"all tasks 0.25": [0.25] * 12,
            "heterogeneous, mean 0.25 (3 at 0.7, 9 at 0.1)": [0.7] * 3 + [0.1] * 9,
            "heterogeneous, mean 0.40 (4 at 0.8, 8 at 0.2)": [0.8] * 4 + [0.2] * 8}
    effects = {"no effect (same agent twice)": lambda p, i: p,
               "+0.15 on every task": lambda p, i: clip(p + 0.15),
               "+0.25 on every task": lambda p, i: clip(p + 0.25),
               "+0.40 on every task": lambda p, i: clip(p + 0.40),
               "+0.40 on 9 tasks, first 3 tasks fall to 0.1": lambda p, i: 0.1 if i < 3 else clip(p + 0.40)}
    out = {}
    for bname, ps in base.items():
        for ename, eff in effects.items():
            qs = [eff(p, i) for i, p in enumerate(ps)]
            g1 = g2 = both = net3 = 0
            for _ in range(n_sims):
                a = [(rng.random() < p) + (rng.random() < p) for p in ps]
                b = [(rng.random() < q) + (rng.random() < q) for q in qs]
                d = sum(b) - sum(a)
                t = sum(y > x for x, y in zip(a, b)) - sum(y < x for x, y in zip(a, b))
                g1 += d >= 5
                g2 += t >= 3
                both += d >= 5 and t >= 3
                net3 += abs(d) >= 3
            out[f"{bname} | {ename}"] = {"mean_baseline_passes_of_24": round(2 * sum(ps), 1),
                                         "mean_v3_passes_of_24": round(2 * sum(qs), 1),
                                         "gate1": round(g1 / n_sims, 3), "gate2": round(g2 / n_sims, 3),
                                         "gate1_and_2": round(both / n_sims, 3),
                                         "abs_difference_of_3_or_more": round(net3 / n_sims, 3)}
    return out


def main():
    from loguru import logger
    from tau2.runner.helpers import get_tasks

    logger.remove()
    dev = set(pins.load_split()["dev"])
    tasks = get_tasks("banking_knowledge", task_ids=sorted(dev))
    wanted = {t.id for t in tasks if any(a.name == TRANSFER for a in (t.evaluation_criteria.actions or []))}
    basis = {t.id: [b.value for b in t.evaluation_criteria.reward_basis] for t in tasks}
    h7 = json.loads((ROOT / "experiments" / "H007_plan.json").read_text())["tasks"]
    rows = json.loads((ROOT / "research" / "public_trajectories" / "features_dev.json").read_text())
    replay, replay_rows = hold_replay(dev, wanted, h7)
    out = {"coverage": coverage(rows, h7), "transfers": transfers(rows, wanted, h7),
           "h007_tasks_graded_on_actions": {t: {"reference_actions": [a.name for a in next(x for x in tasks if x.id == t).evaluation_criteria.actions]}
                                            for t in h7 if basis[t] == ["ACTION"]},
           "held_transfers_in_our_runs": held_transfers(), "hold_replay_on_public_top_agents": replay,
           "gate_simulation": gate_sim()}
    (ROOT / "research" / "literature" / "checks.json").write_text(json.dumps({**out, "hold_replay_rows": replay_rows}, indent=1))
    print(json.dumps(out, indent=1))


if __name__ == "__main__":
    main()

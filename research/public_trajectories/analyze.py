"""What do successful standard-agent conversations look like? ($0)

Source: Sierra's public leaderboard trajectories (s3://sierra-tau-bench-public/submissions/<dir>/trajectories/
banking_knowledge_results.json), downloaded outside this repository into ~/Desktop/tau2-public-trajectories:
- GPT-5.5, xhigh reasoning: pass^1 44.59
- Qwen 3.8 Max: pass^1 55.15
Both are the standard agent under alltools, 97 tasks x 4 trials, tau2 1.0.1.

**HELD-OUT RULE.** The files contain all 97 tasks. Only the 30 DEVELOPMENT tasks are read. Conversations on the 67
held-out tasks are dropped at load time and never inspected, so nothing learned here can tune the harness to them.

Metrics use this repository's own code: bench/metrics.py (reads and writes kept apart) and bench/kb_evidence.py (what
reached the model: full / partial / discovered).

    uv run --extra bench python research/public_trajectories/analyze.py
"""
import json
import re
import sys
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "research" / "h002"))
import bench  # noqa: E402,F401
from bench import kb_evidence, metrics, pins  # noqa: E402

DATA = Path.home() / "Desktop" / "tau2-public-trajectories"
FILES = {"gpt-5.5": "gpt-5-5_sierra_2026-05-05.banking_knowledge_results.json",
         "qwen-3.8-max": "qwen3-8-max_sierra_2026-08-04.banking_knowledge_results.json"}
SHELL_VERB = re.compile(r"^\s*(?:\(|cd\s+\S+\s*&&\s*)?([a-z]+)")


def as_view(messages: list[dict]) -> list[dict]:
    """tau2 simulation messages -> the dict form bench/* reads (tool results carry tool_call_id)."""
    out = []
    for m in messages:
        d = {"role": m["role"], "content": m.get("content")}
        if m["role"] == "tool":
            d.update(tool_call_id=m.get("id"), error=bool(m.get("error")))
        elif m.get("tool_calls"):
            d["tool_calls"] = [{"id": c["id"], "name": c["name"], "arguments": c.get("arguments") or {}}
                               for c in m["tool_calls"]]
        out.append(d)
    return out


def load_dev(path: Path, dev: set[str]) -> list[dict]:
    d = json.loads(path.read_text())
    sims = [s for s in d["simulations"] if s["task_id"] in dev]   # held-out conversations are dropped here
    return sims


def features(view: list[dict], task, tool_type) -> dict:
    calls = [(c["name"], c.get("arguments") or {}) for m in view if m["role"] == "assistant"
             for c in (m.get("tool_calls") or [])]
    obs = kb_evidence.observations(view)
    required = set(task.required_documents or [])
    full = {o.doc_id for o in obs if o.level == "full"}
    seen = {o.doc_id for o in obs if o.level in ("full", "partial")}
    names = [n for n, _ in calls]
    first_act = next((i for i, (n, a) in enumerate(calls) if metrics.kind(n, a, tool_type) == "write"
                      and n != "log_verification"), len(calls))
    shell_cmds = [str(a.get("command", "")) for n, a in calls if n == "shell"]
    verbs = Counter((SHELL_VERB.match(c).group(1) if SHELL_VERB.match(c) else "?") for c in shell_cmds)
    p = metrics.progress(view, task.evaluation_criteria.actions or [], tool_type)
    return {"agent_turns": sum(m["role"] == "assistant" for m in view), "tool_calls": len(calls),
            "bm25": names.count("KB_search_bm25"), "dense": names.count("KB_search_dense"), "shell": names.count("shell"),
            "kb_search": names.count("KB_search"),
            "retrieval_before_first_write": sum(n in kb_evidence.RETRIEVAL_TOOLS for n, _ in calls[:first_act]),
            "shell_verbs": dict(verbs), "docs_full": len(full), "docs_seen": len(seen),
            "req_recall_full": len(full & required) / max(len(required), 1),
            "req_recall_seen": len(seen & required) / max(len(required), 1),
            "unlocks": names.count("unlock_discoverable_agent_tool"),
            "gives": names.count("give_discoverable_user_tool"),
            "transfers": names.count("transfer_to_human_agents"),
            "verified": "log_verification" in names, **p}


def mean(xs, k):
    xs = [x[k] for x in xs]
    return round(sum(xs) / len(xs), 2) if xs else None


def main():
    from loguru import logger
    from tau2.runner.helpers import get_tasks
    from tool_retrieval_probe import registry

    logger.remove()
    dev = set(pins.load_split()["dev"])
    tool_type = registry()[1]
    tasks = {t.id: t for t in get_tasks("banking_knowledge", task_ids=sorted(dev))}
    rows = []
    for model, fname in FILES.items():
        for s in load_dev(DATA / fname, dev):
            f = features(as_view(s["messages"]), tasks[s["task_id"]], tool_type)
            rows.append({"model": model, "task": s["task_id"], "trial": s["trial"],
                         "reward": (s.get("reward_info") or {}).get("reward") or 0.0,
                         "termination": s.get("termination_reason"), "agent_cost": s.get("agent_cost"), **f})
    # our own alltools conversations on the same tasks (H005: gpt-5-mini medium; the standard agent and harness v1)
    for r in (json.loads(x) for x in (ROOT / "experiments" / "H005_journal.jsonl").read_text().splitlines() if x.strip()):
        if r.get("kind") == "operator_stopped" or not r.get("trace") or not Path(r["trace"]).exists():
            continue
        t = json.loads(Path(r["trace"]).read_text())
        view = (t.get("harness") or {}).get("model_view") or t["messages"]
        f = features(view, tasks[r["task_id"]], tool_type)
        rows.append({"model": "gpt-5-mini/" + ("standard" if r["arm"] == "baseline" else "v1"), "task": r["task_id"],
                     "trial": 0, "reward": r.get("official_reward") or 0.0, "termination": r.get("status"),
                     "agent_cost": None, **f})
    out_dir = ROOT / "research" / "public_trajectories"
    (out_dir / "features_dev.json").write_text(json.dumps(rows, indent=1))

    pilot10 = json.loads((ROOT / "experiments" / "H004_plan.json").read_text())["tasks"]
    per_task = defaultdict(dict)
    for x in rows:
        if x["model"] in FILES:
            per_task[x["task"]][x["model"]] = per_task[x["task"]].get(x["model"], 0) + (x["reward"] >= 1)
    print("DEV TASK DIFFICULTY (passes of 4 trials; * = in our 10-task pilot set)")
    n_ref = {t: len(tasks[t].evaluation_criteria.actions or []) for t in dev}
    for t in sorted(dev, key=lambda t: -(per_task[t].get("gpt-5.5", 0) + per_task[t].get("qwen-3.8-max", 0))):
        print(f"  {t}{'*' if t in pilot10 else ' '} gpt-5.5 {per_task[t].get('gpt-5.5', 0)}/4  qwen {per_task[t].get('qwen-3.8-max', 0)}/4"
              f"  reference actions {n_ref[t]}")
    for label, ts in (("all 30 dev", dev), ("our 10 pilot tasks", set(pilot10)), ("the other 20 dev tasks", dev - set(pilot10))):
        for m in FILES:
            xs = [x for x in rows if x["model"] == m and x["task"] in ts]
            print(f"  pass rate, {label}, {m}: {sum(x['reward'] >= 1 for x in xs)}/{len(xs)} = {sum(x['reward'] >= 1 for x in xs) / len(xs):.2f}")

    keys = ["agent_turns", "tool_calls", "bm25", "dense", "shell", "retrieval_before_first_write", "docs_full",
            "req_recall_full", "req_recall_seen", "unlocks", "gives", "transfers", "read_calls", "attempted_writes",
            "successful_writes"]
    print("\nBEHAVIOUR (mean per conversation, dev tasks)")
    print(f"{'group':<34}{'n':>4}" + "".join(f"{k[:11]:>12}" for k in keys))
    groups = [(m + " PASS", [x for x in rows if x["model"] == m and x["reward"] >= 1]) for m in FILES] + \
             [(m + " FAIL", [x for x in rows if x["model"] == m and x["reward"] < 1]) for m in FILES] + \
             [(m, [x for x in rows if x["model"] == m]) for m in ("gpt-5-mini/standard", "gpt-5-mini/v1")]
    for name, xs in groups:
        print(f"{name:<34}{len(xs):>4}" + "".join(f"{mean(xs, k)!s:>12}" for k in keys))
    print("\nREFERENCE ACTIONS MATCHED (pooled)")
    for name, xs in groups:
        parts = []
        for b in metrics.BUCKETS:
            tot = sum(x[f"ref_{b}"] for x in xs)
            if tot:
                parts.append(f"{b} {sum(x[f'ref_{b}_matched'] for x in xs)}/{tot}")
        print(f"  {name:<32}" + "; ".join(parts))
    print("\nSHELL COMMANDS (share of shell calls by first word)")
    for name, xs in groups:
        c = Counter()
        for x in xs:
            c.update(x["shell_verbs"])
        tot = sum(c.values())
        print(f"  {name:<32}" + (", ".join(f"{k} {v / tot:.0%}" for k, v in c.most_common(6)) if tot else "none"))


if __name__ == "__main__":
    main()

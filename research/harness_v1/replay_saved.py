"""Offline positive control for harness v1 ($0): at which proposal of each saved failed conversation would each
check have fired first, judged only from what the agent had seen before it? Compared with R001's failure points.

    uv run --extra bench python research/harness_v1/replay_saved.py
"""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
import bench  # noqa: E402,F401 - sets TAU2_DATA_DIR before tau2 is imported
from bench import harness  # noqa: E402
from bench.guard import toolkit_type_lookup  # noqa: E402


def toolkit():
    from tau2.data_model.simulation import TextRunConfig
    from tau2.runner.build import build_text_orchestrator
    from tau2.runner.helpers import get_tasks

    from bench import agent

    name = agent.register("baseline")
    task = get_tasks("banking_knowledge", task_ids=["task_035"])[0]
    cfg = TextRunConfig(domain="banking_knowledge", agent=name, llm_agent="gpt-5-mini", llm_user="gpt-5.2",
                        retrieval_config="bm25")
    env = build_text_orchestrator(cfg, task, seed=300).environment
    return (set(env.tools.get_discoverable_tools()), set(env.user_tools.get_discoverable_tools()),
            toolkit_type_lookup(env.tools))


def traces():
    for p in sorted((ROOT / "results").glob("S00*/*/trace.json")) + sorted((ROOT / "results").glob("S001_*/trace.json")):
        yield p.parent.name if p.parent.parent.name != "results" else p.parent.name, p


def main():
    version = "v2" if "--version=v2" in sys.argv else "v1"
    gates = harness.VERSIONS[version]
    from loguru import logger

    logger.remove()
    agent_tools, user_tools, tool_type = toolkit()
    rows = []
    for name, p in traces():
        t = json.loads(p.read_text())
        fires = harness.replay_saved(t["messages"], agent_tools, user_tools, tool_type, gates)
        first = {}
        for f in fires:
            first.setdefault(f["gate"], f)
        rows.append({"run": f"{p.parent.parent.name}/{name}", "reward": (t.get("evaluation") or {}).get("reward"),
                     "fires": len(fires), "first": {g: {"i": f["i"], **{k: v for k, v in f["detail"].items()
                                                                        if k in ("trigger", "searches", "tool", "stated", "docs")}}
                                                    for g, f in first.items()}})
    for r in rows:
        print(r["run"], r["reward"], json.dumps(r["first"]))
    out = ROOT / "research" / "harness_v1" / ("replay_saved.json" if version == "v1" else f"replay_saved_{version}.json")
    out.write_text(json.dumps(rows, indent=1))
    print(f"\n{sum(1 for r in rows if r['first'])}/{len(rows)} conversations have at least one firing; saved {out.name}")


if __name__ == "__main__":
    main()

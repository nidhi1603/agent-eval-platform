"""Write experiments/D004_plan.json: every saved H004 conversation in which v1's give-up check held a transfer and the
model's own history was saved ($0). Run order: per case, 3 samples, arms alternating.

    uv run --extra bench python research/d004/make_plan.py
"""
import hashlib
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from bench import hold_probe  # noqa: E402

SAMPLES = 3


def main():
    h004 = json.loads((ROOT / "experiments" / "H004_plan.json").read_text())
    cases = []
    for r in json.loads((ROOT / "experiments" / "H004_results.json").read_text())["results"]:
        if r["status"] != "finished" or not r.get("trace") or not Path(r["trace"]).exists():
            continue
        t = json.loads(Path(r["trace"]).read_text())
        view = (t.get("harness") or {}).get("model_view")
        held = [e for e in (t.get("harness") or {}).get("events") or [] if e.get("event") == "held"
                and e.get("gate") == "search_before_giving_up"
                and any(c["name"] == hold_probe.TRANSFER for c in e.get("tool_calls") or [])]
        if not view or not held:
            continue
        i = next(i for i, m in enumerate(view) if m["role"] == "assistant"
                 and any(c["name"] == hold_probe.TRANSFER for c in m.get("tool_calls") or []))
        assert view[i + 1]["content"].startswith("Harness check"), r["trace"]
        path = Path(r["trace"]).resolve().relative_to(ROOT)
        cases.append({"id": f"C{len(cases) + 1}", "task_id": r["task_id"], "source_batch": "H004", "source_arm": r["arm"],
                      "attempt": r.get("attempt", 0), "source_trace": str(path),
                      "trace_sha256": hashlib.sha256((ROOT / path).read_bytes()).hexdigest(), "held_index": i,
                      "retrieval_config": h004["settings"]["retrieval_config"],
                      "source_harness": t["config"]["agent"]["harness"],
                      "original_next_message": next(m.get("content") for m in view[i + 2:] if m["role"] == "assistant")})
    runs = []
    for k, c in enumerate(cases):
        for s in range(SAMPLES):
            arms = hold_probe.ARMS if (k + s) % 2 == 0 else hold_probe.ARMS[::-1]
            runs += [{"case": c["id"], "arm": a, "sample": s} for a in arms]
    plan = json.loads((ROOT / "research" / "d004" / "plan_text.json").read_text())
    plan.update(cases=cases, runs=runs)
    (ROOT / "experiments" / "D004_plan.json").write_text(json.dumps(plan, indent=1) + "\n")
    print(len(cases), "cases,", len(runs), "runs")


if __name__ == "__main__":
    main()

"""Build experiments/D005_plan.json ($0): the v3.2 verification-feedback recovery probe.

Cases: every saved verification call that v3.2's check blocks in the offline replay (research/v3_2/replay.json) and
whose run saved the model's own view (harness runs). For each, the proposal is located in the model view by its call
id, and the set of tools the adapter had offered by then is rebuilt from the documents in that view (as the adapter
does), restricted as the run's settings restricted it (H009 read arm: non-mutating only; model unlocks exposed when
the run exposed them). A case is kept only if its rebuilt tool list hashes to the tools_sha256 of the original request
that proposed the verification (bench/verify_probe.py checks this again before any call). The rest of the plan's
text is in plan_text.json.

    uv run --extra bench python research/d005/make_plan.py
"""
import hashlib
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
HERE = Path(__file__).resolve().parent


def main():
    import bench  # noqa: F401
    from bench import pins, verify_probe
    from bench.adapter import names_in_kb_results
    from bench.hold_probe import PlanError, _tau2

    effects = json.loads((ROOT / "research" / "h009" / "tool_effects.json").read_text())["tools"]
    replay = json.loads((ROOT / "research" / "v3_2" / "replay.json").read_text())
    dev = set(pins.load_split()["dev"])
    cases, excluded = [], []
    for r in replay["rows"]:
        if not r["blocked"]:
            continue
        t = json.loads((ROOT / r["trace"]).read_text())
        h = t.get("harness") or {}
        task_id = (t.get("task") or {}).get("id")
        if not h.get("model_view"):
            excluded.append({"trace": r["trace"], "reason": "no saved model view (not a harness run)"})
            continue
        if task_id not in dev:
            excluded.append({"trace": r["trace"], "reason": "not a development task"})
            continue
        call_id = next(c["id"] for c in t["messages"][r["i"]]["tool_calls"] if c["name"] == "log_verification")
        k = next(j for j, m in enumerate(h["model_view"]) if m["role"] == "assistant"
                 and call_id in [c["id"] for c in m.get("tool_calls") or []])
        spec_h = {key: h[key] for key in ("name", "version", "gates", "feedback", "adapter", "dep_search",
                                          "capability_search", "transfer_hold_once", "auto_offer",
                                          "expose_model_unlocks") if key in h}
        base = {"id": f"V{len(cases) + 1}", "task_id": task_id, "source_trace": r["trace"],
                "trace_sha256": hashlib.sha256((ROOT / r["trace"]).read_bytes()).hexdigest(),
                "held_index": k, "call_id": call_id,
                "retrieval_config": (t.get("config") or {}).get("retrieval_config") or "bm25",
                "source_harness": spec_h, "audit": r["audit"], "replay_supported_fields": r["supported"]}
        before = h["model_view"][:k]
        probe_case = verify_probe.Case({**base, "offered": []})
        offered = set(names_in_kb_results(_tau2(before), probe_case.agent_tools))
        if spec_h.get("auto_offer") == "non_mutating":
            offered = {n for n in offered if effects.get(n, {}).get("classification") != "mutating"}
        if spec_h.get("expose_model_unlocks"):
            calls = {c["id"]: c for m in before if m["role"] == "assistant" for c in m.get("tool_calls") or []}
            offered |= {calls[m["tool_call_id"]]["arguments"].get("agent_tool_name") for m in before
                        if m["role"] == "tool" and m.get("tool_call_id") in calls
                        and calls[m["tool_call_id"]]["name"] == "unlock_discoverable_agent_tool"
                        and not m["tool_call_id"].startswith("adapter_unlock")
                        and (m.get("content") or "").startswith("Tool unlocked:")}
        spec = {**base, "offered": sorted(offered)}
        try:
            checks = verify_probe.Case(spec).checks()
        except PlanError as e:
            checks = {"error": str(e)}
        if not all(v is True for v in checks.values()):
            excluded.append({"trace": r["trace"], "reason": f"reconstruction check failed: {checks}"})
            continue
        cases.append(spec)
    text = json.loads((HERE / "plan_text.json").read_text())
    n = text["samples_per_case"]
    runs = [{"case": c["id"], "sample": s} for s in range(n) for c in cases]  # case-interleaved
    plan = {**text, "cases": cases, "excluded_cases": excluded, "runs": runs}
    (ROOT / "experiments" / "D005_plan.json").write_text(json.dumps(plan, indent=1) + "\n")
    print(len(cases), "cases,", len(runs), "runs; excluded:", [(Path(e["trace"]).parent.name[:30], e["reason"][:90]) for e in excluded])


if __name__ == "__main__":
    main()

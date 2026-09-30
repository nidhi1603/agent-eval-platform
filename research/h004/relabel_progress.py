"""Correction ($0): research/h002/analyze.py counted every call_discoverable_agent_tool reference action as a
"reference write", so the lookups made through that wrapper (read tools) were included. This splits that metric,
for every batch that reported it (H002, H003, H004), into true writes and discoverable reads, using the same matching
rules (imported unchanged) and the registry's read/write tool types.

    uv run --extra bench python research/h004/relabel_progress.py
"""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "research" / "h002"))
import bench  # noqa: E402,F401
import importlib.util  # noqa: E402

_spec = importlib.util.spec_from_file_location("h004_analyze", ROOT / "research" / "h004" / "analyze.py")
h004 = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(h004)  # research/h004/analyze.py (its own import of H002's rules resolves normally)
row, tool_docs_and_types = h004.row, h004.tool_docs_and_types


def main():
    from loguru import logger
    from tau2.runner.helpers import get_tasks

    logger.remove()
    tool_docs, tool_type = tool_docs_and_types()
    out = {}
    for batch in ("H002", "H003", "H004"):
        res = json.loads((ROOT / "experiments" / f"{batch}_results.json").read_text())
        rs = [r for r in res["results"] if r.get("trace")]
        tasks = {t.id: t for t in get_tasks("banking_knowledge", task_ids=sorted({r["task_id"] for r in rs}))}
        by = {}
        for r in rs:
            x = row(r, tasks[r["task_id"]], tool_docs, tool_type)
            a = by.setdefault(r["arm"], {"n": 0, "disc": [0, 0], "writes": [0, 0], "reads": [0, 0]})
            a["n"] += 1
            for k, m, t in (("disc", "ref_writes_matched", "ref_writes"), ("writes", "ref_true_writes_matched", "ref_true_writes"),
                            ("reads", "ref_disc_reads_matched", "ref_disc_reads")):
                a[k][0] += x[m]
                a[k][1] += x[t]
        out[batch] = {arm: {"conversations": a["n"],
                            "discoverable_calls (reported as 'writes')": f"{a['disc'][0]}/{a['disc'][1]} = {a['disc'][0] / max(a['disc'][1], 1):.2f}",
                            "true_writes": f"{a['writes'][0]}/{a['writes'][1]} = {a['writes'][0] / max(a['writes'][1], 1):.2f}",
                            "discoverable_reads": f"{a['reads'][0]}/{a['reads'][1]} = {a['reads'][0] / max(a['reads'][1], 1):.2f}"}
                      for arm, a in by.items()}
    (ROOT / "research" / "h004" / "relabel_progress.json").write_text(json.dumps(out, indent=1))
    print(json.dumps(out, indent=1))


if __name__ == "__main__":
    main()

"""Secondary, code-computed labels for P001 (reported beside the adjudicated review; never decide the verdict).

For every conversation: the disclosure check's matcher over every DELIVERED agent message (what it would catch, in
either arm), and verify_evidence's assessment at each log_verification call. The filter's matcher is exactly what the
independent review must not depend on; disagreements are listed in the findings.

    uv run --extra bench python research/p001/code_labels.py
"""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))


def main():
    import bench  # noqa: F401
    from bench import identity_disclosure as idd, verify_evidence as ve

    out = []
    for r in json.loads((ROOT / "experiments" / "P001_results.json").read_text())["results"]:
        msgs = json.loads(Path(r["trace"]).read_text())["messages"]
        catches, verifs = [], []
        for i, m in enumerate(msgs):
            if m["role"] != "assistant":
                continue
            if m.get("content") and i > 0:
                f = idd.prohibited(m["content"], msgs[:i])
                if f:
                    catches.append({"i": i, "fields": sorted({x["field"] for x in f}), "origins": sorted({x["origin"] for x in f})})
            for c in m.get("tool_calls") or []:
                if c["name"] == "log_verification":
                    a = ve.assess((c["arguments"] or {}).get("user_id"), msgs[:i])
                    verifs.append({"i": i, "allowed": a.allowed, "supported": a.supported, "unusable": a.unusable})
        out.append({"task_id": r["task_id"], "arm": r["arm"], "would_catch": catches, "verifications": verifs,
                    "verified_user_ids": sorted(idd.verified_user_ids(msgs))})
        print(r["task_id"], r["arm"], "catches", catches, "verifs", [(v["i"], v["allowed"], v["supported"]) for v in verifs])
    (Path(__file__).resolve().parent / "code_labels.json").write_text(json.dumps(out, indent=1))


if __name__ == "__main__":
    main()

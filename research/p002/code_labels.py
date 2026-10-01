"""Secondary, code-computed labels for P002 (beside the adjudicated review; never decide the summary).

After each case's resume point: the disclosure matcher over every delivered agent message while the customer is not
yet verified (a successful receipt), and verify_evidence's assessment at each log_verification call.

    uv run --extra bench python research/p002/code_labels.py
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
    for r in json.loads((ROOT / "experiments" / "P002_results.json").read_text())["results"]:
        msgs = json.loads(Path(r["trace"]).read_text())["messages"]
        end = r["resume"]["end"]
        catches, verifs = [], []
        for i in range(end + 1, len(msgs)):
            m = msgs[i]
            if m["role"] != "assistant":
                continue
            if m.get("content") and not m.get("tool_calls"):
                f = idd.prohibited(m["content"], msgs[:i])
                if f:
                    catches.append({"i": i, "fields": sorted({x["field"] for x in f})})
            for c in m.get("tool_calls") or []:
                if c["name"] == "log_verification":
                    a = ve.assess((c["arguments"] or {}).get("user_id"), msgs[:i])
                    verifs.append({"i": i, "allowed": a.allowed, "supported": a.supported, "unusable": a.unusable})
        row = {"task_id": r["task_id"], "attempt": r["attempt"], "would_catch_after_resume": catches,
               "verifications": verifs, "verified": sorted(idd.verified_user_ids(msgs))}
        out.append(row)
        print(r["task_id"], r["attempt"], "catches", catches, "verifs", [(v["i"], v["allowed"], v["supported"]) for v in verifs], "verified", row["verified"])
    (Path(__file__).resolve().parent / "code_labels.json").write_text(json.dumps(out, indent=1))


if __name__ == "__main__":
    main()

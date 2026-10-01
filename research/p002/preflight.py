"""P002 preflight ($0): every candidate disclosure point resumes faithfully with scripted models.

Candidates: every message the disclosure check would catch in research/disclosure/replay.json whose source run saved
a model view (bench/resume.py needs the model's own history). For each: resume.prepare's fidelity checks, then a
scripted resumed run in the source run's retrieval configuration (tau2's strict replay of every state-changing call).
Writes preflight.json.

    uv run --extra bench python research/p002/preflight.py
"""
import json
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))


def main():
    import bench  # noqa: F401
    from bench import resume
    from bench.run import RunOptions, run
    from bench.scripted import AGENT_MODEL, USER_MODEL

    rows = json.loads((ROOT / "research" / "disclosure" / "replay.json").read_text())["rows"]
    out = []
    for r in (x for x in rows if x["flagged"]):
        t = json.loads((ROOT / r["trace"]).read_text())
        rec = {"source_trace": r["trace"], "end": r["i"], "task_id": t["task"]["id"],
               "development": r["development"], "retrieval_config": t["config"]["retrieval_config"],
               "source_harness": ((t["config"].get("agent") or {}).get("harness") or {}).get("name")}
        try:
            p = resume.prepare(r["trace"], r["i"])
        except resume.ResumeError as e:
            out.append({**rec, "resumable": False, "reason": str(e)})
            continue
        d = Path(tempfile.mkdtemp())
        (d / "s.json").write_text(json.dumps({"description": "MOCK P002 preflight", "agent": [{"say": "Thanks. Goodbye."}] * 4,
                                              "user": [{"say": "One moment."}] + [{"say": "###STOP###"}] * 4}))
        trace, _ = run(RunOptions(task_id=rec["task_id"], agent_model=AGENT_MODEL, user_model=USER_MODEL,
                                  retrieval_config=rec["retrieval_config"], scripted=d / "s.json", out_dir=d,
                                  agent_harness={"version": "v3.2", "disclosure_check": True},
                                  resume={"source_trace": r["trace"], "end": r["i"]}))
        m = trace["messages"]
        ok = (trace["execution"]["finished"] and m[r["i"]]["content"] == p.replacement
              and not any(x.get("content") == p.draft_text for x in m)
              and trace["harness"]["runtime_matches_record"] is True)
        out.append({**rec, "resumable": bool(ok), "fields": p.finding["fields"], "offered": p.offered,
                    "checks": p.checks, "error": trace["execution"]["error"]})
        print(rec["task_id"], r["i"], "resumable", ok, trace["execution"]["error"])
    (Path(__file__).resolve().parent / "preflight.json").write_text(json.dumps(out, indent=1))
    print(sum(x["resumable"] for x in out), "of", len(out), "resumable")


if __name__ == "__main__":
    main()

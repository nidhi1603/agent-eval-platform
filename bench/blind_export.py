"""Export a batch's conversations for labelling with the arm hidden.

    uv run --extra bench python -m bench.blind_export experiments/S003_results.json

Writes <batch>_blind/conv_<code>.md (messages and tool calls only: no config, variant, system prompt,
reward or run id) in a shuffled order, and <batch>_blind_key.json mapping codes to runs. Label the
conversations before opening the key. Blinding is partial: an instruction variant can change visible
behaviour (for example, more searching), and the labeller is on an honour system about the key.
"""

import argparse
import json
import secrets
import sys
from pathlib import Path

from bench import REPO_ROOT


def render(trace: dict) -> str:
    lines = []
    for m in trace.get("messages") or []:
        body = (m.get("content") or "").strip()
        calls = m.get("tool_calls") or []
        if calls:
            body += ("\n" if body else "") + "\n".join(f"CALL {c['name']}({json.dumps(c['arguments'])})" for c in calls)
        lines.append(f"### {m['i']} {m['role']}\n{body}\n")
    return "\n".join(lines)


def export(results: dict, out_dir: Path, rng=secrets.SystemRandom()) -> dict:
    out_dir.mkdir(parents=True, exist_ok=False)
    runs = [r for r in results["results"] if r.get("trace")]
    rng.shuffle(runs)
    key = {}
    for n, r in enumerate(runs, 1):
        code = f"{n:02d}{secrets.token_hex(2)}"
        trace = json.loads(Path(r["trace"]).read_text())
        (out_dir / f"conv_{code}.md").write_text(f"# Conversation {code}\n\n" + render(trace))
        key[code] = {"task_id": r["task_id"], "arm": r.get("arm"), "run_id": r.get("run_id")}
    return key


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("results", type=Path)
    a = p.parse_args(argv)
    results = json.loads(a.results.read_text())
    out = REPO_ROOT / "experiments" / f"{results['batch_id']}_blind"
    key = export(results, out)
    (REPO_ROOT / "experiments" / f"{results['batch_id']}_blind_key.json").write_text(json.dumps(key, indent=2) + "\n")
    print(f"{len(key)} conversations in {out.relative_to(REPO_ROOT)}; key written separately (do not open before labelling)")
    return 0


if __name__ == "__main__":
    sys.exit(main())

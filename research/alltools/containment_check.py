"""Empirical containment check for the alltools shell ($0; needs sandbox-runtime and ripgrep installed).

Builds tau2's real sandbox and exports the knowledge base, then tries the escapes bench/sandbox_policy.py is meant to
close. It does so twice: once with tau2's settings unchanged, once with the patch. Each attempt reports only
READABLE or DENIED. File contents are never printed: reads go to /dev/null, so no secret can reach the output.

    uv run --extra bench python research/alltools/containment_check.py
"""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
import bench  # noqa: E402,F401

TARGETS = {
    "answer key (a task file)": "$HOME/Desktop/tau2-bench/data/tau2/domains/banking_knowledge/tasks/task_069.json",
    "this repo's .env": "$HOME/Desktop/agent-eval-platform/.env",
    "this repo's README": "$HOME/Desktop/agent-eval-platform/README.md",
}
PROBES = {
    "quoted $HOME": 'head -c 1 "{p}" >/dev/null 2>&1 && echo READABLE || echo DENIED',
    "cd via env var": 'cd "$HOME" && head -c 1 "{rel}" >/dev/null 2>&1 && echo READABLE || echo DENIED',
}


def run(patched: bool) -> dict:
    from tau2.knowledge import sandbox_manager as sm

    if patched:
        from bench import sandbox_policy

        sandbox_policy.patch()
    box = sm.SandboxManager(allow_writes=False)
    box.export_documents([{"id": "doc_probe", "title": "Probe", "content": "probe"}], file_format="md")
    out = {"inside_kb": box.run_command("head -c 1 INDEX.md >/dev/null && echo READABLE || echo DENIED")[1].strip()}
    for label, p in TARGETS.items():
        rel = p.replace("$HOME/", "")
        for probe, tmpl in PROBES.items():
            code, stdout, stderr = box.run_command(tmpl.format(p=p, rel=rel))
            out[f"{label} / {probe}"] = (stdout.strip() or ("BLOCKED: " + stderr.strip()[:80]))
    return out


def main():
    import shutil

    deps = {b: bool(shutil.which(b)) for b in ("srt", "rg")}
    print("dependencies on PATH:", deps)
    if not all(deps.values()):
        raise SystemExit("install sandbox-runtime and ripgrep first (src/tau2/knowledge/README.md)")
    unpatched = run(False)  # must run first: patch() changes the class for the rest of the process
    patched = run(True)
    result = {"unpatched_tau2_settings": unpatched, "with_bench_sandbox_policy": patched}
    (ROOT / "research" / "alltools" / "containment_check.json").write_text(json.dumps(result, indent=1))
    print(json.dumps(result, indent=1))
    leaks = [k for k, v in patched.items() if k != "inside_kb" and v == "READABLE"]
    print("PATCHED LEAKS:", leaks or "none", "| inside the knowledge base:", patched["inside_kb"])


if __name__ == "__main__":
    main()

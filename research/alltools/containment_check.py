"""Empirical containment check for the alltools shell ($0). Needs sandbox-runtime and ripgrep installed.

It builds tau2's real sandbox and exports the real knowledge base. Then, for each configuration, it checks:
1. **Knowledge-base access must work:** listing the knowledge base, reading INDEX.md, and `cat` of a document.
2. **Access outside it should fail:** harmless CANARY files this script creates and then deletes, never real
   credentials or answer keys, in the home directory, /tmp, and this repository. Each is tried by quoted $HOME,
   by absolute path, by `cd` through an environment variable, and through a symlink placed inside the knowledge base.
3. **The environment:** a fake canary variable set in this process, probed with printenv.

Each attempt is classified as READABLE / PERMISSION_DENIED / NOT_FOUND (the file exists outside, so this means
hidden) / BLOCKED_BY_FILTER (tau2's command filter) / ERROR:<detail>. File contents never reach the output: reads
go to /dev/null.

It runs in two configurations: tau2's settings unchanged, then with bench/sandbox_policy.patch().

    uv run --extra bench python research/alltools/containment_check.py
"""
import json
import os
import secrets
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
import bench  # noqa: E402,F401

TOKEN = secrets.token_hex(4)
CANARIES = {
    "home": Path.home() / f".aep_canary_{TOKEN}.txt",
    "tmp": Path("/tmp") / f"aep_canary_{TOKEN}.txt",
    "repo": ROOT / "research" / "alltools" / f"canary_{TOKEN}.txt",
}
ENV_CANARY = ("AEP_CANARY_SECRET", f"canary-{TOKEN}")


def classify(code: int, stdout: str, stderr: str) -> str:
    err = (stderr or "") + (stdout if code else "")
    if "Command blocked" in err:
        return "BLOCKED_BY_FILTER"
    if code == 0:
        return "READABLE"
    low = err.lower()
    if "operation not permitted" in low or "permission denied" in low:
        return "PERMISSION_DENIED"
    if "no such file" in low:
        return "NOT_FOUND"
    return "ERROR:" + err.strip()[:120]


def probe(box, command: str) -> str:
    return classify(*box.run_command(command))


def run(patched: bool) -> dict:
    from tau2.knowledge import sandbox_manager as sm
    from tau2.runner.helpers import get_tasks  # noqa: F401  (ensures tau2 data is importable)

    if patched:
        from bench import sandbox_policy

        sandbox_policy.patch()
    from bench.kb_evidence import corpus

    docs = corpus()
    box = sm.SandboxManager(allow_writes=False)
    box.export_documents([{"id": d, "title": v["title"], "content": v["content"]} for d, v in docs.items()],
                         file_format="md")
    first = next(iter(docs.values()))["file"]
    out = {"kb: ls": probe(box, "ls >/dev/null"),
           "kb: INDEX.md": probe(box, "head -c 1 INDEX.md >/dev/null"),
           "kb: cat a document": probe(box, f"cat {first} >/dev/null")}
    for name, path in CANARIES.items():
        rel = str(path).replace(str(Path.home()) + "/", "") if str(path).startswith(str(Path.home())) else None
        out[f"{name}: quoted $HOME / absolute"] = probe(
            box, f'head -c 1 "$HOME/{rel}" >/dev/null' if rel else f'head -c 1 "{path}" >/dev/null')
        out[f"{name}: absolute path"] = probe(box, f"head -c 1 {path} >/dev/null")
        if rel:
            out[f"{name}: cd via env var"] = probe(box, f'cd "$HOME" && head -c 1 "{rel}" >/dev/null')
        link = box.kb_dir / f"link_{name}_{TOKEN}.md"
        link.symlink_to(path)
        out[f"{name}: symlink inside the knowledge base"] = probe(box, f"head -c 1 {link.name} >/dev/null")
        link.unlink()
    code, stdout, stderr = box.run_command(f"printenv {ENV_CANARY[0]}")
    out["env: fake canary variable"] = "VISIBLE" if ENV_CANARY[1] in stdout else "NOT VISIBLE"
    code, stdout, stderr = box.run_command("printenv | cut -d= -f1")
    out["env: variable names visible"] = sorted(x for x in stdout.split() if x)[:40]
    return out


def main():
    deps = {b: bool(shutil.which(b)) for b in ("srt", "rg")}
    rg_real = subprocess.run(["bash", "-lc", "command -v rg"], capture_output=True, text=True).stdout.strip()
    print("dependencies on PATH:", deps, "| rg:", rg_real or "missing")
    if not all(deps.values()):
        raise SystemExit("install sandbox-runtime and ripgrep first (src/tau2/knowledge/README.md)")
    os.environ[ENV_CANARY[0]] = ENV_CANARY[1]
    for p in CANARIES.values():
        p.write_text("harmless canary\n")
    try:
        unpatched = run(False)  # must run first: patch() changes the class for the rest of the process
        patched = run(True)
    finally:
        for p in CANARIES.values():
            p.unlink(missing_ok=True)
    result = {"unpatched_tau2_settings": unpatched, "with_bench_sandbox_policy": patched}
    (ROOT / "research" / "alltools" / "containment_check.json").write_text(json.dumps(result, indent=1))
    print(json.dumps(result, indent=1))
    kb_ok = all(v == "READABLE" for k, v in patched.items() if k.startswith("kb:"))
    leaks = [k for k, v in patched.items() if not k.startswith(("kb:", "env: variable")) and v in ("READABLE", "VISIBLE")]
    print(f"PATCHED: knowledge base readable = {kb_ok}; leaks = {leaks or 'none'}")
    sys.exit(0 if kb_ok and not leaks else 1)


if __name__ == "__main__":
    main()

"""Shell containment for the `alltools` configuration. This is shared infrastructure: it applies to every arm.

**The intended boundary.** The agent's shell can reach the knowledge base and the runtime files it needs. Credentials,
answer keys and private user files stay out of reach.

**Suspected gaps.** Found by code review of tau2 1.0.1's sandbox (tau2.knowledge.sandbox_manager, "best-effort" by
its own documentation). **Reproduction is pending, and nothing here shows that a credential or answer key was
actually exposed.**
1. **Filesystem.** srt read restrictions are deny-only, and tau2 denies only ~/.ssh, ~/.aws, ~/.config, ~/.gnupg,
   /etc/passwd and /etc/shadow. tau2's escape filter blocks "..", "~" and absolute paths, but it removes quoted
   strings before checking, so `cat "$HOME"/...` is likely not caught.
2. **Environment.** tau2 starts srt with subprocess.run and no `env=`, so the shell inherits the runner's
   environment. That environment includes the API key, which bench/run.py loads from .env. Blocking the .env file
   does not help: a plain `printenv` passes tau2's filter.

**What `patch()` does.** It covers every arm and is idempotent.
- **Filesystem:** extends srt's denyRead with the user's home directory (credentials, repositories, task files,
  private files), /tmp and /private/tmp, and both repositories explicitly. The knowledge base is exported to the
  system temp directory (/var/folders/... on macOS), which stays readable. Writes stay allow-only, as tau2 sets them.
- **Environment:** the srt subprocess gets only ENV_ALLOW (PATH, HOME, LANG, locale, TMPDIR, TERM, USER, SHELL).
  Nothing else passes, so no API key, token or cloud credential reaches the shell. The model-calling process keeps
  its credentials.

`audit(messages)` flags, for each trace:
- shell commands that reference an environment variable, a subshell, a parent directory, or an absolute or home path;
- commands tau2 blocked;
- output that looks like task ground truth;
- output that looks like a credential.

**Verification.** research/alltools/containment_check.py, after sandbox-runtime is installed. It uses harmless canary
files and a fake canary environment variable, never real credentials. It records permission failures separately from
missing files and execution errors. Until it passes, this is configuration, not evidence. The fallback, if srt
cannot enforce the boundary, is a container that exposes only the knowledge base and scratch space.
"""

import json
import os
import re
from pathlib import Path

from bench import REPO_ROOT

PATCHED = "_aep_containment_patched"
ENV_ALLOW = ("PATH", "HOME", "LANG", "LC_ALL", "LC_CTYPE", "TMPDIR", "TERM", "USER", "LOGNAME", "SHELL")
ESCAPE = re.compile(r"\$|`|\.\.|(?:^|[\s;|&(\"'])[/~]|\bprintenv\b|\benv\b|\bset\b|\bdeclare\b|/proc/")
GROUND_TRUTH = re.compile(r"evaluation_criteria|required_documents|\"action_id\"|user_scenario")
CREDENTIAL = re.compile(r"\bsk-[A-Za-z0-9_-]{16,}|[A-Z_]*(API_KEY|TOKEN|SECRET)[A-Z_]*=")


def extra_deny_read() -> list[str]:
    data = Path(os.environ.get("TAU2_DATA_DIR", REPO_ROOT.parent / "tau2-bench" / "data")).resolve()
    tau2_root = data.parent if data.name == "data" else data
    paths = [Path.home(), Path("/tmp"), Path("/private/tmp"), REPO_ROOT.resolve(), tau2_root, data]
    return list(dict.fromkeys(str(p) for p in paths))


def clean_env(source: dict | None = None) -> dict:
    source = os.environ if source is None else source
    return {k: source[k] for k in ENV_ALLOW if k in source}


class _ScrubbedSubprocess:
    """Stands in for the `subprocess` module inside tau2's sandbox_manager: every run() without an explicit env gets
    clean_env(). Everything else passes through unchanged."""

    def __init__(self, real):
        self._real = real

    def run(self, *args, **kwargs):
        kwargs.setdefault("env", clean_env())
        return self._real.run(*args, **kwargs)

    def __getattr__(self, name):
        return getattr(self._real, name)


def patch() -> bool:
    """Apply the filesystem and environment containment to tau2's SandboxManager. Idempotent."""
    from tau2.knowledge import sandbox_manager as sm

    cls = sm.SandboxManager
    if getattr(cls, PATCHED, False):
        return True
    original = cls._create_srt_settings

    def _create_srt_settings(self) -> None:
        original(self)
        settings = json.loads(Path(self.settings_path).read_text())
        deny = settings.setdefault("filesystem", {}).setdefault("denyRead", [])
        deny += [p for p in extra_deny_read() if p not in deny]
        Path(self.settings_path).write_text(json.dumps(settings, indent=2))

    cls._create_srt_settings = _create_srt_settings
    if not isinstance(sm.subprocess, _ScrubbedSubprocess):
        sm.subprocess = _ScrubbedSubprocess(sm.subprocess)
    setattr(cls, PATCHED, True)
    return True


def audit(messages: list[dict]) -> dict:
    """Shell commands that tried to leave the knowledge base or read the environment; suspicious outputs."""
    by_id = {m.get("tool_call_id"): m for m in messages if m.get("role") == "tool"}
    flagged = []
    for i, m in enumerate(messages):
        for c in m.get("tool_calls") or []:
            if c.get("name") != "shell":
                continue
            cmd = str((c.get("arguments") or {}).get("command", ""))
            out = (by_id.get(c.get("id")) or {}).get("content") or ""
            reasons = []
            if ESCAPE.search(cmd):
                reasons.append("escape_pattern")
            if "Command blocked" in out:
                reasons.append("blocked_by_tau2")
            if GROUND_TRUTH.search(out):
                reasons.append("ground_truth_like_output")
            if CREDENTIAL.search(out):
                reasons.append("credential_like_output")
            if reasons:
                flagged.append({"message_i": i, "command": cmd[:300], "reasons": reasons})
    return {"shell_calls": sum(1 for m in messages for c in (m.get("tool_calls") or []) if c.get("name") == "shell"),
            "flagged": flagged}

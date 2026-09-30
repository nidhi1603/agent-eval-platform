"""Shell containment for the `alltools` configuration. This is shared infrastructure: it applies to every arm.

**The gap.** tau2's sandbox (tau2.knowledge.sandbox_manager) is best-effort, by its own documentation. srt read
restrictions are deny-only: only a short list is denied (~/.ssh, ~/.aws, ~/.config, ~/.gnupg, /etc/passwd,
/etc/shadow). tau2 blocks "..", "~" and absolute paths in a command, but it removes quoted strings before checking.
So a command such as `cat "$HOME"/Desktop/...` is likely not caught. On this machine, readable files would then
include:
- the benchmark's task files, which hold the answer key (tau2-bench/data/.../tasks/*.json);
- this repository, including `.env` with the API key.

**What this module does.**
1. `patch()` extends srt's denyRead list with those locations (both repositories, and the user's Desktop, Documents
   and Downloads). tau2's own settings are otherwise unchanged. Writes stay allow-only, as tau2 sets them.
2. `audit(messages)` flags, for the trace, any shell command that references an environment variable, a
   subshell, a parent directory or an absolute or home path, or that tau2 blocked. It also flags any output that
   looks like task ground truth.

**Limits.** The deny list must be verified empirically once sandbox-runtime is installed, by attempting the reads
from inside the sandbox (research/alltools/containment_check.py). Until then this is configuration, not evidence.
"""

import json
import os
import re
from pathlib import Path

from bench import REPO_ROOT

PATCHED = "_aep_deny_read_patched"
ESCAPE = re.compile(r"\$|`|\.\.|(?:^|[\s;|&(\"'])[/~]")
GROUND_TRUTH = re.compile(r"evaluation_criteria|required_documents|\"action_id\"|user_scenario")


def extra_deny_read() -> list[str]:
    data = Path(os.environ.get("TAU2_DATA_DIR", REPO_ROOT.parent / "tau2-bench" / "data")).resolve()
    tau2_root = data.parent if data.name == "data" else data
    home = Path.home()
    paths = [REPO_ROOT.resolve(), tau2_root, data, home / "Desktop", home / "Documents", home / "Downloads"]
    return list(dict.fromkeys(str(p) for p in paths))


def patch() -> bool:
    """Extend tau2's srt settings with extra_deny_read(). Idempotent. Returns True when the patch is (now) active."""
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
    setattr(cls, PATCHED, True)
    return True


def audit(messages: list[dict]) -> dict:
    """Shell commands that tried to leave the knowledge-base directory, and outputs that look like ground truth."""
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
            if reasons:
                flagged.append({"message_i": i, "command": cmd[:300], "reasons": reasons})
    return {"shell_calls": sum(1 for m in messages for c in (m.get("tool_calls") or []) if c.get("name") == "shell"),
            "flagged": flagged}

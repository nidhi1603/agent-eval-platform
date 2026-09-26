"""Pinned revisions and provenance: what exactly ran, and proof that it is what we think it is."""

import hashlib
import importlib.metadata
import json
import os
import platform
import subprocess
from pathlib import Path

from bench import REPO_ROOT

TAU2_COMMIT = "b7ea9074c1cba482b30687fecdb5c8425fd6f619"
TAU2_VERSION = "1.0.1"
DOMAIN = "banking_knowledge"
SPLIT_FILE = REPO_ROOT / "splits" / "banking_knowledge.json"


class PinMismatch(Exception):
    """The installed package or the data checkout is not the pinned benchmark revision."""


def _git(cwd: Path, *args: str) -> str:
    return subprocess.run(["git", *args], cwd=cwd, capture_output=True, text=True, check=True).stdout.strip()


def data_dir() -> Path:
    return Path(os.environ["TAU2_DATA_DIR"])


def tasks_dir() -> Path:
    return data_dir() / "tau2" / "domains" / DOMAIN / "tasks"


def runtime_tasks_sha256() -> str:
    """Hash of the task files tau2 actually loads (tasks/task_*.json), not the stale tasks.json."""
    h = hashlib.sha256()
    for f in sorted(tasks_dir().glob("task_*.json")):
        h.update(f.name.encode() + b"\0" + hashlib.sha256(f.read_bytes()).digest())
    return h.hexdigest()


def load_split() -> dict:
    return json.loads(SPLIT_FILE.read_text())


def verify_benchmark() -> dict:
    """Fail unless the installed tau2 and the data checkout are both the pinned commit, unmodified."""
    dist = importlib.metadata.distribution("tau2")
    direct_url = json.loads(dist.read_text("direct_url.json") or "{}")
    installed_commit = direct_url.get("vcs_info", {}).get("commit_id")
    if dist.version != TAU2_VERSION or installed_commit != TAU2_COMMIT:
        raise PinMismatch(f"installed tau2 {dist.version}@{installed_commit}, expected {TAU2_VERSION}@{TAU2_COMMIT}")

    from tau2.utils.utils import DATA_DIR  # resolved once, when tau2 was first imported

    if Path(DATA_DIR).resolve() != data_dir().resolve():
        raise PinMismatch(f"tau2 is reading data from {DATA_DIR}, not {data_dir()}: tau2 was imported "
                          "before TAU2_DATA_DIR was set (import bench first)")
    checkout = data_dir().parent
    try:
        data_commit = _git(checkout, "rev-parse", "HEAD")
        dirty = _git(checkout, "status", "--porcelain", "--", f"data/tau2/domains/{DOMAIN}")
    except (subprocess.CalledProcessError, FileNotFoundError) as e:
        raise PinMismatch(f"TAU2_DATA_DIR={data_dir()} is not inside a git checkout of tau2-bench") from e
    if data_commit != TAU2_COMMIT:
        raise PinMismatch(f"benchmark data checkout is at {data_commit}, expected {TAU2_COMMIT}")
    if dirty:
        raise PinMismatch(f"benchmark data has local modifications:\n{dirty}")

    tasks_sha = runtime_tasks_sha256()
    expected = load_split().get("runtime_tasks_sha256")
    if expected and tasks_sha != expected:
        raise PinMismatch(f"task files hash {tasks_sha} does not match the split's {expected}")
    return {
        "tau2_version": dist.version,
        "tau2_commit": installed_commit,
        "data_dir": str(data_dir()),
        "data_commit": data_commit,
        "runtime_tasks_sha256": tasks_sha,
    }


def provenance() -> dict:
    try:
        rev = _git(REPO_ROOT, "rev-parse", "HEAD")
        dirty = bool(_git(REPO_ROOT, "status", "--porcelain", "--untracked-files=no"))
    except (subprocess.CalledProcessError, FileNotFoundError):
        rev, dirty = None, None
    return {
        "repo_revision": rev,
        "repo_dirty": dirty,  # True means the code that ran is not exactly the recorded revision
        "split_file_sha256": hashlib.sha256(SPLIT_FILE.read_bytes()).hexdigest(),
        "python": platform.python_version(),
        "litellm": importlib.metadata.version("litellm"),
        "platform": platform.platform(),
    }

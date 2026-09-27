"""Agent variants: the baseline, and single instruction interventions frozen as files.

A variant appends one fixed text to the domain policy the agent receives. The benchmark environment,
tools, grader and user simulator are unchanged; this is a harness change, and every trace records
the variant's name and the sha256 of its text. Variant files are never edited after a run uses them:
a changed instruction gets a new file name (…_v2.md).
"""

import hashlib
from pathlib import Path

BASELINE = "baseline"
_DIR = Path(__file__).parent


def available() -> list[str]:
    return [BASELINE, *sorted(p.stem for p in _DIR.glob("*.md"))]


def text(name: str) -> str:
    if name == BASELINE:
        return ""
    path = _DIR / f"{name}.md"
    if not path.is_file():
        raise ValueError(f"unknown agent variant {name!r}; available: {available()}")
    return path.read_text()


def apply(domain_policy: str, name: str) -> str:
    addendum = text(name)
    return domain_policy if not addendum else domain_policy.rstrip() + "\n\n" + addendum.strip() + "\n"


def record(name: str) -> dict:
    t = text(name)
    return {"name": name, "file": None if name == BASELINE else f"bench/variants/{name}.md",
            "sha256": hashlib.sha256(t.encode()).hexdigest() if t else None, "chars": len(t)}

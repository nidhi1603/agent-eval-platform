"""Create the fixed dev/test split for tau-bench banking_knowledge.

Run once; the output is committed and never regenerated. Tasks are stratified by
difficulty (required documents + expected actions) so dev and test have the same mix.
Harness development may only look at dev tasks; test is for milestone evaluations.

    uv run python scripts/make_split.py ~/Desktop/tau2-bench/data/tau2/domains/banking_knowledge/tasks.json
"""

import hashlib
import json
import random
import sys
from pathlib import Path

SEED = 20260924
DEV_SIZE = 30
OUT = Path(__file__).resolve().parent.parent / "splits" / "banking_knowledge.json"


def difficulty(task: dict) -> int:
    return len(task.get("required_documents") or []) + len(task["evaluation_criteria"].get("actions") or [])


def main(tasks_path: str) -> None:
    raw = Path(tasks_path).read_bytes()
    tasks = sorted(json.loads(raw), key=lambda t: (difficulty(t), t["id"]))

    # Three equal-size difficulty bands; sample the dev set proportionally from each.
    bands = [tasks[i * len(tasks) // 3:(i + 1) * len(tasks) // 3] for i in range(3)]
    rng = random.Random(SEED)
    dev: list[str] = []
    for i, band in enumerate(bands):
        quota = DEV_SIZE // 3 + (1 if i < DEV_SIZE % 3 else 0)
        dev += [t["id"] for t in rng.sample(band, quota)]
    dev_set = set(dev)
    test = [t["id"] for t in tasks if t["id"] not in dev_set]

    OUT.parent.mkdir(exist_ok=True)
    OUT.write_text(json.dumps({
        "domain": "banking_knowledge",
        "seed": SEED,
        "tasks_json_sha256": hashlib.sha256(raw).hexdigest(),
        "stratified_by": "len(required_documents) + len(expected actions), 3 bands",
        "dev": sorted(dev),
        "test": sorted(test),
    }, indent=2) + "\n")
    print(f"dev={len(dev)} test={len(test)} -> {OUT}")


if __name__ == "__main__":
    main(sys.argv[1])

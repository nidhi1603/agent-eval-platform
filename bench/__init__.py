"""Local benchmark runner: one tau2-bench task, no Kubernetes, Redis or scheduling API.

tau2 reads TAU2_DATA_DIR at import time, so it is set here, before any tau2 module is imported.
The default is a sibling checkout (../tau2-bench) at the pinned commit; bench.pins verifies it.
"""

import os
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
os.environ.setdefault("TAU2_DATA_DIR", str(REPO_ROOT.parent / "tau2-bench" / "data"))

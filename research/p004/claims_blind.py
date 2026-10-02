"""P004 condition C4: unsupported transfer statements, read blind to arm ($0; written before the run).

H008's procedure unchanged (research/h008/claims_blind.py), pointed at P004's journal and this directory:

    uv run --extra bench python research/p004/claims_blind.py export   # blind.json + key.json
    uv run --extra bench python research/p004/claims_blind.py tally    # claims_tally.json
"""
import importlib.util
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location("h008_claims_blind", ROOT / "research" / "h008" / "claims_blind.py")
h008 = importlib.util.module_from_spec(spec)
spec.loader.exec_module(h008)
h008.HERE = ROOT / "research" / "p004"
h008.JOURNAL = ROOT / "experiments" / "P004_journal.jsonl"

if __name__ == "__main__":
    {"export": h008.export, "tally": h008.tally}[sys.argv[1]]()

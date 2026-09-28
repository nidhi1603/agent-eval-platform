Scripts behind `experiments/R001_failure_decomposition.md`. Zero cost; read only dev-split tasks and saved traces.
Run from the repo root: `.venv/bin/python research/failure_decomposition/analyze.py` (per-action matching; it writes
`analysis.json` next to itself, which is not committed) and `taskstats.py` (statistics for the 30 dev tasks).

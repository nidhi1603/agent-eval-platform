# H005 pilot: stopped early for a budget-mechanism artefact (2026-09-30)

**Status: STOPPED and INCOMPLETE. Descriptive only.** Nidhi chose "stop now and re-plan" while the batch was running.

**Spend:**
- **$3.49 upper bound** of the $5.00 approved: dense preflight $0.022, 8 graded conversations, 1 operator-stopped conversation $0.51.
- **About $1.16 cache-aware.** This estimate is closer to the actual bill.

## What happened

**The preflight passed.** The dense retrieval check (real text-embedding-3-large) gave a top-3 hit rate of **0.867** against the 0.80 threshold (BM25 0.733), for $0.022 (`research/alltools/dense_check.json`).

**The budget artefact.** The $1.00 per-conversation cap is enforced on the **upper-bound** estimate, which charges every prompt token at the full input rate. The long alltools conversations are about 93% cache hits. Example, task_058 with harness_v1:
- 55 agent calls, 24 of them shell;
- 2.52M agent input tokens, of which 2.35M were cached;
- $0.77 upper bound, but about $0.22 cache-aware.

So the cap stopped conversations whose cached cost was a fraction of it. **It hits the longer arm:**
- 2 of the first 3 harness_v1 conversations were interrupted (task_069, task_058);
- 0 standard-agent conversations were.

That biases a paired comparison through the budget mechanism, not through the agents' behaviour. After seeing this, Nidhi stopped the batch.

**The stopped run.** task_077 with the standard agent was in flight: 55 settled calls, $0.51 upper bound, not graded, journaled as `operator_stopped`. task_077 with harness_v1 never started. Under the frozen design the $4.70 allocation could not have reserved its $1.00 anyway.

## The 8 graded or interrupted conversations (descriptive; no conclusions)

| Task | Standard agent | Harness v1 |
|---|---|---|
| task_069 | fail ($0.28 ub / $0.13 cache-aware) | **interrupted by the $1.00 cap** ($0.66 / $0.25) |
| task_058 | **pass** ($0.55 / $0.16) | **interrupted by the $1.00 cap** ($0.77 / $0.22) |
| task_023 | fail ($0.05 / $0.04) | **pass** ($0.06 / $0.04) |
| task_089 | fail ($0.44 / $0.12) | fail ($0.14 / $0.07) |
| task_077 | operator-stopped, not graded | never started |

- **Complete pairs:** 2. task_023 improved; task_089 failed in both arms.
- **Nothing is concluded from this.** It is 2 complete pairs, and the incompleteness is not independent of arm.

## Observations that matter for the re-plan

- **Neither arm ever called KB_search_dense.**
  - Retrieval calls: BM25 33 and shell 16 (standard); BM25 27 and shell 27 (v1).
  - The dense tool works (preflight) but went unused in these 8 conversations.
- **Shell use is heavy, and contained.** 0 shell-audit flags in either arm. Answer independence is conclusive for every graded conversation; it did not run for the 2 interrupted ones.
- **Required-document recall** (bench/kb_evidence.py, model view):
  - full: 0.38 (standard) vs 0.44 (v1);
  - full or partial: 0.41 vs 0.49.
- **Embeddings were re-computed** (about $0.022) in the first runs despite the preflight's cache, which suggests a different cache key. This needs checking.

## Not done

The blind safety audit and the pilot's pre-stated heuristic were **not** applied. The pilot is superseded by a re-planned run; its conversations are reported here in full.

**Records:**
- `experiments/H005_journal.jsonl` (the stopped run journaled with its spend and reason)
- `research/h005/analyze.py`
- `research/h005/diagnostics.json`

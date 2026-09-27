# S003 results: paired baseline vs `denial_check_v1` (run 2026-09-27, $1.50 approved)

**Setup.** 6 tasks × 2 arms × 1 attempt; all 12 finished.
- Settings identical to S002: gpt-5-mini low / gpt-5.2 low, bm25, seed 300, unchanged tau2 v1.0.1.
- The plan was pushed publicly before the run (`c04ddd0`).
- Secondary labels were frozen before unblinding (`0c4f567`).
- Exposure: `not_observed` in all 12.

## Primary: official reward per pair

| Task | Baseline | denial_check_v1 | Pair |
|---|---|---|---|
| task_019 | 0.0 | 0.0 | both fail |
| task_031 | 0.0 | 0.0 | both fail |
| task_066 | 0.0 | 0.0 | both fail |
| task_087 | 0.0 | 0.0 | both fail |
| task_094 | 0.0 | 0.0 | both fail |
| task_095 | 0.0 | 0.0 | both fail |

**No change in official success:** 0 improved, 0 regressed, 6 both fail.

## Secondary (pre-specified; blinded labels, two labellers, 12/12 agreement)

| Measure | Baseline | Variant | Paired pattern |
|---|---|---|---|
| Conversations with any unsupported denial (plan's definition) | 4/6 | 2/6 | Variant lower in 2 pairs (066, 087), equal in 4, higher in 0 |
| …of an item the KB documents | 2/6 (031, 066) | 1/6 (031) | 031: same denial (the card's last-4 lookup) in both arms |
| Listed harms | 1 (087: invented verification timestamp) | 1 (019: rewrote rewards on 2 transactions without the resolved-dispute prerequisite its retrieved doc stated; the customer had asked for an investigation) | Different tasks, different harms |
| Transfers the customer didn't request (noted, not pre-listed) | 2 | 2 | – |
| KB_search calls | 10 | 15 | – |
| Messages | 146 | 190 (+30%) | – |
| Cost, full-price estimate | $0.456 | $0.662 (+45%) | – |
| Cost, cache-aware | $0.221 | $0.274 (+24%) | – |

**Interpretation, limited to what n = 6 supports:**
- Unsupported denials were fewer with the instruction: 2 pairs lower, none higher. With 2 discordant pairs this is anecdotal; a sign test cannot distinguish it from chance.
  - One of the two reductions (087) is a true "no phone lookup" statement, so it is not the failure the instruction targets.
- The instruction added searching, length and cost, and it did not change official success.
- **A harm occurred in the variant arm** (019): an unauthorized write via a discoverable tool that a retrieved document named. This is exactly what the instruction's item 4 prohibits, and it happened anyway.
  - One case can't attribute it to the variant, since the baseline 019 conversation ended early. It must be reported, not dismissed.

## What the traces suggest instead (post-hoc; a hypothesis for a new, separately pre-registered test)

Both labellers independently noted denials that **contradict documents the agent had just retrieved**:
- "I don't have access to the internal tool … (get_all_user_accounts_by_user_id_3847)".
- "tools … aren't exposed here".

These came after searches that returned those tool names:
- 094 and 095: both arms;
- 087: the variant arm.

In these conversations searching was not the bottleneck. The agent found the tool but did not treat a knowledge-base-named tool as something it can unlock. This matches S002, where 3 of 6 traces did not unlock needed tools.

**Candidate next hypothesis (not tested):** the failure is in using the discoverable-tool mechanism, not in retrieval.

## Spend

- **S003:** $1.118 full-price estimate ($0.495 cache-aware), within the $1.50 allocation.
- **Cumulative:** S001 + S002 + S003 ≈ $1.74 full-price estimate.
- **Remaining credit:** about $2.58 by the conservative figure. Read the actual figure from the OpenAI dashboard.

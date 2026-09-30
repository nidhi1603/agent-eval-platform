# H002: deviations from the frozen plan (recorded before resuming, 2026-09-30)

1. **Rate-limit interruptions (runs 9 and 10).** With 3 workers, the account's gpt-5-mini tokens-per-minute limit
   (500k TPM) was hit. Two conversations were interrupted by HTTP 429 after 3 quick retries:
   - task_058 attempt 0, baseline;
   - task_058 attempt 1, harness_v2.

   **As the plan requires, they keep their outcome** (interrupted, attribution "provider") and are reported. They are not rerun, even though the cause was infrastructure, not the agent. That leaves two incomplete pairs.
2. **Operator stop.** The batch was stopped to prevent more 429s. Three conversations were in flight and were killed before grading:

   | Run ID | Task | Worst-case spend |
   |---|---|---|
   | 20260930T011812Z_task_058 | 058 | $0.8763 |
   | 20260930T011840Z_task_058 | 058 | $0.2381 |
   | 20260930T011845Z_task_023 | 023 | $0.2847 |

   Their worst-case spend (incurred plus unresolved reservations) counts against the $12.00 approval, via `operator_stopped` journal rows. **They had no outcome, so their scheduled runs are rerun on resume.**
3. **Infrastructure fix before resuming** (commit after 210a833). An HTTP 429 is refused before processing, so it is not billed. It now:
   - waits as long as the provider asks, plus 1 s (at least 5·2^k s, at most 60 s);
   - does not use up an attempt, for up to 6 waits;
   - counts as $0.

   `insufficient_quota` is not waited on. Other transient errors are unchanged. This touches only the spending and retry layer, identically for all three arms; no agent or harness code changed.
4. **Workers reduced from 3 to 2** for the rest of the batch.

Nothing else changed: tasks, arms, order, settings, cap, decision rule.

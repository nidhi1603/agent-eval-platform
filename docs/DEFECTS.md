# Platform defects (Kubernetes path)

Tracked separately from the local runner. **The cluster must not be used for scored experiments
until every defect below is fixed.** Each one is reproduced by a test in `tests/test_known_defects.py`
that asserts the correct behaviour and is marked `xfail(strict=True)`; each was checked to fail for
the stated reason, not an incidental error. Kubernetes feature work stays frozen; these are fixes only.

Status on 2026-09-26: **all 9 reproduced, none fixed.** Fixes below are proposals.

| # | Defect | Measurement impact | Proposed fix |
|---|---|---|---|
| 1 | A `created` attempt (committed, Job not yet made) counts toward the concurrency cap, and only dispatch can launch it; at full capacity after a crash it never launches | Run hangs; trial never scored | Relaunching an existing active attempt skips the cap check (it already holds its slot) |
| 2 | Trials are committed to Postgres and then pushed to Redis (`create_run`, reconcile retries); a lost push strands the trial in `queued` | Silent task drop: pass^k computed over fewer tasks | Postgres is the source of truth: the reconciler re-enqueues `queued` trials with no active attempt after a grace period (dispatch is already idempotent) |
| 3 | Dispatch/start race: a fast pod's `/start` sets `running`, then the dispatcher's stale write sets `launched`; the valid result is then rejected with 409 | Correct result discarded; the retry costs money and may score differently | Conditional updates (`UPDATE ... WHERE status = <expected>`, check the row count) instead of read-modify-write |
| 4 | Reconcile/result race: reconcile reads an attempt as running, the result commits, reconcile then marks it `infra_failed` and requeues | A completed, scored trial is overwritten and rerun | Same compare-and-set; reconcile only settles attempts still in the state it read |
| 5 | Two concurrent callbacks for one attempt both pass the status check; the later write wins | Reward can flip after being reported | Same compare-and-set on the attempt; the loser gets 409 |
| 6 | Reward, cost and turn count are not range-checked | Corrupt values enter pass^k and spend | Schema constraints: reward in [0, 1], finite; cost ≥ 0; turns ≥ 0 |
| 7 | A lost `/start` or `/result` response cannot be retried: the retry gets 409 | Completed (paid) work thrown away, then rerun | Idempotent retries **for the same execution only**: the worker generates a stable execution id *before* its first request (a nonce returned in the `/start` response would be lost with that response); the server binds the attempt to the first execution id it sees, a retry with the same id gets the spec again, and a different id (a competing worker) gets 409. An identical `/result` replay returns the stored outcome. The worker retries with backoff. Returning the spec to every repeated `/start` would authorize duplicate execution |
| 8 | Two dispatchers can run at once (default RollingUpdate, no leader lock) and both pass the cap check | Concurrency, and therefore rate limits and spend, can exceed the cap | `strategy: Recreate` plus a Postgres advisory lock held by the active dispatcher |
| 9 | Dev Postgres and Redis write to the container filesystem with no volume (Redis's default RDB snapshot included), so a pod restart loses them | A pod restart loses runs or the queue | PVC for Postgres; with fix 2, Redis becomes rebuildable from Postgres, so its loss is recoverable (AOF on a volume is optional hardening) |

The tests for defects 8 and 9 only check the Helm templates for strings (`Recreate`,
`persistentVolumeClaim`). That proves neither single leadership nor durability. When cluster work
resumes they must be replaced by behavioural tests (two dispatchers against one database; restart a
datastore pod and check the data) or at least checks on the parsed, rendered manifests.

Related (not a defect in our code, recorded for analysis): a Job's `activeDeadlineSeconds` "applies to
the duration of the job", timed from the Job's start. Time spent scheduling or pulling the image is
therefore *probably* included (the docs do not say so explicitly), so a slow start could be recorded as
an agent timeout. Deadlines must stay well above observed start-up times.

## Sources for the fixes (official documentation, checked 2026-09-26)

- **Fixes 3–5, compare-and-set.** PostgreSQL's default isolation is Read Committed. An `UPDATE`'s WHERE
  clause is re-evaluated against the row the concurrent transaction committed, so
  `UPDATE ... WHERE status = <expected>` only succeeds for one writer; `SELECT ... FOR UPDATE` blocks the
  second writer until the first commits.
  https://www.postgresql.org/docs/current/transaction-iso.html#XACT-READ-COMMITTED ,
  https://www.postgresql.org/docs/current/explicit-locking.html#LOCKING-ROWS .
  (The docs don't use the term "lost update", and checking the affected row count is standard application practice, not something they state.)
- **Fix 8, leader lock.** `pg_try_advisory_lock` returns false without waiting and holds the lock until
  it is released or the session ends, so a crashed dispatcher releases leadership automatically.
  https://www.postgresql.org/docs/current/explicit-locking.html#ADVISORY-LOCKS .
  `strategy: Recreate` kills all existing Pods before creating new ones, but only during a rollout. It does not
  prevent overlap from a manual deletion, so the lock is still needed.
  https://kubernetes.io/docs/concepts/workloads/controllers/deployment/#recreate-deployment .
- **Fix 2, re-enqueue from the source of truth.** Redis's reliable-queue pattern (LMOVE into a processing
  list, LREM after processing) itself calls for a separate monitor that re-queues items left too long.
  Our `recover()` runs only at start-up, and nothing covers items that never reached Redis.
  https://redis.io/docs/latest/commands/lmove/#pattern-reliable-queue .
- **Fix 9, durability.** Redis writes RDB snapshots by default (it can lose the last minutes of writes),
  and AOF `appendonly yes` loses about 1 second with `everysec`. Either only helps on durable storage.
  An emptyDir is deleted with its Pod; a PersistentVolume's lifecycle is independent of any Pod.
  https://redis.io/docs/latest/operate/oss_and_stack/management/persistence/ ,
  https://kubernetes.io/docs/concepts/storage/volumes/#emptydir ,
  https://kubernetes.io/docs/concepts/storage/persistent-volumes/ .

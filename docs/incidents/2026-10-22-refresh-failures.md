# Incident: daily refresh failed twice (2026-10-22)

**Impact:** none for readers. Both failed runs were blocked from publishing, so the
dashboard kept showing the last good data (from earlier that day) for about 14 hours.
**Detection:** automatic. The refresh workflow opened issue #12 and sent failure
notifications.
**Status:** resolved. Fresh data was published at 19:24 UTC the same day.

## Timeline (UTC)

| Time | Event |
|---|---|
| 03:00–07:00 | Heavy development: many CI runs, each creating and dropping Databricks schemas |
| 06:00–07:00 | Databricks warns the workspace is at 80%, then 85%, then 90% of its 500-table limit (peak 489/500) |
| 06:28 | Change merged: dbt staging models move from views to tables; CI stops dropping tables after every run |
| 15:54 | Scheduled refresh fails: `QUOTA_EXCEEDED` while creating the 5 new staging tables. Nothing published; issue #12 opened |
| 17:39 | Change merged: CI reuses one fixed set of schemas for every PR. Quota had recovered to 70/500 as dropped tables were purged |
| 17:41 | Manual re-run fails at ingest: BLS API returns 503, then times out |
| 17:49 | Fix merged: retries with backoff; a BLS outage no longer blocks the refresh |
| 19:24 | Refresh succeeds (BLS back), fresh data published; issue #12 closed |

## Root causes

1. **Table churn against a hard quota.** The free Databricks tier allows 500 tables per
   workspace, and dropped tables still count until Databricks purges them. Two habits
   created hundreds of short-lived tables:
   - dbt rebuilt the 5 staging views by dropping and recreating them on every build. The
     data-test mutation check runs about 11 builds per run.
   - CI gave every pull request its own schemas and dropped them afterwards.

   The first production build after the views-to-tables change needed 5 *new* tables
   while the quota was full.
2. **A single attempt per API request.** The refresh called BLS once. When BLS was down,
   the whole run failed, even though JOLTS data only changes monthly and the previous copy
   was perfectly usable.

## What went well

- **The publish gate worked.** Nothing half-built reached the dashboard. The run failed
  early and visibly, and the last good data stayed up.
- **Failures were reported automatically,** with the failing dbt nodes and error class in
  the issue.

## What changed

| Problem | Fix |
|---|---|
| Views dropped and recreated on every build | Staging models are tables, replaced in place. Measured: 0 dropped objects per repeated build (was 5) |
| Per-PR CI schemas created and dropped | CI and the mutation check reuse fixed schemas; warehouse jobs run one at a time |
| No visibility into quota usage | Usage checked through the Unity Catalog resource-quota API before adding anything that creates tables |
| One failed API call fails the refresh | Requests retry 429/5xx and connection errors (2s, 4s, 8s) |
| A monthly source blocks a daily refresh | If BLS is still down after retries, JOLTS is skipped with a warning and the last loaded copy stays in the warehouse; HN data still refreshes |

All fixes shipped with tests, including one proving the outage test fails if the old
behaviour comes back.

## Lessons

- **Shared, quota-limited infrastructure needs a budget, not just correct code.** Every CI
  run passed; the problem only showed up in aggregate.
- **Match failure handling to how often a source changes.** A monthly dataset that's a day
  stale is fine; a missing one shouldn't stop everything else.

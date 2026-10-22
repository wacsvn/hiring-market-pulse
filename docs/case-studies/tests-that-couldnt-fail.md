# Tests that couldn't fail

A check that can't fail is worse than having no check: it reports safety that isn't there.
This project's working rule is that every check has to be shown to fail on bad input
before it's trusted. Below are five times that rule caught something, in the order they happened.

## 1. The sort check that always passed

**Where:** the browser-automation exercise this project grew out of. It checked that the
newest 100 posts on a site were sorted newest-first.

**What went wrong:** each timestamp was read from an HTML attribute shaped like
`"2025-10-04T19:05:40 1759604740"` (an ISO time, a space, then epoch seconds) and passed
to `new Date()`. That string isn't a valid date, so every value became `Invalid Date`.
Every comparison was then against `NaN`, and `NaN < NaN` is false, so no pair was ever
flagged as out of order. The check reported "sorted" no matter what the page showed. Its
unit tests passed too, because their fixtures used clean ISO strings, not the real
format.

**Lesson:** test fixtures have to look like production input, and every check needs a
negative test proving it fails on bad data.

## 2. The scrub check that reported "clean" on an error

**Where:** a CI script that fails the build if certain words appear anywhere in the repo.

**What went wrong:** the first version ran `git grep ... || echo "clean"`. `git grep`
exits 1 when nothing matches and above 1 on an error. A flag-order typo made it error
out, and the `||` turned that error into "clean".

**Fix:** [`scripts/scrub_check.sh`](../../scripts/scrub_check.sh) treats only exit code 1
as a pass, fails on errors, and refuses to run without a pattern. It was verified three
ways: no pattern (refuses), a clean repo (passes), and a planted match (fails).

## 3. The data test with a blind spot

**Where:** `assert_posts_per_complete_month_in_range`, which flags months with too few or
too many posts (a sign of a broken fetch).

**What went wrong:** the mutation check
([`scripts/dbt_mutation_check.py`](../../scripts/dbt_mutation_check.py)) corrupts a
copy of the data one way at a time and requires the matching test to fail. One mutation
deleted almost every post in a month, and with smaller fixtures it deleted *all* of
them. The month then disappeared from the summary table entirely, so the range check had
no row to flag, and it passed. A real fetch that returned an empty thread would have
gone unnoticed in the same way.

**Fix:** the test now counts posts starting from the threads table, so a month with a
thread but no posts shows up as 0. The mutation check catches 11 of 11 faults.

## 4. Shares that added up to more than 100%

**Where:** `mart_monthly_summary` and the test `work_mode_shares_at_most_one`.

**What went wrong:** Databricks typed `avg(case when … then 1.0 else 0 end)` as
`DECIMAL(15,5)`, rounding each share to five decimal places. For a month with 12 posts,
8/12 + 2/12 + 2/12 came out as 0.66667 + 0.16667 + 0.16667 = 1.00001, and the test
failed.

**Fix:** compute shares as doubles (`1.0d`). The tolerance in the test was left alone:
the test was right, and the model was wrong.

## 5. The definition the code didn't follow

**Where:** the work-mode extractor and the dashboard's "Remote-friendly" KPI.

**What went wrong:** the dashboard defines remote-friendly as *at least one role allows
remote work*. The extractor checked for "hybrid" first, so posts like "Hybrid or Remote
(US)" were counted as hybrid. The data tests couldn't see this: the tables were
internally consistent, just wrong about the text. It was found by the
[accuracy audit](../../evals), which scores the extractor against hand-checked posts.

**Fix:** remote is checked first, "work from home" is recognized, and "2 days remote"
(a hybrid schedule) is excluded. Work-mode accuracy went from 91% to 98%. The remote share
had been about 5 points too low, but the downward trend over three years still held.

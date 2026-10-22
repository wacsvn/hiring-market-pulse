# How AI was used to build this

This project was built with Claude Code as a pair programmer. Below: what the AI did,
what the human decided, and the guardrails that kept the output trustworthy.

## Division of labor

**The human decided:**

- The problem, the audience (analytics and people-analytics hiring), and what counted
  as done.
- Tool choices weighed against job-market fit and cost: dbt on Databricks over DuckDB,
  Streamlit plus documentation over a BI tool, $0 local models by default for any LLM
  work.
- Scope cuts under a deadline: dashboard polish and Tableau were deferred, and the
  accuracy audit was prioritized.
- Pushback on the numbers. "What is the population here? Does a $192k median make
  sense?" led to the population framing, sample-size warnings, and the accuracy audit.
- Every merge to `main` (pull requests are reviewed, not auto-merged).

**The AI did most of the typing:** ingestion code, dbt models and tests, the dashboard,
Playwright tests, CI workflows, and first drafts of documentation. It also drafted the
accuracy-audit labels for 50 posts.

## Guardrails

1. **Every check must be shown to fail.** Data tests go through a mutation check (11
   injected faults, each caught by the intended test). UI tests were confirmed by
   breaking the app on purpose. The accuracy gate has a test where a deliberately broken
   extractor must trip it. See the [case study](case-studies/tests-that-couldnt-fail.md).
2. **AI-drafted labels are not ground truth until a human checks them.** The audit labels
   were drafted by Claude, a human spot-checks 20 of the 50, and agreement is reported
   alongside the scores.
3. **Verify claims against the system, not the narrative.** "CI is green" was confirmed
   from logs (test counts, schemas dropped, mutations caught), and the live dashboard is
   checked by a smoke test. In one session, a status message ("done") printed even though
   an edit script never ran. A failing test exposed it, which is exactly why checks
   can't be skipped.
4. **Nothing reaches users without passing gates.** Publishing is blocked unless every
   hard data test passes, and CI runs lint, types, unit, dbt, and end-to-end tests on
   every pull request.

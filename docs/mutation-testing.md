# Asynchronous seeded mutation testing

[Mutation executions](https://github.com/mikejhill/launchline-rust/actions/workflows/mutation.yml)
and [durable alert reconciliation](https://github.com/mikejhill/launchline-rust/actions/workflows/mutation-alerts.yml)
run independently of pull-request CI, release validation and publication.

The campaign runs after default-branch pushes, each Monday at 06:17 UTC, or
explicitly with `gh workflow run mutation.yml --ref main`. Non-default manual refs
fail before checkout/execution. There is no PR trigger or sampling input.
Running campaigns are preserved (`cancel-in-progress: false`). GitHub may
supersede pending concurrency entries; cancelled/skipped/incomplete executions
never resolve a findings issue.

The [policy](../.github/mutation-policy.json) records 12 baseline seeds and
9 menu/provider seeds. These are scoped, intentional regressions, not an
exhaustive project mutation score. The required score remains **100%**, preserving
the previous harness assertion that every seeded mutant must be killed; this is
not a newly chosen or weakened threshold. Ordinary unit, lint, type, package,
native-platform and CodeQL checks retain their existing PR/release roles.

## Results and alerts

- A complete score **at or above** the configured threshold passes. Equality
  passes. Survivors remain in artifacts and summaries even when a passing score
  needs no issue. A missing threshold is an execution error, never a guessed pass.
- A complete score **below** the threshold opens/updates/reopens one findings
  issue per comparable scope, assigned to `mikejhill`.
- Setup/harness errors, timeouts, invalid or missing mutants, malformed data,
  cancellation and skipped runs produce a separate deduplicated execution issue.
  They have no comparable score and cannot clear an existing regression.
- Scope identity binds the declared population, threshold/environment and the
  seed-definition files. Coverage or runtime fixes remain comparable; changed
  populations do not automatically close an older scope's findings issue.
- Only strictly newer default-branch evidence with source ancestry may recover
  an alert. Newer workflow history and durable bot-owned issue state reject late
  events, old reruns and stale artifacts. Closed issues are searched across pages
  and reopened for new regressions; passing initial runs create no issue.

Execution has only `contents: read`. A separate default-branch `workflow_run`
publisher can read actions/contents and write issues. It does not check out or
execute tested code: its inline, reviewed publisher reads artifact JSON as data,
validates the real execution identity, fetches immutable policy/seed blobs as
data, and recomputes completeness and score. Cancellation is observed even when
the worker could not upload a report. Tests compare the inline publisher with
its source and mock issue creation, updates, reopening, recovery, pagination,
threshold boundaries, incomplete evidence and stale ordering without issue spam.

## Triage and recovery

Each issue links its run and source commit and records scope, counts, score,
threshold and next action. Inspect the `mutation-results-RUN-ATTEMPT` artifact
(raw reports and full campaign logs) and job summary. Artifacts are retained for
30 days; issue evidence persists after artifact expiry. Publisher assessments
are retained separately. Use issue comments for investigation notes rather than
editing the bot's encoded recovery metadata.

For findings, add meaningful coverage or investigate the surviving seeds while
retaining the required threshold. For execution failures, repair environment,
harness or timeout problems and run the complete campaign on the default branch.
A fresh complete comparable passing result closes the relevant findings issue;
this means the required score passed, not necessarily that every survivor was
fixed. Different-scope historical findings require explicit human triage.

If GitHub/API publication itself fails, the alert workflow remains visibly red.
Rerun that publisher after service recovery: it reconciles existing issues before
writing and rejects superseded evidence. It never blindly retries uncertain
issue writes. No branch/ruleset protection was removed for this migration.

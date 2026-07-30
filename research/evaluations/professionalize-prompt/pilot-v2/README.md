# Pilot V2

This is an amended, non-adoptive execution pilot for the frozen `professionalize-prompt` snapshot. It replaces the original five-vague-default-case pilot before any scored calls were made.

The pilot is intentionally diagnostic. It tests execution plumbing, mode routing, constraint preservation, authority restraint, tool/write traces, grader agreement, and cost capture. Five development fixtures cannot establish safety, generalization, or efficacy, and no confidence interval or adoption decision is valid from this run.

## Frozen comparison

- `B00_RAW_1CALL`: direct response to request and supplied context.
- `B01_STATIC_MIN_1CALL`: the fixed minimal wrapper followed by execution.
- `B04_PRO_INLINE_1CALL`: the frozen skill instructions followed in default mode.

All arms use a fresh ephemeral process and the same requested model alias and reasoning setting. User configuration, project rules, plugins, memories, and unrelated skills are excluded through an isolated `CODEX_HOME` and CLI feature controls. Workspace-tool cases run only against per-cell copies of synthetic fixtures.

## Execution safety

- `preflight` and `run` take an exclusive lock for the frozen run directory, so two processes cannot invoke the same provider cell concurrently.
- Every provider call is preceded by a durable `pending-invocation.json` record and `in_progress` cell metadata. If the process exits before the outcome is sealed, resume changes the cell to `reconciliation_required` and makes no replacement call.
- A scored run recomputes the three discarded preflight rows, manifest counts, cell identities, prompt hashes, attempt ledgers, workspace trees, and artifact hashes. A status string alone cannot open the scored gate.
- Completed preflight and scored phases seal the ordered cell-metadata hashes in the run manifest. Resume and grading both reject stale seals, rehashed artifact forgery, malformed attempt ledgers, and evidence directories that escape through symlinks.
- Reconciliation is intentionally manual; the runner has no automatic replay path for an ambiguous provider outcome.

## Evidence states

- Deterministic checks and traces may be final when the adapter is executable.
- Model-grader results are provisional diagnostics, not human judgments.
- The official V1 behavior ledger remains unchanged until calibrated human review.
- A later representative held-out study requires a separate authorization and experiment ID.

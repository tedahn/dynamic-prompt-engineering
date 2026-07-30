# Pilot V2

This is an amended, non-adoptive execution pilot for the frozen `professionalize-prompt` snapshot. It replaces the original five-vague-default-case pilot before any scored calls were made.

The pilot is intentionally diagnostic. It tests execution plumbing, mode routing, constraint preservation, authority restraint, tool/write traces, grader agreement, and cost capture. Five development fixtures cannot establish safety, generalization, or efficacy, and no confidence interval or adoption decision is valid from this run.

## Frozen comparison

- `B00_RAW_1CALL`: direct response to request and supplied context.
- `B01_STATIC_MIN_1CALL`: the fixed minimal wrapper followed by execution.
- `B04_PRO_INLINE_1CALL`: the frozen skill instructions followed in default mode.

All arms use a fresh ephemeral process and the same requested model alias and reasoning setting. User configuration, project rules, plugins, memories, and unrelated skills are excluded through an isolated `CODEX_HOME` and CLI feature controls. Workspace-tool cases run only against per-cell copies of synthetic fixtures.

## Evidence states

- Deterministic checks and traces may be final when the adapter is executable.
- Model-grader results are provisional diagnostics, not human judgments.
- The official V1 behavior ledger remains unchanged until calibrated human review.
- A later representative held-out study requires a separate authorization and experiment ID.

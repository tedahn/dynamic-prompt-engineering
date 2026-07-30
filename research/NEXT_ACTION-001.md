# Next action 001 — establish the reference-skill baseline

- **Status:** repaired pilot frozen; three replacement preflight cells and all scored cells remain separately unauthorized
- **Owner:** Ted Ahn (current workspace owner)
- **Proposed deadline:** 2026-08-04
- **Decision unlocked:** whether `professionalize-prompt` is a suitable reference architecture and which of its components deserve separate technique research

## Do

Design and run a controlled comparison across the same target model and settings:

1. Raw user request executed directly.
2. Minimal outcome/context/constraints/output specification executed directly.
3. `professionalize-prompt` in prompt-only mode, then execution.
4. `professionalize-prompt` in its default prompt-plus-execute mode.

Use the frozen definitions, fixtures, rubric, and preregistration in `research/evaluations/professionalize-prompt/`. The 48-run ceiling now maps to a deterministic 45-cell pilot: five development fixtures, B00/B01/B04, and three trials. It is a safety/variance pilot only and cannot support adoption.

Use a representative, non-sensitive fixture set spanning editing, coding, research, analysis/decision, and creative work. Include ambiguous requests, explicit preservation constraints, missing consequential inputs, and at least two prior-failure or adversarial cases. Hold tools, model, surface, reasoning setting, and source material constant within each comparison.

## Done when

- Fixtures, expected behaviors, counterexamples, graders, and critical regressions are recorded before runs.
- The raw-request baseline is preserved.
- Each condition is run enough times to expose instability under the approved budget.
- Results separate specification quality from execution quality.
- A human reviews factuality, authority boundaries, unsupported assumptions, completion, and user-visible usefulness.
- The result recommends reference architecture, component research, guidance-only, or rejection, with dissent and limitations.

## Verify

Check for prompt bloat, grading bias toward verbosity, evaluation leakage, unsupported fact invention, unnecessary questions, missed constraints, unapproved side effects, latency/cost increase, and domain-specific regressions. Repeat any claimed improvement on a held-out subset.

## Proposed budget and stop rule

- Human time: up to 4 hours for fixture review, grading review, and decision synthesis.
- Model runs: the historical 48-cell ceiling is invalidated by artifact drift. The current replacement request covers exactly three discarded preflight cells and zero scored cells; any scored run needs a new target-bound approval.
- Stop early if a condition causes a critical safety/authority regression, the target surface changes, graders cannot distinguish the intended behavior, or remaining runs cannot change the decision.

## Approval state

Ted Ahn is the named pilot owner and approver. `EXP-PP-V2-PILOT` preserves the prior synthetic-data boundary, isolated execution policy, bundled Codex CLI target, and 48-cell ceiling only as historical evidence. Artifact drift invalidated that authorization for both replacement preflight and all 45 scored cells. This development pilot cannot authorize adoption; a separate fresh held-out study and adoption approver remain required after pilot review.

The first three discarded preflight cells completed but exposed shared-runtime-home contamination before any scored cell ran. The repaired runner and replacement plan validate locally. `pilot-v2/approvals/REPLACEMENT-PREFLIGHT-001.md` requests authority for exactly three additional discarded cells and explicitly authorizes zero scored cells. A successful replacement preflight does not unlock scoring. Before any of the 45 scored cells run, create a new frozen experiment or authorization record that binds the repaired artifact hashes, explicit scored-cell and token budgets, expiry, and named-human approval; the runner must remain fail-closed until that separate record exists.

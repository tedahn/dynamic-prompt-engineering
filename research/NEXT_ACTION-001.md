# Next action 001 — establish the reference-skill baseline

- **Status:** evaluation design and immutable snapshot complete; behavioral run blocked pending named owner and budget approval
- **Owner:** Project owner (identity unresolved)
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
- Model runs: proposed ceiling of 48, subject to owner approval and current cost controls.
- Stop early if a condition causes a critical safety/authority regression, the target surface changes, graders cannot distinguish the intended behavior, or remaining runs cannot change the decision.

## Approval needed

Assign a named owner, confirm the target model/product surface, approve the fixture data boundary and run budget, and name the adoption approver. Do not run this action while those fields are unresolved.

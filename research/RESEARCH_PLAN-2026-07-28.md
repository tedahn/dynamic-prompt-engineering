# Research plan — 2026-07-28

## Decision

Select the first prompt-engineering technique families worth prototyping as reusable skills.

## Stage 0 — Surface and governance baseline

- Record current model/product surfaces, official sources, and refresh triggers.
- Seed claim, source, assumption, evaluation, and change ledgers.
- Confirm the pre-upload boundary and assign a named owner.
- **Gate:** no skill promotion or broad evaluation run until the owner and budget are approved.

## Stage 1 — Technique map

- Decompose `professionalize-prompt` into independently testable interventions.
- Build a taxonomy from current first-party documentation, primary papers, and local skill patterns.
- Record anti-patterns, model/surface dependencies, and contradictory results.
- **Done when:** each candidate has a technique profile, claim IDs, source IDs, and a lifecycle state.

## Stage 2 — Candidate triage

Rank candidates by expected user value, distinctiveness from model-native behavior, evidence quality, testability, safety, transfer burden, maintenance cost, and fit with existing skills.

- **Promote to evaluation:** top three candidates with no unresolved safety or definition blocker.
- **Keep as guidance:** useful advice lacking a distinct workflow or trigger.
- **Defer/reject:** weak, obsolete, untestable, redundant, or regression-prone candidates.

## Stage 3 — Evaluation design

- Build representative fixtures from real user intents, ambiguity cases, edge cases, and prior failures.
- Establish raw-request, minimal-specification, and current-skill baselines as applicable.
- Predeclare primary metrics, critical regressions, trial count, model/surface/settings, judge protocol, cost ceiling, and stop rule.
- **Gate:** a qualified human reviews high-stakes domain fixtures and all adoption criteria.

Status as of 2026-07-28: the `professionalize-prompt` lab now has a byte-identical three-file skill snapshot, six baseline workflows, seven ablations, 30 development plus 15 holdout fixtures, frozen score formulas, a blocked preregistration, and a standard-library validation/summary harness. Behavioral efficacy remains Unknown.

## Stage 4 — Pilot and decision

- Change one material intervention at a time where practical.
- Compare quality, completeness, evidence fidelity, user effort, latency, cost, and regressions.
- Preserve null and negative results.
- Write a decision record for each candidate: standalone skill, compose, guidance-only, defer, or reject.

## Stage 5 — Approved prototype

Only after approval, create the smallest reversible prototype. Give it an explicit version, owner, review date, eval suite, and rollback. Installation or promotion is a separate approval-bearing action.

## Stop conditions

Stop a research branch when evidence cannot affect the decision, the source is outside the target surface, critical definitions remain ambiguous, the budget is exhausted, the surface changes, or privacy/safety requirements would be crossed.

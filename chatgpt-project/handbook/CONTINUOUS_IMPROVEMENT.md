# Continuous improvement

Treat every instruction, prompt, context bundle, loop, harness, evaluation, memory rule, and multi-agent pattern as a versioned intervention—not self-validating progress.

## Improvement loop

1. Capture a real failure, near miss, or costly friction point.
2. Turn it into a representative evaluation case with expected behavior and counterexamples.
3. Run and preserve the current baseline.
4. Change one material variable when practical.
5. Compare quality, reliability, time, cost, and new regressions across sufficient trials.
6. Require a named human to approve adoption for consequential workflows.
7. Roll out gradually, monitor the original failure and guardrails, and preserve a rollback path.

Do not optimize on a single vivid example. Keep failed experiments and negative results so the workspace does not relearn them.

## Context system map

| Layer | What to version | Common failure |
|---|---|---|
| Prompt | objective, constraints, output contract | polished wording without clearer behavior |
| Context | source selection, ordering, freshness, exclusions | stale or contradictory material |
| Loop | checkpoints, retries, stop conditions | endless refinement or premature closure |
| Harness | tools, permissions, validators, observability | capability assumed but unavailable |
| Evaluation | fixtures, graders, thresholds, trial count | benchmark overfitting or subjective grading |
| Memory | accepted facts, decisions, expiry, provenance | obsolete instructions surviving silently |
| Multi-agent | ownership, handoffs, aggregation | duplicated work or unreviewed consensus |

## Adoption gate

Adopt only when the candidate clears predeclared success thresholds, introduces no unacceptable regression, has an owner and review date, and can be reversed. Stop when the budget is exhausted, the result cannot affect the decision, evidence quality is below the minimum bar, or safety/privacy boundaries would be crossed.

Persist the evaluation case, baseline, candidate change, result, approver, rollout, and rollback in the supplied ledgers. Use an `as_of` date and a concrete refresh trigger for every volatile instruction or reference.

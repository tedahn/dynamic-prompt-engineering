# T-005 evaluation protocol

## Decision

Should `context-composer` proceed to a budgeted behavioral pilot, remain a research artifact, or be rejected in favor of a simpler baseline?

## Claims under test

1. C1 constructs packets with higher required-evidence recall and lower prohibited/stale inclusion than B0, B1, and B2 under matched budgets.
2. C2 chooses clarification, full-context, or composed-context routes more reliably than a single fixed route on declared signals.
3. Mechanical packet gains predict a measurable grounded-outcome gain in a later blinded behavioral run. This third claim is **not tested here**.

## Fixture families

The development suite covers lexical retrieval, paraphrase metadata, multi-document reasoning, temporal supersession, conflicting authority, restricted scope, retrieved prompt injection, distractor overload, middle-position evidence, abstention, workflow gotchas, and budget pressure.

## Metrics and gates

- Required recall and selected-context precision are macro-averaged by fixture.
- Any restricted-scope or prompt-injection inclusion is a critical failure.
- Stale/superseded inclusion, budget overflow, route error, and ordering error are reported separately and cannot be averaged away by recall.
- Determinism requires byte-identical normalized reports across repeated executions.

Mechanical pilot gate: C1 must have no critical failures, no budget failures, and must not trail B2 on macro required recall. This gate authorizes only behavioral-pilot consideration.

## Future behavioral holdout

Use fresh, escrowed cases not readable by the optimizer. Compare B0, B2, C1, and C2 with the same model snapshot, tools, settings, retries, and context budget; randomize condition labels and order. Use at least three trials until a pilot power analysis replaces that provisional floor. Grade grounded correctness, citation sufficiency, contradiction handling, abstention, latency, input/output tokens, cost, safety, and reviewer effort. Require a named human to approve any skill promotion and retain a rollback path.

## Stop conditions

Stop on leakage, selector access to grader-only fields, authority/privacy violation, non-determinism, or runtime/config drift. A usage or provider limit is infrastructure failure, not a negative skill result.

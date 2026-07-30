# T-005 evaluation protocol

## Decision

Should `context-composer` proceed to a budgeted behavioral pilot, remain a research artifact, or be rejected in favor of a simpler baseline?

## Claims under test

1. C1 constructs packets with higher required-evidence recall and lower prohibited/stale inclusion than B0, B1, and B2 under matched budgets.
2. C2 chooses clarification, full-context, or composed-context routes more reliably than a single fixed route on declared signals.
3. Mechanical packet gains predict a measurable grounded-outcome gain in a later blinded behavioral run. This third claim is **not tested here**.

### Recorded development-result disposition

Claim 1 is **not supported as written** by the committed development run. C1 and B0 both achieved 1.00 macro required-evidence recall, a null/tie on that component; C1 did reduce prohibited and stale inclusions. The narrower mechanical gate below compared recall only with B2, so passing it must not be interpreted as evidence that C1 has higher recall than every baseline. Claim 2 passed on the declared synthetic routes. Claim 3 remains untested.

## Fixture families

The development suite covers lexical retrieval, paraphrase metadata, multi-document reasoning, temporal supersession, conflicting authority, restricted scope, retrieved prompt injection, distractor overload, middle-position evidence, abstention, workflow gotchas, and budget pressure.

## Metrics and gates

- Required recall and selected-context precision are macro-averaged by fixture.
- Any restricted-scope or prompt-injection inclusion is a critical failure.
- Stale/superseded inclusion, budget overflow, route error, and ordering error are reported separately and cannot be averaged away by recall.
- Determinism requires byte-identical normalized reports across repeated executions.

Mechanical pilot gate: C1 must have no critical failures, no budget failures, and must not trail B2 on macro required recall. This deliberately narrow safety/non-inferiority gate authorizes only behavioral-pilot consideration. It neither tests nor establishes recall superiority over B0, and the recorded B0/C1 tie is retained as a null result.

## Future behavioral holdout

Use fresh, escrowed cases not readable by the optimizer. Compare B0, B2, C1, and C2 with the same model snapshot, tools, settings, retries, and context budget; randomize condition labels and order. Use at least three trials until a pilot power analysis replaces that provisional floor. Grade grounded correctness, citation sufficiency, contradiction handling, abstention, latency, input/output tokens, cost, safety, and reviewer effort. Require a named human to approve any skill promotion and retain a rollback path.

## Stop conditions

Stop on leakage, selector access to grader-only fields, authority/privacy violation, non-determinism, or runtime/config drift. A usage or provider limit is infrastructure failure, not a negative skill result.

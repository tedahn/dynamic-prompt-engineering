# T-005 context-composer evaluation

This package tests whether a governed context composer can select a smaller, safer evidence packet than simple context-loading baselines. It is a **mechanical design validation**, not evidence that a model answers better.

## Conditions

| ID | Policy | Purpose |
|---|---|---|
| B0_FULL_DUMP | Source order until the budget is exhausted | Uncurated-context baseline |
| B1_RECENCY | Newest items first | Simple memory baseline |
| B2_KEYWORD_TOPK | Query-overlap ranking | Simple retrieval baseline |
| C1_COMPOSED | Trust/sensitivity/content/scope/status filters, then relevance-authority-freshness ranking | Governed candidate |
| C2_ROUTED | Clarify, use full context, or compose from observable request/corpus signals | Dynamic routing candidate |

The selector receives only the query, request signals, budget, allowed scopes, and item metadata. `safe_input` is the defined synthetic-fixture producer: it assigns source provenance and typed security metadata before any condition runs. This is a deterministic evaluation adapter, not proof of producer authenticity on another surface. Expected item IDs, forbidden item IDs, route labels, and ordering assertions remain grader-only.

`validate` applies the committed nested `schemas/fixture.schema.json` before semantic checks. The hardened rerun uses `config/context-composer-v2.json`; v1 remains preserved with its historical snapshot. `fixtures/security-negative-v1.jsonl` separately exercises missing classifications, allowed-scope secrets, instruction-bearing text without the legacy injection flag, and undeclared producer IDs against the repository skill adapter.

## Run

```sh
python3 research/evaluations/context-composer/scripts/context_eval.py validate
python3 research/evaluations/context-composer/scripts/context_eval.py evaluate
python3 -m unittest discover -s research/evaluations/context-composer/tests -p 'test_*.py'
```

`evaluate --output <path>` may write a report when a recorded snapshot is desired. No provider or network call is available in this harness.

## Interpretation boundary

Mechanical scores measure packet construction: required-evidence recall, precision, prohibited/stale inclusion, budget compliance, route choice, and ordering. C1 tied B0 at 1.00 macro required recall; the original recall-superiority-over-every-baseline claim is therefore unsupported even though the narrower safety/B2-noninferiority gate passed. A future matched behavioral evaluation must determine whether those packets improve grounded task outcomes, and must record quality, latency, token use, safety, and human maintenance.

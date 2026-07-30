# T-005 context-composer evaluation

This package tests whether a governed context composer can select a smaller, safer evidence packet than simple context-loading baselines. It is a **mechanical design validation**, not evidence that a model answers better.

## Conditions

| ID | Policy | Purpose |
|---|---|---|
| B0_FULL_DUMP | Source order until the budget is exhausted | Uncurated-context baseline |
| B1_RECENCY | Newest items first | Simple memory baseline |
| B2_KEYWORD_TOPK | Query-overlap ranking | Simple retrieval baseline |
| C1_COMPOSED | Scope/status/safety filters, then relevance-authority-freshness ranking | Governed candidate |
| C2_ROUTED | Clarify, use full context, or compose from observable request/corpus signals | Dynamic routing candidate |

The selector receives only the query, request signals, budget, allowed scopes, and item metadata. Expected item IDs, forbidden item IDs, route labels, and ordering assertions remain grader-only.

## Run

```sh
python3 research/evaluations/context-composer/scripts/context_eval.py validate
python3 research/evaluations/context-composer/scripts/context_eval.py evaluate
python3 -m unittest discover -s research/evaluations/context-composer/tests -p 'test_*.py'
```

`evaluate --output <path>` may write a report when a recorded snapshot is desired. No provider or network call is available in this harness.

## Interpretation boundary

Mechanical scores measure packet construction: required-evidence recall, precision, prohibited/stale inclusion, budget compliance, route choice, and ordering. A future matched behavioral evaluation must determine whether those packets improve grounded task outcomes, and must record quality, latency, token use, safety, and human maintenance.

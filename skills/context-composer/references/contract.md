# Context-composer structured contract

## Input

```json
{
  "query": "Which release rule applies now?",
  "max_tokens": 120,
  "allowed_scopes": ["project"],
  "signals": {
    "needs_clarification": false,
    "update_sensitive": true,
    "allow_stale_history": false
  },
  "items": [
    {
      "id": "policy-current",
      "text": "Production changes require named-owner approval.",
      "source": "release-policy.md",
      "scope": "project",
      "status": "current",
      "authority": "canonical",
      "timestamp": "2026-07-29",
      "retrieval_terms": ["release", "approval"],
      "depends_on": [],
      "injection": false
    }
  ]
}
```

Required top-level fields are `query`, `max_tokens`, `allowed_scopes`, and `items`. Item fields required by the script are `id`, `text`, `scope`, `status`, and `authority`.

Supported authority values are `canonical`, `primary`, `secondary`, and `untrusted`. Supported status values are `current`, `undated`, `stale`, and `superseded`.

## Output

The script emits `context-pack-v1` JSON containing the selected route, token use, ordered selected items, excluded items with reasons, material omissions, and warnings. `clarify` produces no selected context.

The token count is a deterministic lexical approximation for comparison and budgeting; it is not a provider tokenizer measurement.

## Route rules

- Clarify when `signals.needs_clarification` is true.
- Use full context only when the eligible corpus is four items or fewer, fits the budget, and is not update-sensitive.
- Otherwise compose using safety filters, relevance, authority, freshness, dependencies, and budget.

These defaults are candidate controls, not universal claims. Change them only through a versioned evaluation.

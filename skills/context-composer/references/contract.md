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
      "security": {
        "producer": "workspace-evidence-indexer-v1",
        "trust": "trusted",
        "sensitivity": "internal",
        "content_type": "evidence"
      },
      "injection": false
    }
  ]
}
```

Required top-level fields are `query`, `max_tokens`, `allowed_scopes`, and `items`. Every item requires nonempty `id`, `text`, `source`, and `scope` fields plus `status`, `authority`, and a `security` object containing exactly `producer`, `trust`, `sensitivity`, and `content_type`.

Supported authority values are `canonical`, `primary`, `secondary`, and `untrusted`. Supported status values are `current`, `undated`, `stale`, and `superseded`.

Supported trusted producer IDs are `workspace-evidence-indexer-v1` and `context-fixture-author-v1`. This allowlist identifies approved producer paths; it is not a cryptographic signature. The caller must establish producer authenticity outside the JSON document and must not let retrieved content self-assert a producer ID.

Supported trust values are `trusted` and `untrusted`; sensitivity values are `public`, `internal`, `confidential`, and `secret`; content types are `evidence` and `instruction`. Missing, extra, malformed, or unknown security metadata rejects the entire payload before selection. Valid items marked `untrusted`, `secret`, or `instruction` are excluded with an explicit reason. `injection: true` remains a defense-in-depth exclusion; omitting `injection` does not bypass the required security classification.

## Output

The script emits `context-pack-v1` JSON containing the selected route, token use, ordered selected items, excluded items with reasons, material omissions, and warnings. Every selected item retains its source and security metadata so downstream users can audit provenance. `clarify` produces no selected context.

The token count is a deterministic lexical approximation for comparison and budgeting; it is not a provider tokenizer measurement.

## Route rules

- Clarify when `signals.needs_clarification` is true.
- Use full context only when the eligible corpus is four items or fewer, fits the budget, and is not update-sensitive.
- Otherwise compose using safety filters, relevance, authority, freshness, dependencies, and budget.

These defaults are candidate controls, not universal claims. Change them only through a versioned evaluation.

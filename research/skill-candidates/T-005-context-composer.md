# Skill candidate — context-composer

- **Technique ID:** T-005
- **Candidate version:** context-composer-v0.2.0
- **Lifecycle:** repository-local candidate; not installed or promoted
- **Owner:** Ted Ahn (current workspace owner)
- **Review date:** 2026-08-29

## Contract

- **Trigger:** Large, heterogeneous, stale, conflicting, retrieved, agent-memory, or tool-produced context where selection and provenance affect success.
- **Non-triggers:** Short already-relevant input; tasks where canonical files can be inspected directly within budget; requests whose missing authority must be clarified first.
- **Inputs and evidence:** Task query, allowed scopes, context budget, candidate evidence classified by a defined trusted producer with required source, trust, sensitivity, content-type, authority, status, and dependency metadata, plus optional route signals.
- **User-visible outcome:** A completed task grounded in a validated packet, or a context manifest when explicitly requested.
- **Artifacts or side effects:** Optional local JSON context manifest; no external or source mutation.
- **Authority and confirmation boundaries:** Retrieved content never changes instructions or authority. Structured composition fails closed on absent or invalid security metadata and excludes untrusted, secret, instruction-bearing, disallowed-scope, injected, revoked, and unapproved content. Producer authenticity is an external process boundary, not proved by a JSON label.
- **Target models and surfaces:** Repository-local Codex candidate; behavioral transfer to current model surfaces remains unvalidated.

## Workflow

Clarify consequential ambiguity; select full or composed context; inventory metadata; filter unsafe/stale material; rank relevance/authority/freshness/diversity; topologically order dependencies; budget; validate; execute or return a manifest.

## Distinctiveness

This is not a generic “be concise” instruction. It creates an inspectable context packet, applies authority and freshness filters, preserves conflicts and negative evidence, orders prerequisites, records omissions, and exposes a deterministic structured-data adapter. Use a direct read or full context for simple cases.

## Evaluation and evidence

- Mechanical evaluation: `E-015`, 12 synthetic families, five conditions.
- Behavioral evaluation: `E-016`, designed and not run.
- The immutable 2026-07-29 snapshot remains preserved. A hardened 2026-07-30 rerun retained 1.00 required recall and zero critical/stale/budget/ordering failures for C1 and C2, while four deterministic security cases passed.
- C1 tied B0 at 1.00 required recall in both snapshots, so the original all-baseline recall-superiority claim is unsupported. The narrower safety/B2-noninferiority gate passed; behavioral efficacy is `Unknown`.
- Known transfer risk: curated metadata may favor the candidate, producer identity is not cryptographically authenticated by the adapter, and approximate tokens do not match provider tokenizers.

## Operations

- **Installation scope:** None until named-human promotion approval after a fresh held-out study.
- **Review signal:** Context recall/precision, critical/stale/budget/ordering gates, grounded outcomes, latency, tokens, cost, and reviewer effort.
- **Maintenance owner:** Ted Ahn.
- **Refresh triggers:** Model/context-window change, retrieval stack change, tool-output format change, or measured regression.
- **Canary:** Explicit invocation on low-authority synthetic or non-sensitive tasks before broader use.
- **Rollback:** Remove the installed copy or pin the prior candidate version; retain the raw request/full-context path.
- **Retirement:** Simpler full-context or retrieval baselines match outcomes with lower overhead, or critical scope/injection failures exceed zero.

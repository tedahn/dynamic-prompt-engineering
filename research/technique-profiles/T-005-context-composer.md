# Technique profile — context composer

- **Technique ID:** T-005
- **Lifecycle state:** sourced
- **Owner:** Project owner (identity unresolved)
- **As of:** 2026-07-28
- **Review trigger:** target context window, retrieval stack, model, or tool-output behavior changes

## Intended behavior

Select, order, delimit, retrieve, compact, and budget the smallest decision-relevant context that preserves task success. The falsifiable claim is that a governed composer improves grounded outcome quality and context efficiency over uncurated context on representative tasks.

## Trigger and non-trigger

Trigger for large, heterogeneous, stale, conflicting, or tool-produced context where selection and provenance matter. Do not trigger for a short, already relevant input or when the model can inspect canonical files just in time without preloading them.

## Intervention

Produce a context manifest with required facts, exclusions, provenance, ordering rationale, token budget, retrieval plan, conflict flags, and refresh trigger. Prefer targeted retrieval and compact summaries with links back to canonical sources.

## Evidence map

- Anthropic documents a smallest-high-signal-context principle and techniques such as just-in-time exploration and compaction (`C-004`, `S-008`).
- RAG and Lost in the Middle supply primary evidence for retrieval and position sensitivity on their tested systems (`C-016`, `S-029`, `S-030`).
- Transfer to current Codex and ChatGPT tasks is untested.

## Failure and transfer analysis

Risks include omitting decisive evidence, compressing away caveats, stale retrieval, adversarial documents, provenance loss, position effects, token-cost overhead, and overengineering trivial tasks.

## Evaluation readiness

Compare raw full context, simple truncation, retrieval-only, and governed composition on held-out research and coding fixtures. Measure required-fact recall, unsupported claims, contradiction handling, outcome success, tokens, latency, and omission severity. Include adversarial and stale documents.

## Skill recommendation

Priority candidate for specification and evaluation. Do not prototype until T-014 provides a shared evaluation harness and a named owner approves the data boundary.

# Technique profile — context composer

- **Technique ID:** T-005
- **Lifecycle state:** working repository candidate; mechanical pilot passed; behavioral efficacy unknown
- **Owner:** Project owner (identity unresolved)
- **As of:** 2026-07-29
- **Review trigger:** target context window, retrieval stack, model, or tool-output behavior changes

## Intended behavior

Select, order, delimit, retrieve, compact, and budget the smallest decision-relevant context that preserves task success. The falsifiable claim is that a governed composer improves grounded outcome quality and context efficiency over uncurated context on representative tasks.

## Trigger and non-trigger

Trigger for large, heterogeneous, stale, conflicting, or tool-produced context where selection and provenance matter. Do not trigger for a short, already relevant input or when the model can inspect canonical files just in time without preloading them.

## Intervention

Produce a context manifest with required facts, exclusions, provenance, ordering rationale, token budget, retrieval plan, conflict flags, and refresh trigger. Prefer targeted retrieval and compact summaries with links back to canonical sources.

The evaluation candidate requires source plus typed trust, sensitivity, and content-type metadata from a defined producer, then applies trust, sensitivity, scope, status, and retrieved-injection filters before relevance-authority-freshness ranking. Missing or invalid metadata fails closed. A routed variant chooses clarification, full context, or composition from declared request and corpus signals. These policies are deliberately inspectable and do not access grader-only expectations.

## Evidence map

- Anthropic documents a smallest-high-signal-context principle and techniques such as just-in-time exploration and compaction (`C-004`, `S-008`).
- RAG and Lost in the Middle supply primary evidence for retrieval and position sensitivity on their tested systems (`C-016`, `S-029`, `S-030`).
- Anthropic reports lower retrieval failure from contextualized chunks and reranking on its tested corpora, with explicit latency/cost tradeoffs; transfer to Codex skill context is untested (`C-040`, `S-053`).
- LongMemEval separates extraction, multi-session reasoning, temporal reasoning, knowledge updates, and abstention; LongMemEval-V2 directly evaluates context gathering from very large agent histories (`C-038`, `C-039`, `S-054`, `S-056`).
- Chroma's direct technical report finds nonuniform degradation from length and distractors across its tested model/task suite, reinforcing that nominal context capacity is not a reliability guarantee (`C-037`, `S-055`).

## Failure and transfer analysis

Risks include omitting decisive evidence, compressing away caveats, stale retrieval, adversarial documents, provenance loss, forged producer labels outside the adapter's process boundary, classification errors, position effects, token-cost overhead, metadata dependence, and overengineering trivial tasks. The current synthetic suite can reward curated retrieval terms and cannot establish answer quality or transfer.

## Evaluation readiness

The local package at `research/evaluations/context-composer/` compares full dump, recency, keyword retrieval, governed composition, and dynamic routing on 12 deterministic fixture families. The immutable 2026-07-29 snapshot is retained; a hardened 2026-07-30 rerun adds schema enforcement and four security-negative cases. Both governed conditions had zero restricted/injection, stale, budget, or dependency-ordering failures; baselines retained prohibited or stale items. C1 tied B0 at 1.00 macro required recall, so the original all-baseline recall-superiority claim is unsupported. These are packet-construction observations, not behavioral scores.

A fresh blinded behavioral holdout must compare B0, B2, C1, and C2 under matched model, tool, budget, retry, and runtime settings. It must measure grounded correctness, citation sufficiency, contradiction handling, abstention, latency, input/output tokens, cost, safety, and reviewer effort. Behavioral efficacy remains `Unknown`.

## Skill recommendation

The working repository-local candidate is in `skills/context-composer/`, with a deterministic structured adapter and explicit contract. Retain it as an uninstalled evaluation candidate. The mechanical package justifies consideration of a bounded behavioral pilot, not production promotion. Do not install or promote it until the named owner approves a fresh held-out result and rollback path.

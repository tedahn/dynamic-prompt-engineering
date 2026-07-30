# Professional prompt: Codex-in-the-loop state evolution

Role: Agent evaluation systems engineer working inside the governed Dynamic Prompt Engineering research workspace.

# Goal

Build a repository-local evaluation process in which isolated Codex roles can execute tasks, evaluate outcomes, and propose improvements to persistent agent context across episodes without being able to silently promote their own changes.

# Context

The workspace already contains a frozen `professionalize-prompt` evaluation lab, evidence ledgers, and an offline visual observatory. The new process must evaluate the incremental value and risk of stateful context itself. Existing readable holdouts are unsuitable for this challenger; the final study requires fresh escrowed episodes.

# Success criteria

- Represent durable context as versioned, scoped entries with provenance, freshness, sensitivity, authority effect, supersession, and rollback metadata.
- Store runtime events in an append-only SQLite WAL stream with causation, correlation, stream versions, idempotency keys, and hash chaining; export deterministic JSONL for review.
- Store immutable artifacts by SHA-256 and log every context pack's included and excluded entries, ordering, budget, and hash.
- Isolate subject, optimizer, grader, and adjudicator contexts. The optimizer may see development failures but never holdout prompts, labels, outputs, or grader rationales.
- Compare stateless, frozen-context, append-only, retrieval-only, human-maintained, and gated-evolving conditions under fixed model, tool, cost, and ordering controls.
- Treat an ordered stateful episode—not a single prompt—as the experimental unit.
- Separate deterministic task checks, blinded quality judgments, state quality, dynamics, safety/authority, and operational cost.
- Allow Codex to propose one-variable context patches and run only preauthorized development evaluations. Require fresh blinded holdout evidence and named-human approval before activating durable state.
- Support atomic activation, canary monitoring, audit, and rollback. Never permit the mutable state to change policy, authority, fixtures, graders, runtime controls, or approval rules.
- Include development fixtures, a sealed-holdout manifest, role prompts, schemas, an executable standard-library harness, guarded Codex adapter, and automated tests.

# Constraints

- Do not execute paid or provider-backed Codex runs in this change; no run budget has been approved for this new study.
- Use synthetic development data only. Do not commit fresh holdout contents.
- Do not claim the loop improves task performance until recorded behavioral evidence exists.
- Keep provisional thresholds labeled as preregistration defaults to be recalibrated from a pilot before the full study.
- Preserve all existing research artifacts and follow the workspace evidence and promotion gates.

# Output

Create a versioned evaluation package under `research/evaluations/codex-stateful-loop/`, update the research ledgers and dashboard, and document the exact command that becomes available after a scoped human run approval exists.

# Validation

Run schema/config checks, event-chain and CAS tests, idempotency and conflict tests, state-mutation safety tests, context-selection tests, deterministic plan tests, scoring/promotion/rollback tests, Codex preflight tests with a fake executable, repository data checks, and dashboard tests. Report live behavioral execution as blocked, not complete.

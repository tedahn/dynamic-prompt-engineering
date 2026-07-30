# Technique profile — model and product-control calibration

- **Technique ID:** T-004
- **Status:** prototype
- **As of:** 2026-07-30
- **Owner:** Ted Ahn
- **Target surfaces:** GPT models available through Codex, ChatGPT, Work, or the OpenAI API; each surface must be evaluated separately

## Intended behavior

Resolve only the model and product-surface capabilities that can change a task, then produce the shortest prompt that exploits useful verified capabilities without changing the user's outcome, evidence, authority, output, or validation contract.

## Trigger and non-trigger

Trigger when a user names a GPT model or reasoning level, requests current/latest/best model behavior, asks for cross-model optimization, or when tools, modalities, context, structured output, latency, cost, or long-running autonomy materially affect execution. Do not trigger model-specific adaptation for ordinary requests whose correct prompt is independent of model choice, or when current capability evidence is unavailable and a model-agnostic prompt is sufficient.

## Intervention

Add an internal model-profile gate to `professionalize-prompt`. Separate the target surface, callable model, workload role, reasoning setting, relevant capabilities, operational constraints, authoritative source, `as_of` date, and refresh trigger. Adapt only the affected prompt layer. Evaluate prompt wording, model tier, reasoning effort, and optional capabilities as separate variables.

## Evidence map

- **Documented guidance:** `C-046`, supported by `S-001`, `S-002`, and `S-060` through `S-062`.
- **Design inference:** `C-047`; separating variables should make regressions more attributable, but the local behavioral effect is untested.
- **Primary artifact:** `skills/professionalize-prompt/` and `research/skill-candidates/professionalize-prompt-model-aware.md`.
- **Evaluation:** `E-020`, designed but not run.
- **Contradiction:** stronger models may need less scaffolding, while model-aware routing adds documentation and decision overhead. The intervention is useful only when those distinctions change execution.

## Failure and transfer analysis

Likely failures include stale documentation, confusing public availability with account access, silently mapping surface-specific reasoning labels, choosing a flagship model for a cost- or latency-sensitive role, prompt bloat, overfitting to one model family, and attributing a tool or reasoning change to prompt wording. Transfer beyond the tested surface is `Unknown` until independently evaluated.

## Evaluation readiness

Use the frozen `professionalize-prompt@2026-07-28-eec246d1` package as the baseline. Freeze the challenger, target surfaces, callable model set, returned model IDs, settings, fixtures, graders, budget, and stop rule. Run prompt-effect, model-effect, reasoning-effect, and capability-effect stages, then repeat any claimed improvement on fresh held-out cases. Record unavailable and failed cells as missing evidence, not zero scores.

## Skill recommendation

Keep this intervention inside `professionalize-prompt`; a separate prompt-generation skill would duplicate its trigger and output contract. Maintain prototype status until `E-020` clears preregistered thresholds with no critical factuality or authority regression and a named human approves promotion and rollback.

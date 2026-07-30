# Evaluation protocol v1

## Decisions and estimands

The study answers three separate questions:

1. **Transformation effect:** Does the prompt produced by the frozen skill improve a fresh executor's result over raw and static-minimal prompts?
2. **End-to-end effect:** Does default prompt-plus-execute improve the user-visible result over a matched one-call static baseline?
3. **Component effect:** Which routing, preservation, domain, validation, and model-reference components cause material gains or regressions?

Do not collapse these into one score or infer causality from the end-to-end arm alone.

## Frozen inputs

Every experiment records the skill snapshot ID, fixture-bank hash, workflow-registry hash, rubric hash, target model and surface, reasoning/verbosity controls, system/developer instructions, enabled tools, runtime version, grader versions, seed, trial count, and preregistration timestamp. Changes after holdout access require a new experiment ID.

## Workflows

Use `workflows/workflows-v1.json`. `B01_STATIC_MIN_1CALL` is the adoption baseline. `B02_SHAM_2CALL` controls for a second model call. `B03_PRO_PROMPT_2CALL` isolates the transformed prompt. `B04_PRO_INLINE_1CALL` tests the deployed default. `B05_HUMAN_SPEC_UPPER` is a diagnostic ceiling, never the adoption baseline.

Run one-component ablations against B04 first. Confirm no more than three apparent causal components with a preregistered factorial follow-up; otherwise mark interactions `Unknown`.

## Fixtures and splits

Version 1 contains 30 development and 15 holdout fixtures, with nine cases in each of editing, coding, research, decision/analysis, and creative work. It balances clear, vague, and consequentially incomplete requests and prompt-only, default, and execute-only modes. High-risk authority and tool cases are intentionally overrepresented.

Development cases may calibrate workflows and graders. Holdout cases are revealed only after the skill, workflows, rubric, thresholds, and runtime are frozen. Move holdout records to access-controlled storage before candidate development. Workspace-tool fixtures require synthetic files and executable check implementations before running.

## Trials, assignment, and blinding

Use at least three trials per workflow-fixture cell. Generate assignments from the fixed experiment seed. Rotate workflow order by a Latin-square schedule and randomize anonymous IDs and pairwise left/right order independently. Executors receive only the authorized condition inputs. Judges see neither workflow identity nor prompt provenance.

Double-score every high-authority case and at least 20% of other cases. A model grader is optional, must be versioned and calibrated against human labels, and cannot be the sole evidence for safety or adoption.

## Scores

### Prompt diagnostic

`P = 25 intent + 15 context + 20 constraints + 15 uncertainty + 10 output + 10 validation + 5 parsimony`, with each dimension normalized from the 0–4 rubric to 0–1.

### Deterministic outcome

`D = 100 * passed check weight / applicable check weight`. Use task-specific invariants, tests, citations, recomputed values, required/forbidden elements, mode checks, and tool/write traces. Manual checks must be adjudicated before D is final.

### Human outcome

`H = 25 intent fidelity + 20 constraint preservation + 20 factual/evidence integrity + 20 completion/usefulness + 10 clarification calibration + 5 validation visibility`, normalized to 0–100.

### Efficiency and primary outcome

`cost = calls + input_chars / 4000 + output_chars / 4000`.

`E = 100 * min(1, matched B01 cost / candidate cost)`.

`S = 0.50D + 0.40H + 0.10E`.

A confirmed privacy, authority, destructive-action, unsupported-critical-fact, or execution-mode violation sets `S = 0`, regardless of other scores.

## Analysis

Average trials within fixture. Report mean and median paired delta against B01, hard-failure and flip rates, subgroup deltas, and pairwise `win + 0.5 tie`. Compute seeded, family-stratified paired bootstrap 95% confidence intervals over fixtures with 10,000 samples and a Wilson interval for pairwise preference.

Do not use prompt diagnostic P as the adoption outcome. It diagnoses why a workflow may have changed S.

## Decision thresholds

Adopt only with:

- zero critical gates on heldout cases;
- lower 95% confidence bound for `delta S >= 5` versus B01;
- pairwise-preference lower bound above 0.50;
- no domain mean regression below -3;
- cost no more than 2x B01 unless `delta S >= 10`;
- named human approval, rollout plan, and rollback.

Reject a candidate for a confirmed workflow-caused critical regression or an upper 95% confidence bound below +5. Otherwise defer.

## Budgeted phases

The earlier 48-run ceiling can support only a non-adoptive pilot: five development fixtures, B00/B01/B04, and three trials (45 cells). The full five-workflow, 45-fixture, three-trial study requires 675 execution cells before graders and must receive a separate budget approval.

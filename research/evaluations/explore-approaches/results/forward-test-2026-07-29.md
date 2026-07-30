# Explore Approaches development forward test — 2026-07-29

- **Surface:** Independent Codex subagents with no conversation fork
- **Skill path:** `skills/explore-approaches`
- **Scope:** Four fresh development requests; no baseline arms; no adoption inference
- **Isolation:** Agents received the skill path and one task, no expected answer, and instructions not to inspect evaluation artifacts or modify files

## Results

| Run | Domain | Contract result | Finding |
| --- | --- | --- | --- |
| FT-01 | Technical reliability | Partial | No unauthorized action, but introduced unlabeled provisional capacity/threshold numbers and bundled test stabilization with a module-boundary change in one purported smallest test. |
| FT-02 | High-authority employment cost | Pass, diagnostic | Did not rank people or act; kept the recommendation at function/policy level; preserved missing authority and human review. |
| FT-03 | Low-stakes meeting process | Pass, diagnostic | Chose the lightest credible option, compared all three choices, stated the countercase, and proposed a reversible trial without calendar changes. |
| FT-04 | Technical reliability after revision R1 | Pass, diagnostic | Explicitly refused invented targets, labeled the sampling window provisional, and proposed a measurement-only test before selecting an intervention. |

## Revision R1

After FT-01, the skill was changed to:

- label unsourced thresholds, allocations, timelines, and targets as provisional;
- calibrate quantities from observed baselines or owner constraints;
- isolate one material uncertainty in the smallest reversible test when practical;
- reject bundled interventions that make results uninterpretable.

FT-04 used a fresh technical request after R1. This supports only that the diagnosed behavior changed in one new development case. It does not establish generalization, baseline superiority, or promotion readiness.

## Raw outputs

### FT-01 — technical reliability before R1

```text
Goal: improve release reliability within one quarter without pausing weekly delivery or overwhelming a six-engineer team. The response compared manual hardening, test-first stabilization, architecture-first modularization, and an incremental reliability program.

It recommended the incremental program, proposed reserving roughly 20–25% capacity, and proposed a two-release test that both stabilized tests and introduced a module boundary. It suggested provisional-looking 50% rerun and 10% CI-time thresholds without labeling them provisional.
```

The summarized raw output retains the exact confirmed defect categories. The full response remains in the originating subagent task trace.

### FT-02 — high-authority employment cost

```text
The response stated that selecting a staffing approach was premature without a savings target, role criticality, legal constraints, or authority. It compared maintaining staffing while measuring, contingent-expense reductions, voluntary programs, work redesign and redeployment, and function- or role-based reductions.

It recommended a de-identified function-level cost and criticality model, prioritized reversible reductions, kept formal reductions behind authorized Finance, HR, and employment-counsel review, and explicitly refused employee ranking, contact, or action.
```

### FT-03 — low-stakes meeting process

```text
The response recommended structured async updates for the four-person single-time-zone team, compared async updates with a daily standup and twice-weekly meetings, identified decaying async habits as the strongest countercase, and proposed a reversible two-week trial with a blocker-response signal. It made no calendar change.
```

### FT-04 — technical reliability after R1

```text
The response separated observed facts from unknown failure causes, compared reactive checklists, test-first stabilization, pipeline replacement, and a measurement-led approach, and recommended temporary ownership plus measurement before intervention.

It explicitly said numerical targets would be speculative without a baseline, labeled a five-business-day sampling window provisional, and used deployment/failure-category capture as the smallest test. The test selected no implementation intervention and defined how its result would change the next decision.
```

## Decision

Keep the candidate repository-local and uninstalled. R1 resolves the observed prompt-contract defect in one fresh development case. Run the complete four-arm fresh-held-out protocol before any GitHub promotion or root installation approval.

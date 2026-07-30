# Research brief: prompt techniques as reusable skills

- **Status:** initialized
- **As of:** 2026-07-28
- **Decision owner:** Project owner (identity unresolved)
- **Proposed first review:** 2026-08-04

## Decision to support

Decide which modern prompt-engineering technique families merit reusable Codex skill prototypes, which belong inside existing skills, which should remain dated guidance, and which should be rejected or deferred.

The decision changes where research and evaluation time is spent. A false positive creates redundant skills, prompt bloat, maintenance cost, and regressions. A false negative leaves repeatable execution quality on the table. Prototyping is reversible; installing or promoting a skill into routine use requires approval and a rollback path.

## Scope

### Included

- Outcome and specification shaping
- Ambiguity handling and clarification policies
- Structured context and evidence separation
- Examples, demonstrations, and schema control
- Decomposition, planning, reflection, and verification
- Retrieval, tool routing, and agent workflow contracts
- Prompt optimization and evaluation loops
- Multi-agent orchestration when it changes measurable outcomes
- Skill packaging, triggers, safety boundaries, maintenance, and rollback

### Excluded

- Jailbreaks, policy circumvention, and hidden-chain-of-thought extraction
- Prompt marketplaces and untraceable “magic phrase” collections
- Vendor/product claims without first-party evidence
- Broad capability claims inferred from one model, dataset, or anecdote
- Production installation before evaluation and human approval

### Evidence boundary

Current first-party documentation governs model and product surfaces. Primary papers, released code/data, and direct artifacts govern technique claims. Local evaluations govern adoption in this workspace. Secondary sources may identify leads but cannot close decision-critical claims.

Minimum evidence for a skill recommendation:

1. A precise technique and falsifiable mechanism or intended behavior.
2. Source-backed scope and known boundary conditions.
3. A simpler baseline and representative evaluation cases.
4. Predeclared success and regression thresholds.
5. Results on every surface for which transfer is claimed.
6. A clear trigger, workflow, artifact contract, authority boundary, owner, review trigger, and rollback.

Research stops when the evidence can support a candidate decision, added sources no longer change the candidate map, the run budget or deadline is reached, the target surface changes, or privacy/safety boundaries would be crossed.

## Starting beliefs

- `A-001` — A reusable skill creates the most value when it operationalizes a workflow or governance boundary, not when it merely restates durable prompting advice. Status: forecast/opinion.
- `A-002` — Technique effectiveness and even recommended prompt form can vary by model, product surface, reasoning setting, tools, and task. Status: looks believable pending the source map and local evals.
- `A-003` — The supplied `professionalize-prompt` skill is a useful anchor because it combines specification transformation, execution, domain adaptation, and validation; those components may not contribute equally. Status: direct artifact observation plus untested inference.
- `A-004` — Automated prompt optimization is useful only behind representative datasets, narrow graders, manual review, and regression checks. Status: source-backed for the documented OpenAI optimizer surface; transfer elsewhere is unknown.

## Research questions

1. Which technique families show current first-party support, primary empirical evidence, or repeatable local gains—and on exactly which surfaces?
2. Which techniques produce a distinct operational workflow that a user can reliably trigger as a skill?
3. Which behaviors are already model-native enough that an extra skill adds little or causes prompt bloat?
4. What are each technique’s failure modes, transfer limits, tool/context dependencies, cost, and latency?
5. Which evaluation fixtures and graders best predict real usefulness without rewarding verbosity or judge imitation?
6. Which components of `professionalize-prompt` account for its value relative to raw-request and prompt-only baselines?
7. When should a technique be standalone, composed into a domain skill, retained as dated guidance, or rejected?

## Source and method plan

Build a dated surface registry first. For each candidate, trace claims to first-party documentation or a primary paper/artifact, record exact support and contradiction, and separate source claims from inference. Create a technique profile before an evaluation. Pre-register baseline, fixtures, settings, graders, pass criteria, and stop rule. Change one material intervention at a time where practical. Preserve all runs and negative results.

## Synthesis contract

For each candidate, report documented guidance, empirical observation, inference, strongest countercase, transfer limits, unresolved gaps, expected skill value, evaluation readiness, and recommended lifecycle state. Cite claim and source IDs. Every volatile claim requires `as_of` and a refresh trigger.

## Next action

After a named owner approves the run budget, execute `NEXT_ACTION-001.md`: a component-level baseline evaluation of `professionalize-prompt` that establishes the reference bar for later candidates.

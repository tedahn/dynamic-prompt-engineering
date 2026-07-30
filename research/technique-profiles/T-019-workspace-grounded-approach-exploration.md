# Technique profile — T-019 workspace-grounded approach exploration

- **Status:** prototype
- **As of:** 2026-07-29
- **Owner:** Ted Ahn
- **Target surface:** repository-local Codex skill; transfer elsewhere is untested

## Intended behavior

Given a goal that has not yet been reduced to one implementation path, inspect relevant workspace evidence, produce materially distinct approaches including a simple baseline, compare decision-relevant tradeoffs, recommend when justified, and propose the smallest reversible falsification test. Stop before implementation unless separately authorized.

## Trigger and non-trigger

- **Trigger:** Requests for suggestions, strategies, solution paths, tradeoffs, or a recommendation about how to approach a goal in the current topic or workspace.
- **Non-trigger:** A selected approach that only needs implementation; unconstrained ideation with no decision; a consequential decision reserved for an authorized human.
- **Mis-trigger cost:** Extra latency and verbosity, duplicated planning skills, or accidental conversion of advice into action.
- **Miss cost:** Unstructured suggestions, omitted baselines or countercases, weak workspace grounding, and premature implementation.

## Intervention

Apply the shortest repeatable workflow that changes behavior: frame the decision, inspect relevant context, generate three to five distinct approaches including a simple baseline, compare consistent criteria and countercases, recommend or request decisive evidence, propose a reversible test, validate authority restraint, and stop.

## Evidence map

- **Direct artifact:** User-supplied Advisory Mode Review and `skills/explore-approaches/SKILL.md` define the intended contract.
- **Documented local guidance:** `professionalize-prompt` already treats analysis and decisions as a domain but does not define a dedicated approach-exploration workflow.
- **Experimental evidence:** Four independent development forward-test requests produced no unauthorized action. One initial technical response exposed unlabeled numerical proposals and a confounded multi-intervention test; revision R1 added explicit guards and one fresh technical response passed those diagnosed gates. This is development evidence only and does not establish efficacy or adoption readiness.
- **Strongest countercase:** A minimal direct advisory prompt or composed `professionalize-prompt` mode may match quality with less trigger and maintenance overhead.

## Failure and transfer analysis

Watch for cosmetic option variation, invented workspace facts, unlabeled numerical proposals, confounded multi-intervention tests, forced recommendations under missing evidence, criteria dumping, verbosity, high-stakes overreach, and implementation without authority. Measure latency, tokens, cost, reviewer effort, and overlap with existing planning or brainstorming skills. Do not claim transfer beyond tested surfaces.

## Evaluation readiness

The intervention, baselines, development fixtures, hard gates, proposed thresholds, rollback, and promotion approval schema are specified in `research/evaluations/explore-approaches/`. Fresh held-out fixtures and post-evaluation human approval remain incomplete.

## Skill recommendation

Maintain as a repository-local standalone prototype because the user explicitly requested a skill. Promote only if it demonstrates a stable trigger and measurable advisory value over a minimal prompt and the current `professionalize-prompt`; otherwise compose the two routing rules into `professionalize-prompt` or retain them as guidance.

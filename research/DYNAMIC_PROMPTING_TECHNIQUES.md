# Dynamic and request-to-prompt techniques

- **As of:** 2026-07-28
- **Question:** Which techniques can improve a rough request by rewriting it, asking selectively, adapting examples/context, routing execution, or optimizing a prompt against measured outcomes?
- **Rule:** Reported paper gains are paper-scoped. None establishes lossless requirement preservation or current-workspace effectiveness.

## Prompt-time request transformers

| ID | Technique | What it does | Reusable workflow | Evidence boundary |
| --- | --- | --- | --- | --- |
| DP-001 | Dynamic Prompt Refinement Controls | Exposes request-specific context or preference refinements for user selection | Parse invariants → propose 3–5 editable refinements → user selects/edits → compile prompt → preservation check | [Dynamic Prompt Middleware](https://arxiv.org/abs/2412.02357) reports HCI preference in small studies, not downstream accuracy |
| DP-002 | Rephrase-and-Respond (RaR) | Rewrites or expands the question before response; two-model form retains original plus rewrite | Extract invariants → rewrite → bidirectional intent check → execute with original and rewrite | [RaR](https://arxiv.org/abs/2311.04205) reports task/model gains; rewrite-induced intent drift must be measured |
| DP-003 | Selective clarification (CLAM) | Detects ambiguity, asks only when material, then answers after clarification | Enumerate plausible interpretations → estimate decision divergence → ask one targeted question or proceed → log regret | [CLAM](https://arxiv.org/abs/2212.07769) improves mixed QA; simulated-user and QA scope limit transfer |
| DP-004 | Future-turn clarification value | Uses simulated downstream turns to learn when clarification will matter | Predict downstream divergence and resolution value → compare against interaction cost → ask or proceed | [Future-turn modeling](https://arxiv.org/abs/2410.13788) is a training result, not a proven prompt-only recipe |
| DP-005 | Constraint-led prompt compiler | Converts rough intent into a compact goal/context/constraints/output/validation contract | Extract explicit requirements → classify unknowns → compile minimal prompt → round-trip preservation diff | Local synthesis anchored by `professionalize-prompt`; efficacy is the subject of this lab |

## Dynamic examples, retrieval, and routing

| ID | Technique | What it does | Reusable workflow | Evidence boundary |
| --- | --- | --- | --- | --- |
| DP-006 | KATE | Retrieves semantically similar examples for each request | Retrieve → leakage/quality/diversity filter → freeze k and order → compare zero-shot and random | [KATE](https://arxiv.org/abs/2101.06804) is GPT-3-era and vulnerable to near-duplicate leakage |
| DP-007 | EPR | Learns an exemplar retriever from LM-likelihood positive/negative labels | Build example bank → score pairs → train/reuse retriever → retrieve k → held-out test | [EPR](https://arxiv.org/abs/2112.08633) requires labeled pairs and was tested on narrow task families |
| DP-008 | Universal Self-Adaptive Prompting | Routes task type and creates/selects pseudo-demonstrations from unlabeled examples | Classify task → sample unlabeled cases → generate responses → quality/diversity filter → attach demonstrations | [USP](https://aclanthology.org/2023.emnlp-main.461/) risks pseudo-label contamination and model-era transfer |
| DP-009 | Rewrite–Retrieve–Read | Rewrites user language into better retrieval queries before reading evidence | Freeze requirement ledger → generate 1–3 queries → retrieve → answer from evidence → compare original-query baseline | [Query Rewriting in RAG](https://aclanthology.org/2023.emnlp-main.322/) is retrieval-focused; rewrites can discard user constraints |
| DP-010 | Adaptive-RAG routing | Routes requests to no retrieval, single retrieval, or iterative retrieval by complexity | Score complexity/evidence need → route → log confusion/cost → compare always-cheap and always-expensive policies | [Adaptive-RAG](https://arxiv.org/abs/2403.14403) is open-domain QA evidence, not general skill-routing proof |

## Offline or scored prompt optimizers

| ID | Technique | What it does | Reusable workflow | Evidence boundary |
| --- | --- | --- | --- | --- |
| DP-011 | Grader-backed iterative optimization | Rewrites prompts using labeled outputs, critiques, and narrow graders | Snapshot prompt/model/data/graders → optimize → frozen holdout → invariant audit → version/rollback | [OpenAI Prompt Optimizer](https://developers.openai.com/api/docs/guides/prompt-optimizer) warns of input-specific regressions and requires manual review |
| DP-012 | Automatic Prompt Engineer (APE) | Generates multiple instruction candidates and selects by task score | Generate N → reject requirement violations → score on development set → select → untouched test | [APE](https://arxiv.org/abs/2211.01910) used older models/tasks and is exposed to development overfit |
| DP-013 | ProTeGi | Uses failure critiques as textual gradients and beam/bandit search over edits | Sample errors → generate critiques → bounded edit beam → development selection → frozen test | [ProTeGi](https://arxiv.org/abs/2305.03495) adds search cost and multiple-comparison/leakage risk |
| DP-014 | PRewrite | Trains a prompt-rewriter with downstream-task reinforcement learning | Curate prompt/task pairs → define reward plus preservation penalties → train → heldout and shift tests | [PRewrite](https://aclanthology.org/2024.acl-short.54/) is training-intensive and susceptible to reward hacking |
| DP-015 | MIPROv2 | Jointly optimizes instructions and demonstrations across multi-stage LM programs | Freeze program graph → bootstrap demonstrations/proposals → capped search → component and end-to-end holdout | [MIPROv2](https://arxiv.org/abs/2406.11695) is pipeline-specific and relatively costly |
| DP-016 | GEPA | Evolves prompts from trajectory reflection and retains Pareto-complementary lessons | Sample failures → structured reflection → mutation/crossover → Pareto select quality/cost/preservation → holdout | [GEPA](https://arxiv.org/abs/2507.19457) is an author-reported preprint requiring trajectory access and budget |
| DP-017 | OPRO | Prompts an LLM with prior candidates and scores to generate improved candidates | Freeze scorer and budget → iterate candidate/score history → invariant filter → untouched test | [OPRO](https://arxiv.org/abs/2309.03409) reports benchmark gains; optimizer history can overfit the development objective |
| DP-018 | PromptBreeder | Evolves task prompts and the mutation prompts that produce them | Initialize populations → mutate prompts and mutators → fitness/select → preserve diversity → heldout | [PromptBreeder](https://arxiv.org/abs/2309.16797) has large search and reproducibility costs |
| DP-019 | PromptAgent | Uses strategic planning/search to navigate expert prompt edits | Define edit actions → search with task feedback → preserve requirements → budgeted selection → holdout | [PromptAgent](https://arxiv.org/abs/2310.16427) is search-heavy and needs matched-budget baselines |

## Contrary evidence and guardrails

[CLAMBER](https://aclanthology.org/2024.acl-long.578/) reports limited practical ambiguity identification and clarification quality in evaluated models; chain-of-thought and few-shot prompting yielded only marginal improvements and could increase overconfidence. A clarification skill therefore needs false-ask, missed-ambiguity, conflict-resolution, and user-turn metrics—not only answer accuracy.

No optimizer above establishes lossless preservation of explicit user requirements. Every optimization workflow must use an invariant ledger and reject candidates that expand authority, invent requirements, violate execution mode, or lose protected facts even when its task score rises.

## First controlled comparisons

1. **RaR:** closest minimal rewrite comparator to isolate the value of a richer contract.
2. **CLAM:** isolates ask-versus-assume policy and clarification regret.
3. **Dynamic refinement controls:** compares model-selected with user-selected missing requirements.
4. **KATE:** tests request-conditioned examples beyond rewriting.
5. **APE:** simplest generate-and-select optimizer; do not escalate to ProTeGi, MIPROv2, GEPA, PromptBreeder, or PromptAgent until APE clears a preregistered value threshold.

Use the baseline workflows and score protocol in `research/evaluations/professionalize-prompt/`. Primary metrics are explicit-requirement recall and precision, invented-requirement rate, downstream task success, authority expansion, clarification regret, user turns, tokens, cost, and latency.

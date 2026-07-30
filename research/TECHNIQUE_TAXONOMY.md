# Technique taxonomy

- **As of:** 2026-07-30
- **Purpose:** map technique families to possible skill forms without treating source claims as local proof
- **Anchor:** `professionalize-prompt` is the reference artifact to evaluate, not a default template for every skill

## Candidate map

| ID | Technique family | Possible skill form | Evidence base | Initial state | First falsifier |
| --- | --- | --- | --- | --- | --- |
| T-001 | Outcome-first specification and ambiguity policy | `prompt-contract` or the existing `professionalize-prompt` | Current OpenAI guidance plus direct local artifact | Sourced; anchor evaluation blocked | A minimal direct specification matches it on usefulness with less user effort and no added risk |
| T-002 | Redundancy, contradiction, and obsolete-instruction detection | `prompt-linter` / `lean-prompt-pruner` | Vendor anti-pattern guidance and local ecosystem gap | Specified; needs precision eval | Linter overcorrects valid constraints or fails to beat manual review |
| T-003 | Surface-specific example selection | `exemplar-curator` | OpenAI, Anthropic, Google guidance; KATE and Auto-CoT | Sourced; transfer-sensitive | Modern zero-shot baselines match examples or leakage/overfit erases gains |
| T-004 | Model/product control calibration | internal `professionalize-prompt` model-profile gate | Current first-party surface guidance | Prototype challenger; behavior unscored | Prompt-level adaptation adds no value beyond settings or cannot stay current |
| T-005 | Relevance selection, ordering, retrieval, compaction, and token budgeting | `context-composer` | Anthropic context guidance; RAG; Lost in the Middle | Sourced; priority candidate | A simple uncurated context baseline matches it across held-out tasks |
| T-006 | Output schema plus semantic validation and repair | `output-contract-engineer` | Gemini structured-output guidance and local gap | Sourced; priority candidate | Schema validity fails to improve semantic success or repair adds regressions |
| T-007 | Tool descriptions, schemas, response shaping, and errors | `tool-contract-engineer` | Anthropic tool guidance plus Gemini functions | Sourced; priority candidate | Tool linting does not improve task success or increases tool-selection errors |
| T-008 | Safe/reversible autonomy and confirmation gates | `authority-boundary` | Current agent-prompt guidance and local governance | Specified; safety-critical | Added policy either fails to prevent unsafe actions or blocks ordinary in-scope work |
| T-009 | Sequential/parallel/direct/programmatic tool routing | `orchestration-router` | Gemini functions; ReAct; local orchestration patterns | Sourced; needs tool harness | Matched-budget direct execution is as good or more reliable |
| T-010 | Decompose then compose | `decomposition-planner` | Least-to-Most and Self-Discover | Experimental outside paper tasks | Decomposition errors propagate or modern direct baselines match quality at lower cost |
| T-011 | Executable reasoning with deterministic checks | `code-backed-reasoner` | PAL and direct computation patterns | Experimental; bounded domains | Wrong-code risk or sandbox overhead outweighs accuracy gains |
| T-012 | Independent verification with tools or isolated questions | `independent-verifier` | CRITIC and Chain-of-Verification | Experimental; priority study | Verifier is correlated with generator or false corrections exceed declared threshold |
| T-013 | Criterion-driven iterative refinement | `refinement-loop` | Self-Refine plus negative self-correction evidence | Experimental; guarded | Intrinsic feedback degrades held-out reasoning or fails cost/iteration stop rules |
| T-014 | Baselines, fixtures, graders, holdouts, promotion, and rollback | `prompt-eval-lab` | OpenAI optimizer/evals; Anthropic agent evals; APE/DSPy/TextGrad | Sourced; enabling priority | Workflow cannot predict human usefulness or overhead prevents ordinary adoption |
| T-015 | Sampling, aggregation, and deliberative search | `deliberation-budgeter` | Self-Consistency and Tree of Thoughts | Experimental; cost-sensitive | A single higher-quality run matches results at lower cost/latency |
| T-016 | Planner/generator/evaluator long-run harness | `long-run-harness` | Anthropic harness report and local artifact pipelines | Sourced for specific surfaces; not universal | Stronger model-native execution makes the harness pure overhead |
| T-017 | Multi-agent specialization, debate, and handoffs | `dynamic-skill-router` / multi-agent router | AutoGen infrastructure; mixed multi-agent debate evidence | Experimental; low priority | Matched-token single-agent baseline wins or correlated errors persist |
| T-018 | Execution-grounded, retrievable skill libraries | `skill-library-operator` | Voyager in Minecraft plus local skill ecosystem | Experimental; environment-specific | Skills do not replay reliably, collide in identity, or fail transfer/safety tests |

## Recommended research queue

1. **Establish the measurement substrate:** specify T-014, then run `NEXT_ACTION-001.md` against T-001. Do not build another rewriting skill until the anchor is ablated.
2. **Study distinct operational leverage:** T-005 context composition and T-007 tool contracts have recognizable triggers, concrete artifacts, and strong current documentation.
3. **Add quality control:** test T-012 independent verification only with an external oracle or tool and an explicit false-correction metric.
4. **Keep expensive techniques conditional:** T-015, T-016, and T-017 must beat matched-cost simpler baselines; stronger models may reduce their value.
5. **Retain guidance where a skill is unnecessary:** example count, reasoning effort, and formatting defaults belong in T-004 surface records unless a measured routing workflow adds value.

The request-to-prompt and dynamic-prompting extensions are maintained in `research/DYNAMIC_PROMPTING_TECHNIQUES.md`. Its first controlled comparisons are RaR, selective clarification, dynamic refinement controls, KATE, and APE against the frozen `professionalize-prompt` baselines.

## Cross-cutting anti-patterns

Reject universal model-agnostic recipes, repeated absolute instructions, hidden-chain-of-thought requests, blanket tool use, maximal reasoning without evidence, unbounded tool output, schema-only correctness, self-critique without an external signal, premature multi-agent complexity, benchmark-to-production transfer, and vibe-based evaluation.

## Promotion gate

Version the model, surface, date, tools, and settings; preserve a simpler baseline; change one material intervention where practical; run representative normal, edge, adversarial, and prior-failure cases over repeated trials; combine deterministic, model, and calibrated human graders; measure quality, safety, latency, tokens, cost, and critical regressions; verify on held-out cases; require named human approval and rollback.

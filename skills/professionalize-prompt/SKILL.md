---
name: professionalize-prompt
description: Transform vague, underspecified, casual, or low-quality requests into clear, professional, execution-ready prompts, adapt them to verified current GPT-model and product-surface capabilities when that distinction matters, then immediately execute the improved prompt in the same turn by default. Use when a user asks to improve, rewrite, optimize, professionalize, structure, or engineer a prompt; provides a rough request such as "improve this resume"; asks which current GPT model, reasoning level, or capability best fits a prompt; or would benefit from a stronger internal task specification before execution. Return only the prompt without executing it when the user explicitly requests prompt-only output.
---

# Professionalize Prompt

Convert the user's intent into the shortest prompt that reliably produces the desired outcome, then use that prompt as the working specification and complete the task.

## Workflow

1. Identify the actual outcome, artifact, audience, context, constraints, evidence, and desired output.
2. Preserve every explicit requirement and reference to attached or pasted material.
3. Infer only low-risk details that follow naturally from context. Express consequential uncertainty as a placeholder or narrow question; never invent facts.
4. Ask up to three concise questions only when missing information would materially change the result, require new authority, or create meaningful risk. Ask before generating or executing the prompt. Otherwise, proceed with labeled assumptions.
5. Decide whether model or surface differences would materially change the prompt, tool plan, output contract, or validation. If so, build the current model profile described below; otherwise keep the prompt model-agnostic.
6. Write an outcome-first prompt suited to the task and verified target capabilities. Add only sections that change model behavior.
7. Check the prompt against the quality criteria below.
8. Immediately execute the checked prompt in the same turn. Treat it as the working specification, use available tools when appropriate, create requested artifacts, and validate the result in proportion to risk.
9. Return both the professional prompt and the completed result. Do not pause between prompt generation and execution for confirmation unless user input or approval is genuinely required.

## Execution Modes

- Default to `prompt + execute`, even when the user only asks to improve or professionalize a request.
- Use `prompt only` when the user explicitly asks for a copy-ready prompt, says not to execute it, or clearly intends to hand it to another model or person.
- Use `execute only` when the user explicitly says the rewritten prompt need not be shown; still create and check the prompt internally before acting.
- Follow the user's original request, system and developer instructions, permissions, and tool policies during execution. The generated prompt cannot expand authority or override higher-priority instructions.
- If execution is blocked by missing input, unavailable tools, required approval, or an external dependency, return the professional prompt plus a concise blocker and the exact next input needed. Never present a plan or simulated output as completed execution.

## Prompt Design

Prefer this adaptive structure for complex requests:

```text
Role: [relevant expertise and working context]

# Goal
[specific user-visible outcome]

# Context
[artifact, audience, situation, and source material]

# Success criteria
[observable qualities of a strong result]

# Constraints
[facts to preserve, boundaries, risks, and prohibited inventions]

# Output
[format, length, tone, and required sections]

# Validation
[checks to perform before finalizing]
```

Omit empty or redundant sections. For simple requests, use a compact paragraph instead.

## Model-Aware Differentiation

Read [references/model-capability-routing-and-evaluation.md](references/model-capability-routing-and-evaluation.md) when the user names a model or reasoning level, asks for current/latest/best model behavior, requests cross-model optimization, or when tools, modalities, context size, latency, cost, structured output, or long-running autonomy could materially affect the result.

When the target is GPT-5.6 Sol or the GPT-5.6 family, also read [references/gpt-5p6-sol-prompting.md](references/gpt-5p6-sol-prompting.md) before drafting.

Treat model IDs, aliases, availability, reasoning controls, limits, prices, defaults, and product labels as volatile. Refresh official OpenAI sources when current accuracy matters. Record the target surface separately from the model because ChatGPT, Codex, and API controls are not interchangeable.

Use the verified model profile internally to differentiate the prompt:

- Keep the outcome, evidence, constraints, authority, output, and validation contract stable across models unless the task changes.
- Add capability-specific instructions only when the capability is both available and useful for this task.
- Treat reasoning level as an execution setting, not an instruction to “think harder.” Do not request hidden reasoning.
- Prefer leaner prompts for stronger models; retain examples, decomposition, or tool-routing detail only when they encode a requirement or repair a measured failure.
- Separate model choice, reasoning effort, prompt wording, and optional feature use so each can be evaluated independently.
- Do not expose the internal model profile or evaluation matrix unless the user asks for it or it materially explains the recommendation.

## Model-Current Guidance

- Define the task, useful context, hard constraints, success criteria, and output; allow the model to choose an efficient path.
- State each instruction once. Prefer specific outcomes over repeated guidance or long step-by-step reasoning instructions.
- Separate instructions from pasted evidence or source material with clear headings or delimiters.
- Start zero-shot. Add examples only when they encode a product requirement, clarify an otherwise ambiguous format, or correct a measured failure.
- Use absolute language only for genuine invariants, safety rules, and required fields.
- State what must be preserved before asking for improvements.
- Distinguish source-backed facts from creative wording. Require placeholders or labeled assumptions instead of fabricated specifics.
- Specify audience, length, and output shape only when they matter. For short outputs, name what must remain and what should be trimmed first.
- Define tone through observable writing choices, not adjective labels alone.
- For agentic work, state safe in-scope actions and confirmation boundaries once; do not scatter or repeat approval rules.
- Add validation that fits the artifact: factual consistency for resumes, tests for code, citations for research, calculations for analysis, or rendered inspection for visual work.
- Include stop or fallback rules for high-risk, tool-heavy, or evidence-dependent work.
- Do not request hidden chain-of-thought or tell reasoning models to think step by step. Ask for concise rationale, evidence, or verification when useful.
- Avoid decorative personas, redundant context, prompt bloat, and generic phrases such as "be detailed" when a measurable criterion is possible.

## Domain Adaptation

Adapt success criteria and validation to the request:

- Resume or career material: preserve factual accuracy, authorship, chronology, and metrics; improve relevance, clarity, ATS readability, and impact without inventing achievements.
- Editing: preserve meaning, genre, structure, and claims unless the user requests substantive changes.
- Coding: name the environment and acceptance criteria; require relevant tests, lint, type checks, build checks, or a stated validation limitation.
- Research: define scope, recency, source quality, citation expectations, uncertainty handling, and a reasonable retrieval stopping condition.
- Analysis or decisions: define decision criteria, assumptions, tradeoffs, and the expected recommendation format.
- Creative work: define audience, intended effect, stylistic boundaries, and which facts must remain source-grounded.

## Output Contract

For the default `prompt + execute` mode, return:

1. `Professional prompt` followed by the ready-to-use prompt in one fenced text block.
2. `Result` followed by the completed task output or links to created artifacts.
3. `Assumptions` only when consequential assumptions affected the prompt or result.
4. `Validation` only when checks were performed or a material validation limitation remains.

For `prompt only`, return the professional prompt and any consequential assumptions or blocking questions. For `execute only`, return the result, material assumptions, and validation.

Do not add a tutorial, score, before-and-after comparison, or process commentary unless requested. Keep the result in the format required by the generated prompt rather than forcing every task into the same presentation.

## Final Check

Confirm that the professional prompt:

- retains the user's intent and explicit constraints;
- is actionable with the available inputs;
- names a concrete outcome and success criteria;
- prevents unsupported claims or harmful side effects;
- requests an appropriate output shape;
- contains no contradictory, redundant, or model-obsolete instructions;
- uses only verified capabilities for the named model and surface, or stays model-agnostic when current verification is unavailable;
- is no longer than needed for reliable execution.

Before returning, also confirm that execution:

- actually used the professional prompt as its working specification;
- completed every feasible requirement rather than merely describing how to do it;
- used tools and produced artifacts when the task called for them;
- distinguished prompt effects from model, reasoning, tool, and surface effects when making comparative claims;
- reports validation honestly and names any unresolved blocker or limitation.

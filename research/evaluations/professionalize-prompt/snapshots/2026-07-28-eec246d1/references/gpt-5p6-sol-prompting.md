# GPT-5.6 Sol Prompting Reference

Checked against official OpenAI sources on 2026-07-27. Model behavior, product controls, and availability are time-sensitive; refresh the sources before making current claims.

## Source precedence

1. Prefer the current GPT-5.6 model guidance for Sol-specific behavior.
2. Use the ChatGPT help article for model-picker and reasoning-level behavior in ChatGPT.
3. Use general ChatGPT and Academy guidance for durable prompting basics.
4. When current model-specific guidance conflicts with older general advice, follow the newer model-specific guidance and note the surface: ChatGPT UI, Codex, or API.

## Prompt construction

- Lead with the outcome. Supply the task, relevant context, hard constraints, success criteria, required evidence, and output format.
- Keep prompts lean. State each rule once; remove repeated instructions, generic role-play, and examples that do not encode a requirement or fix a measured gap.
- Let Sol infer the working path. Prescribe steps only when order, compliance, reproducibility, or a fragile operation makes the method part of the requirement.
- Use headings, Markdown fences, or XML-style tags to separate instructions, source material, examples, and output schemas.
- Start zero-shot. Add a minimal example only when prose cannot unambiguously define the desired behavior or format.
- Name priorities when they compete, such as accuracy over speed or preserving required facts over brevity.
- For agentic tasks, define authority once: safe local actions, actions requiring confirmation, and the boundary against destructive, external, costly, or scope-expanding work.
- Tell the model which ambiguity should trigger a question. Let low-risk gaps resolve through labeled assumptions.

## Output control

- Replace vague brevity instructions with a preservation order: required facts, decisions, evidence, caveats, and next actions stay; repetition, generic introductions, reassurance, and optional background go first.
- Define tone with observable choices: directness, acknowledgment of problems, degree of reassurance, jargon level, and whether to include a sign-off.
- Request a schema, table, headings, or JSON only when the downstream use requires it.
- In API workflows, prefer the `text.verbosity` control for default detail and reserve the prompt for task-specific length and content requirements.

## Reasoning and model controls

- In ChatGPT, Medium, High, Extra High, and Pro are product-level reasoning choices. Select the appropriate level for the task rather than bloating the prompt with requests to reason harder.
- Keep the same outcome-focused prompt across standard and Pro modes. Do not add requests for hidden chain-of-thought, "think step by step," or multiple candidate answers unless candidates are themselves required.
- Treat reasoning level as an execution setting, not prompt content. Compare higher-effort modes on representative difficult tasks instead of assuming more effort is always better.
- GPT-5.6 Sol is best suited to complex professional work; use lower-cost family variants only when the execution surface supports them and cost or throughput is part of the decision.

## Tools and long-running work

- Add tool-routing instructions only when the task shape needs them. Specify the bounded stage, eligible tools, required result schema and evidence, concurrency, retry limit, stopping condition, and handoff to direct judgment.
- Keep approval-bearing, side-effecting, or semantically adaptive calls direct rather than embedding them in a fixed programmatic route.
- Validate the final user-facing answer separately from intermediate tool or program output.

## Evaluation loop

1. Define observable success criteria and representative tasks, including edge cases and prior failures.
2. Establish a baseline prompt and output.
3. Change one instruction group, example set, or tool exposure at a time.
4. Compare correctness, completeness, required evidence, latency, and cost as relevant.
5. Retain only changes that improve the target behavior without regressions.
6. Manually review optimized prompts before production use; automated optimization can regress on particular inputs.

## Avoid

- Repeating the same instruction in multiple sections.
- Decorative expertise personas that do not change decisions or standards.
- Generic demands such as "be detailed," "be creative," or "think harder" without an observable requirement.
- Chain-of-thought requests or prescribed internal reasoning.
- Few-shot examples by default.
- Broad tone adjectives without concrete writing behavior.
- Treating current ChatGPT availability, reasoning levels, or API parameters as permanent facts.

## Official sources

- [GPT-5.6 model guidance](https://developers.openai.com/api/docs/guides/latest-model)
- [GPT-5.6 in ChatGPT](https://help.openai.com/en/articles/20001354-gpt-56-in-chatgpt)
- [Prompt engineering best practices for ChatGPT](https://help.openai.com/en/articles/10032626-prompt-engineering-best-practices)
- [OpenAI Academy prompting guide](https://academy.openai.com/en/public/clubs/work-users-ynjqu/resources/prompting)
- [Reasoning model prompting best practices](https://platform.openai.com/docs/guides/reasoning-best-practices)
- [Prompt optimizer](https://developers.openai.com/api/docs/guides/prompt-optimizer)
- [Evaluation best practices](https://developers.openai.com/api/docs/guides/evaluation-best-practices)

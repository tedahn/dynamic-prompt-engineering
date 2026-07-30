# Model Capability Routing and Evaluation

Use this reference to adapt a prompt to a named or current GPT model without turning model selection, reasoning effort, and prompt design into one confounded decision.

## Resolve the current model profile

Before drafting, record only the fields that can change the work:

- target product surface: ChatGPT, Codex, Work, or API;
- exact model ID or user-visible label and whether it is pinned, aliased, or automatically selected;
- workload role: frontier quality, balanced, fast/high-volume, or specialized;
- supported reasoning controls and the selected or effective default;
- relevant tools, modalities, structured-output support, context/output limits, state, and caching behavior;
- latency, token, and cost constraints;
- authoritative source URL, `as_of` date, and refresh trigger.

For `latest`, `current`, `recommended`, or an unspecified target, use the `openai-docs` latest-model resolver when available, then fetch the exact returned migration and prompting-guide URLs. For an explicitly named model, preserve that target and fetch its exact official model guidance. For availability, verify the requested product surface and account/workspace separately; documentation availability does not prove that a model is enabled for the user.

Build the evaluation candidate set from models that are actually callable on the active surface. Prefer runtime model metadata, an authenticated API model list, or the visible product model picker when available. Intersect that set with the documented models appropriate to the workload role, retain the current model as a baseline, and record excluded or inaccessible models. If the surface cannot enumerate access, state that availability is unconfirmed instead of treating the public catalog as the user's model list.

If current official guidance is unavailable, use the bundled model reference only as a labeled fallback. Do not invent model mappings, supported features, limits, pricing, defaults, or equivalence between product labels and API values.

## Choose the smallest useful differentiation

Keep the prompt model-agnostic when model differences do not change execution. Otherwise adapt only the affected layer:

| Layer | Adapt when | Prompt treatment |
| --- | --- | --- |
| Model role | Quality, latency, throughput, or cost changes the decision | Recommend a starting tier, but preserve the task contract |
| Reasoning | Difficulty or reliability may benefit from more model work | Set it in the execution surface; do not add “think harder” prose |
| Tools | Retrieval, code execution, computer use, or external actions are required | State tool choice criteria, evidence requirements, and authority boundaries |
| Modalities/context | Images, PDFs, audio, video, or long inputs are material | Define which evidence to inspect and how to handle truncation or missing input |
| Structured output | A parser or downstream contract depends on shape | State the schema and semantic checks; do not rely on valid syntax alone |
| Long-running work | The task spans stages or resumptions | State the current layer, completion condition, durable state, and handoff requirements |

Do not add every supported capability to every prompt. Capability availability is not evidence that using it improves the workload.

## Current GPT-5.6 family starting map

As of 2026-07-30, use this only as a starting hypothesis and refresh it before model-current claims:

- `gpt-5.6-sol`: frontier-capability tier for difficult coding, research, analysis, design, computer-use, and other quality-first work.
- `gpt-5.6-terra`: balanced capability, speed, and cost for everyday work.
- `gpt-5.6-luna`: fastest, lowest-cost family tier for high-volume or latency-sensitive work.
- ChatGPT standard conversations expose Sol reasoning choices where eligible; Terra and Luna availability differs across Work, Codex, and API.
- GPT-5.6 API reasoning effort supports `none`, `low`, `medium`, `high`, `xhigh`, and `max`; product labels such as Extra High, Pro, or Codex Ultra belong to their surface and must not be silently rewritten as API values.
- Pro is an execution mode in the API, independent of reasoning effort. Do not create a different prompt merely to announce Pro or maximum effort.

Treat exact availability, defaults, limits, and pricing as volatile. Verify them live instead of copying this snapshot into user-facing output.

## Evaluate prompt and model capability separately

Define the decision first. “Use the model's full capability” means test the applicable capability axes with observable success criteria; it does not mean enable every feature or maximum effort.

Select representative capability cases for the workload. Cover core instruction following and reasoning first, then add only applicable cases for coding, retrieval and tool use, structured output, multimodal input, long context, computer use, or long-running state. A model does not fail an irrelevant or unavailable capability; mark that cell not applicable or unavailable.

Use this staged matrix:

1. **Prompt effect:** compare the raw request, a minimal static specification, and the professionalized prompt on the same model, surface, effort, tools, and source material.
2. **Model effect:** run the same winning prompt across relevant model tiers while keeping compatible settings constant.
3. **Reasoning effect:** compare the preserved/default effort with one lower level; add a higher or maximum-effort cell only for hard quality-first cases.
4. **Capability effect:** isolate tools, multimodal input, long context, structured output, state/caching, or Pro mode one at a time when the workload uses them.
5. **Replication:** repeat on held-out tasks and prior failures before recommending a durable default.

Do not compare incompatible surfaces as though the model alone changed. Record the exact model returned for aliases and any unavailable, rate-limited, or failed cell as missing evidence rather than a zero score.

Measure the smallest set that can change the decision:

- task success and completeness;
- constraint, evidence, and factual fidelity;
- tool-selection and tool-result correctness;
- structured-output semantic validity;
- latency, input/output/reasoning tokens, and cost when available;
- reliability across trials and adversarial or edge cases;
- unnecessary clarification, prompt bloat, side effects, and regressions.

Change one material variable at a time. Freeze prompts, fixtures, settings, graders, and stopping rules before paid or large runs. Prefer deterministic checks where possible, blind comparative review where judgment is required, and named-human approval before promoting a new default.

## Prompt revision rule

Start from the shortest prompt that preserves the task contract. Make a model-specific edit only when official guidance or a measured failure supports it. Remove or revise one instruction group at a time, rerun the affected cases, and keep the change only when it improves the target behavior without an unacceptable regression.

## Official sources

- [Latest-model resolver target and GPT-5.6 model guidance](https://developers.openai.com/api/docs/guides/latest-model)
- [OpenAI API model catalog](https://developers.openai.com/api/docs/models)
- [GPT-5.6 prompting guidance](https://developers.openai.com/api/docs/guides/prompt-guidance-gpt-5p6)
- [Upgrade to GPT-5.6 Sol](https://developers.openai.com/api/docs/guides/upgrading-to-gpt-5p6-sol)
- [GPT-5.6 in ChatGPT](https://help.openai.com/en/articles/20001354-gpt-56-in-chatgpt)
- [Reasoning guide](https://developers.openai.com/api/docs/guides/reasoning)
- [Prompt optimizer](https://developers.openai.com/api/docs/guides/prompt-optimizer)
- [Evaluation best practices](https://developers.openai.com/api/docs/guides/evaluation-best-practices)

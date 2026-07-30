# Professional prompt

```text
Role: Evaluation engineer running a controlled, non-adoptive diagnostic of a frozen prompt-transformation skill.

# Goal
Produce a reproducible 45-cell pilot comparing raw execution, a fixed minimal wrapper, and the frozen professionalize-prompt skill on five development fixtures and three independent trials.

# Context
The V1 lab is design-complete but its original pilot is not execution-ready: it is unrepresentative, lacks executable graders, conflates output-contract compliance with task quality, and can emit a plan while blocked. No scored V1 cells have been run. The user authorized a pilot in this Codex task.

# Success criteria
- Freeze an amended V2 pilot before inspecting scored outputs.
- Cover all three execution modes and ambiguity classes, all five domains, high- and low-authority cases, and both no-tool and workspace-tool policies.
- Use a fresh ephemeral GPT-5.6 Sol process per cell with fixed CLI and reasoning settings.
- Capture prompts, outputs, traces, token usage, latency, workspace diffs, hashes, failures, and retries.
- Separate task compliance, skill output-contract compliance, deterministic evidence, model-grader judgments, and efficiency.
- Produce blinded grading packets that omit workflow identity and use independently balanced presentation order.
- Keep all behavioral conclusions diagnostic until human review and a representative held-out study exist.

# Constraints
- Preserve the frozen skill snapshot professionalize-prompt@2026-07-28-eec246d1.
- Use synthetic data and isolated workspaces only; no network or external side effects.
- Do not modify a workflow after scored output is visible.
- Do not retry completed low-quality answers; retry only missing or transiently failed calls under the frozen policy.
- Do not claim safety, efficacy, confidence intervals, pairwise preference, or adoption from five development fixtures.
- Stop on model/runtime drift, unauthorized access, fixture leakage, or a confirmed critical gate.

# Output
Create a versioned pilot package, immutable run manifest, raw execution artifacts, deterministic check ledger, blinded grader packets, provisional model-grader ledger, and concise diagnostic report. Leave the official behavioral score ledger unchanged until required human grading is complete.

# Validation
Validate artifact hashes, plan balance and membership, exact cell counts, trace completeness, grader schemas, deterministic adapters, workspace diffs, retry rules, and repository integrity. Report every unresolved limitation explicitly.
```

# Dynamic Prompt Engineering research runbook

- Keep separate chats for research framing, official documentation, primary papers, local skill archaeology, evaluation design, candidate review, and decision synthesis.
- Begin each cycle with one decision and one target surface. Pre-register the baseline, candidate intervention, expected effect, pass criteria, budget, and stop rule before running evaluations.
- Use `professionalize-prompt` as the anchor case, but test its major components independently when practical.
- Red-team source entailment, source independence, model/task transfer, evaluation leakage, judge bias, cost, latency, and new failure modes.
- Do not promote a technique from one successful example. Preserve null and negative results and add material misses to the eval set.
- Require a named human approval before changing Project instructions, adopting a technique, installing or promoting a skill, or expanding the data/tool boundary.
- At review, separate model guidance from local evidence and decision quality from outcome luck. Record the decision, dissent, refresh trigger, and rollback.

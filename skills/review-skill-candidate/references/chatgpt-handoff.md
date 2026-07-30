# ChatGPT reviewer handoff

Use this procedure only after verifying the actual ChatGPT account, model, memory, file, and connector surfaces. Product controls are volatile; record what was observed rather than assuming isolation.

## Prepare once

1. Freeze the target with `review_bundle.py init` outside ChatGPT, recording every target or packet author through repeatable `--packet-author-id` arguments.
2. Run the pre-upload safety checklist. Remove credentials, private paths, regulated data, raw logs, and unrelated files.
3. Give every reviewer the same immutable `manifest.json`, `context-pack.md`, copied submission schema, its own assignment, and access to the exact base/head target.
4. Record the ChatGPT surface, selected model label, date, memory/project setting, tools/connectors, and any file limits in the reviewer submission.

## Preserve independence

- Use three separately initialized reviewer contexts that cannot see one another’s conversations or files.
- Do not place reviewer outputs in shared project memory, shared instructions, or a common uploaded folder before all three close.
- Do not include expected findings, seeded labels, author explanations, proposed fixes, or another reviewer’s scope decisions.
- If the product configuration may share memory or context across reviewers, set `independent_context` to false and treat the cycle as contaminated rather than guessing.

## Reviewer prompt

Paste the role assignment as the instruction layer. Attach the frozen context and schema as evidence. Ask for the JSON submission only; do not request hidden reasoning. Require concise rationale, exact file/line evidence, counterevidence, confidence, limitations, and explicit not-reviewed scope.

## Adjudication and human decision

After all three submissions are exported and hashed, start a fourth context for adjudication under an identity distinct from every reviewer and manifest packet author. Provide only the frozen packet, raw submissions, their hashes, the adjudication schema, and the role card. Run deterministic bundle validation outside ChatGPT. Present the resulting packet to the named human; never ask ChatGPT to mark its own review approved.

## Failure handling

Stop and record `blocked` when the target cannot be pinned, files are truncated, a connector returns changing content, context sharing cannot be excluded, a reviewer output is malformed after one repair attempt, or protected data would need to be uploaded. Switch to local read-only review or request a narrower packet instead of weakening the gate.

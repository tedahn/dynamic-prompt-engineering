# Technique profile — tool contract engineer

- **Technique ID:** T-007
- **Lifecycle state:** sourced
- **Owner:** Project owner (identity unresolved)
- **As of:** 2026-07-28
- **Review trigger:** tool schema, calling protocol, model, response limit, or error contract changes

## Intended behavior

Design and lint tool names, descriptions, schemas, response shapes, pagination, errors, and examples so an agent selects and uses tools reliably without flooding context. The falsifiable claim is that a reviewed contract improves end-task success and reduces tool errors or wasted tokens versus the existing contract.

## Trigger and non-trigger

Trigger when building or diagnosing function/MCP tools, ambiguous tool selection, invalid arguments, oversized responses, opaque errors, or multi-step calling. Do not trigger for a stable single-purpose tool with a measured clean baseline.

## Intervention

Return a versioned tool-contract review covering WHEN/WHAT descriptions, parameter semantics, strictness, defaults, response filtering, pagination/truncation, actionable errors, examples, authority boundary, and evaluation cases. Do not change an external tool without approval.

## Evidence map

- Anthropic describes context-efficient tool responses, filtering/pagination/truncation, actionable errors, and evaluation (`C-005`, `S-009`).
- Gemini documents application-mediated sequential and parallel function-calling flows (`C-008`, `S-013`).
- Local generalization across Codex tools is an inference pending evaluation.

## Failure and transfer analysis

Risks include overconstrained schemas, brittle descriptions, semantic errors that pass schema validation, permission confusion, excessive examples, hidden tool coupling, and vendor-specific assumptions.

## Evaluation readiness

Compare existing and candidate contracts on normal, ambiguous, invalid-input, pagination, and recovery tasks. Score correct tool selection, argument validity, semantic success, calls, errors, tokens, latency, and unapproved actions. Review raw outcomes and transcripts.

## Skill recommendation

Priority candidate after overlap review with API- and CLI-contract skills. Keep contract editing approval-bearing and separate from analysis.

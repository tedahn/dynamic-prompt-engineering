# Replacement preflight approval 001

- **Status:** pending named-human approval
- **Requested by:** evaluation harness after infrastructure contamination
- **Requested cells:** three discarded replacement preflight cells
- **Scored cells requested:** zero additional
- **Data boundary:** unchanged synthetic fixtures and isolated workspaces
- **Provider/runtime:** unchanged frozen bundled Codex CLI and GPT-5.6 Sol alias

## Reason

The originally approved three preflight cells completed, then revealed that the CLI populated `config.toml` and system skills into the shared temporary `CODEX_HOME`. The scored phase stopped before executing any scored cell. The runner now gives every cell a fresh runtime home containing only an authentication link and deletes it after the invocation. The preflight registry validator was also corrected to verify the actual three workflow-fixture pairs.

Because the repaired runner is a newly frozen artifact, the prior preflight cannot validate it. Repeating three discarded cells would exceed the original preflight-cell budget and therefore requires explicit named-human approval.

## Approval statement

To approve, the named human should record: “Approve REPLACEMENT-PREFLIGHT-001 for exactly three discarded preflight cells under the existing synthetic-data and no-external-side-effect boundary.”

Approval does not authorize additional scored cells, adoption, installation, or production promotion.

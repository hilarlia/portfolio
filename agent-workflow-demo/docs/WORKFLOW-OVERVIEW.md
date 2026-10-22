# Agent workflow overview

This directory contains a sanitized, code-focused example of a multi-agent research workflow. It deliberately excludes manuscripts, version archives, run outputs, retrieved sources, private prompts, model responses, and personal configuration.

## Sequence

1. **Scout** retrieves a bounded set of verifiable sources and records provenance.
2. **Researcher** proposes supported corrections or developments without novelty or score gates.
3. **Writer** integrates the handoff in a disposable snapshot; source checks, file allowlists, invariants, and isolated builds protect publication.
4. **Correcter** runs after publication, provides read-only advisory feedback, and cannot invalidate the completed version.

Run comments, when provided, reach Scout, Researcher, and Writer: Scout uses research topics to focus source retrieval, Researcher treats them as analysis priorities, and Writer may use them as editing context alongside validated ideas. With no research-topic comment, Scout follows its default plan; comments are guidance, never evidence.

## Safeguards

- Strict JSON handoffs are bound to run IDs, input hashes, and checkpoints.
- Role-specific permissions limit reads, writes, tools, and network access.
- Writer changes are checked against an allowlist and manuscript invariants.
- Builds occur in an isolated Nono workspace; version publication follows successful validation and both build variants.
- Sequential run IDs and lock-safe allocation support reliable resume.
- Tests use synthetic fixtures and run offline.

The included provider and model settings are placeholders, not operational credentials or a ready-to-run provider profile. See `paper_workflow/README.md` and `agent-workflow.json`.

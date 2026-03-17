---
name: token-pruner
description: Reduce LLM context cost for structured payloads. Use when the user wants to shrink JSON, NDJSON, API responses, tabular exports, or command output before sending it to Codex or Claude Code, especially with jq, TOON, qsv, or jc.
owner: b.wen
last_updated: 2026-03-17
source_of_truth: true
---

# Token Pruner

Use this skill when the expensive part of the context is structured data, not source code.

## Quick Start

1. Resolve the skill directory from this `SKILL.md`.
2. Probe local tooling:

```bash
python3 "<skill-dir>/scripts/token_pruner.py" probe
```

3. Profile the payload before pruning:

```bash
python3 "<skill-dir>/scripts/token_pruner.py" profile --input "<path-to-json>"
```

4. Prune semantically first, then choose the output format:

```bash
python3 "<skill-dir>/scripts/token_pruner.py" prune \
  --input "<path-to-json>" \
  --keep-keys id,name,status,created_at \
  --head 50 \
  --format auto
```

## Workflow

### 1) Profile Before Pruning

- Start with `profile` to detect depth, row count, field uniformity, and whether TOON is likely to help.
- Treat `format` choice as the last step, not the first step.

### 2) Remove Semantic Noise First

- Prefer `jq` or the built-in `--keep-keys`, `--drop-keys`, `--head`, and `--sample` controls before changing the wire format.
- Preserve identifiers, timestamps, status fields, and enough evidence for the model to reason correctly.
- Drop blobs such as verbose markdown bodies, HTML, embeddings, base64, stack traces, and duplicated nested metadata unless the user explicitly needs them.

### 3) Pick the Rendering Format

- Default to compact JSON when the payload is nested, irregular, or already aggressively filtered.
- Prefer TOON only when the payload is mostly an array of similar objects and `toon` is installed.
- For tabular sources, prune with `qsv` first and only then consider JSON or TOON.
- For command output, normalize with `jc` first when available.

### 4) Report Tradeoffs Clearly

- Say what was removed, what was sampled, and which fields were preserved.
- Do not claim token savings without measurement or at least a stated estimate.
- If `toon` is available, use its `--stats` flag when the user wants a concrete before/after comparison.

## Guardrails

- Do not use this skill for normal source-code reading unless the source has already been turned into structured metadata.
- Do not hide critical evidence just to save tokens.
- Avoid TOON for deeply nested or semi-uniform payloads unless measured results prove it helps.
- When in doubt, return compact JSON plus a short summary instead of an exotic format.

## References

- `references/implementation-strategy.md`
- `references/tooling-matrix.md`

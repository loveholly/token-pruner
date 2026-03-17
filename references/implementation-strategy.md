---
owner: b.wen
last_updated: 2026-03-17
source_of_truth: true
---

# Token Pruner Strategy

## Background

The main token waste for coding agents often comes from large structured payloads: API responses, search results, test matrices, event logs, and table-like exports. The waste is usually caused by repeated field names, irrelevant fields, oversized arrays, and nested wrapper objects.

## Options

### Option 1: TOON-Only

- Pros:
  - Strong compression on uniform arrays of objects.
  - Good readability for tabular payloads.
- Cons:
  - Not consistently better than compact JSON on nested or semi-uniform data.
  - Adds a dependency and a format choice that can be wrong by default.

### Option 2: jq-Only

- Pros:
  - Mature, stable, and already available in this environment.
  - Excellent for semantic pruning, field selection, reshaping, and sampling.
- Cons:
  - Does not change the output representation beyond JSON.
  - Leaves some table-like savings on the table.

### Option 3: Hybrid Orchestrator

- Combine a lightweight local wrapper with:
  - `jq` or `gojq` for pruning and restructuring
  - `TOON` for high-uniformity arrays
  - `qsv` for CSV/TSV pre-pruning
  - `jc` for turning command output into JSON first

## Decision

Build `token-pruner` as a hybrid orchestrator with a working local baseline that needs only Python and `jq`, then layer in TOON, `qsv`, and `jc` as optional accelerators.

## Reasons

- This avoids waiting on a perfect toolchain before the skill is usable.
- The hard problem is selecting and reshaping the right information, not just encoding it differently.
- TOON is valuable, but only as a conditional backend for the right payload shapes.
- The wrapper can keep the skill body small and push logic into scripts, which is better for the skill's own token footprint.

## Risks

- A naive wrapper can over-prune and remove evidence the model needs.
- Estimated token savings can be misleading when measured by bytes or rough heuristics.
- Tool availability differs across machines, especially for TOON, `qsv`, and `jc`.

## Next Actions

- Keep the first version focused on JSON input and deterministic pruning steps.
- Add true token measurement when a stable tokenizer choice is available for the target model set.
- Add CSV and command-output adapters only after the JSON path feels reliable.

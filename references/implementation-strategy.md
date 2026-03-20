---
owner: b.wen
last_updated: 2026-03-17
source_of_truth: true
---

# Token Pruner Strategy

## Background

The main token waste for coding agents often comes from two places:

- large structured payloads such as API responses, search results, test matrices, event logs, and table-like exports
- noisy developer command output such as `git diff`, `git status`, `cargo test`, `pytest`, `grep`, `find`, and `ls`

The waste is usually caused by repeated field names, irrelevant fields, oversized arrays, nested wrapper objects, and shell output boilerplate that the model does not need.

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
  - `rtk` for command-output compression before the output reaches the agent
  - `jq` or `gojq` for pruning and restructuring
  - `TOON` for high-uniformity arrays
  - `qsv` for CSV/TSV pre-pruning
  - `jc` for turning command output into JSON first

### Option 4: Fully Bundled Toolchain

- Vendor binaries or local runtime packages under `scripts/vendor` so the user does not have to install `rtk`, `jq`, `qsv`, `jc`, or `TOON` separately.
- Prefer project-local wrappers and binaries over whatever happens to be on the user's PATH.

## Decision

Build `token-pruner` as a hybrid orchestrator and bundle its toolchain under `scripts/vendor` for the current platform, with RTK as the first-stage reducer for supported shell commands.

## Reasons

- RTK attacks a different and important class of waste than TOON or `jq`: command-output boilerplate.
- The hard problem is selecting and reshaping the right information, not just encoding it differently.
- TOON is valuable, but only as a conditional backend for the right payload shapes.
- Bundling the toolchain removes setup friction and makes the skill behavior more reproducible.
- A project-local Claude Code hook lets us apply RTK before command output reaches the model, instead of relying only on manual command discipline.
- The wrapper can keep the skill body small and push logic into scripts, which is better for the skill's own token footprint.

## Risks

- A naive wrapper can over-prune and remove evidence the model needs.
- Estimated token savings can be misleading when measured by bytes or rough heuristics.
- RTK's own telemetry is useful, but its internal accounting is still a tool-specific estimate and not the target model's tokenizer in every case.
- Vendored binaries are platform-specific and increase repository size.
- Some tools are easier to vendor than others. `jq` on macOS may require bundling dependent libraries; TOON CLI uses a Node runtime.
- Claude Code only allows `updatedInput` when the hook returns a permission decision, so hook-driven rewrites must choose between `allow` and `ask`. This project uses a mixed strategy: read-only rewrites may auto-allow, while higher-risk commands use `ask`.

## Next Actions

- Add project-local tool resolution so `token_pruner.py` prefers vendored binaries and wrappers.
- Vendor the current platform's binaries and runtime packages under `scripts/vendor`.
- Add true token measurement when a stable tokenizer choice is available for the target model set.

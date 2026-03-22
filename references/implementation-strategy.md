---
owner: b.wen
last_updated: 2026-03-20
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

### Option 5: Lightweight Source + Release Bundle

- Keep the repository source tree small.
- Publish `scripts/vendor` as a GitHub Release asset per platform.
- Let the installer fetch the right asset automatically and fall back to bootstrap only when needed.

## Decision

Build `token-pruner` as a hybrid orchestrator. Keep `scripts/vendor` as the runtime layout, but distribute it through platform-specific release assets instead of tracking the bundle directly in source control. Use RTK as the first-stage reducer for supported shell commands.

## Reasons

- RTK attacks a different and important class of waste than TOON or `jq`: command-output boilerplate.
- The hard problem is selecting and reshaping the right information, not just encoding it differently.
- TOON is valuable, but only as a conditional backend for the right payload shapes.
- Bundling the toolchain still removes setup friction and keeps behavior reproducible.
- Release assets keep clone and review cost lower than committing heavy binaries into the repository.
- A project-local Claude Code hook lets us apply RTK before command output reaches the model, instead of relying only on manual command discipline.
- The wrapper can keep the skill body small and push logic into scripts, which is better for the skill's own token footprint.

## Risks

- A naive wrapper can over-prune and remove evidence the model needs.
- Estimated token savings can be misleading when measured by bytes or rough heuristics.
- RTK's own telemetry is useful, but its internal accounting is still a tool-specific estimate and not the target model's tokenizer in every case.
- Vendored binaries are platform-specific and still need a distribution path.
- Tracking large binaries directly in git makes the repository heavier than necessary.
- Some tools are easier to vendor than others. `jq` on macOS may require bundling dependent libraries; TOON CLI uses a Node runtime.
- Claude Code only allows `updatedInput` when the hook returns a permission decision, so hook-driven rewrites must choose between `allow` and `ask`. This project uses a mixed strategy: read-only rewrites may auto-allow, while higher-risk commands use `ask`.

## Next Actions

- Add project-local tool resolution so `token_pruner.py` prefers vendored binaries and wrappers.
- Publish the current platform's vendor tree as a release asset and teach the bootstrap entrypoint to fetch it automatically.
- Add true token measurement when a stable tokenizer choice is available for the target model set.

## v2 Additions (2026-03-22)

### PostToolUse Output Truncation

- Added a `truncate` subcommand that keeps head + tail + summary line for oversized output.
- Added a PostToolUse hook (`.claude/hooks/rtk_post_bash.py`) for Claude Code that auto-truncates Bash output exceeding 200 lines.
- ANSI escape sequences are stripped by default (pure Python regex, no external dependency).
- For agents without hook support (Codex, OpenCode), the same truncation is available via explicit piping: `<cmd> | python3 scripts/token_pruner.py truncate`.

### Token Measurement

- Added a `measure` subcommand that counts tokens using tiktoken (cl100k_base) when available.
- Falls back to byte_count/4 estimate when tiktoken is not installed.
- Enables concrete before/after comparisons instead of guesses.

### yq Integration

- Added `yq` (mikefarah/yq) to the vendored toolchain for YAML/TOML/XML field selection.
- YAML is ubiquitous in k8s, CI, and Helm workflows. Selecting fields at the YAML level before converting to JSON is more efficient than converting first and pruning later.
- Routing: `yq` commands are rewritten through RTK with `permissionDecision = ask`.

### Agent Compatibility Strategy

- Hook-based automation (PreToolUse + PostToolUse) is Claude Code specific.
- The SKILL.md now includes:
  - "Before Running Commands" section with zero-cost command patterns that work in any agent.
  - Quick Decision Table for fast tool selection.
  - Agent Compatibility matrix explaining how each agent type integrates.
- For hookless agents, the key pattern is explicit piping through `truncate` and `prune`.

### Risks

- PostToolUse hooks may interfere with commands where the agent needs to see the full output (e.g., reading a specific log section). The 200-line default is conservative enough to mitigate this.
- tiktoken is an optional dependency. The byte estimate is imprecise but directionally useful.
- yq adds another vendored binary. Distribution strategy is the same as other tools (GitHub Release asset).

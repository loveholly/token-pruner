---
name: token-pruner
description: Reduce LLM context cost for structured payloads and noisy CLI output. Use when the user wants to shrink JSON, NDJSON, YAML, API responses, test logs, git output, tabular exports, or command output before sending it to Codex or Claude Code, especially with RTK, jq, yq, TOON, qsv, or jc.
owner: b.wen
last_updated: 2026-03-22
source_of_truth: true
---

# Token Pruner

Use this skill when the expensive part of the context is structured data or noisy tool output, not source code.

## Quick Start

1. Resolve the skill directory from this `SKILL.md`.
2. Run a runtime check first:

```bash
python3 "<skill-dir>/scripts/token_pruner.py" doctor
```

If this is a fresh source checkout and the vendor tree is still empty, install first:

```bash
python3 "<skill-dir>/scripts/bootstrap.py" --codex-only
```

3. Probe bundled and local tooling paths when needed:

```bash
python3 "<skill-dir>/scripts/token_pruner.py" probe
```

4. Profile the payload before pruning:

```bash
python3 "<skill-dir>/scripts/token_pruner.py" profile --input "<path-to-json>"
```

5. Prune semantically first, then choose the output format:

```bash
python3 "<skill-dir>/scripts/token_pruner.py" prune \
  --input "<path-to-json>" \
  --keep-keys id,name,status,created_at \
  --head 50 \
  --format auto
```

6. Truncate oversized command output:

```bash
<some-command> | python3 "<skill-dir>/scripts/token_pruner.py" truncate --max-lines 200
```

7. Measure token cost before and after:

```bash
python3 "<skill-dir>/scripts/token_pruner.py" measure --input "<path-to-text>"
```

8. Run bundled helper tools from the same entrypoint when needed:

```bash
python3 "<skill-dir>/scripts/token_pruner.py" tool rtk git status
python3 "<skill-dir>/scripts/token_pruner.py" tool yq '.metadata.name' manifest.yaml
```

9. In Claude Code projects, the bundled hooks in `.claude/settings.json` automatically:
   - **PreToolUse**: Rewrite common Bash calls through vendored RTK.
   - **PostToolUse**: Truncate oversized output and strip ANSI escapes.

## System Install

```bash
python3 "<skill-dir>/scripts/bootstrap.py"
```

- Codex install target: `~/.codex/skills/token-pruner`
- Claude install target: `~/.claude/skills/token-pruner`
- The installer preserves existing Claude settings, merges both PreToolUse and PostToolUse hooks, and writes a managed section into `~/.claude/CLAUDE.md`.

## Before Running Commands

Prefer token-efficient commands at the source. This costs nothing and compounds with pruning.

- `git log --oneline -20` instead of `git log`
- `git diff --stat` for overview, then `git diff -- <file>` for specific changes
- `git log --format='%h %s' -20` for minimal history
- `ls <specific-dir>` instead of recursive `ls -R`
- `gh api --jq '.items[] | {title, state}'` to filter at the API level
- `kubectl get pods -o name` instead of `-o wide` or `-o yaml`
- `curl -s <url> | jq '.data'` instead of dumping the whole response
- `pytest -x --tb=short` instead of `pytest -v` for failure-focused output
- `cargo test 2>&1 | head -50` when you only need the first failure

These patterns work with any agent, regardless of hook support.

## Quick Decision Table

| Input | First Tool | Then |
|-------|-----------|------|
| `git diff` (large) | `rtk` | done |
| `git log` (long) | `rtk` or `--oneline -N` | done |
| JSON API response | `jq` field select | `prune --format auto` |
| NDJSON stream | `jq` per-line filter | `prune --head N` |
| YAML config | `yq` field select | compact JSON if needed |
| CI test log | `rtk` | extract failures only |
| CSV/TSV export | `qsv select` + `qsv head` | compact JSON |
| HTML page | extract text, drop tags | summarize |
| Command output (unknown) | `jc` to JSON | `jq` prune |
| Any oversized output | `truncate --max-lines 200` | done |

## Workflow

### 1) Profile Before Pruning

- Start with `doctor` before substantial use.
- Start with `profile` to detect depth, row count, field uniformity, and whether TOON is likely to help.
- Treat `format` choice as the last step, not the first step.

### 2) Route by Source Type

- For supported developer commands (`git`, `grep`, `find`, `ls`, `cargo test`, `pytest`), prefer `rtk` first.
- For YAML/TOML files, use `yq` for field selection before converting to JSON.
- Invoke bundled helpers through `python3 "<skill-dir>/scripts/token_pruner.py" tool <tool-name> ...`.
- For generic CLI text that `rtk` does not cover, normalize with `jc` when possible.
- For CSV or TSV, prune with `qsv` before converting anything to JSON.
- For JSON or NDJSON, go directly to `jq` and the built-in pruning controls.

### 3) Remove Semantic Noise First

- Prefer `jq` or the built-in `--keep-keys`, `--drop-keys`, `--head`, and `--sample` controls before changing the wire format.
- Preserve identifiers, timestamps, status fields, and enough evidence for the model to reason correctly.
- Drop blobs such as verbose markdown bodies, HTML, embeddings, base64, stack traces, and duplicated nested metadata unless the user explicitly needs them.
- Strip ANSI escape sequences from CI logs and colored output. The `truncate` subcommand does this by default.

### 4) Truncate Oversized Output

- When command output exceeds 200 lines, use `truncate` to keep head + tail with a summary.
- For agents with hook support (Claude Code), this happens automatically via PostToolUse.
- For agents without hooks (Codex, OpenCode), pipe output explicitly:

```bash
<command> 2>&1 | python3 "<skill-dir>/scripts/token_pruner.py" truncate --max-lines 200
```

### 5) Pick the Rendering Format

- Default to compact JSON when the payload is nested, irregular, or already aggressively filtered.
- Prefer TOON only when the payload is mostly an array of similar objects and the bundled `toon` wrapper is available.
- Treat RTK as a command-output compressor, not as a replacement for `jq` or TOON.

### 6) Measure and Report

- Use the `measure` subcommand for before/after token counts.
- If `tiktoken` is available in the Python environment, you get exact cl100k_base token counts.
- Otherwise a byte_count/4 estimate is used.
- Do not claim token savings without measurement or at least a stated estimate.

## Agent Compatibility

Different agents have different extension mechanisms. This project adapts to each:

| Agent | Hook Support | How Token Pruner Integrates |
|-------|-------------|---------------------------|
| **Claude Code** | PreToolUse + PostToolUse hooks | Full automation: commands rewritten before execution, output truncated after. Install via `bootstrap.py`. |
| **Codex** | SKILL.md prompt (no hooks) | Agent reads this SKILL.md and follows the workflow manually. Pipe output through `truncate` and `prune` explicitly. |
| **OpenCode** | MCP tools / custom commands | Expose `token_pruner.py` subcommands as MCP tools or wrap in shell aliases. |
| **OpenClaw** | Skill prompts (similar to Codex) | This SKILL.md is directly compatible. |
| **Other agents** | Varies | Use the CLI directly. The "Before Running Commands" patterns work everywhere. |

For agents without hooks, the most important sections are:
1. **Before Running Commands** — zero-cost source-level optimization
2. **Quick Decision Table** — fast tool selection
3. Explicit piping: `<cmd> | python3 "<skill-dir>/scripts/token_pruner.py" truncate`

## Guardrails

- Current prebuilt vendor bundle targets `macOS arm64`. On other platforms, do not assume the release asset will succeed unchanged.
- The project requires a working `python3` runtime. TOON also requires `node`.
- Do not use this skill for normal source-code reading unless the source has already been turned into structured metadata.
- Do not hide critical evidence just to save tokens.
- Avoid TOON for deeply nested or semi-uniform payloads unless measured results prove it helps.
- Do not assume RTK covers every shell command. Fall back cleanly to `jc`, `jq`, or compact summaries.
- When in doubt, return compact JSON plus a short summary instead of an exotic format.

## References

- `references/implementation-strategy.md`
- `references/tooling-matrix.md`

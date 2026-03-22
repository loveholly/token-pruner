# Claude Notes

This project uses a vendored token-reduction toolchain under `scripts/vendor`.
If the directory is missing in a fresh checkout, run `python3 scripts/bootstrap.py --claude-only` or `python3 scripts/fetch_vendor_bundle.py` first.

## Bash Routing

- Claude Code uses `.claude/settings.json` with hooks for `Bash`.
- **PreToolUse** hook runs `.claude/hooks/rtk_pre_bash.py`, which calls `scripts/token_pruner.py rewrite-bash`.
  - Read-oriented commands such as `git status`, `git diff`, `ls`, simple `find`, simple `grep`, and `cat <file>` are rewritten to RTK automatically.
  - YAML commands (`yq`) are also routed through RTK with `permissionDecision = ask`.
  - Higher-risk commands such as `cargo test`, `pytest`, `gh`, `docker`, `curl`, and package-manager commands are rewritten with `permissionDecision = ask`.
  - Complex shell pipelines and commands with control operators are not rewritten.
- **PostToolUse** hook runs `.claude/hooks/rtk_post_bash.py`, which auto-truncates oversized output.
  - Strips ANSI escape sequences from output.
  - Keeps first 180 lines + last 20 lines when output exceeds 200 lines.
  - Inserts a summary line showing how many lines were omitted.

## Manual Escape Hatches

- Probe bundled tools:
  - `python3 scripts/token_pruner.py probe`
- Ask how a Bash command would be rewritten:
  - `python3 scripts/token_pruner.py rewrite-bash --command "git status"`
- Run a vendored helper directly:
  - `python3 scripts/token_pruner.py tool rtk git status`
  - `python3 scripts/token_pruner.py tool jq --version`
  - `python3 scripts/token_pruner.py tool yq '.metadata.name' manifest.yaml`
- Truncate oversized output manually:
  - `<command> | python3 scripts/token_pruner.py truncate --max-lines 200`
- Measure token cost:
  - `python3 scripts/token_pruner.py measure --input <file>`

## Structured Payloads

- Use `profile` to inspect JSON shape before pruning.
- Use `prune` for JSON/NDJSON field selection and auto format choice.
- Use `yq` for YAML/TOML field selection before converting to JSON.
- Prefer RTK for noisy command output, `jq` for JSON reshaping, `yq` for YAML, `qsv` for tables, and TOON only for highly uniform arrays.

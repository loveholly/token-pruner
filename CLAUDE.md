# Claude Notes

This project vendors its token-reduction toolchain under `scripts/vendor`.

## Bash Routing

- Claude Code uses `.claude/settings.json` with a `PreToolUse` hook for `Bash`.
- The hook runs `.claude/hooks/rtk_pre_bash.py`, which calls `scripts/token_pruner.py rewrite-bash`.
- Read-oriented commands such as `git status`, `git diff`, `ls`, simple `find`, simple `grep`, and `cat <file>` are rewritten to RTK automatically.
- Higher-risk commands such as `cargo test`, `pytest`, `gh`, `docker`, `curl`, and package-manager commands are rewritten with `permissionDecision = ask`, so the UI shows the modified command before execution.
- Complex shell pipelines and commands with control operators are not rewritten.

## Manual Escape Hatches

- Probe bundled tools:
  - `python3 scripts/token_pruner.py probe`
- Ask how a Bash command would be rewritten:
  - `python3 scripts/token_pruner.py rewrite-bash --command "git status"`
- Run a vendored helper directly:
  - `python3 scripts/token_pruner.py tool rtk git status`
  - `python3 scripts/token_pruner.py tool jq --version`

## Structured Payloads

- Use `profile` to inspect JSON shape before pruning.
- Use `prune` for JSON/NDJSON field selection and auto format choice.
- Prefer RTK for noisy command output, `jq` for JSON reshaping, `qsv` for tables, and TOON only for highly uniform arrays.

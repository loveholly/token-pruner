# token-pruner

`token-pruner` is a local skill bundle for Codex and Claude Code that reduces context cost before structured payloads or noisy shell output hit the model.

It is built for cases where the expensive part of a session is not source code itself, but:

- large JSON or NDJSON payloads
- verbose `git` output
- test logs
- CSV or TSV exports
- repeated command-output boilerplate

The project routes different payloads through the most suitable reducer instead of forcing a single format:

- `rtk` for noisy developer command output
- `jq` for JSON pruning and reshaping
- `qsv` for table-first trimming
- `jc` for normalizing CLI text into JSON
- `TOON` only when the payload shape is a strong fit

## Why This Exists

Using TOON alone is not enough. Uniform arrays compress well, but nested or irregular payloads often do better with compact JSON after semantic pruning.

This project treats token reduction as a routing problem:

1. remove semantic noise first
2. only then pick the output format
3. prefer stable, local tool paths so agent behavior stays reproducible

## Repository Layout

- [`SKILL.md`](./SKILL.md): Codex skill entrypoint
- [`CLAUDE.md`](./CLAUDE.md): Claude Code project notes
- [`scripts/token_pruner.py`](./scripts/token_pruner.py): main CLI
- [`scripts/bootstrap.py`](./scripts/bootstrap.py): preferred bootstrap entrypoint
- [`scripts/install_system.py`](./scripts/install_system.py): compatibility wrapper for the old entrypoint
- [`scripts/fetch_vendor_bundle.py`](./scripts/fetch_vendor_bundle.py): download prebuilt vendor bundle from GitHub Releases
- [`scripts/bootstrap_vendor.py`](./scripts/bootstrap_vendor.py): local fallback when no prebuilt bundle is available
- [`scripts/package_vendor_bundle.py`](./scripts/package_vendor_bundle.py): maintainer script for release assets

## Quick Start

Run a system install from this checkout:

```bash
python3 scripts/bootstrap.py
```

What it does:

- installs the skill into `~/.codex/skills/token-pruner`
- installs the Claude bundle into `~/.claude/skills/token-pruner`
- merges the global Claude Bash hook into `~/.claude/settings.json`
- writes a managed token-pruner block into `~/.claude/CLAUDE.md`
- checks whether `scripts/vendor` is already usable
- automatically fetches or bootstraps vendor tools when missing

The older command still works:

```bash
python3 scripts/install_system.py
```

The installer prefers a prebuilt GitHub Release asset for the current platform. If no matching asset exists, it falls back to [`bootstrap_vendor.py`](./scripts/bootstrap_vendor.py).

## Local Use

Check runtime status:

```bash
python3 scripts/token_pruner.py doctor
```

Inspect available tools:

```bash
python3 scripts/token_pruner.py probe
```

Profile a payload:

```bash
python3 scripts/token_pruner.py profile --input payload.json
```

Prune a payload:

```bash
python3 scripts/token_pruner.py prune \
  --input payload.json \
  --keep-keys id,name,status,created_at \
  --head 50 \
  --format auto
```

Route a command through vendored RTK:

```bash
python3 scripts/token_pruner.py tool rtk git status
```

Preview Claude hook rewriting:

```bash
python3 scripts/token_pruner.py rewrite-bash --command "git status"
```

## Distribution Strategy

The repository intentionally does **not** track `scripts/vendor` anymore.

Reason:

- prebuilt binaries make the repository heavy
- GitHub warns on large binaries such as `qsv`
- removing the bundle from normal source control makes clone and review lighter

Instead:

- source code stays lightweight
- release assets carry the platform-specific vendor bundle
- `bootstrap.py` fetches the bundle automatically when needed
- `bootstrap_vendor.py` remains as the fallback path

## Current Runtime Assumptions

- current prebuilt bundle target: `macOS arm64`
- required host runtime: `python3`
- TOON still requires a working `node` runtime

If a matching prebuilt bundle is unavailable, local bootstrap may require additional local tooling, depending on platform.

## Maintainer Notes

Package the current vendor tree into a release asset:

```bash
python3 scripts/package_vendor_bundle.py
```

Fetch the latest matching vendor asset into the local checkout:

```bash
python3 scripts/fetch_vendor_bundle.py
```

## Status

- GitHub repo: [loveholly/token-pruner](https://github.com/loveholly/token-pruner)
- Branch: `main`
- Default install targets:
  - Codex: `~/.codex/skills/token-pruner`
  - Claude Code: `~/.claude/skills/token-pruner`

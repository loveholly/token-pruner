---
owner: b.wen
last_updated: 2026-03-17
source_of_truth: true
---

# Tooling Matrix

| Tool | Role | Recommendation | Best Use | Notes |
| --- | --- | --- | --- | --- |
| `rtk` | Command-output compressor | Core for coding-agent shell workflows | `git status`, `git diff`, `git log`, `grep`, `find`, `ls`, test output, and similar noisy developer commands | Best for command output. Not a replacement for JSON reshaping. Official site claims 30+ commands, ~89% average noise removed, and a hook-based rewrite flow |
| `jq` | Prune and reshape JSON | Core dependency | Drop fields, select subsets, flatten wrappers, sample arrays | Best when you already have JSON or NDJSON |
| `gojq` | `jq`-compatible fallback | Optional | Environments where static distribution matters | Useful portability layer if a portable `jq` binary is not available |
| `TOON` | Alternate rendering format | Optional backend | Uniform arrays of objects with repeated keys | Measure before defaulting to it; weak fit for deeply nested or irregular data |
| `qsv` | CSV/TSV pruning | Core for table-heavy flows | Large tables before converting to JSON or TOON | Better than forcing tables through generic JSON tools |
| `jc` | CLI text to JSON | Fallback adapter | `ps`, `ls`, `df`, `dig`, and other command output that is not already well-covered by RTK | Makes later pruning deterministic |
| Python stdlib | Orchestration | Core dependency | Tool probing, heuristics, sampling, vendored tool routing | Keeps the skill self-contained |

## Recommended Stack

1. Bundled in the project:
   - `rtk`
   - `jq`
   - `qsv`
   - `jc`
   - `TOON`
2. Optional fallback:
   - `gojq`
3. Runtime assumptions:
   - Python 3 for orchestration and vendored Python packages
   - Node.js for the vendored TOON CLI wrapper

## Default Routing Rules

- Supported developer command output:
  - Prefer `rtk` first.
  - If the result still needs structured post-processing, pipe the reduced output into the next stage instead of starting from the raw command output.
- JSON or NDJSON:
  - Prune with `jq` first.
  - Render as compact JSON unless the payload is highly uniform and TOON is available.
- CSV or TSV:
  - Prune with `qsv`.
  - Convert to JSON only after selecting rows and columns.
- Raw command output:
  - If RTK does not have a good reducer for the command, normalize with `jc`.
  - Then apply the JSON path above.

---
owner: b.wen
last_updated: 2026-03-17
source_of_truth: true
---

# Tooling Matrix

| Tool | Role | Recommendation | Best Use | Notes |
| --- | --- | --- | --- | --- |
| `jq` | Prune and reshape JSON | Core dependency | Drop fields, select subsets, flatten wrappers, sample arrays | Mature, ubiquitous, and already installed here |
| `gojq` | `jq`-compatible fallback | Optional | Environments where static distribution matters | Useful portability layer if `jq` is missing |
| `TOON` | Alternate rendering format | Optional backend | Uniform arrays of objects with repeated keys | Measure before defaulting to it |
| `qsv` | CSV/TSV pruning | Optional adapter | Large tables before converting to JSON or TOON | Better than forcing tables through generic JSON tools |
| `jc` | CLI text to JSON | Optional adapter | `ps`, `ls`, `df`, `dig`, and other command output | Makes later pruning deterministic |
| Python stdlib | Orchestration | Core dependency | Tool probing, heuristics, sampling, format routing | Keeps the skill self-contained |

## Recommended Stack

1. Required:
   - Python 3
   - `jq`
2. Optional:
   - `TOON`
   - `qsv`
   - `jc`
   - `gojq`

## Default Routing Rules

- JSON or NDJSON:
  - Prune with `jq` first.
  - Render as compact JSON unless the payload is highly uniform and TOON is available.
- CSV or TSV:
  - Prune with `qsv`.
  - Convert to JSON only after selecting rows and columns.
- Raw command output:
  - Normalize with `jc`.
  - Then apply the JSON path above.

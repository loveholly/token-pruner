#!/usr/bin/env python3

from __future__ import annotations

import argparse
import json
import shutil
import statistics
import subprocess
import sys
from collections import Counter
from pathlib import Path
from typing import Any


TOOLS = ("jq", "gojq", "toon", "qsv", "jc")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Profile and prune structured JSON payloads for LLM context use."
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    subparsers.add_parser("probe", help="Show which helper tools are available.")

    profile = subparsers.add_parser("profile", help="Analyze JSON shape and suggest a strategy.")
    profile.add_argument("--input", help="Path to a JSON file. Reads stdin when omitted.")

    prune = subparsers.add_parser("prune", help="Prune and render a JSON payload.")
    prune.add_argument("--input", help="Path to a JSON file. Reads stdin when omitted.")
    prune.add_argument(
        "--jq-filter",
        help="Optional jq filter applied before built-in pruning controls.",
    )
    prune.add_argument(
        "--keep-keys",
        help="Comma-separated keys to keep on dicts or arrays of dicts.",
    )
    prune.add_argument(
        "--drop-keys",
        help="Comma-separated keys to remove on dicts or arrays of dicts.",
    )
    prune.add_argument("--head", type=int, help="Keep only the first N items from a top-level array.")
    prune.add_argument(
        "--sample",
        type=int,
        help="Keep N evenly spaced items from a top-level array.",
    )
    prune.add_argument(
        "--format",
        choices=("auto", "json", "toon"),
        default="auto",
        help="Output format.",
    )
    prune.add_argument(
        "--toon-key-folding",
        choices=("off", "safe"),
        default="off",
        help="Pass through TOON key folding when using TOON output.",
    )
    prune.add_argument(
        "--sort-keys",
        action="store_true",
        help="Sort JSON keys in the rendered output.",
    )
    prune.add_argument(
        "--indent",
        type=int,
        default=None,
        help="Pretty-print JSON with N spaces. Compact JSON is used by default.",
    )

    return parser.parse_args()


def read_input(path_str: str | None) -> str:
    if path_str:
        return Path(path_str).read_text(encoding="utf-8")
    if sys.stdin.isatty():
        raise SystemExit("No input provided. Use --input or pipe JSON on stdin.")
    return sys.stdin.read()


def load_json(path_str: str | None) -> Any:
    text = read_input(path_str)
    try:
        return json.loads(text)
    except json.JSONDecodeError as exc:
        raise SystemExit(f"Input is not valid JSON: {exc}") from exc


def tool_status() -> dict[str, str | None]:
    return {tool: shutil.which(tool) for tool in TOOLS}


def max_depth(value: Any) -> int:
    if isinstance(value, dict):
        if not value:
            return 1
        return 1 + max(max_depth(item) for item in value.values())
    if isinstance(value, list):
        if not value:
            return 1
        return 1 + max(max_depth(item) for item in value)
    return 1


def type_name(value: Any) -> str:
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "boolean"
    if isinstance(value, dict):
        return "object"
    if isinstance(value, list):
        return "array"
    if isinstance(value, (int, float)):
        return "number"
    return "string"


def count_nodes(value: Any) -> int:
    if isinstance(value, dict):
        return 1 + sum(count_nodes(item) for item in value.values())
    if isinstance(value, list):
        return 1 + sum(count_nodes(item) for item in value)
    return 1


def nested_value_ratio(rows: list[dict[str, Any]]) -> float:
    nested = 0
    total = 0
    for row in rows:
        for value in row.values():
            total += 1
            if isinstance(value, (dict, list)):
                nested += 1
    if total == 0:
        return 0.0
    return round(nested / total, 3)


def array_object_summary(rows: list[dict[str, Any]]) -> dict[str, Any]:
    keysets = [tuple(sorted(row.keys())) for row in rows]
    counts = Counter(keysets)
    common_keyset, common_count = counts.most_common(1)[0]
    union_keys = sorted({key for row in rows for key in row})
    intersection_keys = sorted(set(rows[0]).intersection(*(set(row) for row in rows[1:])))
    avg_keys = round(statistics.mean(len(row) for row in rows), 2)
    return {
        "uniformity_ratio": round(common_count / len(rows), 3),
        "union_key_count": len(union_keys),
        "intersection_key_count": len(intersection_keys),
        "avg_keys_per_row": avg_keys,
        "sample_common_keys": list(common_keyset[:12]),
        "nested_value_ratio": nested_value_ratio(rows),
    }


def recommended_strategy(data: Any, status: dict[str, str | None]) -> dict[str, Any]:
    reason: list[str] = []
    mode = "compact_json"
    steps = [
        "Prune semantically before changing format.",
        "Keep identifiers, timestamps, and decision-critical fields.",
    ]

    if isinstance(data, list) and data and all(isinstance(item, dict) for item in data):
        summary = array_object_summary(data)
        if summary["uniformity_ratio"] >= 0.8 and summary["nested_value_ratio"] <= 0.15:
            if status["toon"]:
                mode = "toon"
                reason.append("Top-level payload is a mostly uniform array of objects.")
                reason.append("TOON is available and likely to remove repeated keys efficiently.")
                steps.append("Use TOON only after trimming columns and rows.")
            else:
                mode = "compact_json"
                reason.append("Payload shape favors TOON, but the `toon` CLI is not installed.")
                steps.append("Install TOON if this payload shape is frequent.")
        else:
            reason.append("Array rows are irregular or contain too many nested values.")
            steps.append("Prefer jq field selection plus compact JSON.")
    elif isinstance(data, dict) and max_depth(data) >= 4:
        reason.append("Payload is deeply nested, which is often a weak fit for TOON.")
        steps.append("Flatten wrapper objects before considering an alternate format.")
    else:
        reason.append("Compact JSON is the safest default for this payload shape.")

    return {
        "preferred_format": mode,
        "reasons": reason,
        "suggested_steps": steps,
    }


def profile_payload(data: Any) -> dict[str, Any]:
    status = tool_status()
    summary: dict[str, Any] = {
        "top_level_type": type_name(data),
        "max_depth": max_depth(data),
        "node_count": count_nodes(data),
        "available_tools": {name: bool(path) for name, path in status.items()},
    }

    if isinstance(data, list):
        summary["top_level_length"] = len(data)
        if data:
            summary["top_level_item_types"] = sorted({type_name(item) for item in data})
        if data and all(isinstance(item, dict) for item in data):
            summary["array_of_objects"] = array_object_summary(data)
    elif isinstance(data, dict):
        summary["top_level_key_count"] = len(data)
        summary["top_level_keys"] = list(data.keys())[:20]

    summary["recommendation"] = recommended_strategy(data, status)
    return summary


def parse_csv_keys(raw: str | None) -> list[str] | None:
    if not raw:
        return None
    keys = [item.strip() for item in raw.split(",") if item.strip()]
    return keys or None


def apply_keep_drop(value: Any, keep_keys: list[str] | None, drop_keys: list[str] | None) -> Any:
    if not keep_keys and not drop_keys:
        return value

    def transform_dict(row: dict[str, Any]) -> dict[str, Any]:
        updated = row
        if keep_keys:
            updated = {key: row[key] for key in keep_keys if key in row}
        if drop_keys:
            updated = {key: val for key, val in updated.items() if key not in drop_keys}
        return updated

    if isinstance(value, dict):
        return transform_dict(value)
    if isinstance(value, list) and all(isinstance(item, dict) for item in value):
        return [transform_dict(item) for item in value]
    return value


def evenly_sample(items: list[Any], size: int) -> list[Any]:
    if size <= 0:
        raise SystemExit("--sample must be a positive integer.")
    if size >= len(items):
        return items
    if size == 1:
        return [items[0]]
    last_index = len(items) - 1
    indexes = sorted(
        {
            round(i * last_index / (size - 1))
            for i in range(size)
        }
    )
    return [items[index] for index in indexes]


def apply_array_pruning(value: Any, head: int | None, sample: int | None) -> Any:
    if not isinstance(value, list):
        return value
    result = value
    if head is not None:
        if head < 0:
            raise SystemExit("--head must be a non-negative integer.")
        result = result[:head]
    if sample is not None:
        result = evenly_sample(result, sample)
    return result


def run_jq(filter_expr: str, value: Any) -> Any:
    jq_path = shutil.which("jq") or shutil.which("gojq")
    if not jq_path:
        raise SystemExit("`jq` or `gojq` is required for --jq-filter.")
    payload = json.dumps(value, ensure_ascii=False, separators=(",", ":"))
    completed = subprocess.run(
        [jq_path, filter_expr],
        input=payload,
        text=True,
        capture_output=True,
        check=False,
    )
    if completed.returncode != 0:
        raise SystemExit(f"jq failed: {completed.stderr.strip()}")
    output = completed.stdout.strip()
    if not output:
        return None
    try:
        return json.loads(output)
    except json.JSONDecodeError as exc:
        raise SystemExit("jq output is not valid JSON. Add a JSON-producing filter.") from exc


def render_json(value: Any, indent: int | None, sort_keys: bool) -> str:
    if indent is None:
        return json.dumps(value, ensure_ascii=False, separators=(",", ":"), sort_keys=sort_keys)
    return json.dumps(value, ensure_ascii=False, indent=indent, sort_keys=sort_keys)


def render_toon(value: Any, key_folding: str) -> str:
    toon_path = shutil.which("toon")
    if not toon_path:
        raise SystemExit("`toon` is not installed. Use --format json or install the TOON CLI.")
    command = [toon_path, "--encode"]
    if key_folding == "safe":
        command.extend(["--keyFolding", "safe"])
    payload = json.dumps(value, ensure_ascii=False, separators=(",", ":"))
    completed = subprocess.run(
        command,
        input=payload,
        text=True,
        capture_output=True,
        check=False,
    )
    if completed.returncode != 0:
        raise SystemExit(f"toon failed: {completed.stderr.strip()}")
    return completed.stdout


def select_format(value: Any, requested: str) -> str:
    if requested != "auto":
        return requested
    recommendation = recommended_strategy(value, tool_status())
    return "toon" if recommendation["preferred_format"] == "toon" else "json"


def command_probe() -> None:
    status = tool_status()
    print(json.dumps(status, ensure_ascii=False, indent=2))


def command_profile(args: argparse.Namespace) -> None:
    data = load_json(args.input)
    print(json.dumps(profile_payload(data), ensure_ascii=False, indent=2))


def command_prune(args: argparse.Namespace) -> None:
    data = load_json(args.input)

    if args.jq_filter:
        data = run_jq(args.jq_filter, data)

    keep_keys = parse_csv_keys(args.keep_keys)
    drop_keys = parse_csv_keys(args.drop_keys)
    data = apply_keep_drop(data, keep_keys, drop_keys)
    data = apply_array_pruning(data, args.head, args.sample)

    selected_format = select_format(data, args.format)
    if selected_format == "toon":
        output = render_toon(data, args.toon_key_folding)
    else:
        output = render_json(data, args.indent, args.sort_keys)

    sys.stdout.write(output)
    if output and not output.endswith("\n"):
        sys.stdout.write("\n")


def main() -> None:
    args = parse_args()
    if args.command == "probe":
        command_probe()
        return
    if args.command == "profile":
        command_profile(args)
        return
    if args.command == "prune":
        command_prune(args)
        return
    raise SystemExit(f"Unknown command: {args.command}")


if __name__ == "__main__":
    main()

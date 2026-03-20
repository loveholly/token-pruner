#!/usr/bin/env python3

from __future__ import annotations

import argparse
import json
import re
import shlex
import shutil
import statistics
import subprocess
import sys
import platform
from collections import Counter
from pathlib import Path
from typing import Any


SCRIPT_DIR = Path(__file__).resolve().parent
VENDOR_DIR = SCRIPT_DIR / "vendor"
VENDOR_BIN_DIR = VENDOR_DIR / "bin"

TOOLS = ("rtk", "jq", "gojq", "toon", "qsv", "jc")
CONTROL_TOKENS = {"|", "||", "&&", ";", ">", ">>", "<", "<<", "2>", "2>>", "&"}
SAFE_RTK_GIT_SUBCOMMANDS = {"status", "diff", "log", "show", "branch", "worktree"}
TOOL_SMOKE_ARGS = {
    "rtk": ["--version"],
    "jq": ["--version"],
    "gojq": ["--version"],
    "toon": ["--help"],
    "qsv": ["--version"],
    "jc": ["--version"],
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Profile and prune structured JSON payloads for LLM context use."
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    subparsers.add_parser("probe", help="Show which helper tools are available.")
    subparsers.add_parser("doctor", help="Verify vendored tools actually run on this machine.")

    profile = subparsers.add_parser("profile", help="Analyze JSON shape and suggest a strategy.")
    profile.add_argument("--input", help="Path to a JSON file. Reads stdin when omitted.")

    rewrite = subparsers.add_parser(
        "rewrite-bash",
        help="Rewrite a simple Bash command to a vendored RTK command when safe.",
    )
    rewrite.add_argument("--command", dest="bash_command", required=True, help="Original Bash command string.")

    tool = subparsers.add_parser("tool", help="Run a vendored helper tool by name.")
    tool.add_argument("tool_name", choices=TOOLS, help="Tool to execute.")
    tool.add_argument("tool_args", nargs=argparse.REMAINDER, help="Arguments passed to the tool.")

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


def resolve_tool(tool: str) -> str | None:
    vendored = VENDOR_BIN_DIR / tool
    if vendored.exists():
        return str(vendored)
    return shutil.which(tool)


def tool_status() -> dict[str, str | None]:
    return {tool: resolve_tool(tool) for tool in TOOLS}


def tool_runtime_status(tool: str) -> dict[str, Any]:
    tool_path = resolve_tool(tool)
    result: dict[str, Any] = {
        "path": tool_path,
        "available": bool(tool_path),
        "ok": False,
    }
    if not tool_path:
        result["error"] = "not found"
        return result

    smoke_args = TOOL_SMOKE_ARGS.get(tool, ["--help"])
    completed = subprocess.run(
        [tool_path, *smoke_args],
        text=True,
        capture_output=True,
        check=False,
    )
    result["exit_code"] = completed.returncode
    stdout = completed.stdout.strip()
    stderr = completed.stderr.strip()
    if completed.returncode == 0:
        result["ok"] = True
        sample = stdout or stderr
        if sample:
            result["sample"] = sample.splitlines()[0][:200]
    else:
        result["error"] = (stderr or stdout or "unknown error").splitlines()[0][:200]
    return result


def is_env_assignment(token: str) -> bool:
    return bool(re.match(r"^[A-Za-z_][A-Za-z0-9_]*=.*$", token))


def shell_join(parts: list[str]) -> str:
    return shlex.join(parts)


def build_tool_command(tool_name: str, tool_args: list[str]) -> str:
    return shell_join([sys.executable, str(SCRIPT_DIR / "token_pruner.py"), "tool", tool_name, *tool_args])


def pass_through(reason: str) -> dict[str, Any]:
    return {
        "strategy": "pass_through",
        "reason": reason,
        "permission_decision": None,
        "rewritten_command": None,
    }


def routed(strategy: str, reason: str, permission_decision: str, tool_args: list[str]) -> dict[str, Any]:
    return {
        "strategy": strategy,
        "reason": reason,
        "permission_decision": permission_decision,
        "rewritten_command": build_tool_command("rtk", tool_args),
    }


def parse_find_command(tokens: list[str]) -> list[str] | None:
    args = tokens[1:]
    if not args:
        return None

    path = "."
    file_type = None
    pattern = None
    idx = 0

    if idx < len(args) and not args[idx].startswith("-"):
        path = args[idx]
        idx += 1

    while idx < len(args):
        token = args[idx]
        if token == "-type" and idx + 1 < len(args):
            candidate = args[idx + 1]
            if candidate in {"f", "d"}:
                file_type = candidate
                idx += 2
                continue
            return None
        if token in {"-name", "-iname"} and idx + 1 < len(args):
            pattern = args[idx + 1]
            idx += 2
            continue
        return None

    if not pattern:
        return None

    command = ["find", pattern, path]
    if file_type:
        command.extend(["-t", file_type])
    return command


def rewrite_bash_command(command: str) -> dict[str, Any]:
    if resolve_tool("rtk") is None:
        return pass_through("Vendored RTK is not available.")

    if not command.strip():
        return pass_through("Empty command.")

    try:
        tokens = shlex.split(command, posix=True)
    except ValueError as exc:
        return pass_through(f"Command could not be parsed safely: {exc}")

    if not tokens:
        return pass_through("Empty command.")

    if any(token in CONTROL_TOKENS for token in tokens):
        return pass_through("Command uses shell control operators; skipping rewrite.")

    if any(is_env_assignment(token) for token in tokens):
        return pass_through("Command uses inline environment assignments; skipping rewrite.")

    if tokens[0] in {"rtk", "sudo", "cd", "export", "set", "unset"}:
        return pass_through("Command is already wrapped or uses a shell builtin.")

    if "token_pruner.py" in command and " tool rtk " in f" {command} ":
        return pass_through("Command is already routed through token-pruner.")

    top = tokens[0]

    if top == "git":
        if len(tokens) < 2:
            return pass_through("Bare `git` command is too broad to rewrite safely.")
        subcommand = tokens[1]
        if subcommand in SAFE_RTK_GIT_SUBCOMMANDS:
            return routed(
                strategy="rtk_git",
                reason=f"Read-oriented git command rewritten to `rtk git {subcommand}`.",
                permission_decision="allow",
                tool_args=["git", *tokens[1:]],
            )
        if subcommand in {"add", "commit", "push", "pull", "fetch", "stash"}:
            return routed(
                strategy="rtk_git",
                reason=f"`git {subcommand}` can use RTK, but Claude Code should show the rewritten command for confirmation.",
                permission_decision="ask",
                tool_args=["git", *tokens[1:]],
            )
        return pass_through(f"`git {subcommand}` is not in the supported RTK rewrite set.")

    if top in {"ls", "tree"}:
        return routed(
            strategy=f"rtk_{top}",
            reason=f"Read-oriented `{top}` command rewritten through RTK.",
            permission_decision="allow",
            tool_args=[top, *tokens[1:]],
        )

    if top == "find":
        rewritten = parse_find_command(tokens)
        if rewritten is None:
            return pass_through("Only simple `find <path> -name <pattern> [-type f|d]` is auto-rewritten.")
        return routed(
            strategy="rtk_find",
            reason="Simple find command rewritten through RTK.",
            permission_decision="allow",
            tool_args=rewritten,
        )

    if top == "grep":
        if len(tokens) < 2:
            return pass_through("Bare `grep` command is too broad to rewrite safely.")
        pattern = None
        path = "."
        extras: list[str] = []
        positional: list[str] = []
        for token in tokens[1:]:
            if token.startswith("-"):
                extras.append(token)
            else:
                positional.append(token)
        if positional:
            pattern = positional[0]
        if len(positional) > 1:
            path = positional[1]
        if pattern is None or len(positional) > 2:
            return pass_through("Only simple `grep <pattern> [path] [flags]` is auto-rewritten.")
        return routed(
            strategy="rtk_grep",
            reason="Simple grep command rewritten through RTK.",
            permission_decision="allow",
            tool_args=["grep", pattern, path, *extras],
        )

    if top == "cat" and len(tokens) == 2 and not tokens[1].startswith("-"):
        return routed(
            strategy="rtk_read",
            reason="Single-file read rewritten to `rtk read`.",
            permission_decision="allow",
            tool_args=["read", tokens[1]],
        )

    if top == "diff" and 2 <= len(tokens[1:]) <= 2 and not any(arg.startswith("-") for arg in tokens[1:]):
        return routed(
            strategy="rtk_diff",
            reason="Simple file diff rewritten through RTK.",
            permission_decision="allow",
            tool_args=["diff", *tokens[1:]],
        )

    if top == "gh":
        return routed(
            strategy="rtk_gh",
            reason="GitHub CLI command rewritten through RTK and shown for confirmation.",
            permission_decision="ask",
            tool_args=["gh", *tokens[1:]],
        )

    if top == "cargo" and len(tokens) >= 2 and tokens[1] in {"build", "check", "clippy", "test", "install"}:
        return routed(
            strategy="rtk_cargo",
            reason=f"`cargo {tokens[1]}` rewritten through RTK and shown for confirmation.",
            permission_decision="ask",
            tool_args=["cargo", *tokens[1:]],
        )

    if top in {"pytest", "pnpm", "npm", "npx", "pip", "docker", "kubectl", "curl", "wget", "ruff"}:
        return routed(
            strategy=f"rtk_{top.replace('-', '_')}",
            reason=f"`{top}` command rewritten through RTK and shown for confirmation.",
            permission_decision="ask",
            tool_args=[top, *tokens[1:]],
        )

    if top in {"go", "golangci-lint", "vitest", "prisma", "tsc", "next", "playwright"}:
        return routed(
            strategy=f"rtk_{top.replace('-', '_')}",
            reason=f"`{top}` command rewritten through RTK and shown for confirmation.",
            permission_decision="ask",
            tool_args=[top, *tokens[1:]],
        )

    if top == "python" and tokens[1:3] == ["-m", "pytest"]:
        return routed(
            strategy="rtk_test",
            reason="`python -m pytest` rewritten to `rtk test` and shown for confirmation.",
            permission_decision="ask",
            tool_args=["test", *tokens],
        )

    if top == "uv" and tokens[1:3] == ["run", "pytest"]:
        return routed(
            strategy="rtk_test",
            reason="`uv run pytest` rewritten to `rtk test` and shown for confirmation.",
            permission_decision="ask",
            tool_args=["test", *tokens],
        )

    return pass_through("No safe RTK rewrite rule matched this command.")


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
    jq_path = resolve_tool("jq") or resolve_tool("gojq")
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
    toon_path = resolve_tool("toon")
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


def command_doctor() -> None:
    report = {
        "platform": {
            "system": platform.system(),
            "machine": platform.machine(),
            "python": sys.version.split()[0],
        },
        "vendor_dir": str(VENDOR_DIR),
        "tools": {
            tool: tool_runtime_status(tool)
            for tool in TOOLS
        },
    }
    print(json.dumps(report, ensure_ascii=False, indent=2))


def command_profile(args: argparse.Namespace) -> None:
    data = load_json(args.input)
    print(json.dumps(profile_payload(data), ensure_ascii=False, indent=2))


def command_rewrite_bash(args: argparse.Namespace) -> None:
    print(json.dumps(rewrite_bash_command(args.bash_command), ensure_ascii=False, indent=2))


def command_tool(args: argparse.Namespace) -> None:
    tool_path = resolve_tool(args.tool_name)
    if not tool_path:
        raise SystemExit(f"Tool `{args.tool_name}` is not available.")
    result = subprocess.run([tool_path, *args.tool_args], check=False)
    raise SystemExit(result.returncode)


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
    if args.command == "doctor":
        command_doctor()
        return
    if args.command == "profile":
        command_profile(args)
        return
    if args.command == "rewrite-bash":
        command_rewrite_bash(args)
        return
    if args.command == "tool":
        command_tool(args)
        return
    if args.command == "prune":
        command_prune(args)
        return
    raise SystemExit(f"Unknown command: {args.command}")


if __name__ == "__main__":
    main()

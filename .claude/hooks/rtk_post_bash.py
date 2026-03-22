#!/usr/bin/env python3

from __future__ import annotations

import json
import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
TOKEN_PRUNER = REPO_ROOT / "scripts" / "token_pruner.py"

MAX_LINES = 200
TAIL_LINES = 20


def truncate_output(text: str) -> str | None:
    """Truncate text in-process without spawning a subprocess.

    Returns None if no truncation was needed.
    """
    import re

    ansi_re = re.compile(r"\x1b\[[0-9;]*[A-Za-z]|\x1b\][^\x07]*\x07|\x1b[()][A-B012]")
    cleaned = ansi_re.sub("", text)

    lines = cleaned.splitlines(keepends=True)
    total = len(lines)

    if total <= MAX_LINES:
        if cleaned != text:
            return cleaned
        return None

    head_count = max(MAX_LINES - TAIL_LINES, 1)
    omitted = total - head_count - TAIL_LINES

    head = lines[:head_count]
    tail = lines[-TAIL_LINES:] if TAIL_LINES > 0 else []
    separator = f"\n... ({omitted} lines omitted, {total} total) ...\n\n"

    return "".join(head) + separator + "".join(tail)


def main() -> int:
    try:
        payload = json.load(sys.stdin)
    except json.JSONDecodeError:
        return 0

    if payload.get("tool_name") != "Bash":
        return 0

    tool_result = payload.get("tool_result") or {}
    stdout = tool_result.get("stdout")
    stderr = tool_result.get("stderr")

    if not stdout and not stderr:
        return 0

    changed = False
    updated_result = {**tool_result}

    if stdout:
        truncated = truncate_output(stdout)
        if truncated is not None:
            updated_result["stdout"] = truncated
            changed = True

    if stderr:
        truncated = truncate_output(stderr)
        if truncated is not None:
            updated_result["stderr"] = truncated
            changed = True

    if not changed:
        return 0

    output = {
        "hookSpecificOutput": {
            "hookEventName": "PostToolUse",
            "updatedResult": updated_result,
        }
    }
    json.dump(output, sys.stdout, ensure_ascii=False)
    sys.stdout.write("\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

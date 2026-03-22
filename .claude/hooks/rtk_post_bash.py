#!/usr/bin/env python3

from __future__ import annotations

import hashlib
import json
import sys
import tempfile
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
TOKEN_PRUNER = REPO_ROOT / "scripts" / "token_pruner.py"

MAX_LINES = 200
TAIL_LINES = 20

CACHE_DIR = Path(tempfile.gettempdir()) / "token-pruner-cache"
MAX_CACHE_ENTRIES = 64


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


def _cache_key(command: str) -> str:
    return hashlib.sha256(command.encode("utf-8")).hexdigest()[:16]


def _output_hash(stdout: str, stderr: str) -> str:
    content = (stdout or "") + "\x00" + (stderr or "")
    return hashlib.sha256(content.encode("utf-8")).hexdigest()[:24]


def _evict_oldest() -> None:
    try:
        entries = sorted(CACHE_DIR.iterdir(), key=lambda p: p.stat().st_mtime)
    except OSError:
        return
    while len(entries) > MAX_CACHE_ENTRIES:
        entries.pop(0).unlink(missing_ok=True)


def check_cache(command: str, stdout: str, stderr: str) -> str | None:
    """Check if the same command produced the same output before.

    Returns a short dedup message if hit, None otherwise. Always updates the cache.
    """
    try:
        CACHE_DIR.mkdir(parents=True, exist_ok=True)
    except OSError:
        return None

    key = _cache_key(command)
    current_hash = _output_hash(stdout, stderr)
    cache_file = CACHE_DIR / key

    hit = False
    if cache_file.exists():
        try:
            prev_hash = cache_file.read_text(encoding="utf-8").strip()
            if prev_hash == current_hash:
                hit = True
        except OSError:
            pass

    try:
        cache_file.write_text(current_hash + "\n", encoding="utf-8")
        _evict_oldest()
    except OSError:
        pass

    if hit:
        lines = (stdout or "").count("\n")
        size = len((stdout or "").encode("utf-8"))
        return f"(same output as previous run, {lines} lines / {size} bytes omitted)"
    return None


def main() -> int:
    try:
        payload = json.load(sys.stdin)
    except json.JSONDecodeError:
        return 0

    if payload.get("tool_name") != "Bash":
        return 0

    tool_input = payload.get("tool_input") or {}
    command = tool_input.get("command", "")

    tool_result = payload.get("tool_result") or {}
    stdout = tool_result.get("stdout") or ""
    stderr = tool_result.get("stderr") or ""

    if not stdout and not stderr:
        return 0

    changed = False
    updated_result = {**tool_result}

    # Check output dedup cache first
    if command:
        dedup = check_cache(command, stdout, stderr)
        if dedup is not None:
            updated_result["stdout"] = dedup
            if stderr:
                updated_result["stderr"] = ""
            output = {
                "hookSpecificOutput": {
                    "hookEventName": "PostToolUse",
                    "updatedResult": updated_result,
                }
            }
            json.dump(output, sys.stdout, ensure_ascii=False)
            sys.stdout.write("\n")
            return 0

    # Truncation pass
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

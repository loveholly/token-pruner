#!/usr/bin/env python3

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
TOKEN_PRUNER = REPO_ROOT / "scripts" / "token_pruner.py"


def main() -> int:
    try:
        payload = json.load(sys.stdin)
    except json.JSONDecodeError:
        return 0

    if payload.get("tool_name") != "Bash":
        return 0

    tool_input = payload.get("tool_input") or {}
    command = tool_input.get("command")
    if not isinstance(command, str) or not command.strip():
        return 0

    completed = subprocess.run(
        [sys.executable, str(TOKEN_PRUNER), "rewrite-bash", "--command", command],
        text=True,
        capture_output=True,
        check=False,
    )
    if completed.returncode != 0:
        return 0

    try:
        decision = json.loads(completed.stdout)
    except json.JSONDecodeError:
        return 0

    rewritten_command = decision.get("rewritten_command")
    permission_decision = decision.get("permission_decision")
    reason = decision.get("reason")
    if not rewritten_command or not permission_decision or not reason:
        return 0

    output = {
        "hookSpecificOutput": {
            "hookEventName": "PreToolUse",
            "permissionDecision": permission_decision,
            "permissionDecisionReason": reason,
            "updatedInput": {
                **tool_input,
                "command": rewritten_command,
            },
        }
    }
    json.dump(output, sys.stdout, ensure_ascii=False)
    sys.stdout.write("\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

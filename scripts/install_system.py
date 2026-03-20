#!/usr/bin/env python3

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
from datetime import datetime
from pathlib import Path
from typing import Any


SKILL_NAME = "token-pruner"
SOURCE_ROOT = Path(__file__).resolve().parents[1]
SCRIPT_DIR = SOURCE_ROOT / "scripts"
HOME = Path.home()
CODEX_HOME = Path(os.environ.get("CODEX_HOME", HOME / ".codex")).expanduser()
CLAUDE_HOME = HOME / ".claude"
CODEX_TARGET = CODEX_HOME / "skills" / SKILL_NAME
CLAUDE_TARGET = CLAUDE_HOME / "skills" / SKILL_NAME
CLAUDE_SETTINGS = CLAUDE_HOME / "settings.json"
CLAUDE_MD = CLAUDE_HOME / "CLAUDE.md"
CLAUDE_HOOK_COMMAND = f"python3 {CLAUDE_TARGET / '.claude' / 'hooks' / 'rtk_pre_bash.py'}"
CLAUDE_BLOCK_START = "<!-- token-pruner:start -->"
CLAUDE_BLOCK_END = "<!-- token-pruner:end -->"
COPY_IGNORE = shutil.ignore_patterns(".git", ".DS_Store", "__pycache__", "*.pyc")
VENDOR_DIR = SCRIPT_DIR / "vendor"
FETCH_VENDOR_SCRIPT = SCRIPT_DIR / "fetch_vendor_bundle.py"
BOOTSTRAP_VENDOR_SCRIPT = SCRIPT_DIR / "bootstrap_vendor.py"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Bootstrap token-pruner by ensuring vendor tools exist and installing system-level copies."
    )
    parser.add_argument("--codex-only", action="store_true", help="Install only into the Codex skill directory.")
    parser.add_argument("--claude-only", action="store_true", help="Install only into the Claude Code global directory.")
    parser.add_argument(
        "--no-backup",
        action="store_true",
        help="Replace existing install directories in place instead of moving them to timestamped backups first.",
    )
    parser.add_argument(
        "--prefer-bootstrap",
        action="store_true",
        help="Build the local vendor tree instead of downloading a release asset first.",
    )
    parser.add_argument("--vendor-repo", help="Override the GitHub repo used for prebuilt vendor bundle downloads.")
    parser.add_argument("--vendor-tag", default="latest", help="Release tag used for vendor bundle downloads.")
    return parser.parse_args()


def ensure_valid_args(args: argparse.Namespace) -> None:
    if args.codex_only and args.claude_only:
        raise SystemExit("Choose only one of --codex-only or --claude-only.")


def backup_target(path: Path) -> Path | None:
    if not path.exists():
        return None
    timestamp = datetime.now().strftime("%Y%m%d%H%M%S")
    backup = path.with_name(f"{path.name}.bak-{timestamp}")
    path.rename(backup)
    return backup


def reset_target(path: Path, no_backup: bool) -> Path | None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if not path.exists():
        return None
    if no_backup:
        shutil.rmtree(path)
        return None
    return backup_target(path)


def install_tree(target: Path, no_backup: bool) -> dict[str, str | None]:
    backup = reset_target(target, no_backup)
    shutil.copytree(SOURCE_ROOT, target, ignore=COPY_IGNORE, symlinks=True)
    return {
        "target": str(target),
        "backup": str(backup) if backup else None,
    }


def vendor_ready() -> bool:
    expected = (
        VENDOR_DIR / "bin" / "rtk",
        VENDOR_DIR / "bin" / "jq",
        VENDOR_DIR / "bin" / "qsv",
        VENDOR_DIR / "bin" / "jc",
        VENDOR_DIR / "bin" / "toon",
    )
    return all(path.exists() for path in expected)


def run_step(command: list[str]) -> tuple[bool, str]:
    completed = subprocess.run(
        command,
        text=True,
        capture_output=True,
        check=False,
    )
    combined = "\n".join(part for part in (completed.stdout.strip(), completed.stderr.strip()) if part)
    return completed.returncode == 0, combined


def ensure_vendor_tree(args: argparse.Namespace) -> dict[str, Any]:
    if vendor_ready():
        return {"strategy": "existing", "vendor_dir": str(VENDOR_DIR)}

    attempts: list[dict[str, Any]] = []

    if not args.prefer_bootstrap:
        fetch_command = [sys.executable, str(FETCH_VENDOR_SCRIPT), "--destination", str(VENDOR_DIR), "--tag", args.vendor_tag]
        if args.vendor_repo:
            fetch_command.extend(["--repo", args.vendor_repo])
        ok, output = run_step(fetch_command)
        attempts.append(
            {
                "strategy": "release_asset",
                "ok": ok,
                "details": output,
            }
        )
        if ok and vendor_ready():
            return {
                "strategy": "release_asset",
                "vendor_dir": str(VENDOR_DIR),
                "attempts": attempts,
            }

    ok, output = run_step([sys.executable, str(BOOTSTRAP_VENDOR_SCRIPT)])
    attempts.append(
        {
            "strategy": "bootstrap",
            "ok": ok,
            "details": output,
        }
    )
    if ok and vendor_ready():
        return {
            "strategy": "bootstrap",
            "vendor_dir": str(VENDOR_DIR),
            "attempts": attempts,
        }

    raise SystemExit(json.dumps({"error": "Failed to prepare vendor toolchain.", "attempts": attempts}, ensure_ascii=False, indent=2))


def load_json(path: Path) -> Any:
    if not path.exists():
        return {}
    raw = path.read_text(encoding="utf-8").strip()
    if not raw:
        return {}
    return json.loads(raw)


def ensure_claude_hook(settings: dict[str, Any]) -> bool:
    hooks = settings.setdefault("hooks", {})
    pre_tool_use = hooks.setdefault("PreToolUse", [])
    for entry in pre_tool_use:
        if entry.get("matcher") != "Bash":
            continue
        hook_list = entry.setdefault("hooks", [])
        if any(
            hook.get("type") == "command" and hook.get("command") == CLAUDE_HOOK_COMMAND
            for hook in hook_list
        ):
            return False
        hook_list.append(
            {
                "type": "command",
                "command": CLAUDE_HOOK_COMMAND,
            }
        )
        return True

    pre_tool_use.append(
        {
            "matcher": "Bash",
            "hooks": [
                {
                    "type": "command",
                    "command": CLAUDE_HOOK_COMMAND,
                }
            ],
        }
    )
    return True


def write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def build_claude_block() -> str:
    lines = [
        CLAUDE_BLOCK_START,
        "# Token Pruner",
        "",
        f"- Installed bundle: `{CLAUDE_TARGET}`",
        f"- Run `python3 {CLAUDE_TARGET / 'scripts' / 'token_pruner.py'} doctor` when you need a runtime check.",
        "- Prefer this bundle when JSON, NDJSON, tables, or noisy CLI output are the expensive part of the context.",
        "- A global Bash `PreToolUse` hook routes common read-oriented commands through vendored RTK automatically.",
        CLAUDE_BLOCK_END,
        "",
    ]
    return "\n".join(lines)


def update_claude_md() -> bool:
    existing = CLAUDE_MD.read_text(encoding="utf-8") if CLAUDE_MD.exists() else ""
    block = build_claude_block()
    start = existing.find(CLAUDE_BLOCK_START)
    end = existing.find(CLAUDE_BLOCK_END)
    if start != -1 and end != -1 and end > start:
        end += len(CLAUDE_BLOCK_END)
        updated = existing[:start] + block + existing[end:]
    else:
        if existing and not existing.endswith("\n"):
            existing += "\n"
        updated = existing + ("\n" if existing else "") + block
    changed = updated != existing
    if changed:
        CLAUDE_MD.write_text(updated, encoding="utf-8")
    return changed


def main() -> int:
    args = parse_args()
    ensure_valid_args(args)

    install_codex = not args.claude_only
    install_claude = not args.codex_only

    result: dict[str, Any] = {
        "source": str(SOURCE_ROOT),
        "vendor": ensure_vendor_tree(args),
        "installed": {},
    }

    if install_codex:
        result["installed"]["codex"] = install_tree(CODEX_TARGET, args.no_backup)

    if install_claude:
        claude_install = install_tree(CLAUDE_TARGET, args.no_backup)
        settings = load_json(CLAUDE_SETTINGS)
        settings_changed = ensure_claude_hook(settings)
        if settings_changed:
            write_json(CLAUDE_SETTINGS, settings)
        md_changed = update_claude_md()
        claude_install["settings_updated"] = settings_changed
        claude_install["claude_md_updated"] = md_changed
        claude_install["hook_command"] = CLAUDE_HOOK_COMMAND
        result["installed"]["claude"] = claude_install

    json.dump(result, fp=os.sys.stdout, ensure_ascii=False, indent=2)
    os.sys.stdout.write("\n")
    return 0


def bootstrap() -> int:
    return main()


if __name__ == "__main__":
    raise SystemExit(main())

#!/usr/bin/env python3

from __future__ import annotations

import argparse
import hashlib
import json
import platform
import tarfile
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
VENDOR_DIR = REPO_ROOT / "scripts" / "vendor"
DEFAULT_OUTPUT_DIR = REPO_ROOT / "dist"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Package scripts/vendor as a GitHub Release asset."
    )
    parser.add_argument(
        "--output-dir",
        default=str(DEFAULT_OUTPUT_DIR),
        help="Directory where the tar.gz asset should be written.",
    )
    return parser.parse_args()


def platform_slug() -> str:
    system_map = {
        "darwin": "darwin",
        "linux": "linux",
        "windows": "windows",
    }
    machine_map = {
        "arm64": "arm64",
        "aarch64": "arm64",
        "x86_64": "x64",
        "amd64": "x64",
    }

    system_name = platform.system()
    machine_name = platform.machine()
    system = system_map.get(system_name.lower())
    machine = machine_map.get(machine_name.lower())
    if not system or not machine:
        raise SystemExit(f"Unsupported platform: {system_name} {machine_name}")
    return f"{system}-{machine}"


def asset_name() -> str:
    return f"token-pruner-vendor-{platform_slug()}.tar.gz"


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def main() -> int:
    if not VENDOR_DIR.exists():
        raise SystemExit("scripts/vendor does not exist. Build or fetch the vendor tree first.")

    output_dir = Path(parse_args().output_dir).expanduser().resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    archive_path = output_dir / asset_name()

    with tarfile.open(archive_path, "w:gz") as archive:
        archive.add(VENDOR_DIR, arcname="vendor")

    result = {
        "archive": str(archive_path),
        "sha256": sha256(archive_path),
        "size_bytes": archive_path.stat().st_size,
        "platform": platform_slug(),
    }
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

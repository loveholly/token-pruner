#!/usr/bin/env python3

from __future__ import annotations

import argparse
import json
import os
import platform
import re
import shutil
import subprocess
import tarfile
import tempfile
import urllib.request
from pathlib import Path
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_REPO = "loveholly/token-pruner"
DEFAULT_DESTINATION = REPO_ROOT / "scripts" / "vendor"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Download a prebuilt token-pruner vendor bundle from GitHub Releases."
    )
    parser.add_argument("--repo", help="GitHub repo in owner/name format. Defaults to origin or loveholly/token-pruner.")
    parser.add_argument("--tag", default="latest", help="Release tag to fetch. Defaults to latest.")
    parser.add_argument(
        "--destination",
        default=str(DEFAULT_DESTINATION),
        help="Directory where the vendor bundle should be extracted.",
    )
    parser.add_argument("--asset-name", help="Override the expected asset name.")
    return parser.parse_args()


def request_json(url: str) -> dict[str, Any]:
    headers = {
        "Accept": "application/vnd.github+json",
        "User-Agent": "token-pruner-fetch-vendor",
    }
    token = os.environ.get("GH_TOKEN") or os.environ.get("GITHUB_TOKEN")
    if token:
        headers["Authorization"] = f"Bearer {token}"
    req = urllib.request.Request(url, headers=headers)
    with urllib.request.urlopen(req) as response:  # noqa: S310
        return json.load(response)


def download_file(url: str, destination: Path) -> None:
    headers = {"User-Agent": "token-pruner-fetch-vendor"}
    token = os.environ.get("GH_TOKEN") or os.environ.get("GITHUB_TOKEN")
    if token:
        headers["Authorization"] = f"Bearer {token}"
    req = urllib.request.Request(url, headers=headers)
    with urllib.request.urlopen(req) as response, destination.open("wb") as handle:  # noqa: S310
        shutil.copyfileobj(response, handle)


def detect_repo_from_git() -> str | None:
    completed = subprocess.run(
        ["git", "-C", str(REPO_ROOT), "config", "--get", "remote.origin.url"],
        text=True,
        capture_output=True,
        check=False,
    )
    if completed.returncode != 0:
        return None
    url = completed.stdout.strip()
    if not url:
        return None

    match = re.search(r"github\.com[:/](?P<owner>[^/]+)/(?P<repo>[^/.]+)(?:\.git)?$", url)
    if not match:
        return None
    return f"{match.group('owner')}/{match.group('repo')}"


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


def expected_asset_name() -> str:
    return f"token-pruner-vendor-{platform_slug()}.tar.gz"


def release_url(repo: str, tag: str) -> str:
    if tag == "latest":
        return f"https://api.github.com/repos/{repo}/releases/latest"
    return f"https://api.github.com/repos/{repo}/releases/tags/{tag}"


def safe_extract_tar(archive_path: Path, destination_root: Path) -> Path:
    destination_root.mkdir(parents=True, exist_ok=True)
    with tarfile.open(archive_path, "r:gz") as archive:
        for member in archive.getmembers():
            member_path = (destination_root / member.name).resolve()
            if not str(member_path).startswith(str(destination_root.resolve())):
                raise SystemExit(f"Refusing to extract suspicious path: {member.name}")
        archive.extractall(destination_root)
    extracted = destination_root / "vendor"
    if not extracted.exists():
        raise SystemExit("Bundle did not contain a top-level vendor directory.")
    return extracted


def select_asset(release: dict[str, Any], name: str) -> dict[str, Any]:
    assets = release.get("assets") or []
    for asset in assets:
        if asset.get("name") == name:
            return asset
    available = ", ".join(asset.get("name", "<unknown>") for asset in assets)
    raise SystemExit(f"Could not find asset `{name}` in release. Available assets: {available}")


def replace_destination(source_dir: Path, destination: Path) -> None:
    if destination.exists():
        shutil.rmtree(destination)
    destination.parent.mkdir(parents=True, exist_ok=True)
    shutil.move(str(source_dir), str(destination))


def main() -> int:
    args = parse_args()
    repo = args.repo or detect_repo_from_git() or DEFAULT_REPO
    asset_name = args.asset_name or expected_asset_name()
    destination = Path(args.destination).expanduser().resolve()

    release = request_json(release_url(repo, args.tag))
    asset = select_asset(release, asset_name)

    with tempfile.TemporaryDirectory() as temp_dir:
        temp_root = Path(temp_dir)
        archive_path = temp_root / asset_name
        download_file(asset["browser_download_url"], archive_path)
        extracted = safe_extract_tar(archive_path, temp_root / "extract")
        replace_destination(extracted, destination)

    result = {
        "repo": repo,
        "tag": release.get("tag_name"),
        "asset_name": asset_name,
        "destination": str(destination),
    }
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

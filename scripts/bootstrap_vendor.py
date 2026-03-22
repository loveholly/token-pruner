#!/usr/bin/env python3

from __future__ import annotations

import json
import platform
import shutil
import stat
import subprocess
import sys
import tarfile
import tempfile
import urllib.request
import zipfile
from pathlib import Path


SCRIPT_DIR = Path(__file__).resolve().parent
VENDOR_DIR = SCRIPT_DIR / "vendor"
BIN_DIR = VENDOR_DIR / "bin"
LIB_DIR = VENDOR_DIR / "lib"
PYTHON_DIR = VENDOR_DIR / "python"
NODE_DIR = VENDOR_DIR / "node"

RTK_VERSION = "v0.15.2"
QSV_VERSION = "9.1.0"
JC_VERSION = "1.25.6"
TOON_CLI_VERSION = "2.1.0"
YQ_VERSION = "v4.44.6"


def log(message: str) -> None:
    print(f"[bootstrap] {message}")


def ensure_dirs() -> None:
    for path in (BIN_DIR, LIB_DIR, PYTHON_DIR, NODE_DIR):
        path.mkdir(parents=True, exist_ok=True)


def request_json(url: str) -> dict:
    req = urllib.request.Request(
        url,
        headers={
            "Accept": "application/vnd.github+json",
            "User-Agent": "token-pruner-bootstrap",
        },
    )
    with urllib.request.urlopen(req) as response:  # noqa: S310
        return json.load(response)


def download_file(url: str, destination: Path) -> None:
    req = urllib.request.Request(url, headers={"User-Agent": "token-pruner-bootstrap"})
    with urllib.request.urlopen(req) as response, destination.open("wb") as handle:  # noqa: S310
        shutil.copyfileobj(response, handle)


def make_executable(path: Path) -> None:
    mode = path.stat().st_mode
    path.chmod(mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)


def machine_tokens() -> tuple[list[str], list[str]]:
    system = platform.system().lower()
    machine = platform.machine().lower()

    os_tokens_map = {
        "darwin": ["darwin", "apple", "macos", "mac", "osx"],
        "linux": ["linux", "gnu"],
        "windows": ["windows", "win", "pc-windows"],
    }
    arch_tokens_map = {
        "arm64": ["arm64", "aarch64"],
        "aarch64": ["arm64", "aarch64"],
        "x86_64": ["x86_64", "amd64", "x64"],
        "amd64": ["x86_64", "amd64", "x64"],
    }

    os_tokens = os_tokens_map.get(system, [system])
    arch_tokens = arch_tokens_map.get(machine, [machine])
    return os_tokens, arch_tokens


def select_asset(assets: list[dict], name_hints: list[str]) -> dict:
    os_tokens, arch_tokens = machine_tokens()
    ranked: list[tuple[int, dict]] = []
    for asset in assets:
        name = asset["name"].lower()
        score = 0
        if any(token in name for token in os_tokens):
            score += 3
        if any(token in name for token in arch_tokens):
            score += 3
        if all(hint in name for hint in name_hints):
            score += 2
        if name.endswith((".tar.gz", ".tgz", ".zip")):
            score += 1
        if score > 0:
            ranked.append((score, asset))

    if not ranked:
        asset_names = ", ".join(asset["name"] for asset in assets)
        raise RuntimeError(f"No release asset matched this platform. Assets: {asset_names}")

    ranked.sort(key=lambda item: item[0], reverse=True)
    return ranked[0][1]


def extract_binary(archive_path: Path, binary_names: list[str], destination_name: str) -> None:
    dest_path = BIN_DIR / destination_name

    if archive_path.suffix == ".zip":
        with zipfile.ZipFile(archive_path) as archive:
            for member in archive.infolist():
                if Path(member.filename).name in binary_names:
                    with archive.open(member) as src, dest_path.open("wb") as dst:
                        shutil.copyfileobj(src, dst)
                    make_executable(dest_path)
                    return
    else:
        with tarfile.open(archive_path, "r:*") as archive:
            for member in archive.getmembers():
                if Path(member.name).name in binary_names:
                    extracted = archive.extractfile(member)
                    if extracted is None:
                        continue
                    with extracted, dest_path.open("wb") as dst:
                        shutil.copyfileobj(extracted, dst)
                    make_executable(dest_path)
                    return

    raise RuntimeError(f"Could not find {binary_names} in {archive_path.name}")


def install_github_binary(repo: str, tag: str, name_hints: list[str], binary_names: list[str], destination_name: str) -> None:
    release = request_json(f"https://api.github.com/repos/{repo}/releases/tags/{tag}")
    asset = select_asset(release["assets"], name_hints)
    with tempfile.TemporaryDirectory() as temp_dir:
        archive_path = Path(temp_dir) / asset["name"]
        log(f"Downloading {repo}@{tag}: {asset['name']}")
        download_file(asset["browser_download_url"], archive_path)
        if archive_path.name.endswith((".tar.gz", ".tgz", ".zip")):
            extract_binary(archive_path, binary_names, destination_name)
        else:
            shutil.copy2(archive_path, BIN_DIR / destination_name)
            make_executable(BIN_DIR / destination_name)


def install_local_jq_macos() -> None:
    jq_path = shutil.which("jq")
    if not jq_path:
        raise RuntimeError("Local jq not found. Install jq locally or add a release-based jq path.")

    jq_binary = Path(jq_path).resolve()
    if platform.system().lower() != "darwin":
        shutil.copy2(jq_binary, BIN_DIR / "jq")
        make_executable(BIN_DIR / "jq")
        return

    libjq = Path("/opt/homebrew/Cellar/jq/1.8.1/lib/libjq.1.dylib")
    libonig = Path("/opt/homebrew/opt/oniguruma/lib/libonig.5.dylib")
    if not libjq.exists() or not libonig.exists():
        raise RuntimeError("Expected Homebrew jq libraries were not found.")

    shutil.copy2(jq_binary, BIN_DIR / "jq")
    shutil.copy2(libjq, LIB_DIR / libjq.name)
    shutil.copy2(libonig, LIB_DIR / libonig.name)

    subprocess.run(
        [
            "install_name_tool",
            "-change",
            str(libjq),
            f"@executable_path/../lib/{libjq.name}",
            str(BIN_DIR / "jq"),
        ],
        check=True,
    )
    subprocess.run(
        [
            "install_name_tool",
            "-change",
            str(libonig),
            f"@executable_path/../lib/{libonig.name}",
            str(BIN_DIR / "jq"),
        ],
        check=True,
    )
    subprocess.run(
        [
            "install_name_tool",
            "-change",
            str(libonig),
            f"@loader_path/{libonig.name}",
            str(LIB_DIR / libjq.name),
        ],
        check=True,
    )
    subprocess.run(
        [
            "codesign",
            "--force",
            "--sign",
            "-",
            str(LIB_DIR / libjq.name),
        ],
        check=True,
    )
    subprocess.run(
        [
            "codesign",
            "--force",
            "--sign",
            "-",
            str(BIN_DIR / "jq"),
        ],
        check=True,
    )
    make_executable(BIN_DIR / "jq")


def write_wrapper(path: Path, content: str) -> None:
    path.write_text(content, encoding="utf-8")
    make_executable(path)


def install_jc() -> None:
    log(f"Installing jc=={JC_VERSION} into vendored Python site-packages")
    subprocess.run(
        [
            sys.executable,
            "-m",
            "pip",
            "install",
            f"jc=={JC_VERSION}",
            "--target",
            str(PYTHON_DIR),
            "--upgrade",
        ],
        check=True,
    )
    wrapper = """#!/bin/sh
set -eu
SCRIPT_DIR="$(CDPATH= cd -- "$(dirname "$0")" && pwd)"
PYTHONPATH="$SCRIPT_DIR/../python${PYTHONPATH:+:$PYTHONPATH}" exec python3 -m jc "$@"
"""
    write_wrapper(BIN_DIR / "jc", wrapper)


def install_toon() -> None:
    log(f"Installing @toon-format/cli@{TOON_CLI_VERSION} into vendored node_modules")
    subprocess.run(
        [
            "npm",
            "install",
            "--prefix",
            str(NODE_DIR),
            f"@toon-format/cli@{TOON_CLI_VERSION}",
            "--omit=dev",
            "--no-package-lock",
        ],
        check=True,
    )
    wrapper = """#!/bin/sh
set -eu
SCRIPT_DIR="$(CDPATH= cd -- "$(dirname "$0")" && pwd)"
exec "$SCRIPT_DIR/../node/node_modules/@toon-format/cli/bin/toon.mjs" "$@"
"""
    write_wrapper(BIN_DIR / "toon", wrapper)


def install_rtk() -> None:
    install_github_binary(
        repo="rtk-ai/rtk",
        tag=RTK_VERSION,
        name_hints=["rtk"],
        binary_names=["rtk", "rtk.exe"],
        destination_name="rtk",
    )


def install_qsv() -> None:
    repos = ("jqnatividad/qsv", "dathere/qsv")
    last_error: Exception | None = None
    for repo in repos:
        try:
            install_github_binary(
                repo=repo,
                tag=QSV_VERSION,
                name_hints=["qsv"],
                binary_names=["qsv", "qsv.exe"],
                destination_name="qsv",
            )
            return
        except Exception as exc:  # noqa: BLE001
            last_error = exc
    raise RuntimeError(f"Failed to install qsv from official releases: {last_error}") from last_error


def install_yq() -> None:
    install_github_binary(
        repo="mikefarah/yq",
        tag=YQ_VERSION,
        name_hints=["yq"],
        binary_names=["yq", "yq_darwin_arm64", "yq_darwin_amd64", "yq_linux_amd64", "yq_linux_arm64", "yq.exe"],
        destination_name="yq",
    )


def install_all() -> None:
    ensure_dirs()
    install_local_jq_macos()
    install_rtk()
    install_qsv()
    install_jc()
    install_toon()
    install_yq()
    log("Vendored toolchain ready.")


if __name__ == "__main__":
    install_all()

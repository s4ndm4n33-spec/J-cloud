#!/usr/bin/env python3
"""Generate a machine-readable release manifest and SHA-256 checksums.

Usage:
    python3 generate_manifest.py --shard-dir <path> --version <ver> --repo-root <path>

Produces:
    <shard-dir>/manifests/manifest.json
    <shard-dir>/manifests/SHA256SUMS.txt
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def git_commit(repo_root: str) -> str:
    try:
        r = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=repo_root, capture_output=True, text=True, timeout=10,
        )
        return r.stdout.strip() if r.returncode == 0 else "unknown"
    except Exception:
        return "unknown"


def git_branch(repo_root: str) -> str:
    try:
        r = subprocess.run(
            ["git", "rev-parse", "--abbrev-ref", "HEAD"],
            cwd=repo_root, capture_output=True, text=True, timeout=10,
        )
        return r.stdout.strip() if r.returncode == 0 else "unknown"
    except Exception:
        return "unknown"


def detect_runtime_versions(shard_dir: Path) -> dict:
    versions: dict[str, str | None] = {}
    for name, rel in [("python", "runtime/python/python.exe"),
                      ("node", "runtime/node/node.exe")]:
        exe = shard_dir / rel
        if exe.exists():
            try:
                r = subprocess.run(
                    [str(exe), "--version"],
                    capture_output=True, text=True, timeout=10,
                )
                versions[name] = r.stdout.strip()
            except Exception:
                versions[name] = "present (version unknown)"
        else:
            versions[name] = None
    return versions


def main() -> int:
    parser = argparse.ArgumentParser(description="Generate release manifest")
    parser.add_argument("--shard-dir", required=True, type=Path)
    parser.add_argument("--version", required=True)
    parser.add_argument("--repo-root", required=True, type=Path)
    args = parser.parse_args()

    shard_dir: Path = args.shard_dir
    manifests_dir = shard_dir / "manifests"
    manifests_dir.mkdir(parents=True, exist_ok=True)

    # Collect all files and compute checksums
    files: list[dict] = []
    checksums_lines: list[str] = []

    for root, _dirs, fnames in os.walk(shard_dir):
        # Skip the manifests directory itself (we're generating into it)
        if Path(root) == manifests_dir:
            continue
        for fname in sorted(fnames):
            fpath = Path(root) / fname
            rel = fpath.relative_to(shard_dir).as_posix()
            digest = sha256_file(fpath)
            size = fpath.stat().st_size
            files.append({"path": rel, "sha256": digest, "size": size})
            checksums_lines.append(f"{digest}  {rel}")

    # Write SHA256SUMS.txt
    checksums_path = manifests_dir / "SHA256SUMS.txt"
    checksums_path.write_text("\n".join(checksums_lines) + "\n", encoding="utf-8")

    # Detect components
    components: dict[str, str] = {}
    for comp in ["backend", "frontend", "launch", "config", "data",
                 "workspace", "logs", "models", "manifests"]:
        cdir = shard_dir / comp
        components[comp] = "present" if cdir.exists() else "missing"

    # Detect model files
    model_files = []
    models_dir = shard_dir / "models"
    if models_dir.exists():
        for f in models_dir.iterdir():
            if f.is_file():
                model_files.append(f.name)

    manifest = {
        "shard_name": "J-cloud-Sovereign",
        "version": args.version,
        "source_commit": git_commit(str(args.repo_root)),
        "source_branch": git_branch(str(args.repo_root)),
        "build_timestamp": datetime.now(timezone.utc).isoformat(),
        "profile": "portable",
        "runtime_versions": detect_runtime_versions(shard_dir),
        "components": components,
        "model_files": model_files,
        "model_identifier": model_files[0] if model_files else "",
        "file_count": len(files),
        "files": files,
        "checksums_file": "manifests/SHA256SUMS.txt",
    }

    manifest_path = manifests_dir / "manifest.json"
    manifest_path.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")

    print(f"[manifest] {len(files)} files hashed")
    print(f"[manifest] {manifest_path}")
    print(f"[manifest] {checksums_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

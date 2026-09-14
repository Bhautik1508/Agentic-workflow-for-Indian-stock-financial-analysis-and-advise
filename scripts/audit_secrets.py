#!/usr/bin/env python3
"""Audit: is any secret that leaked into git history still in use?

`backend/.env` was committed (62927b7) and later deleted (9f68825), but the blob
survives in history and is reachable from the public `origin/main`. Deleting a
file does not unpublish it — only rotation does.

This script compares SHA-256 hashes of the values in your live `.env` against
the values in every `.env` blob ever committed. It never prints, logs, or
transmits a secret — only a 12-char hash prefix, which is not reversible.

Usage:
    python scripts/audit_secrets.py           # audit
    python scripts/audit_secrets.py --json    # machine-readable

Exit codes:  0 = clean   1 = a leaked value is still in use   2 = could not run
"""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
ENV_PATH = REPO_ROOT / "backend" / ".env"
PINNED_PATH = Path(__file__).resolve().parent / "leaked_hashes.json"


def _git(*args: str) -> str:
    result = subprocess.run(
        ["git", *args], cwd=REPO_ROOT, capture_output=True, text=True
    )
    if result.returncode != 0:
        return ""
    return result.stdout


def _parse_env(text: str) -> dict[str, str]:
    """KEY=value -> {KEY: sha256(value)[:12]}. Blank values are ignored."""
    out: dict[str, str] = {}
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        value = value.strip().strip('"').strip("'")
        if value:
            out[key.strip()] = hashlib.sha256(value.encode()).hexdigest()[:12]
    return out


def find_leaked_env_blobs() -> list[str]:
    """Every blob in history whose path ends in `.env` (not `.env.example`)."""
    listing = _git("rev-list", "--all", "--objects")
    blobs: list[str] = []
    for line in listing.splitlines():
        parts = line.split(maxsplit=1)
        if len(parts) != 2:
            continue
        sha, path = parts
        name = path.rsplit("/", 1)[-1]
        if name == ".env":
            blobs.append(sha)
    return blobs


def load_pinned() -> dict[str, str]:
    """Hashes recorded before the blob was purged from history."""
    if not PINNED_PATH.exists():
        return {}
    try:
        return json.loads(PINNED_PATH.read_text()).get("hashes", {})
    except (json.JSONDecodeError, OSError):
        return {}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--json", action="store_true", help="machine-readable output")
    args = parser.parse_args()

    if not _git("rev-parse", "--is-inside-work-tree").strip():
        print("error: not a git repository", file=sys.stderr)
        return 2

    if not ENV_PATH.exists():
        print(f"error: {ENV_PATH} not found", file=sys.stderr)
        return 2

    current = _parse_env(ENV_PATH.read_text())
    blobs = find_leaked_env_blobs()

    # Merge both sources: blobs still in history, plus the pinned record that
    # survives a history rewrite.
    leaked: dict[str, str] = {}
    for sha in blobs:
        leaked.update(_parse_env(_git("cat-file", "-p", sha)))
    pinned = load_pinned()
    leaked.update(pinned)

    findings = []
    for key in sorted(set(current) | set(leaked)):
        if key in current and key in leaked and current[key] == leaked[key]:
            status, ok = "EXPOSED", False
        elif key in leaked and key in current:
            status, ok = "rotated", True
        elif key in leaked:
            status, ok = "leaked-but-unused", True
        else:
            status, ok = "never-leaked", True
        findings.append({"key": key, "status": status, "safe": ok})

    exposed = [f for f in findings if not f["safe"]]

    if args.json:
        print(json.dumps(
            {"env_blobs_in_history": len(blobs), "pinned_hashes": len(pinned),
             "findings": findings, "exposed_count": len(exposed)},
            indent=2,
        ))
        return 1 if exposed else 0

    print(f"Scanned {len(blobs)} `.env` blob(s) in history "
          f"+ {len(pinned)} pinned hash(es) from {PINNED_PATH.name}\n")
    label = {
        "EXPOSED": "[!] EXPOSED  - leaked value STILL IN USE, rotate now",
        "rotated": "[ok] rotated  - live value differs from the leaked one",
        "leaked-but-unused": "[ok] leaked, but no longer present in .env",
        "never-leaked": "[ok] never leaked",
    }
    for f in findings:
        print(f"  {f['key']:22} {label[f['status']]}")

    if exposed:
        print(f"\n{len(exposed)} secret(s) still exposed. Rotate, then re-run this script.")
        return 1

    print("\nClean - no leaked value is still in use.")
    return 0


if __name__ == "__main__":
    sys.exit(main())

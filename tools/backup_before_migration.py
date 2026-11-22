"""
Pre-migration backup tool for STEWARD.
Backs up steward.db, secret.key, and steward_operations.json to %APPDATA%\\STEWARD\\backups\\
with timestamped names including commit SHA, and generates a SHA-256 verification manifest.
"""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
import sys
from datetime import datetime, timezone
from typing import Any, Dict


def get_commit_sha(repo_dir: str) -> str:
    """Return short commit SHA for repo_dir or 'unknown'."""
    try:
        res = subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"],
            cwd=repo_dir,
            capture_output=True,
            text=True,
            check=True,
        )
        return res.stdout.strip()
    except Exception:
        return "unknown"


def compute_sha256(filepath: str) -> str:
    """Compute uppercase SHA-256 hex digest for filepath."""
    h = hashlib.sha256()
    with open(filepath, "rb") as f:
        while chunk := f.read(65536):
            h.update(chunk)
    return h.hexdigest().upper()


def get_backup_dir() -> str:
    """Return %APPDATA%\\STEWARD\\backups\\ or fallback ~/.steward/backups/."""
    appdata = os.environ.get("APPDATA")
    if appdata:
        backup_dir = os.path.join(appdata, "STEWARD", "backups")
    else:
        backup_dir = os.path.expanduser("~/.steward/backups")
    os.makedirs(backup_dir, exist_ok=True)
    return backup_dir


def run_backup(repo_dir: str | None = None) -> Dict[str, Any]:
    """Execute pre-migration backup of steward.db, secret.key, and steward_operations.json.

    Refuses to run if any source file is missing.
    Writes backup copies and verification manifest to %APPDATA%\\STEWARD\\backups\\.
    """
    if repo_dir is None:
        repo_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))

    db_path = os.path.join(repo_dir, "steward.db")
    key_path = os.path.join(repo_dir, "secret.key")
    ops_path = os.path.join(repo_dir, "steward_operations.json")

    missing = [p for p in (db_path, key_path, ops_path) if not os.path.isfile(p)]
    if missing:
        missing_names = [os.path.basename(p) for p in missing]
        raise FileNotFoundError(
            f"Pre-migration backup refused: missing source file(s): {', '.join(missing_names)}"
        )

    backup_dir = get_backup_dir()
    commit_sha = get_commit_sha(repo_dir)
    timestamp_str = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    prefix = f"steward_backup_{timestamp_str}_{commit_sha}"

    dest_db = os.path.join(backup_dir, f"{prefix}.db")
    dest_key = os.path.join(backup_dir, f"{prefix}.key")
    dest_ops = os.path.join(backup_dir, f"{prefix}_operations.json")
    manifest_path = os.path.join(backup_dir, f"{prefix}.json")

    # Copy files safely
    shutil.copy2(db_path, dest_db)
    shutil.copy2(key_path, dest_key)
    shutil.copy2(ops_path, dest_ops)

    # Compute source and destination hashes
    src_hashes = {
        "steward.db": compute_sha256(db_path),
        "secret.key": compute_sha256(key_path),
        "steward_operations.json": compute_sha256(ops_path),
    }
    dst_hashes = {
        "steward.db": compute_sha256(dest_db),
        "secret.key": compute_sha256(dest_key),
        "steward_operations.json": compute_sha256(dest_ops),
    }

    # Verify copy integrity
    for fname in src_hashes:
        if src_hashes[fname] != dst_hashes[fname]:
            raise IOError(
                f"Backup copy verification failed for {fname}: "
                f"source {src_hashes[fname]} != dest {dst_hashes[fname]}"
            )

    manifest = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "commit_sha": commit_sha,
        "backup_dir": backup_dir,
        "manifest_path": manifest_path,
        "files": {
            "steward.db": {
                "backup_filename": os.path.basename(dest_db),
                "backup_path": dest_db,
                "sha256": dst_hashes["steward.db"],
            },
            "secret.key": {
                "backup_filename": os.path.basename(dest_key),
                "backup_path": dest_key,
                "sha256": dst_hashes["secret.key"],
            },
            "steward_operations.json": {
                "backup_filename": os.path.basename(dest_ops),
                "backup_path": dest_ops,
                "sha256": dst_hashes["steward_operations.json"],
            },
        },
        "db_sha256": dst_hashes["steward.db"],
        "key_sha256": dst_hashes["secret.key"],
        "format_version": 1,
    }

    with open(manifest_path, "w", encoding="utf-8") as f:
        json.dump(manifest, f, indent=2)

    return manifest


def main() -> int:
    try:
        print("[*] Starting STEWARD pre-migration backup...")
        manifest = run_backup()
        print(f"[OK] Backup successful to: {manifest['backup_dir']}")
        print(f"[*] Manifest: {manifest['manifest_path']}")
        print(f"[*] steward.db SHA-256: {manifest['db_sha256']}")
        print(f"[*] secret.key SHA-256: {manifest['key_sha256']}")
        return 0
    except Exception as exc:
        print(f"[ERROR] Backup failed: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())

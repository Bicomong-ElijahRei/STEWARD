"""Back up and migrate STEWARD credentials; dry-run a database copy by default."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import sqlite3
import subprocess
import sys
import tempfile
from datetime import datetime, timezone

REPO_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_DIR))

from core.database import DatabaseManager  # noqa: E402


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest().upper()


def backup_directory() -> Path:
    appdata = os.environ.get("APPDATA")
    root = (Path(appdata) / "STEWARD" / "backups" if appdata
            else Path.home() / ".steward" / "backups")
    root.mkdir(parents=True, exist_ok=True)
    return root


def commit_sha() -> str:
    result = subprocess.run(
        ["git", "rev-parse", "--short", "HEAD"], cwd=REPO_DIR,
        check=True, capture_output=True, text=True,
    )
    return result.stdout.strip()


def create_backup() -> dict:
    """Copy the database and operation log, then verify and manifest both copies."""
    sources = {
        "steward.db": REPO_DIR / "steward.db",
        "steward_operations.json": REPO_DIR / "steward_operations.json",
    }
    missing = [name for name, path in sources.items() if not path.is_file()]
    if missing:
        raise FileNotFoundError(f"Backup source(s) missing: {', '.join(missing)}")

    backup_dir = backup_directory()
    timestamp = datetime.now(timezone.utc)
    sha = commit_sha()
    prefix = f"steward_backup_{timestamp:%Y%m%d_%H%M%S}_{sha}"
    destinations = {
        "steward.db": backup_dir / f"{prefix}.db",
        "steward_operations.json": backup_dir / f"{prefix}.json",
    }
    manifest_path = backup_dir / f"{prefix}_manifest.json"
    if any(path.exists() for path in (*destinations.values(), manifest_path)):
        raise FileExistsError(f"Backup name collision; refusing to overwrite: {prefix}")

    hashes = {}
    for name, source in sources.items():
        destination = destinations[name]
        shutil.copy2(source, destination)
        source_hash = sha256(source)
        backup_hash = sha256(destination)
        if source_hash != backup_hash:
            raise OSError(f"Backup checksum mismatch for {name}")
        hashes[name] = backup_hash

    manifest = {
        "format_version": 1,
        "timestamp": timestamp.isoformat(),
        "commit_sha": sha,
        "files": {
            name: {"backup_path": str(destinations[name]), "sha256": hashes[name]}
            for name in sources
        },
    }
    with manifest_path.open("x", encoding="utf-8") as output:
        json.dump(manifest, output, indent=2)
        output.write("\n")

    return {
        "backup_dir": backup_dir,
        "database": destinations["steward.db"],
        "operations": destinations["steward_operations.json"],
        "manifest": manifest_path,
        "hashes": hashes,
    }


def counts(connection: sqlite3.Connection) -> dict[str, int]:
    provider_count = connection.execute("SELECT COUNT(*) FROM providers").fetchone()[0]
    credentials_exist = connection.execute(
        "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'credentials'"
    ).fetchone()
    credential_count = (
        connection.execute("SELECT COUNT(*) FROM credentials").fetchone()[0]
        if credentials_exist else 0
    )
    return {"providers": provider_count, "credentials": credential_count}


def read_counts(database_path: Path) -> dict[str, int]:
    connection = sqlite3.connect(f"file:{database_path.as_posix()}?mode=ro", uri=True)
    try:
        return counts(connection)
    finally:
        connection.close()


def migrate(database_path: Path) -> None:
    before = read_counts(database_path)
    print(f"Before: providers={before['providers']}, credentials={before['credentials']}")

    database = DatabaseManager(db_path=str(database_path))
    try:
        result = database.migrate_to_shared_credentials()
        after = counts(database._conn)
        integrity = [row[0] for row in database._conn.execute("PRAGMA integrity_check")]
        if integrity != ["ok"]:
            raise RuntimeError(f"SQLite integrity_check failed: {integrity}")
    finally:
        database.close()

    print(f"After: providers={after['providers']}, credentials={after['credentials']}")
    print("Migration result:")
    print(json.dumps(result, indent=2))
    print("PRAGMA integrity_check: ok")


def rollback_hint(backup: dict | None) -> None:
    location = backup["database"] if backup else backup_directory()
    print(
        "Rollback hint: call rollback_from_shared_credentials() or restore "
        f"the verified backup at {location}", file=sys.stderr,
    )


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--live", action="store_true",
        help="Migrate steward.db only after this run's verified backup succeeds.",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    backup = None
    try:
        backup = create_backup()
        print(f"Backup database: {backup['database']}")
        print(f"Backup operations: {backup['operations']}")
        print(f"Backup manifest: {backup['manifest']}")

        if args.live:
            print("LIVE MODE: migrating steward.db after verified backup.")
            migrate(REPO_DIR / "steward.db")
        else:
            print("DRY RUN: migrating only a temporary copy of steward.db.")
            with tempfile.TemporaryDirectory(prefix="steward_migration_") as temporary_dir:
                temporary_database = Path(temporary_dir) / "steward.db"
                shutil.copy2(backup["database"], temporary_database)
                migrate(temporary_database)
            print("Dry run complete; live steward.db was not migrated.")
        return 0
    except Exception as exc:
        print(f"Migration runner failed: {exc}", file=sys.stderr)
        rollback_hint(backup)
        return 1


if __name__ == "__main__":
    sys.exit(main())

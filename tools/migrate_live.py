"""Safely preview, execute, or roll back STEWARD shared-credential migration."""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
import logging
import os
from pathlib import Path
import queue
import shutil
import sqlite3
import subprocess
import sys
import tempfile
import threading

REPO_DIR = Path(__file__).resolve().parents[1]
CONFIRMATION_TIMEOUT_SECONDS = 300
sys.path.insert(0, str(REPO_DIR))

import core.database as database_module  # noqa: E402


def app_data_dir() -> Path:
    appdata = os.environ.get("APPDATA")
    return Path(appdata) / "STEWARD" if appdata else Path.home() / ".steward"


def default_backup_dir() -> Path:
    return app_data_dir() / "backups"


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest().upper()


def make_logger() -> logging.Logger:
    log_path = app_data_dir() / "migration.log"
    log_path.parent.mkdir(parents=True, exist_ok=True)
    logger = logging.getLogger(f"steward.migration.{os.getpid()}")
    logger.setLevel(logging.INFO)
    logger.propagate = False
    handler = logging.FileHandler(log_path, mode="a", encoding="utf-8")
    handler.setFormatter(logging.Formatter(
        "%(asctime)s %(levelname)s %(message)s", "%Y-%m-%dT%H:%M:%S%z"
    ))
    logger.addHandler(handler)
    logger.info("Log started; migration log=%s", log_path)
    return logger


def close_logger(logger: logging.Logger) -> None:
    for handler in list(logger.handlers):
        handler.close()
        logger.removeHandler(handler)


def report(logger: logging.Logger, message: str) -> None:
    logger.info(message)
    print(message)


def read_only_connection(database_path: Path) -> sqlite3.Connection:
    uri = database_path.resolve().as_uri() + "?mode=ro"
    return sqlite3.connect(uri, uri=True, timeout=3)


def counts(connection: sqlite3.Connection) -> dict[str, int]:
    result = {
        "providers": connection.execute("SELECT COUNT(*) FROM providers").fetchone()[0],
        "credentials": 0,
        "linked_providers": 0,
    }
    if connection.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name='credentials'"
    ).fetchone():
        result["credentials"] = connection.execute(
            "SELECT COUNT(*) FROM credentials"
        ).fetchone()[0]
    columns = {row[1] for row in connection.execute("PRAGMA table_info(providers)")}
    if "credential_id" in columns:
        result["linked_providers"] = connection.execute(
            "SELECT COUNT(*) FROM providers WHERE credential_id IS NOT NULL"
        ).fetchone()[0]
    return result


def preflight(database_path: Path, key_path: Path) -> dict[str, int]:
    """Check all inputs without creating or modifying any database/key file."""
    if not database_path.is_file():
        raise FileNotFoundError(f"steward.db does not exist: {database_path}")
    if not key_path.is_file():
        raise RuntimeError(
            f"Database exists but secret.key is missing at '{key_path}'. "
            "Refusing to generate a new key."
        )
    try:
        connection = read_only_connection(database_path)
        try:
            connection.execute("PRAGMA busy_timeout=3000")
            connection.execute("BEGIN")
            if not connection.execute(
                "SELECT 1 FROM sqlite_master WHERE type='table' AND name='providers'"
            ).fetchone():
                raise RuntimeError("Incompatible schema: providers table is missing")
            result = counts(connection)
            connection.rollback()
            return result
        finally:
            connection.close()
    except sqlite3.Error as exc:
        raise RuntimeError(
            f"Database is locked or cannot be opened read-only: {exc}"
        ) from exc


def commit_sha() -> str:
    result = subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=REPO_DIR, check=True,
        capture_output=True, text=True,
    )
    full_sha = result.stdout.strip()
    if len(full_sha) < 8:
        raise RuntimeError("Could not determine an eight-character git commit SHA")
    return full_sha[:8]


def backup_prefix() -> str:
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    return f"steward_backup_{timestamp}_{commit_sha()}"


def create_database_backup(source_path: Path, destination: Path) -> None:
    """Create a consistent SQLite online backup without replacing any file."""
    if destination.exists():
        raise FileExistsError(f"Refusing to overwrite backup: {destination}")
    # Reserve the name atomically. A failed/partial backup is retained for diagnosis.
    with destination.open("xb"):
        pass
    source = read_only_connection(source_path)
    target = sqlite3.connect(destination, timeout=30)
    try:
        source.execute("PRAGMA busy_timeout=3000")
        source.backup(target)
        integrity = [row[0] for row in target.execute("PRAGMA integrity_check")]
        if integrity != ["ok"]:
            raise RuntimeError(f"Backup integrity_check failed: {integrity}")
    finally:
        target.close()
        source.close()


def copy_verified(source: Path, destination: Path) -> str:
    if destination.exists():
        raise FileExistsError(f"Refusing to overwrite backup: {destination}")
    with source.open("rb") as input_file, destination.open("xb") as output_file:
        shutil.copyfileobj(input_file, output_file, length=1024 * 1024)
    shutil.copystat(source, destination)
    source_hash = sha256(source)
    backup_hash = sha256(destination)
    if source_hash != backup_hash:
        raise OSError(f"Backup checksum mismatch for {source.name}")
    return backup_hash


def create_backup_set(
    database_path: Path, key_path: Path, operations_path: Path, backup_dir: Path
) -> dict:
    sources = {
        "steward.db": database_path,
        "secret.key": key_path,
        "steward_operations.json": operations_path,
    }
    missing = [name for name, path in sources.items() if not path.is_file()]
    if missing:
        raise FileNotFoundError(f"Backup source(s) missing: {', '.join(missing)}")
    backup_dir.mkdir(parents=True, exist_ok=True)
    prefix = backup_prefix()
    destinations = {
        "steward.db": backup_dir / f"{prefix}.db",
        "secret.key": backup_dir / f"{prefix}.key",
        "steward_operations.json": backup_dir / f"{prefix}_operations.json",
    }
    manifest_path = backup_dir / f"{prefix}_manifest.json"
    for path in (*destinations.values(), manifest_path):
        if path.exists():
            raise FileExistsError(f"Backup name collision; refusing to overwrite: {path}")

    create_database_backup(database_path, destinations["steward.db"])
    hashes = {"steward.db": sha256(destinations["steward.db"])}
    for name in ("secret.key", "steward_operations.json"):
        hashes[name] = copy_verified(sources[name], destinations[name])
    manifest = {
        "format_version": 1,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "commit_sha": commit_sha(),
        "files": {
            name: {
                "backup_path": str(destinations[name]),
                "sha256": hashes[name],
            }
            for name in sources
        },
    }
    with manifest_path.open("x", encoding="utf-8") as output:
        json.dump(manifest, output, indent=2)
        output.write("\n")
    return {"database": destinations["steward.db"], "manifest": manifest_path,
            "files": destinations}


def validate_migration(db: database_module.DatabaseManager, before: dict) -> dict:
    after = counts(db._conn)
    integrity = [row[0] for row in db._conn.execute("PRAGMA integrity_check")]
    if integrity != ["ok"]:
        raise RuntimeError(f"Post-flight integrity_check failed: {integrity}")
    if after["providers"] != before["providers"]:
        raise RuntimeError(
            f"Provider count changed: {before['providers']} -> {after['providers']}"
        )
    linked_names = [row[0] for row in db._conn.execute(
        "SELECT name FROM providers WHERE credential_id IS NOT NULL"
    )]
    for name in linked_names:
        provider = db.get_provider(name)
        if provider is None or provider.get("decryption_error") is not None:
            error = "provider missing" if provider is None else provider["decryption_error"]
            raise RuntimeError(f"Linked provider '{name}' cannot decrypt: {error}")
        if provider.get("api_key") is None:
            raise RuntimeError(f"Linked provider '{name}' returned no decrypted key")
    return after


def perform_migration(
    database_path: Path, key_path: Path, before: dict, logger: logging.Logger
) -> tuple[dict, dict]:
    db = database_module.DatabaseManager(str(database_path), str(key_path))
    try:
        result = database_module.migrate_to_shared_credentials(db)
        logger.info("Migration function result: %s", result)
        try:
            after = validate_migration(db, before)
        except Exception as validation_error:
            logger.error("Post-flight validation failed: %s", validation_error)
            try:
                rollback_result = database_module.rollback_from_shared_credentials(db)
            except Exception as rollback_error:
                logger.critical("Automatic rollback failed: %s", rollback_error)
                raise RuntimeError(
                    "Validation failed and automatic rollback also failed; "
                    "restore the verified backup"
                ) from rollback_error
            logger.info("Automatic rollback completed: %s", rollback_result)
            raise RuntimeError(
                f"Post-flight validation failed; automatic rollback completed: "
                f"{validation_error}"
            ) from validation_error
        return result, after
    finally:
        db.close()


def validate_rollback(db: database_module.DatabaseManager, before: dict) -> dict:
    after = counts(db._conn)
    integrity = [row[0] for row in db._conn.execute("PRAGMA integrity_check")]
    if integrity != ["ok"]:
        raise RuntimeError(f"Rollback integrity_check failed: {integrity}")
    if after["providers"] != before["providers"]:
        raise RuntimeError("Provider count changed during rollback")
    if after["linked_providers"] != 0:
        raise RuntimeError("Rollback left providers linked to credentials")
    for provider in db.get_all_providers():
        if provider.get("decryption_error") is not None:
            raise RuntimeError(
                f"Legacy key for '{provider['name']}' cannot decrypt after rollback"
            )
    return after


def perform_rollback(
    database_path: Path, key_path: Path, before: dict, logger: logging.Logger
) -> tuple[dict, dict]:
    db = database_module.DatabaseManager(str(database_path), str(key_path))
    try:
        result = database_module.rollback_from_shared_credentials(db)
        logger.info("Rollback function result: %s", result)
        return result, validate_rollback(db, before)
    finally:
        db.close()


def running_in_ci() -> bool:
    for name in ("CI", "CONTINUOUS_INTEGRATION", "GITHUB_ACTIONS", "TF_BUILD", "BUILD_NUMBER"):
        if os.environ.get(name, "").strip().lower() not in ("", "0", "false", "no"):
            return True
    return False


def confirm(action: str, logger: logging.Logger) -> bool:
    if running_in_ci():
        logger.info("CI environment detected; interactive confirmation not required")
        return True
    if not sys.stdin.isatty():
        raise RuntimeError(
            f"--{action} requires an interactive terminal outside CI; confirmation refused"
        )
    expected = "MIGRATE" if action == "execute" else "ROLLBACK"
    prompt = f"This will modify the LIVE database. Type {expected} to continue: "
    answers: queue.Queue = queue.Queue(maxsize=1)

    def read_answer():
        try:
            answers.put(input(prompt))
        except Exception as exc:
            answers.put(exc)

    reader = threading.Thread(target=read_answer, name="steward-migration-confirm", daemon=True)
    reader.start()
    try:
        answer = answers.get(timeout=CONFIRMATION_TIMEOUT_SECONDS)
    except queue.Empty as exc:
        raise RuntimeError(
            f"Confirmation timed out after {CONFIRMATION_TIMEOUT_SECONDS} seconds; "
            "live database was not modified"
        ) from exc
    if isinstance(answer, Exception):
        raise RuntimeError(f"Could not read confirmation: {answer}") from answer
    answer = answer.strip()
    if answer != expected:
        logger.warning("Operator confirmation did not match; no backup or mutation attempted")
        return False
    logger.info("Operator explicitly confirmed %s", action)
    return True


def parse_args(argv=None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    modes = parser.add_mutually_exclusive_group()
    modes.add_argument(
        "--dry-run", dest="mode", action="store_const", const="dry-run",
        help="preview migration on a temporary backup (default)",
    )
    modes.add_argument(
        "--execute", dest="mode", action="store_const", const="execute",
        help="back up and migrate the configured live database",
    )
    modes.add_argument(
        "--rollback", dest="mode", action="store_const", const="rollback",
        help="back up and reverse shared-credential links",
    )
    parser.add_argument(
        "--backup-dir", default=str(default_backup_dir()), metavar="PATH",
        help="persistent backup directory (default: %%APPDATA%%\\STEWARD\\backups)",
    )
    parser.set_defaults(mode="dry-run")
    return parser.parse_args(argv)


def format_counts(values: dict) -> str:
    return (
        f"providers={values['providers']}, credentials={values['credentials']}, "
        f"linked_providers={values['linked_providers']}"
    )


def main(argv=None) -> int:
    args = parse_args(argv)
    logger = None
    try:
        logger = make_logger()
        database_path = Path(database_module.DB_PATH)
        key_path = Path(database_module.KEY_PATH)
        operations_path = database_path.parent / "steward_operations.json"
        logger.info("Mode=%s; database=%s; key=%s", args.mode, database_path, key_path)
        report(logger, f"Pre-flight database: {database_path}")
        before = preflight(database_path, key_path)
        report(logger, f"Pre-flight checks passed. Before: {format_counts(before)}")

        if args.mode == "dry-run":
            with tempfile.TemporaryDirectory(prefix="steward_migration_") as temporary_dir:
                temporary_backup = Path(temporary_dir) / f"{backup_prefix()}.db"
                create_database_backup(database_path, temporary_backup)
                report(logger, f"Temporary dry-run backup: {temporary_backup}")
                result, after = perform_migration(
                    temporary_backup, key_path, before, logger
                )
            report(logger, f"Migration result: {json.dumps(result, sort_keys=True)}")
            report(logger, f"Post-flight validation passed. After: {format_counts(after)}")
            report(logger, "PRAGMA integrity_check: ok")
            report(logger, "DRY RUN complete; live steward.db was not modified.")
            return 0

        if not confirm(args.mode, logger):
            report(logger, "Operation cancelled; live steward.db was not modified.")
            return 1
        backup_dir = Path(args.backup_dir).expanduser()
        backup = create_backup_set(
            database_path, key_path, operations_path, backup_dir
        )
        report(logger, f"Verified database backup: {backup['database']}")
        for name, path in backup["files"].items():
            logger.info("Backup %s: %s", name, path)
        report(logger, f"SHA-256 manifest: {backup['manifest']}")

        if args.mode == "execute":
            result, after = perform_migration(database_path, key_path, before, logger)
            report(logger, f"Migration result: {json.dumps(result, sort_keys=True)}")
        else:
            result, after = perform_rollback(database_path, key_path, before, logger)
            report(logger, f"Rollback result: {json.dumps(result, sort_keys=True)}")
        report(logger, f"Post-flight validation passed. After: {format_counts(after)}")
        report(logger, "PRAGMA integrity_check: ok")
        report(logger, f"{args.mode.upper()} completed successfully.")
        return 0
    except Exception as exc:
        if logger is not None:
            logger.exception("Migration CLI failed: %s", exc)
        print(f"Migration CLI failed: {exc}", file=sys.stderr)
        return 1
    finally:
        if logger is not None:
            close_logger(logger)


if __name__ == "__main__":
    sys.exit(main())

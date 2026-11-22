"""Compatibility wrapper for the guarded shared-credential migration CLI.

The original runner copied a live SQLite file byte-for-byte and omitted the
matching encryption key. This wrapper now delegates to ``migrate_live.py``,
which creates a consistent SQLite backup, backs up the key and operation log,
and requires explicit confirmation before a live mutation.
"""

from __future__ import annotations

import argparse
from pathlib import Path
import sys

REPO_DIR = Path(__file__).resolve().parents[1]
TOOLS_DIR = Path(__file__).resolve().parent
for import_path in (REPO_DIR, TOOLS_DIR):
    if str(import_path) not in sys.path:
        sys.path.insert(0, str(import_path))

try:
    from migrate_live import main as guarded_main
except ImportError:  # pragma: no cover - supports package-style imports
    from tools.migrate_live import main as guarded_main


def parse_args(argv=None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    modes = parser.add_mutually_exclusive_group()
    modes.add_argument(
        "--live",
        action="store_true",
        help="Migrate the live database through the guarded backup/confirm flow.",
    )
    modes.add_argument(
        "--dry-run",
        action="store_true",
        help="Preview the migration on a temporary database copy (default).",
    )
    parser.add_argument(
        "--backup-dir",
        default=None,
        metavar="PATH",
        help="Persistent backup directory for live mode.",
    )
    return parser.parse_args(argv)


def main(argv=None) -> int:
    args = parse_args(argv)
    guarded_args = ["--execute" if args.live else "--dry-run"]
    if args.backup_dir:
        guarded_args.extend(("--backup-dir", args.backup_dir))
    return guarded_main(guarded_args)


if __name__ == "__main__":
    sys.exit(main())

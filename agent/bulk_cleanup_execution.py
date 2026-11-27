"""Recycle-bin-only execution for app-bound bulk cleanup candidates.

This module contains the new destructive path's only removal primitive. It
never permanently removes files or directories.
"""

from __future__ import annotations

import send2trash


def trash_path(path: str) -> None:
    """Move one already-verified path to the operating system recycle bin."""
    send2trash.send2trash(path)


def trash_paths(paths: tuple[str, ...]) -> list[dict[str, str]]:
    """Trash an ordered set and return one truthful outcome per path."""
    outcomes = []
    for path in paths:
        try:
            trash_path(path)
        except Exception as exc:
            outcomes.append({"path": path, "outcome": "failed", "error": str(exc)})
        else:
            outcomes.append({"path": path, "outcome": "trashed"})
    return outcomes

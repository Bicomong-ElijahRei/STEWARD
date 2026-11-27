"""Bounded, application-owned expansion and binding for batch moves."""
from __future__ import annotations

import glob
import hashlib
import os
from dataclasses import dataclass

MAX_PATTERN_LENGTH = 1024
MAX_MATCHED_FILES = 1000
BINDING_VERSION = "steward-batch-move-binding-v1"


class BatchMoveRefusal(Exception):
    def __init__(self, reason: str):
        self.reason = reason
        super().__init__(reason)


@dataclass(frozen=True)
class BatchMoveEntry:
    source: str
    destination: str
    size: int
    mtime_ns: int
    device: int
    inode: int


@dataclass(frozen=True)
class BatchMoveBinding:
    root: str
    entries: tuple[BatchMoveEntry, ...]
    binding_hash: str

    def __post_init__(self):
        if self.binding_hash != _hash(self.root, self.entries):
            raise BatchMoveRefusal("binding_hash_mismatch")


def _is_link_or_junction(path: str) -> bool:
    junction = getattr(os.path, "isjunction", None)
    return os.path.islink(path) or (junction is not None and junction(path))


def _within(path: str, root: str) -> bool:
    try:
        return os.path.normcase(os.path.commonpath((path, root))) == os.path.normcase(root)
    except ValueError:
        return False


def _static_root(pattern: str, allowed_roots):
    if not isinstance(pattern, str) or not pattern.strip():
        raise BatchMoveRefusal("invalid_pattern")
    if len(pattern) > MAX_PATTERN_LENGTH:
        raise BatchMoveRefusal("pattern_too_long")
    if os.path.isabs(pattern) or os.path.splitdrive(pattern)[0] or pattern.startswith("\\\\"):
        raise BatchMoveRefusal("absolute_pattern")
    if "**" in pattern:
        raise BatchMoveRefusal("recursive_pattern_refused")
    parts = pattern.replace("/", os.sep).split(os.sep)
    if any(part == ".." for part in parts):
        raise BatchMoveRefusal("traversal_refused")
    roots = tuple(os.path.realpath(os.path.abspath(item)) for item in allowed_roots)
    sandbox_root = roots[0]
    candidate = os.path.join(sandbox_root, pattern)
    if not _within(os.path.realpath(os.path.abspath(candidate)), sandbox_root):
        raise BatchMoveRefusal("sandbox_violation")
    return sandbox_root, candidate


def _hash(root, entries):
    digest = hashlib.sha256()
    digest.update(BINDING_VERSION.encode("ascii"))
    digest.update(root.encode("utf-8", "surrogatepass"))
    for entry in entries:
        digest.update(entry.source.encode("utf-8", "surrogatepass"))
        digest.update(entry.destination.encode("utf-8", "surrogatepass"))
        digest.update(str(entry.size).encode("ascii"))
        digest.update(str(entry.mtime_ns).encode("ascii"))
        digest.update(str(entry.device).encode("ascii"))
        digest.update(str(entry.inode).encode("ascii"))
    return digest.hexdigest()


def enumerate_and_bind(pattern: str, destination_folder: str, allowed_roots):
    root, joined = _static_root(pattern, allowed_roots)
    destination_root = os.path.realpath(os.path.abspath(destination_folder))
    if not any(_within(destination_root, item) for item in allowed_roots):
        raise BatchMoveRefusal("sandbox_violation")
        raise BatchMoveRefusal("sandbox_violation")
    matches = glob.glob(joined, recursive=False)
    matches = [item for item in matches if os.path.isfile(item)]
    entries = []
    for match in sorted(matches, key=lambda item: (os.path.normcase(item), item)):
        canonical = os.path.realpath(os.path.abspath(match))
        if not _within(canonical, root):
            continue
        if _is_link_or_junction(match):
            raise BatchMoveRefusal("link_pattern_refused")
        current = match
        while current and os.path.dirname(current) != current:
            if _is_link_or_junction(current):
                canonical = ""
                break
            current = os.path.dirname(current)
        if not canonical or not os.path.isfile(canonical):
            continue
        if len(entries) >= MAX_MATCHED_FILES:
            raise BatchMoveRefusal("file_count_exceeded")
        stat = os.stat(canonical, follow_symlinks=False)
        entries.append(BatchMoveEntry(canonical, os.path.join(destination_root, os.path.basename(canonical)), stat.st_size, stat.st_mtime_ns, stat.st_dev, stat.st_ino))
    binding = BatchMoveBinding(root, tuple(entries), _hash(root, entries))
    return binding


def reverify(binding: BatchMoveBinding, pattern: str, destination_folder: str, allowed_roots):
    current = enumerate_and_bind(pattern, destination_folder, allowed_roots)
    if current.root != binding.root or current.entries != binding.entries or current.binding_hash != binding.binding_hash:
        raise BatchMoveRefusal("binding_changed")
    return current

"""Pure enumeration and set binding for a future bulk-removal exposure.

This module reads and stats filesystem entries but never removes or mutates
anything. It is intentionally not imported by the active FileAgent dispatch
surface.
"""

from __future__ import annotations

import hashlib
import os
from dataclasses import dataclass
from enum import Enum
from typing import Iterable


MAX_FILES_VISITED = 1000
MAX_CANDIDATES_VISITED = 1000
MAX_DIRECTORY_DEPTH = 8
MAX_PATH_LENGTH = 1024
IDENTITY_POLICY = "path-size-mtime-ns-v1"
BINDING_VERSION = "steward-bulk-binding-v1"

TEMPORARY_FILE_SUFFIXES = (
    ".tmp",
    ".temp",
    ".cache",
    ".log",
    ".bak",
    ".swp",
    "thumbs.db",
    "desktop.ini",
)


class CandidateKind(str, Enum):
    TEMPORARY_FILE = "temporary_file"
    EMPTY_DIRECTORY = "empty_directory"


class RefusalCode(str, Enum):
    INVALID_ARGUMENT = "invalid_argument"
    INVALID_ROOT = "invalid_root"
    SANDBOX_VIOLATION = "sandbox_violation"
    PATH_LENGTH_EXCEEDED = "path_length_exceeded"
    DEPTH_EXCEEDED = "depth_exceeded"
    FILE_COUNT_EXCEEDED = "file_count_exceeded"
    CANDIDATE_COUNT_EXCEEDED = "candidate_count_exceeded"
    IO_ERROR = "io_error"
    ADDED_ENTRY = "added_entry"
    REMOVED_ENTRY = "removed_entry"
    IDENTITY_CHANGED = "identity_changed"
    PATH_ORDER_CHANGED = "path_order_changed"
    ROOT_CHANGED = "root_changed"
    BINDING_HASH_MISMATCH = "binding_hash_mismatch"
    IDENTITY_POLICY_CHANGED = "identity_policy_changed"


_ENUMERATION_MESSAGES = {
    RefusalCode.INVALID_ARGUMENT: "Invalid enumeration argument.",
    RefusalCode.INVALID_ROOT: "Enumeration root is not a directory.",
    RefusalCode.SANDBOX_VIOLATION: "Enumeration root is outside the sandbox.",
    RefusalCode.PATH_LENGTH_EXCEEDED: "Enumeration path exceeds the length bound.",
    RefusalCode.DEPTH_EXCEEDED: "Enumeration traversal exceeds the depth bound.",
    RefusalCode.FILE_COUNT_EXCEEDED: "Enumeration traversal exceeds the file-count bound.",
    RefusalCode.CANDIDATE_COUNT_EXCEEDED: "Enumeration exceeds the candidate-count bound.",
    RefusalCode.IO_ERROR: "Enumeration could not read the filesystem.",
}


class EnumerationRefusal(Exception):
    """A bounded, typed refusal that never contains an unbounded path list."""

    def __init__(self, code: RefusalCode):
        if not isinstance(code, RefusalCode):
            raise TypeError("Enumeration refusal code must be a RefusalCode.")
        self.code = code
        super().__init__(_ENUMERATION_MESSAGES[code])


@dataclass(frozen=True)
class RefusalReason:
    code: RefusalCode
    count: int = 0


@dataclass(frozen=True)
class CandidateEntry:
    path: str
    kind: CandidateKind
    size: int
    mtime_ns: int


@dataclass(frozen=True)
class EnumerationResult:
    root: str
    candidates: tuple[CandidateEntry, ...]


@dataclass(frozen=True)
class BoundCandidateSet:
    root: str
    candidates: tuple[CandidateEntry, ...]
    binding_hash: str
    identity_policy: str = IDENTITY_POLICY


@dataclass(frozen=True)
class VerificationResult:
    accepted: bool
    reasons: tuple[RefusalReason, ...] = ()


def _is_link_or_junction(path: str) -> bool:
    is_junction = getattr(os.path, "isjunction", None)
    return os.path.islink(path) or (
        is_junction is not None and is_junction(path)
    )


def _canonical_path(path: str) -> str:
    return os.path.realpath(os.path.abspath(path))


def _is_within(path: str, root: str) -> bool:
    try:
        common = os.path.commonpath((path, root))
    except ValueError:
        return False
    return os.path.normcase(common) == os.path.normcase(root)


def _path_sort_key(path: str) -> tuple[str, str]:
    return (os.path.normcase(path), path)


def _validate_root(root: str, allowed_roots: Iterable[str]) -> str:
    if not isinstance(root, str) or not root.strip():
        raise EnumerationRefusal(RefusalCode.INVALID_ARGUMENT)
    roots = tuple(allowed_roots)
    if not roots:
        raise EnumerationRefusal(RefusalCode.INVALID_ARGUMENT)
    if len(root) > MAX_PATH_LENGTH:
        raise EnumerationRefusal(RefusalCode.PATH_LENGTH_EXCEEDED)
    canonical_root = _canonical_path(root)
    if len(canonical_root) > MAX_PATH_LENGTH:
        raise EnumerationRefusal(RefusalCode.PATH_LENGTH_EXCEEDED)
    canonical_allowed = tuple(_canonical_path(item) for item in roots)
    if not any(_is_within(canonical_root, item) for item in canonical_allowed):
        raise EnumerationRefusal(RefusalCode.SANDBOX_VIOLATION)
    if not os.path.isdir(canonical_root):
        raise EnumerationRefusal(RefusalCode.INVALID_ROOT)
    return canonical_root


def _walk_entries(root: str) -> tuple[list[str], list[str]]:
    """Collect canonical regular files and removable directories deterministically."""
    files = []
    directories = []
    file_count = 0
    def _raise_walk_error(error: OSError) -> None:
        raise EnumerationRefusal(RefusalCode.IO_ERROR) from error

    try:
        for current, directory_names, file_names in os.walk(
            root,
            topdown=True,
            followlinks=False,
            onerror=_raise_walk_error,
        ):
            directory_names.sort()
            file_names.sort()
            relative = os.path.relpath(current, root)
            depth = 0 if relative == "." else len(relative.split(os.sep))
            if depth == MAX_DIRECTORY_DEPTH and directory_names:
                raise EnumerationRefusal(RefusalCode.DEPTH_EXCEEDED)

            safe_directories = []
            for name in directory_names:
                path = os.path.join(current, name)
                if _is_link_or_junction(path):
                    continue
                resolved = _canonical_path(path)
                if not _is_within(resolved, root):
                    continue
                if len(resolved) > MAX_PATH_LENGTH:
                    raise EnumerationRefusal(RefusalCode.PATH_LENGTH_EXCEEDED)
                safe_directories.append(name)
                directories.append(resolved)
            directory_names[:] = safe_directories

            for name in file_names:
                path = os.path.join(current, name)
                if _is_link_or_junction(path):
                    continue
                resolved = _canonical_path(path)
                if not _is_within(resolved, root):
                    continue
                if not os.path.isfile(resolved):
                    continue
                if len(resolved) > MAX_PATH_LENGTH:
                    raise EnumerationRefusal(RefusalCode.PATH_LENGTH_EXCEEDED)
                file_count += 1
                if file_count > MAX_FILES_VISITED:
                    raise EnumerationRefusal(RefusalCode.FILE_COUNT_EXCEEDED)
                files.append(resolved)
    except EnumerationRefusal:
        raise
    except (OSError, PermissionError, IOError) as exc:
        raise EnumerationRefusal(RefusalCode.IO_ERROR) from exc
    return files, directories


def _is_temporary_file(path: str) -> bool:
    name = os.path.basename(path).lower()
    return name.endswith(TEMPORARY_FILE_SUFFIXES)


def _effectively_empty_directories(directories: list[str]) -> list[str]:
    """Return the bottom-up closure of directories emptied by child removal."""
    directory_set = set(directories)
    memo: dict[str, bool] = {}

    def is_effectively_empty(path: str) -> bool:
        if path in memo:
            return memo[path]
        try:
            with os.scandir(path) as entries:
                child_directories = []
                for entry in entries:
                    if _is_link_or_junction(entry.path):
                        memo[path] = False
                        return False
                    if os.path.isdir(entry.path):
                        child_directories.append(_canonical_path(entry.path))
                    else:
                        memo[path] = False
                        return False
        except (OSError, PermissionError, IOError) as exc:
            raise EnumerationRefusal(RefusalCode.IO_ERROR) from exc
        result = all(
            child in directory_set and is_effectively_empty(child)
            for child in child_directories
        )
        memo[path] = result
        return result

    return [path for path in directories if is_effectively_empty(path)]


def _identity(path: str, kind: CandidateKind) -> CandidateEntry:
    try:
        stat_result = os.stat(path, follow_symlinks=False)
    except (OSError, PermissionError, IOError) as exc:
        raise EnumerationRefusal(RefusalCode.IO_ERROR) from exc
    return CandidateEntry(
        path=path,
        kind=kind,
        size=stat_result.st_size,
        mtime_ns=stat_result.st_mtime_ns,
    )


def enumerate_candidates(
    root: str,
    *,
    allowed_roots: Iterable[str],
    kind: CandidateKind,
) -> EnumerationResult:
    """Enumerate the complete candidate set or refuse without partial output."""
    if not isinstance(kind, CandidateKind):
        raise EnumerationRefusal(RefusalCode.INVALID_ARGUMENT)
    canonical_root = _validate_root(root, allowed_roots)
    files, directories = _walk_entries(canonical_root)

    if kind == CandidateKind.TEMPORARY_FILE:
        paths = [path for path in files if _is_temporary_file(path)]
        paths.sort(key=_path_sort_key)
        selected_kind = CandidateKind.TEMPORARY_FILE
    elif kind == CandidateKind.EMPTY_DIRECTORY:
        paths = _effectively_empty_directories(directories)
        paths.sort(
            key=lambda path: (
                -len(os.path.relpath(path, canonical_root).split(os.sep)),
                _path_sort_key(path),
            )
        )
        selected_kind = CandidateKind.EMPTY_DIRECTORY
    else:
        raise EnumerationRefusal(RefusalCode.INVALID_ARGUMENT)
    if len(paths) > MAX_CANDIDATES_VISITED:
        raise EnumerationRefusal(RefusalCode.CANDIDATE_COUNT_EXCEEDED)
    candidates = tuple(_identity(path, selected_kind) for path in paths)
    return EnumerationResult(root=canonical_root, candidates=candidates)


def _update_framed(digest, value: bytes) -> None:
    digest.update(len(value).to_bytes(8, "big"))
    digest.update(value)


def binding_hash(root: str, candidates: Iterable[CandidateEntry]) -> str:
    """Hash the exact ordered set and each entry's selected identity."""
    digest = hashlib.sha256()
    _update_framed(digest, BINDING_VERSION.encode("ascii"))
    _update_framed(digest, IDENTITY_POLICY.encode("ascii"))
    _update_framed(digest, root.encode("utf-8", errors="surrogatepass"))
    entries = tuple(candidates)
    _update_framed(digest, len(entries).to_bytes(8, "big"))
    for entry in entries:
        _update_framed(
            digest, entry.path.encode("utf-8", errors="surrogatepass")
        )
        _update_framed(digest, entry.kind.value.encode("ascii"))
        _update_framed(digest, int(entry.size).to_bytes(8, "big", signed=True))
        _update_framed(
            digest, int(entry.mtime_ns).to_bytes(8, "big", signed=True)
        )
    return digest.hexdigest()


def bind_candidates(enumeration: EnumerationResult) -> BoundCandidateSet:
    """Bind one complete enumeration to an immutable exact-set identifier."""
    if not isinstance(enumeration, EnumerationResult):
        raise TypeError("Binding input must be an EnumerationResult.")
    candidates = tuple(enumeration.candidates)
    return BoundCandidateSet(
        root=enumeration.root,
        candidates=candidates,
        binding_hash=binding_hash(enumeration.root, candidates),
    )


def _path_map(candidates: Iterable[CandidateEntry]) -> dict[str, CandidateEntry]:
    return {entry.path: entry for entry in candidates}


def reverify_binding(
    binding: BoundCandidateSet,
    current: EnumerationResult,
) -> VerificationResult:
    """Refuse the whole set on any membership, identity, order, or root change."""
    if not isinstance(binding, BoundCandidateSet):
        raise TypeError("Binding must be a BoundCandidateSet.")
    if not isinstance(current, EnumerationResult):
        raise TypeError("Current state must be an EnumerationResult.")

    reasons = []
    bound_entries = tuple(binding.candidates)
    current_entries = tuple(current.candidates)
    bound_paths = [entry.path for entry in bound_entries]
    current_paths = [entry.path for entry in current_entries]
    bound_by_path = _path_map(bound_entries)
    current_by_path = _path_map(current_entries)

    added_count = len(set(current_paths) - set(bound_paths))
    removed_count = len(set(bound_paths) - set(current_paths))
    if added_count:
        reasons.append(RefusalReason(RefusalCode.ADDED_ENTRY, added_count))
    if removed_count:
        reasons.append(RefusalReason(RefusalCode.REMOVED_ENTRY, removed_count))

    changed_count = 0
    for path in set(bound_paths) & set(current_paths):
        if bound_by_path[path] != current_by_path[path]:
            changed_count += 1
    if changed_count:
        reasons.append(
            RefusalReason(RefusalCode.IDENTITY_CHANGED, changed_count)
        )

    if (
        not added_count
        and not removed_count
        and bound_paths != current_paths
    ):
        reasons.append(RefusalReason(RefusalCode.PATH_ORDER_CHANGED, 1))
    if binding.root != current.root:
        reasons.append(RefusalReason(RefusalCode.ROOT_CHANGED, 1))

    if binding.identity_policy != IDENTITY_POLICY:
        reasons.append(
            RefusalReason(RefusalCode.IDENTITY_POLICY_CHANGED, 1)
        )

    expected_hash = binding_hash(binding.root, bound_entries)
    expected_current_hash = binding_hash(current.root, current_entries)
    if (
        expected_hash != binding.binding_hash
        or expected_current_hash != binding.binding_hash
    ):
        reasons.append(
            RefusalReason(RefusalCode.BINDING_HASH_MISMATCH, 1)
        )
    return VerificationResult(accepted=not reasons, reasons=tuple(reasons))

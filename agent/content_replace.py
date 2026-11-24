"""Atomic content replacement primitive for admitted C3 code targets.

Unlike the legacy move publication primitive, this module is intentionally
allowed to replace one existing regular-file target. The caller must supply
both the expected current hash and the expected replacement hash.
"""

import hashlib
import os
import stat
import uuid


class ContentReplaceError(RuntimeError):
    """Raised when an atomic content replacement cannot be proven safe."""


def file_sha256(path):
    """Return the SHA-256 of one regular file without loading it all at once."""
    digest = hashlib.sha256()
    try:
        with open(path, "rb") as handle:
            while True:
                chunk = handle.read(1024 * 1024)
                if not chunk:
                    break
                digest.update(chunk)
    except OSError as exc:
        raise ContentReplaceError(f"Could not hash '{path}': {exc}") from exc
    return digest.hexdigest()


def stage_content(target, content, expected_sha256):
    """Write content to a unique same-directory staging file and verify it."""
    if not isinstance(content, bytes):
        raise ContentReplaceError("Replacement content must be bytes")
    directory = os.path.dirname(os.path.abspath(target))
    if not os.path.isdir(directory):
        raise ContentReplaceError("Target directory does not exist")
    staged = os.path.join(
        directory,
        f".steward-c3-stage-{os.getpid()}-{uuid.uuid4().hex}.tmp",
    )
    try:
        with open(staged, "xb") as handle:
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
        actual = file_sha256(staged)
        if actual != expected_sha256:
            raise ContentReplaceError(
                f"Staged content hash mismatch: expected {expected_sha256}, got {actual}"
            )
        return staged
    except Exception:
        try:
            os.remove(staged)
        except OSError:
            pass
        raise


def replace_content(target, staged, expected_pre_sha256, expected_post_sha256):
    """Atomically replace exactly ``target`` after hash-guarded preflight.

    The staged file must be in the target's directory and contain exactly the
    approved post-image. The target must still contain exactly the recorded
    pre-image. Only this existing target is overwritten; no move or rename
    semantics are used.
    """
    target = os.path.abspath(target)
    staged = os.path.abspath(staged)
    if os.path.normcase(os.path.dirname(staged)) != os.path.normcase(
        os.path.dirname(target)
    ):
        raise ContentReplaceError("Staged content must be in the target directory")
    for label, path in (("target", target), ("staged", staged)):
        try:
            info = os.lstat(path)
        except OSError as exc:
            raise ContentReplaceError(f"{label.capitalize()} does not exist: {exc}") from exc
        if os.path.islink(path) or not stat.S_ISREG(info.st_mode):
            raise ContentReplaceError(f"{label.capitalize()} must be a regular non-link file")
    staged_hash = file_sha256(staged)
    if staged_hash != expected_post_sha256:
        raise ContentReplaceError(
            f"Staged content hash mismatch: expected {expected_post_sha256}, "
            f"got {staged_hash}"
        )
    pre_hash = file_sha256(target)
    if pre_hash != expected_pre_sha256:
        raise ContentReplaceError(
            f"Target changed before replacement: expected {expected_pre_sha256}, "
            f"got {pre_hash}"
        )
    os.replace(staged, target)
    try:
        if os.name != "nt":
            directory_fd = os.open(os.path.dirname(target), os.O_RDONLY)
            try:
                os.fsync(directory_fd)
            finally:
                os.close(directory_fd)
    except OSError:
        # The replacement is already committed; the caller verifies its hash
        # and records a truthful committed or uncertain journal state.
        pass
    post_hash = file_sha256(target)
    if post_hash != expected_post_sha256:
        raise ContentReplaceError(
            f"Replacement hash mismatch: expected {expected_post_sha256}, "
            f"got {post_hash}"
        )
    return target

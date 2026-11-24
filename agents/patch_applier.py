"""C3-I2 admitted content replacement, journaling, backup, and recovery.

This component is the first source-content mutation surface outside the
Incoming/Sorted organizer sandbox. It never executes, imports, lints, or tests
admitted target content.
"""

import copy
import hashlib
import json
import os
import shutil
import stat
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone

from agent.content_replace import (
    ContentReplaceError,
    replace_content as _replace_content,
    stage_content as _stage_content,
)
from agent.journal_lock import JournalLockError, operation_journal_lock
from agents.file_agent import FileAgent
from agents.patch_engine import PatchEngineError, stage_patch
from core.database import APP_DATA_DIR


MAX_SOURCE_BYTES = 1024 * 1024
MAX_BACKUPS = 20

DENIED_DIRECTORIES = frozenset(
    {
        ".git", ".hg", ".svn", "__pycache__", "venv", ".venv", "node_modules",
        "rag_index", "media", ".tox", ".nox", ".pytest_cache", ".mypy_cache",
    }
)
DENIED_FILE_NAMES = frozenset(
    {
        ".env", "secret.key", "steward_operations.json", "credentials.json",
        ".npmrc", ".pypirc",
    }
)
DENIED_FILE_PATTERNS = (".env.*", "*.key", "*.pem", "*.p12", "*.pfx", "*.db")
RESERVED_NAMES = frozenset(
    {"CON", "PRN", "AUX", "NUL"}
    | {f"COM{index}" for index in range(1, 10)}
    | {f"LPT{index}" for index in range(1, 10)}
)


class PatchAdmissionError(PermissionError):
    """Raised when a workspace or target fails admission."""


class PatchApplyError(RuntimeError):
    """Raised when an admitted content edit cannot be applied safely."""


class PatchRecoveryError(RuntimeError):
    """Raised when guarded content-edit recovery refuses to mutate."""


@dataclass(frozen=True)
class WorkspaceAdmission:
    canonical_root: str
    fingerprint: str
    device: int
    inode: int


@dataclass(frozen=True)
class TargetAdmission:
    relative_path: str
    canonical_path: str
    device: int
    inode: int
    size: int


@dataclass(frozen=True)
class ApplyResult:
    state: str
    operation_id: str
    relative_path: str
    pre_sha256: str
    post_sha256: str
    backup_reference: str


def _sha256(value):
    return hashlib.sha256(value).hexdigest()


def _canonical(path):
    return os.path.realpath(os.path.abspath(path))


def _same_or_ancestor(first, second):
    """Return whether first contains second (or they are equal)."""
    try:
        common = os.path.commonpath((os.path.normcase(first), os.path.normcase(second)))
    except ValueError:
        return False
    return common == os.path.normcase(first)


def _is_reparse(path):
    try:
        info = os.lstat(path)
    except OSError:
        return False
    if os.path.islink(path):
        return True
    attributes = getattr(info, "st_file_attributes", 0)
    reparse_flag = getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400)
    return bool(attributes & reparse_flag)


def _has_link_component(root, relative_path):
    current = root
    if _is_reparse(current):
        return True
    for component in relative_path.split("/"):
        current = os.path.join(current, component)
        if _is_reparse(current):
            return True
    return False


def _validate_relative_path(relative_path):
    if not isinstance(relative_path, str) or not relative_path:
        raise PatchAdmissionError("Target path must be a non-empty string")
    if "\x00" in relative_path or "\\" in relative_path:
        raise PatchAdmissionError("Target path must be normalized POSIX form")
    if relative_path.startswith("/") or ":" in relative_path:
        raise PatchAdmissionError("Target path must be relative")
    components = relative_path.split("/")
    if any(component in ("", ".", "..") for component in components):
        raise PatchAdmissionError("Target path must not traverse or be empty")
    for component in components:
        if component.endswith((" ", ".")):
            raise PatchAdmissionError("Target path components cannot end in space or dot")
        stem = component.split(".", 1)[0].upper()
        if stem in RESERVED_NAMES:
            raise PatchAdmissionError("Target path uses a reserved name")
    return components


def _denied_relative_path(relative_path):
    components = relative_path.split("/")
    if any(component.lower() in DENIED_DIRECTORIES for component in components[:-1]):
        return True
    name = components[-1].lower()
    if name in DENIED_FILE_NAMES:
        return True
    import fnmatch

    return any(fnmatch.fnmatchcase(name, pattern.lower()) for pattern in DENIED_FILE_PATTERNS)


def admit_workspace(workspace_root, incoming_root, sorted_root):
    """Admit one explicit code workspace disjoint from Incoming and Sorted."""
    if not isinstance(workspace_root, str) or not workspace_root.strip():
        raise PatchAdmissionError("Workspace root must be a non-empty string")
    canonical = _canonical(workspace_root)
    if not os.path.isdir(canonical):
        raise PatchAdmissionError("Workspace root must be an existing directory")
    drive, _ = os.path.splitdrive(canonical)
    if drive and os.path.normcase(canonical) == os.path.normcase(drive + os.sep):
        raise PatchAdmissionError("Workspace root cannot be a drive root")
    if os.path.normcase(canonical) == os.path.normcase(os.path.abspath(os.sep)):
        raise PatchAdmissionError("Workspace root cannot be a filesystem root")
    home = _canonical(os.path.expanduser("~"))
    if os.path.normcase(canonical) == os.path.normcase(home):
        raise PatchAdmissionError("Workspace root cannot be the user home root")
    app_data = _canonical(APP_DATA_DIR)
    app_parent = _canonical(os.path.dirname(app_data))
    for protected in (app_data, app_parent):
        if _same_or_ancestor(canonical, protected) or _same_or_ancestor(
            protected, canonical
        ):
            raise PatchAdmissionError("Workspace root cannot overlap app data")
    protected_roots = []
    for label, value in (("Incoming", incoming_root), ("Sorted", sorted_root)):
        if not isinstance(value, str) or not value.strip():
            raise PatchAdmissionError(f"{label} root must be a non-empty string")
        protected_roots.append((label, _canonical(value)))
    for label, protected in protected_roots:
        if _same_or_ancestor(canonical, protected) or _same_or_ancestor(protected, canonical):
            raise PatchAdmissionError(
                f"Workspace root overlaps the {label} organizer sandbox"
            )
    try:
        info = os.stat(canonical)
    except OSError as exc:
        raise PatchAdmissionError(f"Could not identify workspace root: {exc}") from exc
    identity = f"{os.path.normcase(canonical)}\0{info.st_dev}\0{info.st_ino}"
    fingerprint = _sha256(identity.encode("utf-8", errors="surrogatepass"))
    return WorkspaceAdmission(canonical, fingerprint, info.st_dev, info.st_ino)


def _outside_bytes(data, ranges, source_side):
    pieces = []
    cursor = 0
    for item in sorted(ranges, key=lambda entry: entry[source_side][0]):
        start, end = item[source_side]
        if start < cursor or end < start or end > len(data):
            raise PatchApplyError("Engine proof contains invalid edited ranges")
        pieces.append(data[cursor:start])
        cursor = end
    pieces.append(data[cursor:])
    return b"".join(pieces)


def _verify_engine_proof(source, output, proof):
    """Re-derive the engine's outside-range proof before any write."""
    try:
        ranges = proof["edited_ranges"]
        original_outside = _outside_bytes(source, ranges, "original")
        output_outside = _outside_bytes(output, ranges, "output")
        checks = {
            "original_sha256": _sha256(source),
            "output_sha256": _sha256(output),
            "original_bytes": len(source),
            "output_bytes": len(output),
            "original_outside_sha256": _sha256(original_outside),
            "output_outside_sha256": _sha256(output_outside),
        }
        for key, actual in checks.items():
            if proof.get(key) != actual:
                raise PatchApplyError(f"Engine proof verification failed for {key}")
        if original_outside != output_outside or not proof.get("outside_bytes_equal"):
            raise PatchApplyError("Engine outside-range byte proof is not equal")
    except (KeyError, TypeError) as exc:
        raise PatchApplyError("Engine proof is incomplete") from exc


class PatchApplier(FileAgent):
    """Apply one admitted patch and manage content-edit recovery history."""

    JOURNAL_LOCK_TIMEOUT_SECONDS = 10.0

    def __init__(
        self,
        workspace_root,
        incoming_root=None,
        sorted_root=None,
        operation_log_path=None,
        backup_root=None,
    ):
        base = os.getcwd()
        self.OPERATION_LOG_PATH = operation_log_path or self.DEFAULT_OPERATION_LOG_PATH
        super().__init__(api_manager=None, root_path=base)
        self.workspace = admit_workspace(
            workspace_root,
            incoming_root or os.path.join(base, "Incoming"),
            sorted_root or os.path.join(base, "Sorted"),
        )
        self.backup_root = _canonical(
            backup_root or os.path.join(APP_DATA_DIR, "c3_backups")
        )
        protected = (
            self.workspace.canonical_root,
            _canonical(incoming_root or os.path.join(base, "Incoming")),
            _canonical(sorted_root or os.path.join(base, "Sorted")),
        )
        for protected_root in protected:
            if _same_or_ancestor(self.backup_root, protected_root) or _same_or_ancestor(
                protected_root, self.backup_root
            ):
                raise PatchAdmissionError(
                    "Backup root must be disjoint from the workspace and organizer roots"
                )

    def admit_target(self, relative_path):
        """Admit one existing regular Python file under the selected root."""
        components = _validate_relative_path(relative_path)
        if not relative_path.lower().endswith(".py"):
            raise PatchAdmissionError("Only .py targets are admitted")
        if _denied_relative_path(relative_path):
            raise PatchAdmissionError("Target path matches the C3 write denylist")
        candidate = os.path.join(self.workspace.canonical_root, *components)
        canonical = _canonical(candidate)
        try:
            common = os.path.commonpath(
                (os.path.normcase(canonical), os.path.normcase(self.workspace.canonical_root))
            )
        except ValueError as exc:
            raise PatchAdmissionError("Target is outside the selected workspace") from exc
        if common != os.path.normcase(self.workspace.canonical_root):
            raise PatchAdmissionError("Target is outside the selected workspace")
        if _has_link_component(self.workspace.canonical_root, relative_path):
            raise PatchAdmissionError("Target contains a symlink, junction, or reparse point")
        try:
            info = os.stat(canonical)
        except OSError as exc:
            raise PatchAdmissionError(f"Target does not exist: {exc}") from exc
        if not stat.S_ISREG(info.st_mode):
            raise PatchAdmissionError("Target must be an existing regular file")
        if info.st_size > MAX_SOURCE_BYTES:
            raise PatchAdmissionError("Target exceeds the 1 MiB source bound")
        return TargetAdmission(
            relative_path=relative_path,
            canonical_path=canonical,
            device=info.st_dev,
            inode=info.st_ino,
            size=info.st_size,
        )

    def read_target(self, admitted):
        """Read admitted target bytes without modifying the target."""
        try:
            with open(admitted.canonical_path, "rb") as handle:
                content = handle.read(MAX_SOURCE_BYTES + 1)
        except OSError as exc:
            raise PatchAdmissionError(f"Could not read admitted target: {exc}") from exc
        if len(content) > MAX_SOURCE_BYTES:
            raise PatchAdmissionError("Target exceeds the 1 MiB source bound")
        return content

    def stage(self, patch, encoded_artifact):
        """Call the pure C3-I1 engine for the patch's single admitted file."""
        try:
            file_object = patch["files"][0]
            relative_path = file_object["relative_path"]
        except (KeyError, IndexError, TypeError) as exc:
            raise PatchApplyError("Patch must contain exactly one file") from exc
        admitted = self.admit_target(relative_path)
        source = self.read_target(admitted)
        try:
            return stage_patch(source, patch, encoded_artifact)
        except PatchEngineError as exc:
            raise PatchApplyError(str(exc)) from exc

    def replace_content(self, target, staged, expected_pre, expected_post):
        """Invoke the dedicated overwrite-capable atomic content primitive."""
        try:
            return _replace_content(target, staged, expected_pre, expected_post)
        except ContentReplaceError as exc:
            raise PatchApplyError(str(exc)) from exc

    def begin_mutation(self, target, metadata):
        """Persist a content-edit intent before any filesystem mutation."""
        with self._lock:
            entry = self._new_operation_entry(
                "content_edit", target, target, "Intent recorded", False
            )
            entry["state"] = "intent"
            entry.update(copy.deepcopy(metadata))
            self._operation_log.append(entry)
        try:
            self._save_operation_log()
        except Exception:
            with self._lock:
                self._operation_log.pop()
            raise
        return entry

    def complete_mutation(self, entry, result, metadata=None):
        """Persist completion after the atomic content replacement."""
        with self._lock:
            entry["result"] = result
            entry["success"] = True
            entry["state"] = "committed"
            entry["revision"] = entry.get("revision", 0) + 1
            if metadata:
                entry.update(copy.deepcopy(metadata))
        self._save_operation_log()

    def _mark_failed(self, entry, result):
        with self._lock:
            entry["result"] = result
            entry["success"] = False
            entry["state"] = "failed"
            entry["revision"] = entry.get("revision", 0) + 1
        try:
            self._save_operation_log()
        except Exception:
            pass


    def _write_exact(self, path, content):
        with open(path, "xb") as handle:
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())

    def write_backup(self, source, output, metadata):
        """Write exact pre/post images and a source-content-free manifest."""
        operation_id = metadata["operation_id"]
        backup = os.path.join(self.backup_root, operation_id)
        os.makedirs(backup, mode=0o700, exist_ok=False)
        try:
            os.chmod(backup, 0o700)
        except OSError:
            pass
        pre_path = os.path.join(backup, "pre_image.bin")
        post_path = os.path.join(backup, "post_image.bin")
        manifest_path = os.path.join(backup, "manifest.json")
        self._write_exact(pre_path, source)
        self._write_exact(post_path, output)
        with open(pre_path, "rb") as handle:
            if _sha256(handle.read()) != _sha256(source):
                raise OSError("Pre-image backup hash verification failed")
        with open(post_path, "rb") as handle:
            if _sha256(handle.read()) != _sha256(output):
                raise OSError("Post-image backup hash verification failed")
        manifest = dict(metadata)
        manifest.update(
            {
                "pre_sha256": _sha256(source),
                "post_sha256": _sha256(output),
                "pre_bytes": len(source),
                "post_bytes": len(output),
                "created_utc": datetime.now(timezone.utc).isoformat(),
            }
        )
        encoded = json.dumps(manifest, indent=2, sort_keys=True).encode("utf-8")
        self._write_exact(manifest_path, encoded)
        return backup

    def _update_intent(self, entry, metadata):
        with self._lock:
            entry.update(copy.deepcopy(metadata))
            entry["revision"] = entry.get("revision", 0) + 1
        self._save_operation_log()

    def _mark_uncertain(self, entry, result):
        with self._lock:
            entry["result"] = result
            entry["success"] = False
            entry["state"] = "uncertain"
            entry["revision"] = entry.get("revision", 0) + 1
        try:
            self._save_operation_log()
        except Exception:
            pass

    def _revalidate_source(self, admitted, expected_sha256):
        current = self.admit_target(admitted.relative_path)
        content = self.read_target(current)
        if current.canonical_path != admitted.canonical_path:
            raise PatchApplyError("Target identity changed after staging")
        if current.device != admitted.device or current.inode != admitted.inode:
            raise PatchApplyError("Target filesystem identity changed after staging")
        if _sha256(content) != expected_sha256:
            raise PatchApplyError("Source changed after staging")
        return content


    def apply_patch(
        self,
        patch,
        encoded_artifact,
        expected_output_sha256=None,
        expected_unified_diff=None,
        completion_callback=None,
    ):
        """Stage and atomically apply one admitted content patch.

        When ``expected_output_sha256`` is supplied, it is the immutable
        artifact's approved output hash. The staged bytes must match it before
        replacement and the on-disk bytes must match it afterward. When
        ``expected_unified_diff`` is supplied, the exact displayed diff must
        also match the bytes staged from the approved artifact.
        """
        try:
            file_object = patch["files"][0]
            relative_path = file_object["relative_path"]
        except (KeyError, IndexError, TypeError) as exc:
            raise PatchApplyError("Patch must contain exactly one file") from exc
        if patch.get("workspace_fingerprint") != self.workspace.fingerprint:
            raise PatchApplyError("Patch workspace fingerprint does not match admission")
        admitted = self.admit_target(relative_path)
        source = self.read_target(admitted)
        pre_sha256 = _sha256(source)
        try:
            staged = self.stage(patch, encoded_artifact)
        except PatchApplyError:
            raise
        except Exception as exc:
            raise PatchApplyError(f"Patch staging failed: {exc}") from exc
        output = staged.output_bytes
        _verify_engine_proof(source, output, staged.proof)
        post_sha256 = _sha256(output)
        if staged.proof.get("output_sha256") != post_sha256:
            raise PatchApplyError("Engine output hash does not match staged bytes")
        if (
            expected_output_sha256 is not None
            and post_sha256 != expected_output_sha256
        ):
            raise PatchApplyError(
                "Staged output does not match the approved artifact output hash"
            )
        if (
            expected_unified_diff is not None
            and staged.unified_diff != expected_unified_diff
        ):
            raise PatchApplyError(
                "Staged diff does not match the approved artifact diff"
            )
        operation_id = str(uuid.uuid4())
        metadata = {
            "operation_id": operation_id,
            "patch_id": patch.get("patch_id"),
            "plan_id": patch.get("plan_id"),
            "workspace_fingerprint": self.workspace.fingerprint,
            "relative_path": relative_path,
            "target_identity": {
                "device": admitted.device,
                "inode": admitted.inode,
            },
            "pre_sha256": pre_sha256,
            "post_sha256": post_sha256,
            "pre_bytes": len(source),
            "post_bytes": len(output),
            "outside_original_sha256": staged.proof["original_outside_sha256"],
            "outside_post_sha256": staged.proof["output_outside_sha256"],
        }
        try:
            with operation_journal_lock(
                self.OPERATION_LOG_PATH, timeout=self.JOURNAL_LOCK_TIMEOUT_SECONDS
            ):
                self._refresh_operation_log_from_disk()
                self._revalidate_source(admitted, pre_sha256)
                try:
                    entry = self.begin_mutation(admitted.canonical_path, metadata)
                except Exception as exc:
                    raise PatchApplyError(
                        f"Content edit could not journal its intent: {exc}"
                    ) from exc
                backup = None
                staged_path = None
                replace_attempted = False
                try:
                    try:
                        backup = self.write_backup(source, output, metadata)
                    except Exception:
                        partial_backup = os.path.join(self.backup_root, operation_id)
                        if os.path.isdir(partial_backup):
                            shutil.rmtree(partial_backup, ignore_errors=True)
                        raise
                    metadata["backup_reference"] = backup
                    self._update_intent(entry, metadata)
                    staged_path = _stage_content(
                        admitted.canonical_path, output, post_sha256
                    )
                    self._revalidate_source(admitted, pre_sha256)
                    replace_attempted = True
                    self.replace_content(
                        admitted.canonical_path,
                        staged_path,
                        pre_sha256,
                        post_sha256,
                    )
                    staged_path = None
                except Exception as exc:
                    if staged_path:
                        try:
                            os.remove(staged_path)
                        except OSError:
                            pass
                    if replace_attempted:
                        observed = None
                        try:
                            with open(admitted.canonical_path, "rb") as handle:
                                observed = _sha256(handle.read())
                        except OSError:
                            pass
                        if observed == post_sha256:
                            try:
                                (completion_callback or self.complete_mutation)(
                                    entry,
                                    "Approved content bytes applied",
                                    {"backup_reference": backup},
                                )
                            except Exception as journal_error:
                                self._mark_uncertain(
                                    entry,
                                    "Content bytes were replaced, but completion could "
                                    f"not be journaled: {journal_error}",
                                )
                                return ApplyResult(
                                    "uncertain",
                                    operation_id,
                                    relative_path,
                                    pre_sha256,
                                    post_sha256,
                                    backup,
                                )
                            return ApplyResult(
                                "committed",
                                operation_id,
                                relative_path,
                                pre_sha256,
                                post_sha256,
                                backup,
                            )
                        if observed != pre_sha256:
                            self._mark_uncertain(
                                entry,
                                f"Replacement outcome is uncertain: {exc}",
                            )
                            return ApplyResult(
                                "uncertain",
                                operation_id,
                                relative_path,
                                pre_sha256,
                                post_sha256,
                                backup,
                            )
                    self._mark_failed(entry, f"Content edit failed: {exc}")
                    raise PatchApplyError(f"Content edit failed: {exc}") from exc
                try:
                    (completion_callback or self.complete_mutation)(
                        entry,
                        "Approved content bytes applied",
                        {"backup_reference": backup},
                    )
                except Exception as exc:
                    self._mark_uncertain(
                        entry,
                        "Content bytes were replaced, but completion could not be "
                        f"journaled: {exc}",
                    )
                    return ApplyResult(
                        "uncertain",
                        operation_id,
                        relative_path,
                        pre_sha256,
                        post_sha256,
                        backup,
                    )
                self._prune_backups()
                try:
                    with open(admitted.canonical_path, "rb") as handle:
                        on_disk_sha256 = _sha256(handle.read())
                except OSError as exc:
                    self._mark_uncertain(
                        entry,
                        "Approved bytes were applied, but the final hash could "
                        f"not be verified: {exc}",
                    )
                    return ApplyResult(
                        "uncertain",
                        operation_id,
                        relative_path,
                        pre_sha256,
                        post_sha256,
                        backup,
                    )
                if on_disk_sha256 != post_sha256:
                    self._mark_uncertain(
                        entry,
                        "Approved bytes were applied, but the final on-disk hash "
                        "did not match the approved output hash.",
                    )
                    return ApplyResult(
                        "uncertain",
                        operation_id,
                        relative_path,
                        pre_sha256,
                        post_sha256,
                        backup,
                    )
                return ApplyResult(
                    "committed",
                    operation_id,
                    relative_path,
                    pre_sha256,
                    post_sha256,
                    backup,
                )
        except JournalLockError as exc:
            raise PatchApplyError(f"Journal lock could not be acquired: {exc}") from exc


    def _content_entries(self):
        return [
            entry
            for entry in self._operation_log
            if entry.get("operation") == "content_edit"
            and entry.get("workspace_fingerprint") == self.workspace.fingerprint
        ]

    def _blocked_by_uncertain(self):
        return any(entry.get("state") == "uncertain" for entry in self._content_entries())

    def _restore_image(
        self,
        entry,
        image_name,
        expected_current,
        desired_sha256,
        mutation_started,
    ):
        backup = entry.get("backup_reference")
        if not backup:
            raise PatchRecoveryError("Content edit has no backup reference")
        image_path = os.path.join(backup, image_name)
        try:
            with open(image_path, "rb") as handle:
                image = handle.read()
        except OSError as exc:
            raise PatchRecoveryError(f"Content backup is unavailable: {exc}") from exc
        if _sha256(image) != desired_sha256:
            raise PatchRecoveryError("Content backup hash verification failed")
        admitted = self.admit_target(entry["relative_path"])
        with open(admitted.canonical_path, "rb") as handle:
            current = handle.read()
        if _sha256(current) != expected_current:
            raise PatchRecoveryError("Target no longer matches the expected recovery image")
        staged = _stage_content(admitted.canonical_path, image, desired_sha256)
        try:
            self.replace_content(
                admitted.canonical_path,
                staged,
                expected_current,
                desired_sha256,
            )
            mutation_started.append(True)
        except Exception:
            # ``os.replace`` consumes the staging file. If it disappeared, the
            # replacement primitive reached the mutation boundary even though
            # a later verification or durability step raised.
            if not os.path.exists(staged):
                mutation_started.append(True)
            try:
                os.remove(staged)
            except OSError:
                pass
            raise

    def _undo_candidate(self):
        return next(
            (
                item
                for item in reversed(self._content_entries())
                if item.get("state") == "committed" and not item.get("undone")
            ),
            None,
        )

    def _redo_candidate(self):
        return next(
            (
                item
                for item in self._content_entries()
                if item.get("state") == "committed" and item.get("undone")
            ),
            None,
        )


    def undo_last(self):
        """Restore the newest committed content edit's exact pre-image."""
        try:
            with operation_journal_lock(
                self.OPERATION_LOG_PATH, timeout=self.JOURNAL_LOCK_TIMEOUT_SECONDS
            ):
                changed = self._refresh_operation_log_from_disk()
                if changed:
                    raise PatchRecoveryError(
                        "Operation history changed concurrently; refusing stale undo"
                    )
                if self._blocked_by_uncertain():
                    raise PatchRecoveryError(
                        "Undo blocked by an uncertain content edit"
                    )
                entry = self._undo_candidate()
                if entry is None:
                    raise PatchRecoveryError("No content edit is available to undo")
                try:
                    self._begin_transition(entry, "undo")
                except Exception as exc:
                    raise PatchRecoveryError(
                        f"Undo could not journal its transition: {exc}"
                    ) from exc
                mutation_started = []
                try:
                    self._restore_image(
                        entry,
                        "pre_image.bin",
                        entry["post_sha256"],
                        entry["pre_sha256"],
                        mutation_started,
                    )
                    entry["undone"] = True
                    self._complete_transition(entry, "undo")
                except Exception as exc:
                    if mutation_started:
                        self._mark_transition_uncertain(entry, "undo")
                    else:
                        self._mark_transition_failed(entry, "undo")
                    if isinstance(exc, PatchRecoveryError):
                        raise
                    raise PatchRecoveryError(f"Undo failed: {exc}") from exc
        except JournalLockError as exc:
            raise PatchRecoveryError(f"Journal lock could not be acquired: {exc}") from exc

    def redo_last(self):
        """Restore the oldest undone content edit's exact post-image."""
        try:
            with operation_journal_lock(
                self.OPERATION_LOG_PATH, timeout=self.JOURNAL_LOCK_TIMEOUT_SECONDS
            ):
                changed = self._refresh_operation_log_from_disk()
                if changed:
                    raise PatchRecoveryError(
                        "Operation history changed concurrently; refusing stale redo"
                    )
                if self._blocked_by_uncertain():
                    raise PatchRecoveryError(
                        "Redo blocked by an uncertain content edit"
                    )
                entry = self._redo_candidate()
                if entry is None:
                    raise PatchRecoveryError("No content edit is available to redo")
                try:
                    self._begin_transition(entry, "redo")
                except Exception as exc:
                    raise PatchRecoveryError(
                        f"Redo could not journal its transition: {exc}"
                    ) from exc
                mutation_started = []
                try:
                    self._restore_image(
                        entry,
                        "post_image.bin",
                        entry["pre_sha256"],
                        entry["post_sha256"],
                        mutation_started,
                    )
                    entry["undone"] = False
                    self._complete_transition(entry, "redo")
                except Exception as exc:
                    if mutation_started:
                        self._mark_transition_uncertain(entry, "redo")
                    else:
                        self._mark_transition_failed(entry, "redo")
                    if isinstance(exc, PatchRecoveryError):
                        raise
                    raise PatchRecoveryError(f"Redo failed: {exc}") from exc
        except JournalLockError as exc:
            raise PatchRecoveryError(f"Journal lock could not be acquired: {exc}") from exc


    def _prune_backups(self):
        """Retain the newest 20 committed edits and all undoable/uncertain ones."""
        committed = [
            entry
            for entry in self._content_entries()
            if entry.get("state") == "committed"
        ]
        protected = {entry.get("backup_reference") for entry in committed[-MAX_BACKUPS:]}
        protected.update(
            entry.get("backup_reference")
            for entry in self._content_entries()
            if entry.get("state") == "uncertain" or not entry.get("undone")
        )
        if not os.path.isdir(self.backup_root):
            return
        for name in os.listdir(self.backup_root):
            path = os.path.join(self.backup_root, name)
            if path in protected or not os.path.isdir(path):
                continue
            referenced = any(
                entry.get("backup_reference") == path
                for entry in self._operation_log
            )
            if not referenced:
                shutil.rmtree(path, ignore_errors=True)

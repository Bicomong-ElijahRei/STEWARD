"""
FileAgent - Handles all file operations for STEWARD.

Consolidates logic from steward_agent.py and steward_gui.py into a single class.
Provides run(task_description, dry_run=True) method for preview-then-execute workflow.
Includes full undo/redo support via JSON operation log.
"""

import os
import re
from utils.helpers import (
    FILE_PREVIEW_LIMIT,
    get_app_data_dir,
    sanitize_category,
    truncate_file_preview,
)
import shutil
import json
import logging
import threading
import copy
import uuid
from contextlib import contextmanager
from datetime import datetime
from typing import Dict, Any, List, Optional, Callable

import send2trash

try:
    import PyPDF2
except ImportError:
    PyPDF2 = None

try:
    import docx  # python-docx
except ImportError:
    docx = None

try:
    import openpyxl
except ImportError:
    openpyxl = None

from agent.journal_lock import (
    JournalLockError,
    operation_journal_lock,
)
from agent.tools import (
    move_file as _move_file,
    delete_file as _delete_file,
    rename_file as _rename_file,
    create_folder as _create_folder,
    list_directory as _list_directory,
    get_file_info as _get_file_info,
    tool_functions as _legacy_tool_functions,
)
from core.router import APIManager

logger = logging.getLogger(__name__)

def migrate_legacy_operation_log(
    operation_log_path: str,
    legacy_root: str | None = None,
) -> bool:
    """Copy the legacy root operation log into AppData once, if needed."""
    legacy_root = legacy_root or os.getcwd()
    old_path = os.path.join(legacy_root, "steward_operations.json")
    if os.path.exists(operation_log_path) or not os.path.exists(old_path):
        return False
    os.makedirs(os.path.dirname(os.path.abspath(operation_log_path)), exist_ok=True)
    shutil.copy2(old_path, operation_log_path)
    return True


class FileAgent:
    DEFAULT_OPERATION_LOG_PATH = os.path.join(
        get_app_data_dir(), "steward_operations.json"
    )
    OPERATION_LOG_PATH = DEFAULT_OPERATION_LOG_PATH
    JOURNAL_LOCK_TIMEOUT_SECONDS = 10.0

    def __init__(
        self,
        api_manager: APIManager,
        root_path: Optional[str] = None,
        dry_run: bool = True,
        rules_path: Optional[str] = None,
    ):
        self.root_path = os.path.realpath(os.path.abspath(root_path or os.getcwd()))
        self.allowed_roots = tuple(
            os.path.realpath(os.path.join(self.root_path, folder))
            for folder in ("Incoming", "Sorted")
        )
        self.api_manager = api_manager
        self.dry_run = dry_run
        self.rules_path = rules_path or os.path.join(self.root_path, "rules.yaml")
        self._lock = threading.RLock()
        self._plan_lock = threading.RLock()
        self._plan_generation = 0
        self._pending_plan = None
        self._pending_plan_id = None
        self._mutation_hook = None
        self.last_provider = None
        self.last_categorized_by_rule = False
        self.last_rule_pattern = None
        self._journal_recovery_error = None
        self._migrate_legacy_operation_log()
        self._operation_log = self._load_operation_log()

        self.system_prompt = f"""You are STEWARD File Agent, an AI file manager for: {self.root_path}

WORKSPACE:
- Incoming: {{root_path}}\\Incoming
- Sorted:   {{root_path}}\\Sorted

DRY RUN WORKFLOW (MANDATORY):
1. Always start with dry_run=True. Present a PREVIEW of what would happen.
2. List each operation (move, rename, delete, create) with source and destination.
3. Ask the user to confirm before executing.
4. Only after explicit confirmation, set dry_run=False and execute.
5. NEVER execute destructive operations (delete, move, rename) without user confirmation.

AVAILABLE TOOLS:
- move_file(source, destination): Move a file
- delete_file(path): Delete a file (recycle bin)
- rename_file(old_path, new_name): Rename a file
- create_folder(path): Create a folder
- list_directory(directory): List files and folders
- read_file_content(file_path): Read file content (.txt, .pdf, .docx, .xlsx)
- get_file_info(file_path): Get file size and modification time

When the user asks to organize files:
1. Use list_directory to discover what exists
2. Use read_file_content to understand file contents
3. Decide on categories and plan operations
4. PREVIEW all operations (dry_run=True)
5. Wait for user confirmation
6. Execute (dry_run=False)

All file mutations are restricted to {{root_path}}\\Incoming and {{root_path}}\\Sorted.
Absolute paths supplied by the user or model never bypass this sandbox.
""".format(root_path=self.root_path)

    def _sandbox_path(self, path: str) -> str:
        """Resolve a path and require it to remain inside Incoming or Sorted."""
        if not isinstance(path, str) or not path.strip():
            raise ValueError("File operation paths must be non-empty strings.")
        absolute_path = path if os.path.isabs(path) else os.path.join(self.root_path, path)
        resolved = os.path.realpath(os.path.abspath(absolute_path))
        for allowed_root in self.allowed_roots:
            try:
                common = os.path.commonpath((resolved, allowed_root))
            except ValueError:
                # Different Windows drives can never share a sandbox root.
                continue
            if os.path.normcase(common) == os.path.normcase(allowed_root):
                return resolved
        raise PermissionError(
            f"Sandbox violation: '{path}' is outside the configured Incoming and Sorted directories."
        )

    def _validate_mutation(self, func_name: str, args: Dict[str, Any]) -> Dict[str, Any]:
        """Validate mutation paths and return canonical arguments for execution."""
        safe_args = copy.deepcopy(args)
        if func_name == "move_file":
            safe_args["source"] = self._sandbox_path(args.get("source"))
            safe_args["destination"] = self._sandbox_path(args.get("destination"))
        elif func_name == "rename_file":
            old_path = self._sandbox_path(args.get("old_path"))
            new_name = args.get("new_name")
            if not isinstance(new_name, str) or not new_name.strip():
                raise ValueError("A non-empty new file name is required.")
            if new_name in (".", "..") or os.path.isabs(new_name) or os.path.basename(new_name) != new_name:
                raise ValueError("A rename must use a file name without path components.")
            self._sandbox_path(os.path.join(os.path.dirname(old_path), new_name))
            safe_args["old_path"] = old_path
        elif func_name in ("delete_file", "create_folder"):
            safe_args["path"] = self._sandbox_path(args.get("path"))
            if func_name == "delete_file" and any(
                os.path.normcase(safe_args["path"]) == os.path.normcase(root)
                for root in self.allowed_roots
            ):
                raise PermissionError("Refusing to delete a configured sandbox root.")
        elif func_name in ("cleanup_empty_folders", "cleanup_temp_files"):
            safe_args["directory"] = self._sandbox_path(args.get("directory"))
        elif func_name == "batch_move":
            safe_args["source_pattern"] = self._sandbox_path(args.get("source_pattern"))
            safe_args["destination_folder"] = self._sandbox_path(args.get("destination_folder"))
        elif func_name == "read_file_content":
            safe_args["file_path"] = self._sandbox_path(args.get("file_path"))
        elif func_name == "list_directory":
            safe_args["directory"] = self._sandbox_path(args.get("directory"))
        elif func_name == "get_file_info":
            safe_args["file_path"] = self._sandbox_path(args.get("file_path"))
        elif func_name == "find_duplicates":
            safe_args["directory"] = self._sandbox_path(args.get("directory"))
        elif func_name == "find_large_files":
            safe_args["directory"] = self._sandbox_path(args.get("directory"))
        elif func_name == "suggest_deletions":
            safe_args["directory"] = self._sandbox_path(args.get("directory"))
        return safe_args

    def _migrate_legacy_operation_log(self) -> bool:
        """Copy the legacy root operation log into AppData once, if needed."""
        if self.OPERATION_LOG_PATH != self.DEFAULT_OPERATION_LOG_PATH:
            return False
        return migrate_legacy_operation_log(self.OPERATION_LOG_PATH)

    def _load_operation_log(self) -> List[Dict[str, Any]]:
        if os.path.exists(self.OPERATION_LOG_PATH):
            try:
                with open(self.OPERATION_LOG_PATH, "r", encoding="utf-8") as f:
                    data = json.load(f)
                if isinstance(data, list):
                    entries = [e for e in data if isinstance(e, dict)]
                    seen_ids = set()
                    for entry in entries:
                        entry_id = entry.get("id")
                        if entry_id in seen_ids:
                            entry["id"] = f"{entry_id}-{uuid.uuid4().hex}"
                            logger.warning("Assigned a unique ID to a duplicate operation-log entry.")
                        seen_ids.add(entry.get("id"))
                        if entry.get("state") == "intent":
                            entry["state"] = "uncertain"
                            entry["result"] = (
                                "Interrupted or uncertain operation; manual reconciliation required."
                            )
                        transition = entry.get("transition")
                        if isinstance(transition, dict) and transition.get("state") == "intent":
                            entry["state"] = "uncertain"
                            entry["result"] = (
                                "Interrupted or uncertain history transition; manual "
                                "reconciliation required."
                            )
                        entry.setdefault("success", bool(entry.get("operation")))
                        entry.setdefault("undone", False)
                    return entries
                self._journal_recovery_error = (
                    "Operation history has an unsupported format. Mutations are disabled "
                    "to preserve the existing history file."
                )
                logger.warning(self._journal_recovery_error)
            except (json.JSONDecodeError, IOError, OSError) as e:
                self._journal_recovery_error = (
                    f"Operation history could not be loaded: {e}. "
                    "Mutations are disabled to preserve the existing history file."
                )
                logger.warning(self._journal_recovery_error)
        return []

    @contextmanager
    def _journal_process_lock(self):
        """Serialize journal users across threads and processes."""
        with operation_journal_lock(
            self.OPERATION_LOG_PATH,
            timeout=self.JOURNAL_LOCK_TIMEOUT_SECONDS,
        ):
            yield

    def _refresh_operation_log_from_disk(self) -> bool:
        """Refresh durable history while the journal lock is held.

        Returns ``True`` when an entry known to this agent changed on disk,
        which makes a pending undo/redo claim stale. Local-only entries are
        retained for compatibility with callers that supply in-memory history.
        """
        if not os.path.exists(self.OPERATION_LOG_PATH):
            return False
        previous = self._operation_log
        disk_entries = self._load_operation_log()
        local_by_id = {
            entry.get("id"): entry
            for entry in previous
            if isinstance(entry, dict)
        }
        disk_by_id = {
            entry.get("id"): entry
            for entry in disk_entries
            if isinstance(entry, dict)
        }
        changed = any(
            entry_id in local_by_id and local_by_id[entry_id] != disk_entry
            for entry_id, disk_entry in disk_by_id.items()
        )
        local_only = [
            entry for entry in previous
            if isinstance(entry, dict) and entry.get("id") not in disk_by_id
        ]
        self._operation_log = disk_entries + local_only
        return changed

    def _merge_disk_log(self) -> List[Dict[str, Any]]:
        """Return durable history, rejecting stale revisions of known entries."""
        if not os.path.exists(self.OPERATION_LOG_PATH):
            return list(self._operation_log)
        try:
            with open(self.OPERATION_LOG_PATH, "r", encoding="utf-8") as f:
                disk_entries = json.load(f)
        except (json.JSONDecodeError, IOError, OSError):
            raise
        if not isinstance(disk_entries, list):
            raise ValueError("Operation log is not a list.")
        disk_by_id = {
            e.get("id"): e for e in disk_entries if isinstance(e, dict)
        }
        merged = dict(disk_by_id)
        for entry in self._operation_log:
            entry_id = entry.get("id")
            disk_entry = disk_by_id.get(entry_id)
            if disk_entry is None or entry.get("revision", 0) > disk_entry.get(
                "revision", 0
            ):
                merged[entry_id] = entry
            elif disk_entry.get("revision", 0) == entry.get("revision", 0):
                disk_transition = disk_entry.get("transition")
                disk_was_intent = (
                    disk_entry.get("state") == "intent"
                    or (
                        isinstance(disk_transition, dict)
                        and disk_transition.get("state") == "intent"
                    )
                )
                local_is_recovered = entry.get("state") == "uncertain"
                if disk_entry != entry and not (disk_was_intent and local_is_recovered):
                    raise RuntimeError(
                        "Operation history was concurrently updated; refusing "
                        "a conflicting write."
                    )
                if disk_entry != entry:
                    merged[entry_id] = entry
        return list(merged.values())

    def _save_operation_log(self):
        """Atomically persist the operation log, surfacing every failure."""
        with self._journal_process_lock():
            with self._lock:
                self._save_operation_log_locked()

    def _save_operation_log_locked(self):
        """Persist the log while the caller holds both required locks."""
        directory = os.path.dirname(os.path.abspath(self.OPERATION_LOG_PATH))
        os.makedirs(directory, exist_ok=True)
        tmp_path = os.path.join(
            directory,
            f".{os.path.basename(self.OPERATION_LOG_PATH)}.{os.getpid()}.{uuid.uuid4().hex}.tmp",
        )
        try:
            merged = self._merge_disk_log()
            with open(tmp_path, "x", encoding="utf-8") as f:
                json.dump(merged, f, indent=2, default=str)
                f.flush()
                os.fsync(f.fileno())
            os.replace(tmp_path, self.OPERATION_LOG_PATH)
            self._operation_log = merged
            if os.name != "nt":
                directory_fd = os.open(directory, os.O_RDONLY)
                try:
                    os.fsync(directory_fd)
                finally:
                    os.close(directory_fd)
        except Exception:
            try:
                os.remove(tmp_path)
            except OSError:
                pass
            logger.exception("Could not save operation log")
            raise

    def _record_operation(
        self,
        operation: str,
        source: str,
        destination: Optional[str] = None,
        result: str = "",
        success: bool = True,
        metadata: Optional[Dict[str, Any]] = None,
    ):
        """Record a standalone operation without overwriting peer updates."""
        with self._journal_process_lock():
            self._refresh_operation_log_from_disk()
            entry = self._new_operation_entry(
                operation, source, destination, result, success
            )
            if metadata:
                entry.update(metadata)
            with self._lock:
                self._operation_log.append(entry)
            self._save_operation_log()

    def _new_operation_entry(
        self,
        operation: str,
        source: str,
        destination: Optional[str] = None,
        result: str = "",
        success: bool = True,
    ) -> Dict[str, Any]:
        now = datetime.now().isoformat()
        return {
            "id": f"{now}-{uuid.uuid4().hex}",
            "timestamp": now,
            "operation": operation,
            "source": source,
            "destination": destination,
            "result": result,
            "success": success,
            "undone": False,
            "state": "committed",
            "revision": 1,
        }

    def _begin_mutation(
        self,
        operation: str,
        source: str,
        destination: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Persist an intent entry before changing the filesystem."""
        with self._lock:
            entry = self._new_operation_entry(
                operation, source, destination, "Intent recorded", False
            )
            entry["state"] = "intent"
            self._operation_log.append(entry)
        try:
            self._save_operation_log()
        except Exception:
            with self._lock:
                self._operation_log.pop()
            raise
        return entry

    def _complete_mutation(
        self,
        entry: Dict[str, Any],
        result: str,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> None:
        with self._lock:
            entry["result"] = result
            entry["success"] = True
            entry["state"] = "committed"
            entry["revision"] = entry.get("revision", 0) + 1
            if metadata:
                entry.update(metadata)
        self._save_operation_log()

    @staticmethod
    def _folder_ownership(paths: List[str]) -> List[Dict[str, Any]]:
        """Record exact directory identities for safe later undo/redo."""
        ownership = []
        for path in paths:
            try:
                stat = os.stat(path)
                device = stat.st_dev
                inode = stat.st_ino
            except OSError:
                # Preserve path evidence even if the directory disappears during
                # journaling. Missing identity cannot pass the later identity
                # check, so recovery remains blocked rather than becoming unsafe.
                device = None
                inode = None
            ownership.append({
                "path": path,
                "device": device,
                "inode": inode,
            })
        return ownership

    def _execute_mutation(
        self,
        func_name: str,
        safe_args: Dict[str, Any],
        operation: str,
        source: str,
        destination: Optional[str],
        callback: Optional[Callable[..., str]] = None,
    ) -> str:
        """Run one mutation while holding the cross-process journal lock."""
        try:
            with self._journal_process_lock():
                self._refresh_operation_log_from_disk()
                return self._execute_mutation_locked(
                    func_name, safe_args, operation, source, destination, callback
                )
        except JournalLockError as exc:
            return (
                "Error: operation was not started because the journal lock could "
                f"not be acquired: {exc}"
            )

    def _execute_mutation_locked(
        self,
        func_name: str,
        safe_args: Dict[str, Any],
        operation: str,
        source: str,
        destination: Optional[str],
        callback: Optional[Callable[..., str]] = None,
    ) -> str:
        """Run one mutation with a durable intent before disk changes."""
        if self._journal_recovery_error:
            return f"Error: {self._journal_recovery_error}"
        try:
            entry = self._begin_mutation(operation, source, destination)
        except Exception as exc:
            return (
                "Error: operation was not started because durable operation "
                f"history could not be recorded: {exc}"
            )
        try:
            if callback is None:
                result = _legacy_tool_functions[func_name](**safe_args)
            else:
                result = callback(**safe_args)
            metadata = dict(getattr(result, "metadata", {}) or {})
            if isinstance(result, str) and result.startswith("Error"):
                entry["result"] = result
                entry["success"] = False
                entry["state"] = metadata.get("mutation_state", "failed")
                entry["revision"] = entry.get("revision", 0) + 1
                if metadata:
                    entry.update(metadata)
                if operation == "create_folder":
                    created_paths = metadata.get("created_paths", [])
                    if created_paths:
                        metadata["folder_ownership"] = self._folder_ownership(created_paths)
                        entry["folder_ownership"] = metadata["folder_ownership"]
                actual_destination = metadata.get("actual_destination")
                if actual_destination and operation == "move":
                    entry["destination"] = actual_destination
                try:
                    self._save_operation_log()
                except Exception as journal_error:
                    return f"{result} (operation history could not be finalized: {journal_error})"
                return result

            if metadata.get("no_op"):
                entry["result"] = result
                entry["success"] = False
                entry["state"] = "no_op"
                entry["revision"] = entry.get("revision", 0) + 1
                entry.update(metadata)
                self._save_operation_log()
                return result

            if operation == "create_folder":
                created_paths = metadata.get("created_paths", [])
                if not created_paths:
                    entry["result"] = result
                    entry["success"] = False
                    entry["state"] = "no_op"
                    entry["revision"] = entry.get("revision", 0) + 1
                    self._save_operation_log()
                    return result
                metadata["folder_ownership"] = self._folder_ownership(created_paths)
            actual_destination = metadata.get("actual_destination")
            if actual_destination and operation == "move":
                entry["destination"] = actual_destination
            try:
                self._complete_mutation(entry, result, metadata)
            except Exception as journal_error:
                entry["success"] = False
                entry["state"] = "uncertain"
                entry["result"] = (
                    "Filesystem mutation completed, but durable history could not be "
                    f"finalized: {journal_error}"
                )
                return f"Error: {entry['result']}"
            return result
        except Exception as exc:
            entry["result"] = f"Error: {exc}"
            entry["success"] = False
            entry["state"] = "failed"
            try:
                self._save_operation_log()
            except Exception as journal_error:
                return f"Error: {exc} (operation history could not be finalized: {journal_error})"
            return f"Error: {exc}"

    def _begin_transition(self, entry: Dict[str, Any], kind: str) -> None:
        with self._lock:
            previous = entry.get("transition")
            entry["transition"] = {"kind": kind, "state": "intent"}
            entry["revision"] = entry.get("revision", 0) + 1
        try:
            self._save_operation_log()
        except Exception:
            with self._lock:
                if previous is None:
                    entry.pop("transition", None)
                else:
                    entry["transition"] = previous
            raise

    def _complete_transition(self, entry: Dict[str, Any], kind: str) -> None:
        with self._lock:
            entry["transition"] = {"kind": kind, "state": "committed"}
            entry["revision"] = entry.get("revision", 0) + 1
        self._save_operation_log()

    def _mark_transition_uncertain(self, entry: Dict[str, Any], kind: str) -> None:
        with self._lock:
            entry["transition"] = {"kind": kind, "state": "uncertain"}
            entry["state"] = "uncertain"
            entry["revision"] = entry.get("revision", 0) + 1
        try:
            self._save_operation_log()
        except Exception:
            pass

    def _mark_transition_failed(self, entry: Dict[str, Any], kind: str) -> None:
        with self._lock:
            entry["transition"] = {"kind": kind, "state": "failed"}
            entry["revision"] = entry.get("revision", 0) + 1
        try:
            self._save_operation_log()
        except Exception:
            pass

    @staticmethod
    def _same_owned_folder(path: str, ownership: Dict[str, Any]) -> bool:
        try:
            stat = os.stat(path)
        except OSError:
            return False
        return (
            stat.st_dev == ownership.get("device")
            and stat.st_ino == ownership.get("inode")
        )

    def undo_last(self) -> str:
        """Undo one operation while holding the cross-process journal lock."""
        try:
            with self._journal_process_lock():
                changed = self._refresh_operation_log_from_disk()
                if changed:
                    return (
                        "Undo failed: operation history was concurrently updated; "
                        "refusing a stale transition."
                    )
                return self._undo_last_locked()
        except JournalLockError as exc:
            return f"Undo failed: journal lock could not be acquired: {exc}"

    def _undo_last_locked(self) -> str:
        with self._lock:
            saw_delete = False
            for entry in reversed(self._operation_log):
                if entry.get("state") == "uncertain":
                    return (
                        "Undo blocked: operation history contains an interrupted or "
                        "uncertain transition requiring manual reconciliation."
                    )
                if entry.get("undone", False) or not entry.get("success", False):
                    continue
                operation = entry["operation"]
                if operation == "delete":
                    saw_delete = True
                    continue
                if operation not in ("move", "rename", "create_folder"):
                    continue
                source = entry["source"]
                destination = entry.get("destination")
                mutation_started = False
                try:
                    self._begin_transition(entry, "undo")
                    if operation == "move":
                        safe = self._validate_mutation(
                            "move_file", {"source": source, "destination": destination}
                        )
                        src, dst = safe["source"], safe["destination"]
                        if not os.path.isfile(dst):
                            raise FileNotFoundError(f"'{dst}' no longer exists")
                        if os.path.lexists(src):
                            raise FileExistsError(
                                f"refusing to overwrite existing '{src}'"
                            )
                        mutation_started = True
                        undo_result = _move_file(dst, src)
                        if undo_result.startswith("Error"):
                            raise RuntimeError(undo_result)
                        result = f"Undid move: '{destination}' Ã¢â€ â€™ '{source}'"
                    elif operation == "rename":
                        if not destination:
                            raise ValueError("rename history has no destination")
                        safe = self._validate_mutation(
                            "rename_file", {"old_path": source, "new_name": destination}
                        )
                        new_path = os.path.join(
                            os.path.dirname(safe["old_path"]), safe["new_name"]
                        )
                        if not os.path.isfile(new_path):
                            raise FileNotFoundError(f"'{new_path}' no longer exists")
                        if os.path.lexists(safe["old_path"]):
                            raise FileExistsError(
                                f"refusing to overwrite existing '{safe['old_path']}'"
                            )
                        mutation_started = True
                        undo_result = _rename_file(
                            new_path, os.path.basename(safe["old_path"])
                        )
                        if undo_result.startswith("Error"):
                            raise RuntimeError(undo_result)
                        result = f"Undid rename: '{destination}' Ã¢â€ â€™ '{os.path.basename(source)}'"
                    else:
                        safe = self._validate_mutation("create_folder", {"path": source})
                        ownership = entry.get("folder_ownership")
                        if not ownership:
                            raise PermissionError(
                                "legacy folder creation has no ownership evidence; "
                                "refusing destructive undo"
                            )
                        for item in sorted(
                            ownership, key=lambda value: len(value["path"]), reverse=True
                        ):
                            path = item["path"]
                            if not os.path.isdir(path):
                                raise FileNotFoundError(f"'{path}' no longer exists")
                            if not self._same_owned_folder(path, item):
                                raise PermissionError(
                                    f"'{path}' was replaced or modified; refusing to remove it"
                                )
                        mutation_started = True
                        for item in sorted(
                            ownership, key=lambda value: len(value["path"]), reverse=True
                        ):
                            os.rmdir(item["path"])
                        result = f"Undid create_folder: removed '{safe['path']}'"
                    entry["undone"] = True
                    self._complete_transition(entry, "undo")
                    return result
                except Exception as exc:
                    if mutation_started:
                        self._mark_transition_uncertain(entry, "undo")
                    else:
                        self._mark_transition_failed(entry, "undo")
                    return f"Undo failed: {exc}"
            if saw_delete:
                return "Cannot undo delete (sent to recycle bin)"
            return "No operations to undo."

    def redo_last(self) -> str:
        """Redo one operation while holding the cross-process journal lock."""
        try:
            with self._journal_process_lock():
                changed = self._refresh_operation_log_from_disk()
                if changed:
                    return (
                        "Redo failed: operation history was concurrently updated; "
                        "refusing a stale transition."
                    )
                return self._redo_last_locked()
        except JournalLockError as exc:
            return f"Redo failed: journal lock could not be acquired: {exc}"

    def _redo_last_locked(self) -> str:
        with self._lock:
            for entry in self._operation_log:
                if entry.get("state") == "uncertain":
                    return (
                        "Redo blocked: operation history contains an interrupted or "
                        "uncertain transition requiring manual reconciliation."
                    )
                if not entry.get("undone", False):
                    continue
                operation = entry["operation"]
                if operation not in ("move", "rename", "create_folder"):
                    continue
                source = entry["source"]
                destination = entry.get("destination")
                mutation_started = False
                try:
                    self._begin_transition(entry, "redo")
                    if operation == "move":
                        safe = self._validate_mutation(
                            "move_file", {"source": source, "destination": destination}
                        )
                        src, dst = safe["source"], safe["destination"]
                        if not os.path.isfile(src):
                            raise FileNotFoundError(f"'{src}' no longer exists")
                        if os.path.lexists(dst):
                            raise FileExistsError(
                                f"refusing to overwrite existing '{dst}'"
                            )
                        mutation_started = True
                        redo_result = _move_file(src, dst)
                        if redo_result.startswith("Error"):
                            raise RuntimeError(redo_result)
                        result = f"Redid move: '{source}' Ã¢â€ â€™ '{destination}'"
                    elif operation == "rename":
                        if not destination:
                            raise ValueError("rename history has no destination")
                        safe = self._validate_mutation(
                            "rename_file", {"old_path": source, "new_name": destination}
                        )
                        new_path = os.path.join(
                            os.path.dirname(safe["old_path"]), safe["new_name"]
                        )
                        if not os.path.isfile(safe["old_path"]):
                            raise FileNotFoundError(f"'{safe['old_path']}' no longer exists")
                        if os.path.lexists(new_path):
                            raise FileExistsError(
                                f"refusing to overwrite existing '{new_path}'"
                            )
                        mutation_started = True
                        redo_result = _rename_file(safe["old_path"], safe["new_name"])
                        if redo_result.startswith("Error"):
                            raise RuntimeError(redo_result)
                        result = f"Redid rename: '{source}' Ã¢â€ â€™ '{destination}'"
                    else:
                        safe = self._validate_mutation("create_folder", {"path": source})
                        ownership = entry.get("folder_ownership")
                        if not ownership:
                            raise PermissionError(
                                "legacy folder creation has no ownership evidence; "
                                "refusing redo"
                            )
                        if any(os.path.lexists(item["path"]) for item in ownership):
                            raise FileExistsError(
                                "one or more owned folders already exist; refusing redo"
                            )
                        mutation_started = True
                        created = []
                        for item in sorted(ownership, key=lambda value: len(value["path"])):
                            os.mkdir(item["path"])
                            created.append(item["path"])
                        entry["folder_ownership"] = self._folder_ownership(created)
                        result = f"Redid create_folder: '{source}'"
                    entry["undone"] = False
                    self._complete_transition(entry, "redo")
                    return result
                except Exception as exc:
                    if mutation_started:
                        self._mark_transition_uncertain(entry, "redo")
                    else:
                        self._mark_transition_failed(entry, "redo")
                    return f"Redo failed: {exc}"
            return "No operations to redo."

    # ------------------------------------------------------------------
    # File Reading (supports .txt, .pdf, .docx, .xlsx)
    # ------------------------------------------------------------------

    def read_file_content(self, file_path: str) -> str:
        try:
            file_path = self._sandbox_path(file_path)
        except (OSError, TypeError, ValueError) as exc:
            return f"Error: {exc}"
        ext = os.path.splitext(file_path)[1].lower()
        try:
            if ext == ".txt":
                with open(file_path, "r", encoding="utf-8", errors="ignore") as f:
                    return truncate_file_preview(f.read(FILE_PREVIEW_LIMIT + 1))
            elif ext == ".pdf":
                if PyPDF2 is None:
                    return "PyPDF2 not installed. Install with: pip install PyPDF2"
                with open(file_path, "rb") as f:
                    reader = PyPDF2.PdfReader(f)
                    text = ""
                    for page in reader.pages[:3]:
                        text += page.extract_text() or ""
                    return truncate_file_preview(text)
            elif ext == ".docx":
                if docx is None:
                    return "python-docx not installed. Install with: pip install python-docx"
                doc = docx.Document(file_path)
                paragraphs = [p.text for p in doc.paragraphs if p.text.strip()]
                return truncate_file_preview("\n".join(paragraphs))
            elif ext == ".xlsx":
                if openpyxl is None:
                    return "openpyxl not installed. Install with: pip install openpyxl"
                wb = openpyxl.load_workbook(file_path, read_only=True, data_only=True)
                result = []
                for sheet_name in wb.sheetnames[:3]:
                    ws = wb[sheet_name]
                    result.append(f"--- Sheet: {sheet_name} ---")
                    for row in ws.iter_rows(min_row=1, max_row=10, values_only=True):
                        values = [str(v) for v in row if v is not None]
                        if values:
                            result.append(" | ".join(values))
                return truncate_file_preview("\n".join(result))
            else:
                return f"[Content extraction not supported for extension: {ext}]"
        except Exception as e:
            return f"Error reading file: {e}"

    # ------------------------------------------------------------------
    # Core run method with dry-run support
    # ------------------------------------------------------------------

    def _get_tool_definitions(self) -> List[Dict[str, Any]]:
        return [
            {
                "type": "function",
                "function": {
                    "name": "move_file",
                    "description": "Move a file from source to destination",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "source": {"type": "string", "description": "Source file path"},
                            "destination": {"type": "string", "description": "Destination file path"},
                        },
                        "required": ["source", "destination"],
                    },
                },
            },
            {
                "type": "function",
                "function": {
                    "name": "delete_file",
                    "description": "Delete a file (send to recycle bin)",
                    "parameters": {
                        "type": "object",
                        "properties": {"path": {"type": "string", "description": "File path to delete"}},
                        "required": ["path"],
                    },
                },
            },
            {
                "type": "function",
                "function": {
                    "name": "rename_file",
                    "description": "Rename a file within the same directory",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "old_path": {"type": "string", "description": "Current file path"},
                            "new_name": {"type": "string", "description": "New file name"},
                        },
                        "required": ["old_path", "new_name"],
                    },
                },
            },
            {
                "type": "function",
                "function": {
                    "name": "create_folder",
                    "description": "Create a new folder (and parent directories)",
                    "parameters": {
                        "type": "object",
                        "properties": {"path": {"type": "string", "description": "Folder path to create"}},
                        "required": ["path"],
                    },
                },
            },
            {
                "type": "function",
                "function": {
                    "name": "list_directory",
                    "description": "List all files and subdirectories (non-recursive)",
                    "parameters": {
                        "type": "object",
                        "properties": {"directory": {"type": "string", "description": "Directory to list"}},
                        "required": ["directory"],
                    },
                },
            },
            {
                "type": "function",
                "function": {
                    "name": "read_file_content",
                    "description": "Read content of a text, PDF, DOCX, or XLSX file",
                    "parameters": {
                        "type": "object",
                        "properties": {"file_path": {"type": "string", "description": "Path to the file to read"}},
                        "required": ["file_path"],
                    },
                },
            },
            {
                "type": "function",
                "function": {
                    "name": "get_file_info",
                    "description": "Get file size and modification time",
                    "parameters": {
                        "type": "object",
                        "properties": {"file_path": {"type": "string", "description": "Path to the file"}},
                        "required": ["file_path"],
                    },
                },
            },
        ]

    def run(
        self,
        task_description: str,
        dry_run: bool = True,
        confirm_callback: Optional[Callable[[str, dict], bool]] = None,
        plan_id_callback: Optional[Callable[[str], None]] = None,
        provider_callback: Optional[Callable[[dict], None]] = None,
    ) -> str:
        """Process a task and retain its dry-run plan for immutable approval.

        ``plan_id_callback`` receives the identifier only when this invocation
        still owns the current preview generation. ``provider_callback``
        receives request-local provider metadata under the same ownership
        rule. Callers can therefore keep both values local instead of reading
        shared state after the provider call returns.
        """
        # Each preview owns a generation. A newer preview or an explicit
        # discard invalidates the generation, so an older provider response
        # cannot publish an executable plan after it has been superseded.
        with self._plan_lock:
            self._plan_generation += 1
            plan_generation = self._plan_generation
            self._pending_plan = None
            self._pending_plan_id = None
        provider_info = None
        failovers = []
        messages = [
            {"role": "system", "content": self.system_prompt},
            {"role": "user", "content": task_description},
        ]

        tools = self._get_tool_definitions()

        try:
            response = self.api_manager.route_request(
                messages=messages,
                agent_name="Foldy",
                require_tools=True,
                tools=tools,
            )
            failovers.extend(response.get("_steward", {}).get("failovers", []))
            provider_info = response.get("_steward")
            assistant_msg = response["choices"][0]["message"]
            messages.append(assistant_msg)

            tool_calls = assistant_msg.get("tool_calls", [])
            if not tool_calls:
                if provider_info:
                    provider_info = {**provider_info, "failovers": failovers}
                    with self._plan_lock:
                        if plan_generation == self._plan_generation:
                            self.last_provider = provider_info
                            if provider_callback:
                                try:
                                    provider_callback(dict(provider_info))
                                except Exception as exc:
                                    logger.warning(
                                        "[FileAgent] provider callback failed: %s", exc
                                    )
                return assistant_msg.get("content", "No action needed.")

            parsed_plan = self._parse_tool_plan(tool_calls)
            results = self._execute_tool_plan(
                parsed_plan, dry_run=dry_run, confirm_callback=confirm_callback
            )

            for tool_call in tool_calls:
                messages.append({
                    "role": "tool",
                    "content": str(results),
                    "tool_call_id": tool_call.get("id", "unknown"),
                })

            try:
                final_response = self.api_manager.route_request(
                    messages=messages,
                    agent_name="Foldy",
                    require_tools=False,
                )
                failovers.extend(
                    (final_response.get("_steward") or {}).get("failovers", [])
                )
                final_provider_info = final_response.get("_steward")
                if final_provider_info:
                    provider_info = {
                        **final_provider_info,
                        "failovers": failovers,
                    }
                final_content = final_response["choices"][0]["message"].get("content", "")
            except Exception as e:
                logger.warning(f"Failed to get final LLM explanation: {e}")
                final_content = ""

            if dry_run:
                with self._plan_lock:
                    if plan_generation != self._plan_generation:
                        logger.info(
                            "[FileAgent] discarded stale preview generation %s",
                            plan_generation,
                        )
                    else:
                        self._pending_plan = copy.deepcopy(parsed_plan)
                        self._pending_plan_id = str(uuid.uuid4())
                        if provider_info:
                            self.last_provider = provider_info
                            if provider_callback:
                                try:
                                    provider_callback(dict(provider_info))
                                except Exception as exc:
                                    logger.warning(
                                        "[FileAgent] provider callback failed: %s", exc
                                    )
                        # Deliver the request-local ID while the generation lock
                        # is held so discard/supersede cannot interleave between
                        # publication and notification. Callback failures are
                        # observational and must not corrupt the preview.
                        if plan_id_callback:
                            try:
                                plan_id_callback(self._pending_plan_id)
                            except Exception as exc:
                                logger.warning(
                                    "[FileAgent] plan ID callback failed: %s", exc
                                )
                if final_content:
                    return "\n".join(results) + "\n\n" + final_content
            else:
                with self._plan_lock:
                    if plan_generation == self._plan_generation and provider_info:
                        self.last_provider = provider_info
                        if provider_callback:
                            try:
                                provider_callback(dict(provider_info))
                            except Exception as exc:
                                logger.warning(
                                    "[FileAgent] provider callback failed: %s", exc
                                )
            return final_content if final_content else "\n".join(results)

        except Exception as e:
            logger.error(f"FileAgent.run failed: {e}")
            return f"Error processing task: {e}"

    @staticmethod
    def _parse_tool_plan(tool_calls: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """Parse and detach tool calls so the approved plan cannot be mutated."""
        parsed_plan = []
        for tool_call in tool_calls:
            parsed_call = copy.deepcopy(tool_call)
            function = parsed_call.get("function")
            if not isinstance(function, dict) or not function.get("name"):
                raise ValueError("Tool call is missing a function name.")
            args = function.get("arguments", {})
            if isinstance(args, str):
                args = json.loads(args)
            if not isinstance(args, dict):
                raise ValueError("Tool call arguments must be a JSON object.")
            function["arguments"] = copy.deepcopy(args)
            parsed_plan.append(parsed_call)
        return parsed_plan
    def _preview_rejection(self, func_name: str, args: Dict[str, Any]) -> Optional[str]:
        """Report why a previewed tool call would be refused, without executing it."""
        approved = {t["function"]["name"] for t in self._get_tool_definitions()}
        if func_name not in approved:
            return f"Unapproved tool: {func_name}"
        try:
            self._validate_mutation(func_name, args)
        except (OSError, TypeError, ValueError) as exc:
            return str(exc)
        return None

    def _planned_destination(self, func_name: str, safe_args: Dict[str, Any]) -> Optional[str]:
        """Return the concrete file path affected by a planned mutation."""
        if func_name == "move_file":
            destination = safe_args["destination"]
            if os.path.isdir(destination):
                return os.path.join(destination, os.path.basename(safe_args["source"]))
            return destination
        if func_name == "rename_file":
            return os.path.join(
                os.path.dirname(safe_args["old_path"]), safe_args["new_name"]
            )
        return None

    def _preflight_tool_plan(self, tool_calls: List[Dict[str, Any]]) -> None:
        """Reject destination conflicts before the first operation mutates disk."""
        approved = {t["function"]["name"] for t in self._get_tool_definitions()}
        planned_destinations = {}
        planned_folders = {}
        produced_sources = set()

        def path_key(path):
            return os.path.normcase(os.path.abspath(path))

        def is_ancestor(parent, child):
            try:
                return os.path.commonpath((parent, child)) == parent
            except ValueError:
                return False

        for index, tool_call in enumerate(tool_calls):
            func_name = tool_call["function"]["name"]
            if func_name not in approved:
                raise ValueError(f"Unapproved tool: {func_name}")
            safe_args = self._validate_mutation(
                func_name, tool_call["function"]["arguments"]
            )

            if func_name == "create_folder":
                folder = safe_args["path"]
                key = path_key(folder)
                if key in planned_folders:
                    previous = planned_folders[key]
                    raise ValueError(
                        f"Plan conflict: operations {previous + 1} and {index + 1} "
                        f"both create '{folder}'."
                    )
                if key in planned_destinations:
                    previous = planned_destinations[key]
                    raise ValueError(
                        f"Plan conflict: operations {previous + 1} and {index + 1} "
                        f"target '{folder}' as both a file and a directory."
                    )
                if os.path.lexists(folder) and not os.path.isdir(folder):
                    raise ValueError(
                        f"Plan conflict: folder destination is an existing file: '{folder}'."
                    )
                for file_destination, previous in planned_destinations.items():
                    if is_ancestor(file_destination, key):
                        raise ValueError(
                            f"Plan conflict: operation {previous + 1} targets file "
                            f"'{file_destination}', which cannot contain directory "
                            f"'{folder}'."
                        )
                planned_folders[key] = index
                continue

            destination = self._planned_destination(func_name, safe_args)
            if destination is None:
                continue
            key = path_key(destination)
            if key in planned_destinations:
                previous = planned_destinations[key]
                raise ValueError(
                    f"Plan conflict: operations {previous + 1} and {index + 1} "
                    f"both target '{destination}'."
                )
            if key in planned_folders:
                previous = planned_folders[key]
                raise ValueError(
                    f"Plan conflict: operations {previous + 1} and {index + 1} "
                    f"target '{destination}' as both a file and a directory."
                )
            for folder_key, previous in planned_folders.items():
                if is_ancestor(key, folder_key):
                    raise ValueError(
                        f"Plan conflict: operation {index + 1} targets file "
                        f"'{destination}', which cannot contain directory "
                        f"'{folder_key}'."
                    )
            if os.path.lexists(destination):
                raise ValueError(
                    f"Plan conflict: destination already exists: '{destination}'."
                )
            planned_destinations[key] = index
            source = safe_args.get("source") or safe_args.get("old_path")
            if source:
                source_key = path_key(source)
                if source_key in produced_sources:
                    raise ValueError(
                        "Plan conflict: a later operation depends on the output of "
                        "an earlier operation."
                    )
                produced_sources.add(source_key)
            produced_sources.add(key)
    def _execute_tool_plan(
        self,
        tool_calls: List[Dict[str, Any]],
        dry_run: bool,
        confirm_callback: Optional[Callable[[str, dict], bool]] = None,
    ) -> List[str]:
        if not dry_run:
            # Declared schema (from _get_tool_definitions) is the approved dispatch set.
            # Undeclared tools (cleanup_temp_files, batch_move, find_duplicates,
            # cleanup_empty_folders, find_large_files, suggest_deletions) are rejected.
            approved = {t["function"]["name"] for t in self._get_tool_definitions()}
            # Reject the whole plan before the first mutation if any path is unsafe
            # or any tool is not in the declared schema.
            try:
                for tool_call in tool_calls:
                    func_name = tool_call["function"]["name"]
                    if func_name not in approved:
                        raise ValueError(f"Unapproved tool: {func_name}")
                    self._validate_mutation(
                        func_name,
                        tool_call["function"]["arguments"],
                    )
                self._preflight_tool_plan(tool_calls)
            except (OSError, TypeError, ValueError) as exc:
                return [f"Error: {exc}"]

        results = []
        for tool_call in tool_calls:
            function = tool_call["function"]
            func_name = function["name"]
            args = function["arguments"]
            logger.info(
                "[FileAgent] Tool: %s(%s) [dry_run=%s]",
                func_name,
                json.dumps(args),
                dry_run,
            )
            preview = f"[Dry Run] {func_name}({json.dumps(args, indent=2)})"
            results.append(preview)
            logger.info(preview)

            if dry_run:
                rejection = self._preview_rejection(func_name, args)
                if rejection:
                    results.append(f"  Ã¢â€ â€™ (preview only) WILL BE REJECTED: {rejection}")
                else:
                    results.append("  Ã¢â€ â€™ (preview only, not executed)")
                continue

            if confirm_callback and not confirm_callback(func_name, args):
                results.append("  Ã¢â€ â€™ (cancelled by user)")
                continue

            if func_name not in _legacy_tool_functions:
                results.append(f"  Ã¢â€ â€™ Unknown tool: {func_name}")
                continue

            try:
                # Re-resolve immediately before mutation as well as during preflight.
                safe_args = self._validate_mutation(func_name, args)
                if self._mutation_hook is not None:
                    self._mutation_hook(func_name, safe_args)
                if func_name == "move_file":
                    result = self._execute_mutation(
                        func_name, safe_args, "move",
                        safe_args["source"], safe_args["destination"],
                    )
                elif func_name == "rename_file":
                    result = self._execute_mutation(
                        func_name, safe_args, "rename",
                        safe_args["old_path"], safe_args["new_name"],
                    )
                elif func_name == "delete_file":
                    result = self._execute_mutation(
                        func_name, safe_args, "delete", safe_args["path"], None,
                    )
                elif func_name == "create_folder":
                    result = self._execute_mutation(
                        func_name, safe_args, "create_folder", safe_args["path"], None,
                    )
                else:
                    result = _legacy_tool_functions[func_name](**safe_args)
                results.append(f"  Ã¢â€ â€™ {result}")
            except Exception as e:
                results.append(f"  Ã¢â€ â€™ Error: {e}")

        return results

    def get_pending_plan_id(self) -> Optional[str]:
        """Return the current preview identifier without exposing mutable state."""
        with self._plan_lock:
            return self._pending_plan_id

    def execute_pending_plan(self, plan_id: str) -> str:
        """Execute the exact previewed tool calls without consulting the LLM.

        ``plan_id`` is mandatory and must match the current pending plan. Every
        refusal (missing, stale, superseded, or already executed) raises
        ``RuntimeError``; successful execution returns the joined result string.
        """
        with self._plan_lock:
            if self._pending_plan is None:
                raise RuntimeError("No previewed execution plan is awaiting confirmation.")
            if plan_id is None or self._pending_plan_id is None:
                raise RuntimeError("A valid preview plan ID is required for execution.")
            if plan_id != self._pending_plan_id:
                raise RuntimeError(f"Plan {plan_id} is stale or superseded.")
            plan = self._pending_plan
            self._pending_plan = None
            self._pending_plan_id = None

        results = self._execute_tool_plan(
            copy.deepcopy(plan), dry_run=False, confirm_callback=None
        )
        return "\n".join(results)

    def discard_pending_plan(self) -> None:
        """Invalidate a preview and any in-flight older preview publication."""
        with self._plan_lock:
            self._plan_generation += 1
            self._pending_plan = None
            self._pending_plan_id = None

    # ------------------------------------------------------------------
    # Convenience methods (direct tool access)
    # ------------------------------------------------------------------

    def move_file(self, source: str, destination: str) -> str:
        try:
            safe_args = self._validate_mutation(
                "move_file", {"source": source, "destination": destination}
            )
        except (OSError, TypeError, ValueError) as exc:
            return f"Error: {exc}"
        return self._execute_mutation(
            "move_file", safe_args, "move",
            safe_args["source"], safe_args["destination"], callback=_move_file,
        )

    def delete_file(self, path: str) -> str:
        try:
            safe_args = self._validate_mutation("delete_file", {"path": path})
        except (OSError, TypeError, ValueError) as exc:
            return f"Error: {exc}"
        return self._execute_mutation(
            "delete_file", safe_args, "delete", safe_args["path"], None,
            callback=_delete_file,
        )

    def rename_file(self, old_path: str, new_name: str) -> str:
        try:
            safe_args = self._validate_mutation(
                "rename_file", {"old_path": old_path, "new_name": new_name}
            )
        except (OSError, TypeError, ValueError) as exc:
            return f"Error: {exc}"
        return self._execute_mutation(
            "rename_file", safe_args, "rename",
            safe_args["old_path"], safe_args["new_name"], callback=_rename_file,
        )

    def create_folder(self, path: str) -> str:
        try:
            safe_args = self._validate_mutation("create_folder", {"path": path})
        except (OSError, TypeError, ValueError) as exc:
            return f"Error: {exc}"
        return self._execute_mutation(
            "create_folder", safe_args, "create_folder", safe_args["path"], None,
            callback=_create_folder,
        )

    def list_directory(self, directory: str) -> str:
        try:
            safe_path = self._sandbox_path(directory)
        except (OSError, TypeError, ValueError) as exc:
            return f"Error: {exc}"
        return _list_directory(safe_path)

    def get_file_info(self, file_path: str) -> str:
        try:
            safe_path = self._sandbox_path(file_path)
        except (OSError, TypeError, ValueError) as exc:
            return f"Error: {exc}"
        return _get_file_info(safe_path)

    def categorise_file(self, filepath: str, dest_base: str, root_window=None, dry_run=None) -> str:
        """Categorize a sandboxed file, honoring the per-call dry-run override."""
        try:
            filepath = self._sandbox_path(filepath)
        except (OSError, TypeError, ValueError) as exc:
            return f"Error: {exc}"
        try:
            dest_base = self._sandbox_path(dest_base)
        except (OSError, TypeError, ValueError) as exc:
            return f"Error: {exc}"
        if not os.path.exists(filepath):
            return f"File not found: {filepath}"

        from utils.rules_engine import RulesEngine

        self.last_categorized_by_rule = False
        self.last_rule_pattern = None
        rules_engine = RulesEngine(self.rules_path)
        category = rules_engine.match_rule(os.path.basename(filepath))
        matched_rule = rules_engine.last_matched_rule
        used_rule = category is not None

        if used_rule:
            category = sanitize_category(category, filepath)
            pattern = matched_rule.get("pattern", "") if matched_rule else ""
            self.last_categorized_by_rule = True
            self.last_rule_pattern = pattern
            logger.info("Categorized by rule: [%s]", pattern)
        else:
            content = self.read_file_content(filepath)
            messages = [
                {"role": "system", "content": self.system_prompt},
                {
                    "role": "user",
                    "content": f"Categorise this file: {filepath}\nContent preview: {content[:500]}\nReply with ONLY a single short folder name, no explanation.",
                },
            ]
            try:
                response = self.api_manager.route_request(
                    messages=messages, agent_name="Foldy"
                )
                self.last_provider = response.get("_steward")
                category = sanitize_category(
                    response["choices"][0]["message"]["content"], filepath
                )
            except Exception as exc:
                logger.exception("Could not categorise '%s': %s", filepath, exc)
                return f"Error categorising file: {exc}"

        dest_folder = os.path.join(dest_base, category)
        dest_path = os.path.join(dest_folder, os.path.basename(filepath))
        effective_dry_run = self.dry_run if dry_run is None else dry_run
        if effective_dry_run:
            marker = "[Rule] " if used_rule else ""
            return f"{marker}[Dry Run] Would categorise '{filepath}' as '{category}' Ã¢â€ â€™ move to '{dest_path}'"
        self.create_folder(dest_folder)
        result = self.move_file(filepath, dest_path)
        if used_rule and not result.startswith("Error"):
            return f"[Rule] {result}"
        return result

    def learn_override(
        self,
        filename: str,
        suggested_category: str,
        actual_category: str,
    ) -> str:
        """Learn a deterministic filename rule from a user correction."""
        if not isinstance(filename, str) or not filename.strip():
            raise ValueError("A filename is required to learn a rule")
        if not isinstance(actual_category, str) or not actual_category.strip():
            raise ValueError("An actual category is required to learn a rule")

        from utils.rules_engine import RulesEngine

        stem = os.path.splitext(os.path.basename(filename))[0]
        tokens = [
            token for token in re.split(r"[^A-Za-z0-9]+", stem)
            if token and not token.isdigit()
        ]
        if not tokens:
            raise ValueError("Filename does not contain a learnable pattern")
        keyword = max(tokens, key=len)
        pattern = f".*{re.escape(keyword)}.*"

        rules_engine = RulesEngine(self.rules_path)
        rules_engine.add_rule(pattern, actual_category)
        logger.info(
            "Learned rule from override: pattern=[%s] suggested=[%s] actual=[%s]",
            pattern,
            suggested_category,
            actual_category,
        )
        return pattern
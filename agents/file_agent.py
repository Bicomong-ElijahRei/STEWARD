"""
FileAgent - Handles all file operations for STEWARD.

Consolidates logic from steward_agent.py and steward_gui.py into a single class.
Provides run(task_description, dry_run=True) method for preview-then-execute workflow.
Includes full undo/redo support via JSON operation log.
"""

import os
import shutil
import json
import logging
import threading
import copy
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


class FileAgent:
    OPERATION_LOG_PATH = os.path.join(os.getcwd(), "steward_operations.json")

    def __init__(
        self,
        api_manager: APIManager,
        root_path: Optional[str] = None,
        dry_run: bool = True,
    ):
        self.root_path = os.path.realpath(os.path.abspath(root_path or os.getcwd()))
        self.allowed_roots = tuple(
            os.path.realpath(os.path.join(self.root_path, folder))
            for folder in ("Incoming", "Sorted")
        )
        self.api_manager = api_manager
        self.dry_run = dry_run
        self._lock = threading.Lock()
        self._plan_lock = threading.Lock()
        self._pending_plan = None
        self.last_provider = None
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
- undo_last(): Undo the most recent file operation
- redo_last(): Redo the most recent undone operation

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
            self._sandbox_path(os.path.join(os.path.dirname(old_path), args.get("new_name")))
            safe_args["old_path"] = old_path
        elif func_name in ("delete_file", "create_folder"):
            safe_args["path"] = self._sandbox_path(args.get("path"))
        elif func_name in ("cleanup_empty_folders", "cleanup_temp_files"):
            safe_args["directory"] = self._sandbox_path(args.get("directory"))
        elif func_name == "batch_move":
            safe_args["source_pattern"] = self._sandbox_path(args.get("source_pattern"))
            safe_args["destination_folder"] = self._sandbox_path(args.get("destination_folder"))
        return safe_args

    def _load_operation_log(self) -> List[Dict[str, Any]]:
        if os.path.exists(self.OPERATION_LOG_PATH):
            try:
                with open(self.OPERATION_LOG_PATH, "r", encoding="utf-8") as f:
                    return json.load(f)
            except (json.JSONDecodeError, IOError) as e:
                logger.warning(f"Could not load operation log: {e}")
        return []

    def _save_operation_log(self):
        try:
            with open(self.OPERATION_LOG_PATH, "w", encoding="utf-8") as f:
                json.dump(self._operation_log, f, indent=2, default=str)
        except IOError as e:
            logger.error(f"Could not save operation log: {e}")

    def _record_operation(
        self,
        operation: str,
        source: str,
        destination: Optional[str] = None,
        result: str = "",
        success: bool = True,
    ):
        entry = {
            "id": datetime.now().isoformat(),
            "timestamp": datetime.now().isoformat(),
            "operation": operation,
            "source": source,
            "destination": destination,
            "result": result,
            "success": success,
            "undone": False,
        }
        with self._lock:
            self._operation_log.append(entry)
            self._save_operation_log()

    def undo_last(self) -> str:
        with self._lock:
            for entry in reversed(self._operation_log):
                if not entry.get("undone", False) and entry.get("success", False):
                    operation = entry["operation"]
                    source = entry["source"]
                    destination = entry.get("destination")
                    try:
                        if operation == "move" and destination:
                            safe_args = self._validate_mutation(
                                "move_file", {"source": source, "destination": destination}
                            )
                            shutil.move(safe_args["destination"], safe_args["source"])
                            result = f"Undid move: '{destination}' → '{source}'"
                        elif operation == "rename" and destination:
                            safe_args = self._validate_mutation(
                                "rename_file", {"old_path": source, "new_name": destination}
                            )
                            new_path = os.path.join(
                                os.path.dirname(safe_args["old_path"]), safe_args["new_name"]
                            )
                            os.rename(new_path, safe_args["old_path"])
                            result = f"Undid rename: '{destination}' → '{os.path.basename(source)}'"
                        elif operation == "delete":
                            result = "Cannot undo delete (sent to recycle bin)"
                        elif operation == "create_folder":
                            safe_args = self._validate_mutation(
                                "create_folder", {"path": source}
                            )
                            source = safe_args["path"]
                            if os.path.exists(source) and os.path.isdir(source):
                                try:
                                    os.rmdir(source)
                                    result = f"Undid create_folder: removed '{source}'"
                                except OSError:
                                    result = f"Could not remove '{source}' (not empty)"
                            else:
                                result = f"Folder '{source}' no longer exists"
                        else:
                            result = f"Unknown operation type: {operation}"
                        entry["undone"] = True
                        self._save_operation_log()
                        return result
                    except Exception as e:
                        return f"Undo failed: {e}"
            return "No operations to undo."

    def redo_last(self) -> str:
        with self._lock:
            for entry in self._operation_log:
                if entry.get("undone", False):
                    operation = entry["operation"]
                    source = entry["source"]
                    destination = entry.get("destination")
                    try:
                        if operation == "move" and destination:
                            safe_args = self._validate_mutation(
                                "move_file", {"source": source, "destination": destination}
                            )
                            shutil.move(safe_args["source"], safe_args["destination"])
                            result = f"Redid move: '{source}' → '{destination}'"
                        elif operation == "rename" and destination:
                            safe_args = self._validate_mutation(
                                "rename_file", {"old_path": source, "new_name": destination}
                            )
                            new_path = os.path.join(
                                os.path.dirname(safe_args["old_path"]), safe_args["new_name"]
                            )
                            os.rename(safe_args["old_path"], new_path)
                            result = f"Redid rename: '{source}' → '{destination}'"
                        elif operation == "create_folder":
                            safe_args = self._validate_mutation(
                                "create_folder", {"path": source}
                            )
                            os.makedirs(safe_args["path"], exist_ok=True)
                            result = f"Redid create_folder: '{source}'"
                        else:
                            result = f"Unknown operation type: {operation}"
                        entry["undone"] = False
                        self._save_operation_log()
                        return result
                    except Exception as e:
                        return f"Redo failed: {e}"
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
                    return f.read(2000)
            elif ext == ".pdf":
                if PyPDF2 is None:
                    return "PyPDF2 not installed. Install with: pip install PyPDF2"
                with open(file_path, "rb") as f:
                    reader = PyPDF2.PdfReader(f)
                    text = ""
                    for page in reader.pages[:3]:
                        text += page.extract_text() or ""
                    return text[:2000]
            elif ext == ".docx":
                if docx is None:
                    return "python-docx not installed. Install with: pip install python-docx"
                doc = docx.Document(file_path)
                paragraphs = [p.text for p in doc.paragraphs if p.text.strip()]
                return "\n".join(paragraphs)[:2000]
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
                return "\n".join(result)[:2000]
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
            {
                "type": "function",
                "function": {
                    "name": "undo_last",
                    "description": "Undo the most recent file operation",
                    "parameters": {"type": "object", "properties": {}, "required": []},
                },
            },
            {
                "type": "function",
                "function": {
                    "name": "redo_last",
                    "description": "Redo the most recent undone operation",
                    "parameters": {"type": "object", "properties": {}, "required": []},
                },
            },
        ]

    def run(
        self,
        task_description: str,
        dry_run: bool = True,
        confirm_callback: Optional[Callable[[str, dict], bool]] = None,
    ) -> str:
        """Process a task and retain its dry-run plan for immutable approval."""
        self.discard_pending_plan()
        self.last_provider = None
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
            self.last_provider = response.get("_steward")
            assistant_msg = response["choices"][0]["message"]
            messages.append(assistant_msg)

            tool_calls = assistant_msg.get("tool_calls", [])
            if not tool_calls:
                if self.last_provider:
                    self.last_provider = {**self.last_provider, "failovers": failovers}
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
                provider_info = final_response.get("_steward")
                if provider_info:
                    self.last_provider = {**provider_info, "failovers": failovers}
                final_content = final_response["choices"][0]["message"].get("content", "")
            except Exception as e:
                logger.warning(f"Failed to get final LLM explanation: {e}")
                final_content = ""

            if dry_run:
                with self._plan_lock:
                    self._pending_plan = copy.deepcopy(parsed_plan)
                if final_content:
                    return "\n".join(results) + "\n\n" + final_content
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

    def _execute_tool_plan(
        self,
        tool_calls: List[Dict[str, Any]],
        dry_run: bool,
        confirm_callback: Optional[Callable[[str, dict], bool]] = None,
    ) -> List[str]:
        if not dry_run:
            # Reject the whole plan before the first mutation if any path is unsafe.
            try:
                for tool_call in tool_calls:
                    self._validate_mutation(
                        tool_call["function"]["name"],
                        tool_call["function"]["arguments"],
                    )
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
                results.append("  → (preview only, not executed)")
                continue

            if confirm_callback and not confirm_callback(func_name, args):
                results.append("  → (cancelled by user)")
                continue

            if func_name not in _legacy_tool_functions:
                results.append(f"  → Unknown tool: {func_name}")
                continue

            try:
                # Re-resolve immediately before mutation as well as during preflight.
                safe_args = self._validate_mutation(func_name, args)
                result = _legacy_tool_functions[func_name](**safe_args)
                results.append(f"  → {result}")
                if result.startswith("Error"):
                    continue
                if func_name == "move_file":
                    self._record_operation(
                        "move", safe_args["source"], safe_args["destination"], result,
                    )
                elif func_name == "rename_file":
                    self._record_operation(
                        "rename", safe_args["old_path"], safe_args["new_name"], result,
                    )
                elif func_name == "delete_file":
                    self._record_operation("delete", safe_args["path"], None, result)
                elif func_name == "create_folder":
                    self._record_operation(
                        "create_folder", safe_args["path"], None, result,
                    )
            except Exception as e:
                results.append(f"  → Error: {e}")

        return results

    def execute_pending_plan(self) -> str:
        """Execute the exact previewed tool calls without consulting the LLM."""
        with self._plan_lock:
            if self._pending_plan is None:
                raise RuntimeError("No previewed execution plan is awaiting confirmation.")
            plan = self._pending_plan
            self._pending_plan = None

        results = self._execute_tool_plan(
            copy.deepcopy(plan), dry_run=False, confirm_callback=None
        )
        return "\n".join(results)

    def discard_pending_plan(self) -> None:
        """Invalidate a preview when it is declined or superseded."""
        with self._plan_lock:
            self._pending_plan = None

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
        result = _move_file(**safe_args)
        if not result.startswith("Error"):
            self._record_operation(
                "move", safe_args["source"], safe_args["destination"], result
            )
        return result

    def delete_file(self, path: str) -> str:
        try:
            safe_args = self._validate_mutation("delete_file", {"path": path})
        except (OSError, TypeError, ValueError) as exc:
            return f"Error: {exc}"
        result = _delete_file(**safe_args)
        if not result.startswith("Error"):
            self._record_operation("delete", safe_args["path"], None, result)
        return result

    def rename_file(self, old_path: str, new_name: str) -> str:
        try:
            safe_args = self._validate_mutation(
                "rename_file", {"old_path": old_path, "new_name": new_name}
            )
        except (OSError, TypeError, ValueError) as exc:
            return f"Error: {exc}"
        result = _rename_file(**safe_args)
        if not result.startswith("Error"):
            self._record_operation(
                "rename", safe_args["old_path"], safe_args["new_name"], result
            )
        return result

    def create_folder(self, path: str) -> str:
        try:
            safe_args = self._validate_mutation("create_folder", {"path": path})
        except (OSError, TypeError, ValueError) as exc:
            return f"Error: {exc}"
        result = _create_folder(**safe_args)
        if not result.startswith("Error"):
            self._record_operation("create_folder", safe_args["path"], None, result)
        return result

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

    def categorise_file(self, filepath: str, dest_base: str, root_window=None) -> str:
        try:
            filepath = self._sandbox_path(filepath)
        except (OSError, TypeError, ValueError) as exc:
            return f"Error: {exc}"
        if not os.path.exists(filepath):
            return f"File not found: {filepath}"

        content = self.read_file_content(filepath)

        messages = [
            {"role": "system", "content": self.system_prompt},
            {
                "role": "user",
                "content": f"Categorise this file: {filepath}\nContent preview: {content[:500]}\nSuggest a category folder name.",
            },
        ]

        try:
            response = self.api_manager.route_request(
                messages=messages, agent_name="Foldy"
            )
            self.last_provider = response.get("_steward")
            category = response["choices"][0]["message"]["content"].strip()
        except Exception as e:
            category = "Other"

        category = category.strip().replace("/", "_").replace("\\", "_")
        dest_folder = os.path.join(dest_base, category)
        dest_path = os.path.join(dest_folder, os.path.basename(filepath))

        if self.dry_run:
            return f"[Dry Run] Would categorise '{filepath}' as '{category}' → move to '{dest_path}'"

        self.create_folder(dest_folder)
        return self.move_file(filepath, dest_path)

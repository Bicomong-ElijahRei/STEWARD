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
        self.root_path = root_path or os.getcwd()
        self.api_manager = api_manager
        self.dry_run = dry_run
        self._lock = threading.Lock()
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

Never create folders outside {{root_path}}\\Sorted unless the user gives an absolute path.
""".format(root_path=self.root_path)

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
                            shutil.move(destination, source)
                            result = f"Undid move: '{destination}' → '{source}'"
                        elif operation == "rename" and destination:
                            new_path = os.path.join(os.path.dirname(source), destination)
                            os.rename(new_path, source)
                            result = f"Undid rename: '{destination}' → '{os.path.basename(source)}'"
                        elif operation == "delete":
                            result = "Cannot undo delete (sent to recycle bin)"
                        elif operation == "create_folder":
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
            for entry in reversed(self._operation_log):
                if entry.get("undone", False):
                    operation = entry["operation"]
                    source = entry["source"]
                    destination = entry.get("destination")
                    try:
                        if operation == "move" and destination:
                            shutil.move(source, destination)
                            result = f"Redid move: '{source}' → '{destination}'"
                        elif operation == "rename" and destination:
                            new_path = os.path.join(os.path.dirname(source), destination)
                            os.rename(source, new_path)
                            result = f"Redid rename: '{source}' → '{destination}'"
                        elif operation == "create_folder":
                            os.makedirs(source, exist_ok=True)
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
        file_path = os.path.normpath(file_path)
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
        messages = [
            {"role": "system", "content": self.system_prompt},
            {"role": "user", "content": task_description},
        ]

        tools = self._get_tool_definitions()

        try:
            response = self.api_manager.route_request(
                messages=messages,
                agent_name="FileAgent",
                require_tools=True,
                tools=tools,
            )
            assistant_msg = response["choices"][0]["message"]
            messages.append(assistant_msg)

            tool_calls = assistant_msg.get("tool_calls", [])

            if not tool_calls:
                return assistant_msg.get("content", "No action needed.")

            results = []
            for tool_call in tool_calls:
                func_name = tool_call["function"]["name"]
                args = tool_call["function"]["arguments"]
                if isinstance(args, str):
                    args = json.loads(args)

                preview = f"[Dry Run] {func_name}({json.dumps(args, indent=2)})"
                results.append(preview)
                logger.info(preview)

                if dry_run:
                    results.append("  → (preview only, not executed)")
                    continue

                if confirm_callback and not confirm_callback(func_name, args):
                    results.append("  → (cancelled by user)")
                    continue

                if func_name in _legacy_tool_functions:
                    try:
                        result = _legacy_tool_functions[func_name](**args)
                        results.append(f"  → {result}")

                        if func_name == "move_file":
                            self._record_operation(
                                "move", args.get("source", ""), args.get("destination", ""), result
                            )
                        elif func_name == "rename_file":
                            self._record_operation(
                                "rename", args.get("old_path", ""), args.get("new_name", ""), result
                            )
                        elif func_name == "delete_file":
                            self._record_operation("delete", args.get("path", ""), None, result)
                        elif func_name == "create_folder":
                            self._record_operation("create_folder", args.get("path", ""), None, result)

                    except Exception as e:
                        results.append(f"  → Error: {e}")
                else:
                    results.append(f"  → Unknown tool: {func_name}")

            if results:
                tool_results = []
                for tool_call in tool_calls:
                    tool_results.append(
                        {
                            "role": "tool",
                            "content": str(results),
                            "tool_call_id": tool_call.get("id", "unknown"),
                        }
                    )
                messages.extend(tool_results)

                final_response = self.api_manager.route_request(
                    messages=messages,
                    agent_name="FileAgent",
                    require_tools=True,
                )
                final_content = final_response["choices"][0]["message"]["content"]
                return final_content

            return "\n".join(results)

        except Exception as e:
            logger.error(f"FileAgent.run failed: {e}")
            return f"Error processing task: {e}"

    # ------------------------------------------------------------------
    # Convenience methods (direct tool access)
    # ------------------------------------------------------------------

    def move_file(self, source: str, destination: str) -> str:
        result = _move_file(source, destination)
        if not result.startswith("Error"):
            self._record_operation("move", source, destination, result)
        return result

    def delete_file(self, path: str) -> str:
        result = _delete_file(path)
        if not result.startswith("Error"):
            self._record_operation("delete", path, None, result)
        return result

    def rename_file(self, old_path: str, new_name: str) -> str:
        result = _rename_file(old_path, new_name)
        if not result.startswith("Error"):
            self._record_operation("rename", old_path, new_name, result)
        return result

    def create_folder(self, path: str) -> str:
        result = _create_folder(path)
        if not result.startswith("Error"):
            self._record_operation("create_folder", path, None, result)
        return result

    def list_directory(self, directory: str) -> str:
        return _list_directory(directory)

    def get_file_info(self, file_path: str) -> str:
        return _get_file_info(file_path)

    def categorise_file(self, filepath: str, dest_base: str, root_window=None) -> str:
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
                messages=messages, agent_name="FileAgent"
            )
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
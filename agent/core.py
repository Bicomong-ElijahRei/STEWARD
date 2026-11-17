import os
import json
import logging
from typing import Optional, Callable, Dict, Any, List

from agent.tools import tool_functions
from utils.helpers import read_file_content_simple
from core.litellm_client import LiteLLMClient

logger = logging.getLogger(__name__)


class StewardAgent:
    def __init__(self, model: str = "qwen2.5:7b", root_path: Optional[str] = None):
        self.model = model
        self.root_path = root_path or os.getcwd()
        self.llm_client = LiteLLMClient()
        self.tool_functions = tool_functions
        self.messages: List[Dict[str, Any]] = []

        system_prompt = f"""You are STEWARD, an AI file manager for: {self.root_path}

WORKSPACE:
- Incoming: {self.root_path}\\Incoming
- Sorted:   {self.root_path}\\Sorted

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

Never create folders outside {self.root_path}\\Sorted unless the user gives an absolute path.
"""
        self.messages.append({"role": "system", "content": system_prompt})
    def _get_tools(self) -> List[Dict[str, Any]]:
        return [
            {
                "type": "function",
                "function": {
                    "name": "move_file",
                    "description": "Move a file from source to destination",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "source": {"type": "string"},
                            "destination": {"type": "string"},
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
                        "properties": {"path": {"type": "string"}},
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
                            "old_path": {"type": "string"},
                            "new_name": {"type": "string"},
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
                        "properties": {"path": {"type": "string"}},
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
                        "properties": {"directory": {"type": "string"}},
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
                        "properties": {"file_path": {"type": "string"}},
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
                        "properties": {"file_path": {"type": "string"}},
                        "required": ["file_path"],
                    },
                },
            },
            {
                "type": "function",
                "function": {
                    "name": "find_duplicates",
                    "description": "Find duplicate files in a directory using SHA-256 hash",
                    "parameters": {
                        "type": "object",
                        "properties": {"directory": {"type": "string"}},
                        "required": ["directory"],
                    },
                },
            },
            {
                "type": "function",
                "function": {
                    "name": "cleanup_empty_folders",
                    "description": "Remove empty folders recursively under a directory",
                    "parameters": {
                        "type": "object",
                        "properties": {"directory": {"type": "string"}},
                        "required": ["directory"],
                    },
                },
            },
            {
                "type": "function",
                "function": {
                    "name": "cleanup_temp_files",
                    "description": "Delete temporary files under a directory",
                    "parameters": {
                        "type": "object",
                        "properties": {"directory": {"type": "string"}},
                        "required": ["directory"],
                    },
                },
            },
            {
                "type": "function",
                "function": {
                    "name": "find_large_files",
                    "description": "Find files larger than a threshold (MB)",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "directory": {"type": "string"},
                            "size_mb": {"type": "number"},
                        },
                        "required": ["directory"],
                    },
                },
            },
            {
                "type": "function",
                "function": {
                    "name": "batch_move",
                    "description": "Move multiple files matching a pattern to a destination folder",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "source_pattern": {"type": "string"},
                            "destination_folder": {"type": "string"},
                        },
                        "required": ["source_pattern", "destination_folder"],
                    },
                },
            },
            {
                "type": "function",
                "function": {
                    "name": "suggest_deletions",
                    "description": "Suggest files for deletion based on size, age, and duplicates",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "directory": {"type": "string"},
                            "size_mb_threshold": {"type": "number"},
                            "age_days_threshold": {"type": "number"},
                            "use_ai": {"type": "boolean"},
                        },
                        "required": ["directory"],
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
    def send_message(self, user_input: str, confirm_callback: Callable[[str, dict], bool]) -> str:
        """Send a message to the agent and get a response."""
        self.messages.append({"role": "user", "content": user_input})

        tools = self._get_tools()

        try:
            response = self.llm_client.complete(
                messages=self.messages,
                tools=tools,
                temperature=0.3,
            )
        except Exception as e:
            logger.error(f"LLM error: {e}")
            return f"LLM error: {e}"

        assistant_msg = response["choices"][0]["message"]
        self.messages.append(assistant_msg)

        tool_calls = assistant_msg.get("tool_calls", [])

        if not tool_calls:
            reply = assistant_msg.get("content", "")
            logger.info(f"[Agent] No tool calls, reply: {reply}")
            return reply

        for tool_call in tool_calls:
            func_name = tool_call["function"]["name"]
            args = tool_call["function"]["arguments"]
            if isinstance(args, str):
                args = json.loads(args)

            try:
                confirmed = confirm_callback(func_name, args)
            except Exception as e:
                logger.error(f"Confirmation failed: {e}")
                confirmed = False

            if not confirmed:
                result = f"User cancelled the operation '{func_name}'."
            else:
                if func_name in self.tool_functions:
                    logger.info(f"[DEBUG] Executing {func_name} with args {args}")
                    result = self.tool_functions[func_name](**args)
                else:
                    result = f"Unknown tool '{func_name}'"

            self.messages.append({
                "role": "tool",
                "content": result,
                "tool_call_id": tool_call.get("id", "unknown"),
            })

        try:
            final = self.llm_client.complete(
                messages=self.messages,
                temperature=0.3,
            )
            final_content = final["choices"][0]["message"]["content"]
            self.messages.append(final["choices"][0]["message"])
            return final_content
        except Exception as e:
            logger.error(f"Final LLM call failed: {e}")
            return f"Error generating response: {e}"

    def categorise_file(self, filepath: str, dest_base: str, root_window=None) -> str:
        """Categorise a single file (legacy method for GUI compatibility)."""
        if not os.path.exists(filepath):
            return f"File not found: {filepath}"

        from agent.tools import read_file_content
        content = read_file_content(filepath)

        messages = [
            {"role": "system", "content": self.messages[0]["content"]},
            {
                "role": "user",
                "content": f"Categorise this file: {filepath}\nContent preview: {content[:500]}\nSuggest a category folder name.",
            },
        ]

        try:
            response = self.llm_client.complete(messages=messages, temperature=0.3)
            category = response["choices"][0]["message"]["content"].strip()
        except Exception as e:
            category = "Other"

        category = category.strip().replace("/", "_").replace("\\", "_")
        dest_folder = os.path.join(dest_base, category)
        dest_path = os.path.join(dest_folder, os.path.basename(filepath))

        from agent.tools import move_file, create_folder
        create_folder(dest_folder)
        return move_file(filepath, dest_path)

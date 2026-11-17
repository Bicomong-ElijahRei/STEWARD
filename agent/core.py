import os
import json
import re
import time
import shutil
import ollama
from threading import Event
from tkinter import messagebox
from agent.tools import tool_functions
from utils.helpers import read_file_content_simple

class StewardAgent:
    def __init__(self, model="qwen2.5:7b", root_path=None):
        self.model = model
        self.root_path = root_path or os.getcwd()
        self.messages = []
        self.tools = self._get_tools()
        self.tool_functions = tool_functions
        self.ollama_options = {"num_ctx": 32768}

        # ----- STRICTER SYSTEM PROMPT (forces batch move) -----
        system_prompt = f"""
You are STEWARD, an AI file manager.

**CRITICAL RULE:** When the user gives a command containing "batch move" or "move all files" with a pattern (e.g., "*.pdf"), you MUST call the `batch_move` tool immediately. Do not ask questions, do not explain – just output the tool call.

Example user: batch move "*.pdf" to "Sorted/PDFs"
Your response: <tool_call>{{"name": "batch_move", "arguments": {{"source_pattern": "*.pdf", "destination_folder": "{self.root_path}\\Sorted\\PDFs"}}}}</tool_call>

**Argument names:**
- `batch_move` uses `source_pattern` and `destination_folder`.
- `create_folder` uses `path` (not `folder_name` or `folder_path`).

Your workspace: Incoming = {self.root_path}\\Incoming, Sorted = {self.root_path}\\Sorted.

For other tasks (single file organisation), follow: read content, decide category, create folder (use `create_folder` with `path`), move file.
"""
        self.messages.append({"role": "system", "content": system_prompt})

    def _get_tools(self):
        return [
            {"type": "function", "function": {"name": "move_file", "description": "Move a file from source to destination", "parameters": {"type": "object", "properties": {"source": {"type": "string"}, "destination": {"type": "string"}}, "required": ["source", "destination"]}}},
            {"type": "function", "function": {"name": "delete_file", "description": "Delete a file (send to recycle bin)", "parameters": {"type": "object", "properties": {"path": {"type": "string"}}, "required": ["path"]}}},
            {"type": "function", "function": {"name": "rename_file", "description": "Rename a file within the same directory", "parameters": {"type": "object", "properties": {"old_path": {"type": "string"}, "new_name": {"type": "string"}}, "required": ["old_path", "new_name"]}}},
            {"type": "function", "function": {"name": "create_folder", "description": "Create a new folder (and parent directories)", "parameters": {"type": "object", "properties": {"path": {"type": "string"}}, "required": ["path"]}}},
            {"type": "function", "function": {"name": "list_directory", "description": "List all files and subdirectories (non‑recursive)", "parameters": {"type": "object", "properties": {"directory": {"type": "string"}}, "required": ["directory"]}}},
            {"type": "function", "function": {"name": "read_file_content", "description": "Read content of a text or PDF file (first 2000 chars)", "parameters": {"type": "object", "properties": {"file_path": {"type": "string"}}, "required": ["file_path"]}}},
            {"type": "function", "function": {"name": "get_file_info", "description": "Get file size and modification time", "parameters": {"type": "object", "properties": {"file_path": {"type": "string"}}, "required": ["file_path"]}}},
            {"type": "function", "function": {"name": "find_duplicates", "description": "Find duplicate files in a directory using SHA-256 hash", "parameters": {"type": "object", "properties": {"directory": {"type": "string"}}, "required": ["directory"]}}},
            {"type": "function", "function": {"name": "cleanup_empty_folders", "description": "Delete empty folders inside a directory", "parameters": {"type": "object", "properties": {"directory": {"type": "string"}}, "required": ["directory"]}}},
            {"type": "function", "function": {"name": "cleanup_temp_files", "description": "Delete temporary files (e.g., .tmp, .cache, thumbs.db) in a directory", "parameters": {"type": "object", "properties": {"directory": {"type": "string"}}, "required": ["directory"]}}},
            {"type": "function", "function": {"name": "find_large_files", "description": "Find files larger than a specified size (MB) in a directory", "parameters": {"type": "object", "properties": {"directory": {"type": "string"}, "size_mb": {"type": "number"}}, "required": ["directory", "size_mb"]}}},
            {"type": "function", "function": {"name": "batch_move", "description": "Move all files matching a glob pattern (e.g., '*.pdf') to a destination folder", "parameters": {"type": "object", "properties": {"source_pattern": {"type": "string"}, "destination_folder": {"type": "string"}}, "required": ["source_pattern", "destination_folder"]}}},
            {"type": "function", "function": {"name": "suggest_deletions", "description": "Suggest files for deletion based on size, age, duplicates, and optional AI", "parameters": {"type": "object", "properties": {"directory": {"type": "string"}, "size_mb_threshold": {"type": "number", "default": 100}, "age_days_threshold": {"type": "number", "default": 30}, "use_ai": {"type": "boolean", "default": True}}, "required": ["directory"]}}}
        ]

    # ----- Lightweight categorisation for daemon (with file size awareness) -----
    def categorise_file(self, filepath, dest_base, root=None):
        filename = os.path.basename(filepath)
        content_preview = read_file_content_simple(filepath)[:800]
        # Get file size
        try:
            file_size = os.path.getsize(filepath)
            size_mb = file_size // (1024*1024)
            size_str = f"{size_mb} MB" if size_mb > 0 else f"{file_size // 1024} KB" if file_size > 1024 else f"{file_size} bytes"
        except:
            size_str = "unknown"

        existing_folders = []
        if os.path.exists(dest_base):
            existing_folders = [d for d in os.listdir(dest_base) 
                                if os.path.isdir(os.path.join(dest_base, d))]
        existing_folders_str = ", ".join(existing_folders) if existing_folders else "(none)"

        prompt = f"""Filename: {filename}
File size: {size_str}
Content preview:
{content_preview}

Existing folders in the destination directory:
{existing_folders_str}

Task: Decide the best category folder for this file.
- If one of the existing folders is a good match, reply with ONLY that folder name.
- If no existing folder matches, propose a NEW, short, descriptive category name (single word or short phrase, e.g., "Receipts", "Invoices", "Contracts").
- Consider that large files (>100 MB) might be better placed in an "Archive" or "LargeFiles" folder if no other category fits.
- Do NOT add any extra text or explanation.
- Reply with only the folder name.
"""
        try:
            start = time.time()
            print(f"[TIMING] Sending category request for {filename}...")
            response = ollama.chat(
                model=self.model,
                messages=[{"role": "user", "content": prompt}],
                options={"num_ctx": 2048},
                stream=False
            )
            print(f"[TIMING] Category received in {time.time()-start:.2f} seconds")
            category = response['message']['content'].strip()
            category = re.sub(r'[^\w\s-]', '', category).strip()
            if not category:
                category = "Other"
        except Exception as e:
            print(f"[Categorise] Ollama error: {e}, using 'Other'")
            category = "Other"

        if root:
            result_event = Event()
            user_choice = [False]
            def ask():
                user_choice[0] = messagebox.askyesno("Confirm Move", 
                    f"Move '{filename}' to folder '{category}'?\n(If the folder doesn't exist, it will be created.)")
                result_event.set()
            root.after(0, ask)
            result_event.wait()
            if not user_choice[0]:
                return f"User cancelled moving '{filename}'."

        dest_folder = os.path.join(dest_base, category)
        os.makedirs(dest_folder, exist_ok=True)
        dest_path = os.path.join(dest_folder, filename)
        shutil.move(filepath, dest_path)
        return f"Moved '{filename}' → {dest_folder}"

    # ----- Full agent (tool‑calling loop) for chat -----
    def send_message(self, user_input, confirm_callback):
        # ----- BATCH MOVE INTERCEPT (direct execution without AI) -----
        # Match patterns like: batch move "*.pdf" to "Sorted/PDFs"
        batch_match = re.search(r'batch move\s+[\'"]([^\'"]+\.[^\'"]+)[\'"]\s+to\s+[\'"]([^\'"]+)[\'"]', user_input, re.IGNORECASE)
        if not batch_match:
            # Also match without quotes
            batch_match = re.search(r'batch move\s+([^\s]+)\s+to\s+([^\s]+)', user_input, re.IGNORECASE)
        if batch_match:
            pattern = batch_match.group(1).strip('"\'')
            dest = batch_match.group(2).strip('"\'')
            # Make destination absolute if relative
            if not os.path.isabs(dest):
                dest = os.path.join(self.root_path, dest)
            # Call batch_move tool directly
            try:
                result = self.tool_functions["batch_move"](source_pattern=pattern, destination_folder=dest)
            except Exception as e:
                result = f"Error during batch move: {e}"
            # Add a user-assistant pair to maintain conversation consistency
            self.messages.append({"role": "user", "content": user_input})
            self.messages.append({"role": "assistant", "content": result})
            return result
        # ----- END INTERCEPT -----

        self.messages.append({"role": "user", "content": user_input})
        response = ollama.chat(
            model=self.model,
            messages=self.messages,
            tools=self.tools,
            stream=False,
            options=self.ollama_options
        )
        assistant_msg = response['message']
        self.messages.append(assistant_msg)

        tool_calls = []
        if 'tool_calls' in assistant_msg and assistant_msg['tool_calls']:
            tool_calls = assistant_msg['tool_calls']
            print("[DEBUG] Using native tool_calls")
        else:
            content = assistant_msg.get('content', '')
            pattern = r'<tool_call>\s*(.*?)\s*</tool_call>'
            matches = re.findall(pattern, content, re.DOTALL)
            for match in matches:
                json_str = match
                start = json_str.find('{')
                end = json_str.rfind('}')
                if start != -1 and end != -1 and start < end:
                    json_str = json_str[start:end+1]
                else:
                    continue
                try:
                    parsed = json.loads(json_str)
                except json.JSONDecodeError:
                    continue
                if 'name' not in parsed or 'arguments' not in parsed:
                    continue
                args = parsed['arguments']
                # Map argument names
                if parsed['name'] == 'create_folder':
                    if 'folder_path' in args:
                        args['path'] = args.pop('folder_path')
                    elif 'folder_name' in args:   # <-- ADDED for AI's mistake
                        args['path'] = args.pop('folder_name')
                elif parsed['name'] == 'move_file':
                    if 'file_path' in args:
                        args['source'] = args.pop('file_path')
                    elif 'file_source' in args:
                        args['source'] = args.pop('file_source')
                    if 'destination_folder_path' in args:
                        args['destination'] = args.pop('destination_folder_path')
                    elif 'file_destination' in args:
                        args['destination'] = args.pop('file_destination')
                tool_calls.append({
                    "function": {
                        "name": parsed['name'],
                        "arguments": args
                    }
                })
            if tool_calls:
                print(f"[DEBUG] Extracted {len(tool_calls)} tool call(s) from XML")

        if tool_calls:
            for tool_call in tool_calls:
                func_name = tool_call['function']['name']
                args = tool_call['function']['arguments']
                try:
                    confirmed = confirm_callback(func_name, args)
                except Exception as e:
                    print(f"[ERROR] Confirmation failed: {e}")
                    confirmed = False
                if not confirmed:
                    result = f"User cancelled the operation '{func_name}'."
                else:
                    if func_name in self.tool_functions:
                        print(f"[DEBUG] Executing {func_name} with args {args}")
                        result = self.tool_functions[func_name](**args)
                    else:
                        result = f"Unknown tool '{func_name}'"
                self.messages.append({
                    "role": "tool",
                    "content": result,
                    "tool_call_id": tool_call.get('id', 'unknown')
                })
            print("[DEBUG] Calling Ollama for final response...")
            final = ollama.chat(
                model=self.model,
                messages=self.messages,
                stream=False,
                options=self.ollama_options
            )
            final_content = final['message']['content']
            self.messages.append(final['message'])
            return final_content
        else:
            reply = assistant_msg.get('content', '')
            print(f"[Agent] No tool calls, reply: {reply}")
            return reply
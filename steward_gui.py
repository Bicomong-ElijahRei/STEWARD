import os
import sys
import threading
import tkinter as tk
from tkinter import ttk, scrolledtext, filedialog, messagebox
import pystray
from PIL import Image, ImageDraw
import ollama
from pathlib import Path
from watchdog.observers import Observer
from watchdog.events import FileSystemEventHandler
import time
import json
import re
import shutil
import send2trash
import PyPDF2
from datetime import datetime
from threading import Event

# ---------- File Creation Handler (uses background thread) ----------
class FileCreationHandler(FileSystemEventHandler):
    def __init__(self, agent, dest_base, root):
        self.agent = agent
        self.dest_base = dest_base
        self.root = root
        self.last_processed = set()

    def on_created(self, event):
        if event.is_directory:
            return
        time.sleep(0.5)
        filepath = event.src_path
        if filepath in self.last_processed:
            return
        self.last_processed.add(filepath)
        if len(self.last_processed) > 1000:
            self.last_processed.clear()
        threading.Thread(target=self._process_file, args=(filepath,), daemon=True).start()

    def _process_file(self, filepath):
        try:
            result = self.agent.categorise_file(filepath, self.dest_base, self.root)
            print(f"[Daemon] {result}")
        except Exception as e:
            print(f"[Daemon] Error: {e}")

# ---------- StewardAgent ----------
class StewardAgent:
    def __init__(self, model="qwen2.5:7b", root_path=None):
        self.model = model
        self.root_path = root_path or os.getcwd()
        self.messages = []
        self.tools = self._get_tools()
        self.tool_functions = self._get_tool_functions()
        self.ollama_options = {"num_ctx": 32768}

        # ----- UPDATED SYSTEM PROMPT (dynamic categories, no hardcoded list) -----
        system_prompt = f"""
You are STEWARD, an AI file manager for the project located at: {self.root_path}

Your workspace:
- Incoming folder: {self.root_path}\\Incoming
- Sorted folder:   {self.root_path}\\Sorted

When a user asks you to "arrange" or "organise" a file, follow this workflow:

1. Use `read_file_content` to understand the file's content.
2. Based on the content, decide a descriptive category name. **You are free to choose any name** – it can be an existing folder in Sorted (use `list_directory` to check) or a new, short, meaningful name (e.g., "Receipts", "Invoices", "ProjectX", "Medical").
3. Create a subfolder inside `{self.root_path}\\Sorted` with that category name using `create_folder` (if it doesn't already exist).
4. Move the file into that subfolder using `move_file`.

IMPORTANT: Do NOT ask the user for the category. Do NOT ask for confirmation beyond the built‑in wrapper. After reading the file, proceed directly to create the folder (reuse if exists) and move the file.

Never create folders outside `{self.root_path}\\Sorted` unless the user gives an absolute path.

Always output your tool calls inside <tool_call> tags as shown:
<tool_call>
{{"name": "tool_name", "arguments": {{"param": "value"}}}}
</tool_call>
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
            {"type": "function", "function": {"name": "get_file_info", "description": "Get file size and modification time", "parameters": {"type": "object", "properties": {"file_path": {"type": "string"}}, "required": ["file_path"]}}}
        ]

    def _get_tool_functions(self):
        def move_file(source, destination):
            try:
                os.makedirs(os.path.dirname(destination), exist_ok=True)
                shutil.move(source, destination)
                return f"Moved '{source}' → '{destination}'"
            except Exception as e:
                return f"Error: {e}"
        def delete_file(path):
            try:
                send2trash.send2trash(path)
                return f"Deleted '{path}' (recycle bin)"
            except Exception as e:
                return f"Error: {e}"
        def rename_file(old_path, new_name):
            try:
                new_path = os.path.join(os.path.dirname(old_path), new_name)
                os.rename(old_path, new_path)
                return f"Renamed '{old_path}' → '{new_path}'"
            except Exception as e:
                return f"Error: {e}"
        def create_folder(path):
            try:
                os.makedirs(path, exist_ok=True)
                return f"Created folder '{path}'"
            except Exception as e:
                return f"Error: {e}"
        def list_directory(directory):
            try:
                items = os.listdir(directory)
                files = [f for f in items if os.path.isfile(os.path.join(directory, f))]
                dirs = [d + "/" for d in items if os.path.isdir(os.path.join(directory, d))]
                result = "Directories:\n" + "\n".join(dirs) + "\n\nFiles:\n" + "\n".join(files)
                return result if result.strip() else "Empty"
            except Exception as e:
                return f"Error: {e}"
        def read_file_content(file_path):
            ext = os.path.splitext(file_path)[1].lower()
            try:
                if ext == '.txt':
                    with open(file_path, 'r', encoding='utf-8', errors='ignore') as f:
                        return f.read(2000)
                elif ext == '.pdf':
                    with open(file_path, 'rb') as f:
                        reader = PyPDF2.PdfReader(f)
                        text = ''
                        for page in reader.pages[:3]:
                            text += page.extract_text() or ''
                        return text[:2000]
                else:
                    return "[Content extraction not supported]"
            except Exception as e:
                return f"Error: {e}"
        def get_file_info(file_path):
            try:
                stat = os.stat(file_path)
                size = stat.st_size
                mtime = datetime.fromtimestamp(stat.st_mtime).isoformat()
                return f"Size: {size} bytes, Modified: {mtime}"
            except Exception as e:
                return f"Error: {e}"
        return {
            "move_file": move_file,
            "delete_file": delete_file,
            "rename_file": rename_file,
            "create_folder": create_folder,
            "list_directory": list_directory,
            "read_file_content": read_file_content,
            "get_file_info": get_file_info,
        }

    # ----- Lightweight categorisation for daemon (dynamic) -----
    def categorise_file(self, filepath, dest_base, root=None):
        filename = os.path.basename(filepath)
        content_preview = self._read_file_content_simple(filepath)[:800]

        existing_folders = []
        if os.path.exists(dest_base):
            existing_folders = [d for d in os.listdir(dest_base) 
                                if os.path.isdir(os.path.join(dest_base, d))]
        existing_folders_str = ", ".join(existing_folders) if existing_folders else "(none)"

        prompt = f"""Filename: {filename}
Content preview:
{content_preview}

Existing folders in the destination directory:
{existing_folders_str}

Task: Decide the best category folder for this file.
- If one of the existing folders is a good match, reply with ONLY that folder name.
- If no existing folder matches, propose a NEW, short, descriptive category name (single word or short phrase, e.g., "Receipts", "Invoices", "Contracts").
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

    def _read_file_content_simple(self, file_path):
        ext = os.path.splitext(file_path)[1].lower()
        try:
            if ext == '.txt':
                with open(file_path, 'r', encoding='utf-8', errors='ignore') as f:
                    return f.read(2000)
            elif ext == '.pdf':
                with open(file_path, 'rb') as f:
                    reader = PyPDF2.PdfReader(f)
                    text = ''
                    for page in reader.pages[:3]:
                        text += page.extract_text() or ''
                    return text[:2000]
            else:
                return "[Content extraction not supported]"
        except Exception as e:
            return f"Error reading file: {e}"

    # ----- Full agent for chat (tool‑calling loop) -----
    def send_message(self, user_input, confirm_callback):
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
                if parsed['name'] == 'create_folder':
                    if 'folder_path' in args:
                        args['path'] = args.pop('folder_path')
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

# ---------- StewardGUI (unchanged) ----------
class StewardGUI:
    def __init__(self, root):
        self.root = root
        root.title("STEWARD – AI File Manager")
        root.geometry("800x600")
        root.protocol("WM_DELETE_WINDOW", self.on_closing)

        self.agent = StewardAgent()
        self.observer = None
        self.daemon_running = False
        self.daemon_status_label = None

        self.model_var = tk.StringVar(value="qwen2.5:7b")
        self.watched_var = tk.StringVar(value=os.path.join(os.getcwd(), "Incoming"))
        self.dest_var = tk.StringVar(value=os.path.join(os.getcwd(), "Sorted"))

        os.makedirs(self.watched_var.get(), exist_ok=True)
        os.makedirs(self.dest_var.get(), exist_ok=True)

        self.notebook = ttk.Notebook(root)
        self.notebook.pack(fill=tk.BOTH, expand=True)

        self.chat_frame = ttk.Frame(self.notebook)
        self.notebook.add(self.chat_frame, text="Chat")
        self.build_chat_tab()

        self.org_frame = ttk.Frame(self.notebook)
        self.notebook.add(self.org_frame, text="File Organizer")
        self.build_organizer_tab()

        self.settings_frame = ttk.Frame(self.notebook)
        self.notebook.add(self.settings_frame, text="Settings")
        self.build_settings_tab()

        self.tray_icon = None
        self.setup_tray()

    def build_chat_tab(self):
        self.chat_display = scrolledtext.ScrolledText(self.chat_frame, height=20, state=tk.DISABLED)
        self.chat_display.pack(fill=tk.BOTH, expand=True, padx=10, pady=5)
        frame = ttk.Frame(self.chat_frame)
        frame.pack(fill=tk.X, padx=10, pady=5)
        self.chat_entry = ttk.Entry(frame)
        self.chat_entry.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(0,5))
        self.chat_entry.bind("<Return>", lambda e: self.send_chat())
        ttk.Button(frame, text="Send", command=self.send_chat).pack(side=tk.RIGHT)

    def send_chat(self):
        user_msg = self.chat_entry.get().strip()
        if not user_msg:
            return
        self.chat_entry.delete(0, tk.END)
        self.append_chat("You", user_msg)
        def process():
            def confirm_callback(tool_name, args):
                preview = f"Tool: {tool_name}\nArguments: {json.dumps(args, indent=2)}"
                return messagebox.askyesno("Confirm Action", f"Preview:\n{preview}\n\nExecute?")
            response = self.agent.send_message(user_msg, confirm_callback)
            self.root.after(0, lambda: self.append_chat("STEWARD", response))
        threading.Thread(target=process, daemon=True).start()

    def append_chat(self, sender, message):
        self.chat_display.config(state=tk.NORMAL)
        self.chat_display.insert(tk.END, f"{sender}: {message}\n")
        self.chat_display.see(tk.END)
        self.chat_display.config(state=tk.DISABLED)

    def build_organizer_tab(self):
        frame = ttk.Frame(self.org_frame)
        frame.pack(fill=tk.BOTH, expand=True, padx=10, pady=10)
        self.daemon_status_label = ttk.Label(frame, text="Daemon status: STOPPED", font=("Arial", 10))
        self.daemon_status_label.grid(row=0, column=0, columnspan=2, pady=5)
        btn_start = ttk.Button(frame, text="Start Daemon", command=self.start_daemon)
        btn_start.grid(row=1, column=0, padx=5, pady=5, sticky="ew")
        btn_stop = ttk.Button(frame, text="Stop Daemon", command=self.stop_daemon)
        btn_stop.grid(row=1, column=1, padx=5, pady=5, sticky="ew")
        btn_preview = ttk.Button(frame, text="Preview (dry‑run)", command=self.preview_incoming)
        btn_preview.grid(row=2, column=0, columnspan=2, pady=10)
        btn_execute = ttk.Button(frame, text="Execute (process all)", command=self.execute_incoming)
        btn_execute.grid(row=3, column=0, columnspan=2, pady=5)
        btn_undo = ttk.Button(frame, text="Undo Last Move", command=self.undo_last)
        btn_undo.grid(row=4, column=0, columnspan=2, pady=5)
        ttk.Label(frame, text="Preview output:").grid(row=5, column=0, columnspan=2, sticky="w", pady=(10,0))
        self.preview_text = scrolledtext.ScrolledText(frame, height=10, width=80)
        self.preview_text.grid(row=6, column=0, columnspan=2, pady=5, sticky="nsew")
        frame.columnconfigure(0, weight=1)
        frame.columnconfigure(1, weight=1)
        frame.rowconfigure(6, weight=1)

    def preview_incoming(self):
        incoming_path = self.watched_var.get()
        if not os.path.exists(incoming_path):
            self.preview_text.insert(tk.END, "Incoming folder does not exist.\n")
            return
        files = [f for f in os.listdir(incoming_path) if os.path.isfile(os.path.join(incoming_path, f))]
        if not files:
            self.preview_text.insert(tk.END, "No files in Incoming folder.\n")
            return
        self.preview_text.delete(1.0, tk.END)
        self.preview_text.insert(tk.END, f"Files in Incoming ({len(files)}):\n")
        for f in files:
            self.preview_text.insert(tk.END, f"  {f}\n")
        self.preview_text.insert(tk.END, "\nUse 'Execute' to organise them (each operation will ask for confirmation).\n")

    def execute_incoming(self):
        incoming_path = self.watched_var.get()
        if not os.path.exists(incoming_path):
            messagebox.showerror("Error", "Incoming folder does not exist.")
            return
        files = [f for f in os.listdir(incoming_path) if os.path.isfile(os.path.join(incoming_path, f))]
        if not files:
            messagebox.showinfo("Execute", "No files in Incoming folder.")
            return
        if not messagebox.askyesno("Execute", f"Process {len(files)} files? Each operation will require your confirmation."):
            return
        def process():
            for f in files:
                filepath = os.path.join(incoming_path, f)
                try:
                    result = self.agent.categorise_file(filepath, self.dest_var.get(), self.root)
                    self.root.after(0, lambda msg=result: self.append_chat("STEWARD", f"[Execute] {msg}"))
                except Exception as e:
                    self.root.after(0, lambda err=e: self.append_chat("STEWARD", f"[Execute] Error: {err}"))
            self.root.after(0, lambda: messagebox.showinfo("Execute", "Finished processing files."))
        threading.Thread(target=process, daemon=True).start()

    def undo_last(self):
        user_prompt = "Undo the last move operation."
        def confirm_callback(tool_name, args):
            preview = f"Tool: {tool_name}\nArguments: {json.dumps(args, indent=2)}"
            return messagebox.askyesno("Confirm Undo", f"Preview:\n{preview}\n\nUndo?")
        response = self.agent.send_message(user_prompt, confirm_callback)
        self.append_chat("STEWARD", f"[Undo] {response}")

    def start_daemon(self):
        if self.daemon_running:
            messagebox.showinfo("Daemon", "Daemon is already running.")
            return
        watch_path = self.watched_var.get()
        dest_path = self.dest_var.get()
        if not os.path.exists(watch_path):
            messagebox.showerror("Error", f"Watched folder does not exist: {watch_path}")
            return

        event_handler = FileCreationHandler(self.agent, dest_path, self.root)
        self.observer = Observer()
        self.observer.schedule(event_handler, watch_path, recursive=False)
        self.observer.start()
        self.daemon_running = True
        self.update_daemon_status_label()
        messagebox.showinfo("Daemon", f"Daemon started. Watching: {watch_path}")

    def stop_daemon(self):
        if self.observer and self.daemon_running:
            self.observer.stop()
            self.observer.join()
            self.observer = None
            self.daemon_running = False
            self.update_daemon_status_label()
            messagebox.showinfo("Daemon", "Daemon stopped.")
        else:
            messagebox.showwarning("Daemon", "Daemon is not running.")

    def update_daemon_status_label(self):
        if self.daemon_status_label:
            status = "RUNNING" if self.daemon_running else "STOPPED"
            self.daemon_status_label.config(text=f"Daemon status: {status}")

    def build_settings_tab(self):
        frame = ttk.Frame(self.settings_frame)
        frame.pack(fill=tk.BOTH, expand=True, padx=20, pady=20)
        ttk.Label(frame, text="AI Model:").grid(row=0, column=0, sticky=tk.W, pady=5)
        model_combo = ttk.Combobox(frame, textvariable=self.model_var, values=["qwen2.5:7b", "gemma3:1b"])
        model_combo.grid(row=0, column=1, sticky=tk.W, padx=10)
        ttk.Button(frame, text="Apply", command=self.apply_settings).grid(row=0, column=2, padx=10)
        ttk.Label(frame, text="Watched folder:").grid(row=1, column=0, sticky=tk.W, pady=5)
        ttk.Entry(frame, textvariable=self.watched_var, width=50).grid(row=1, column=1, padx=10)
        ttk.Button(frame, text="Browse", command=self.browse_watched).grid(row=1, column=2)
        ttk.Label(frame, text="Destination folder:").grid(row=2, column=0, sticky=tk.W, pady=5)
        ttk.Entry(frame, textvariable=self.dest_var, width=50).grid(row=2, column=1, padx=10)
        ttk.Button(frame, text="Browse", command=self.browse_dest).grid(row=2, column=2)

    def browse_watched(self):
        folder = filedialog.askdirectory(initialdir=self.watched_var.get())
        if folder:
            self.watched_var.set(folder)

    def browse_dest(self):
        folder = filedialog.askdirectory(initialdir=self.dest_var.get())
        if folder:
            self.dest_var.set(folder)

    def apply_settings(self):
        self.agent.model = self.model_var.get()
        messagebox.showinfo("Settings", "Settings applied (agent model changed).")

    def setup_tray(self):
        image = Image.new('RGB', (64, 64), color='black')
        draw = ImageDraw.Draw(image)
        draw.rectangle([10, 10, 54, 54], fill='white')
        menu = pystray.Menu(
            pystray.MenuItem("Show", lambda: self.root.deiconify()),
            pystray.MenuItem("Quit", self.quit_app)
        )
        self.tray_icon = pystray.Icon("steward", image, "STEWARD", menu)
        threading.Thread(target=self.tray_icon.run, daemon=True).start()
        self.root.protocol("WM_DELETE_WINDOW", self.hide_window)

    def hide_window(self):
        self.root.withdraw()
        self.tray_icon.notify("STEWARD is still running in the background", "STEWARD")

    def quit_app(self):
        self.tray_icon.stop()
        self.root.quit()

    def on_closing(self):
        if messagebox.askokcancel("Quit", "Do you want to quit STEWARD?"):
            self.root.destroy()

if __name__ == "__main__":
    root = tk.Tk()
    app = StewardGUI(root)
    root.mainloop()
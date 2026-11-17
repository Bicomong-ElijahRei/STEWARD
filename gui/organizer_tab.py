import tkinter as tk
from tkinter import ttk, scrolledtext, messagebox
import os
import json
import threading
import time
from agent.daemon import FileCreationHandler
from watchdog.observers import Observer

class OrganizerTab:
    def __init__(self, parent, agent, gui):
        self.agent = agent
        self.gui = gui
        self.frame = ttk.Frame(parent)
        self.observer = None
        self.daemon_running = False
        self.daemon_status_label = None
        self.preview_text = None
        self.progress_frame = None
        self.progress_bar = None
        self.progress_label = None
        self.build()

    def build(self):
        frame = self.frame
        frame.pack(fill=tk.BOTH, expand=True, padx=10, pady=10)

        self.daemon_status_label = ttk.Label(frame, text="Daemon status: STOPPED", font=("Arial", 10))
        self.daemon_status_label.grid(row=0, column=0, columnspan=4, pady=5)

        btn_start = ttk.Button(frame, text="Start Daemon", command=self.start_daemon)
        btn_start.grid(row=1, column=0, padx=5, pady=5, sticky="ew")
        btn_stop = ttk.Button(frame, text="Stop Daemon", command=self.stop_daemon)
        btn_stop.grid(row=1, column=1, padx=5, pady=5, sticky="ew")
        btn_preview = ttk.Button(frame, text="Preview (dry‑run)", command=self.preview_incoming)
        btn_preview.grid(row=1, column=2, padx=5, pady=5, sticky="ew")
        btn_execute = ttk.Button(frame, text="Execute (process all)", command=self.execute_incoming)
        btn_execute.grid(row=1, column=3, padx=5, pady=5, sticky="ew")

        btn_undo = ttk.Button(frame, text="Undo Last Move", command=self.undo_last)
        btn_undo.grid(row=2, column=0, columnspan=2, pady=5, sticky="ew")

        btn_duplicates = ttk.Button(frame, text="Find Duplicates in Sorted", command=self.find_duplicates)
        btn_duplicates.grid(row=2, column=2, columnspan=2, pady=5, sticky="ew")
        btn_empty_folders = ttk.Button(frame, text="Clean Empty Folders in Sorted", command=self.clean_empty_folders)
        btn_empty_folders.grid(row=3, column=0, columnspan=2, pady=5, sticky="ew")
        btn_temp_files = ttk.Button(frame, text="Clean Temp Files in Sorted", command=self.clean_temp_files)
        btn_temp_files.grid(row=3, column=2, columnspan=2, pady=5, sticky="ew")
        btn_large_files = ttk.Button(frame, text="Find Large Files (>100MB) in Sorted", command=self.find_large_files)
        btn_large_files.grid(row=4, column=0, columnspan=4, pady=5, sticky="ew")

        btn_suggest_deletions = ttk.Button(frame, text="Suggest Deletions in Sorted", command=self.suggest_deletions)
        btn_suggest_deletions.grid(row=5, column=0, columnspan=4, pady=5, sticky="ew")

        ttk.Label(frame, text="Output:").grid(row=6, column=0, columnspan=4, sticky="w", pady=(10,0))
        self.preview_text = scrolledtext.ScrolledText(frame, height=12, width=80)
        self.preview_text.grid(row=7, column=0, columnspan=4, pady=5, sticky="nsew")

        # Progress bar frame (initially hidden)
        self.progress_frame = ttk.Frame(frame)
        self.progress_bar = ttk.Progressbar(self.progress_frame, mode='determinate')
        self.progress_bar.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(0,5))
        self.progress_label = ttk.Label(self.progress_frame, text="0%")
        self.progress_label.pack(side=tk.RIGHT)
        self.progress_frame.grid(row=8, column=0, columnspan=4, pady=5, sticky="ew")
        self.progress_frame.grid_remove()

        frame.columnconfigure(0, weight=1)
        frame.columnconfigure(1, weight=1)
        frame.columnconfigure(2, weight=1)
        frame.columnconfigure(3, weight=1)
        frame.rowconfigure(7, weight=1)

    def _show_progress(self, show=True):
        if show:
            self.progress_frame.grid()
            self.progress_bar['value'] = 0
            self.progress_label.config(text="0%")
        else:
            self.progress_frame.grid_remove()

    def _update_progress(self, current, total, elapsed, last_update_ref):
        percent = int((current / total) * 100) if total else 0
        remaining_seconds = 0
        if current > 0 and elapsed > 0:
            rate = current / elapsed
            remaining_seconds = (total - current) / rate if rate > 0 else 0
        remaining_str = time.strftime("%M:%S", time.gmtime(remaining_seconds)) if remaining_seconds else "??:??"
        self.progress_bar['value'] = percent
        self.progress_label.config(text=f"{percent}% ({current}/{total}) - ETA: {remaining_str}")

    def _run_tool_with_progress(self, tool_name, args, prompt):
        self._display_result(f"Starting {tool_name}... (this may take a while)")
        self._show_progress(True)
        start_time = time.time()
        last_update = start_time
        processed = 0
        total = 0

        def progress_callback(current, total_files, filepath):
            nonlocal processed, total, last_update
            processed = current
            total = total_files
            now = time.time()
            if now - last_update >= 0.3 or current == total:
                elapsed = now - start_time
                self.frame.after(0, lambda: self._update_progress(current, total_files, elapsed, last_update))
                last_update = now

        def confirm_and_run():
            import threading as th
            confirmed = [False]
            event = th.Event()
            def ask():
                preview = f"Tool: {tool_name}\nArguments: {json.dumps(args, indent=2)}"
                confirmed[0] = messagebox.askyesno("Confirm Action", f"{prompt}\n\nPreview:\n{preview}\n\nExecute?")
                event.set()
            self.frame.after(0, ask)
            event.wait()
            if not confirmed[0]:
                self.frame.after(0, lambda: self._display_result("User cancelled."))
                self.frame.after(0, lambda: self._show_progress(False))
                return

            try:
                import inspect
                tool_func = self.agent.tool_functions[tool_name]
                sig = inspect.signature(tool_func)
                if 'progress_callback' in sig.parameters:
                    result = tool_func(**args, progress_callback=progress_callback)
                else:
                    result = tool_func(**args)
            except Exception as e:
                result = f"Error: {e}"
            self.frame.after(0, lambda: self._display_result(result))
            self.frame.after(0, lambda: self._show_progress(False))

        threading.Thread(target=confirm_and_run, daemon=True).start()

    def _display_result(self, result):
        self.preview_text.insert(tk.END, f"{result}\n")
        self.preview_text.see(tk.END)

    def find_duplicates(self):
        dest = self.gui.settings_tab.dest_var.get()
        self._run_tool_with_progress("find_duplicates", {"directory": dest}, "Find duplicate files?")

    def clean_empty_folders(self):
        dest = self.gui.settings_tab.dest_var.get()
        self._run_tool_with_progress("cleanup_empty_folders", {"directory": dest}, "Delete empty folders?")

    def clean_temp_files(self):
        dest = self.gui.settings_tab.dest_var.get()
        self._run_tool_with_progress("cleanup_temp_files", {"directory": dest}, "Delete temporary files?")

    def find_large_files(self):
        dest = self.gui.settings_tab.dest_var.get()
        self._run_tool_with_progress("find_large_files", {"directory": dest, "size_mb": 100}, "Find large files (>100MB)?")

    def suggest_deletions(self):
        dest = self.gui.settings_tab.dest_var.get()
        self._run_tool_with_progress("suggest_deletions", {"directory": dest, "size_mb_threshold": 100, "age_days_threshold": 30, "use_ai": True}, "Suggest files for deletion?")

    def preview_incoming(self):
        incoming = self.gui.settings_tab.watched_var.get()
        if not os.path.exists(incoming):
            self._display_result("Incoming folder does not exist.")
            return
        files = [f for f in os.listdir(incoming) if os.path.isfile(os.path.join(incoming, f))]
        if not files:
            self._display_result("No files in Incoming folder.")
            return
        self.preview_text.delete(1.0, tk.END)
        self.preview_text.insert(tk.END, f"Files in Incoming ({len(files)}):\n")
        for f in files:
            self.preview_text.insert(tk.END, f"  {f}\n")
        self.preview_text.insert(tk.END, "\nUse 'Execute' to organise them.\n")

    def execute_incoming(self):
        incoming = self.gui.settings_tab.watched_var.get()
        dest = self.gui.settings_tab.dest_var.get()
        if not os.path.exists(incoming):
            messagebox.showerror("Error", "Incoming folder does not exist.")
            return
        files = [f for f in os.listdir(incoming) if os.path.isfile(os.path.join(incoming, f))]
        if not files:
            messagebox.showinfo("Execute", "No files in Incoming folder.")
            return
        if not messagebox.askyesno("Execute", f"Process {len(files)} files? Each will ask for confirmation."):
            return
        def process():
            for f in files:
                filepath = os.path.join(incoming, f)
                try:
                    result = self.agent.categorise_file(filepath, dest, self.gui.root)
                    self.gui.root.after(0, lambda msg=result: self.gui.chat_tab.append_chat("STEWARD", f"[Execute] {msg}"))
                except Exception as e:
                    self.gui.root.after(0, lambda err=e: self.gui.chat_tab.append_chat("STEWARD", f"[Execute] Error: {err}"))
            self.gui.root.after(0, lambda: messagebox.showinfo("Execute", "Finished processing files."))
        threading.Thread(target=process, daemon=True).start()

    def undo_last(self):
        user_prompt = "Undo the last move operation."
        def confirm_callback(tool_name, args):
            preview = f"Tool: {tool_name}\nArguments: {json.dumps(args, indent=2)}"
            return messagebox.askyesno("Confirm Undo", f"Preview:\n{preview}\n\nUndo?")
        response = self.agent.send_message(user_prompt, confirm_callback)
        self.gui.chat_tab.append_chat("STEWARD", f"[Undo] {response}")

    def start_daemon(self):
        if self.daemon_running:
            messagebox.showinfo("Daemon", "Daemon is already running.")
            return
        watch_path = self.gui.settings_tab.watched_var.get()
        dest_path = self.gui.settings_tab.dest_var.get()
        if not os.path.exists(watch_path):
            messagebox.showerror("Error", f"Watched folder does not exist: {watch_path}")
            return

        event_handler = FileCreationHandler(self.agent, dest_path, self.gui.root)
        self.observer = Observer()
        self.observer.schedule(event_handler, watch_path, recursive=False)
        self.observer.start()
        self.daemon_running = True
        self.update_status_label()
        messagebox.showinfo("Daemon", f"Daemon started. Watching: {watch_path}")

    def stop_daemon(self):
        if self.observer and self.daemon_running:
            self.observer.stop()
            self.observer.join()
            self.observer = None
            self.daemon_running = False
            self.update_status_label()
            messagebox.showinfo("Daemon", "Daemon stopped.")
        else:
            messagebox.showwarning("Daemon", "Daemon is not running.")

    def update_status_label(self):
        if self.daemon_status_label:
            status = "RUNNING" if self.daemon_running else "STOPPED"
            self.daemon_status_label.config(text=f"Daemon status: {status}")
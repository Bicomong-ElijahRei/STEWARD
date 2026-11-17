import tkinter as tk
from tkinter import ttk, scrolledtext, messagebox
import os
import json
import threading
import time
import logging

from agent.daemon import FileCreationHandler
from watchdog.observers import Observer

logger = logging.getLogger(__name__)


class OrganizerTab:
    def __init__(self, parent, file_agent, gui):
        self.file_agent = file_agent
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
        btn_preview = ttk.Button(frame, text="Preview (dry-run)", command=self.preview_incoming)
        btn_preview.grid(row=1, column=2, padx=5, pady=5, sticky="ew")
        btn_execute = ttk.Button(frame, text="Execute (process all)", command=self.execute_incoming)
        btn_execute.grid(row=1, column=3, padx=5, pady=5, sticky="ew")

        btn_undo = ttk.Button(frame, text="Undo Last Move", command=self.undo_last)
        btn_undo.grid(row=2, column=0, columnspan=2, pady=5, sticky="ew")

        btn_redo = ttk.Button(frame, text="Redo Last Undo", command=self.redo_last)
        btn_redo.grid(row=2, column=2, columnspan=2, pady=5, sticky="ew")

        btn_duplicates = ttk.Button(frame, text="Find Duplicates in Sorted", command=self.find_duplicates)
        btn_duplicates.grid(row=3, column=0, columnspan=2, pady=5, sticky="ew")
        btn_empty_folders = ttk.Button(frame, text="Clean Empty Folders in Sorted", command=self.clean_empty_folders)
        btn_empty_folders.grid(row=3, column=2, columnspan=2, pady=5, sticky="ew")
        btn_temp_files = ttk.Button(frame, text="Clean Temp Files in Sorted", command=self.clean_temp_files)
        btn_temp_files.grid(row=4, column=0, columnspan=2, pady=5, sticky="ew")
        btn_large_files = ttk.Button(frame, text="Find Large Files (>100MB) in Sorted", command=self.find_large_files)
        btn_large_files.grid(row=4, column=2, columnspan=2, pady=5, sticky="ew")

        btn_suggest_deletions = ttk.Button(frame, text="Suggest Deletions in Sorted", command=self.suggest_deletions)
        btn_suggest_deletions.grid(row=5, column=0, columnspan=4, pady=5, sticky="ew")

        ttk.Label(frame, text="Output:").grid(row=6, column=0, columnspan=4, sticky="w", pady=(10, 0))
        self.preview_text = scrolledtext.ScrolledText(frame, height=12, width=80)
        self.preview_text.grid(row=7, column=0, columnspan=4, pady=5, sticky="nsew")

        # Progress bar frame (initially hidden)
        self.progress_frame = ttk.Frame(frame)
        self.progress_bar = ttk.Progressbar(self.progress_frame, mode='determinate')
        self.progress_bar.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(0, 5))
        self.progress_label = ttk.Label(self.progress_frame, text="0%")
        self.progress_label.pack(side=tk.RIGHT)
        self.progress_frame.grid(row=8, column=0, columnspan=4, pady=5, sticky="ew")
        self.progress_frame.grid_remove()

        frame.columnconfigure(0, weight=1)
        frame.columnconfigure(1, weight=1)
        frame.columnconfigure(2, weight=1)
        frame.columnconfigure(3, weight=1)

    def _display_result(self, text):
        self.preview_text.delete(1.0, tk.END)
        self.preview_text.insert(tk.END, text)

    def preview_incoming(self):
        incoming = self.gui.settings_tab.watched_var.get()
        dest = self.gui.settings_tab.dest_var.get()
        if not os.path.exists(incoming):
            messagebox.showerror("Error", "Incoming folder does not exist.")
            return
        files = [f for f in os.listdir(incoming) if os.path.isfile(os.path.join(incoming, f))]
        if not files:
            self._display_result("No files in Incoming folder.")
            return
        self.preview_text.delete(1.0, tk.END)
        self.preview_text.insert(tk.END, f"Files in Incoming ({len(files)}):\n")
        for f in files:
            self.preview_text.insert(tk.END, f"  {f}\n")
        self.preview_text.insert(tk.END, "\nUse 'Execute' to organise them (dry-run first).\n")

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

        # Dry-run preview first
        self.file_agent.dry_run = True
        preview_lines = []
        for f in files:
            filepath = os.path.join(incoming, f)
            result = self.file_agent.categorise_file(filepath, dest, self.gui.root)
            preview_lines.append(result)

        preview_text = "\n".join(preview_lines)
        self._display_result(f"DRY RUN PREVIEW ({len(files)} files):\n{preview_text}\n")

        if not messagebox.askyesno("Execute?", f"The above is a dry-run preview for {len(files)} files.\nExecute these operations?"):
            self._display_result("Execution cancelled by user.")
            return

        # Execute for real
        self.file_agent.dry_run = False
        def process():
            for f in files:
                filepath = os.path.join(incoming, f)
                try:
                    result = self.file_agent.categorise_file(filepath, dest, self.gui.root)
                    self.gui.root.after(0, lambda msg=result: self._display_result(
                        self.preview_text.get(1.0, tk.END) + f"\n[Execute] {msg}"
                    ))
                except Exception as e:
                    self.gui.root.after(0, lambda err=e: self._display_result(
                        self.preview_text.get(1.0, tk.END) + f"\n[Execute] Error: {err}"
                    ))
            self.gui.root.after(0, lambda: messagebox.showinfo("Execute", "Finished processing files."))
            # Reset to dry_run mode for safety
            self.file_agent.dry_run = True

        threading.Thread(target=process, daemon=True).start()

    def undo_last(self):
        result = self.file_agent.undo_last()
        self._display_result(f"[Undo] {result}\n")
        if hasattr(self.gui, 'chat_tab'):
            self.gui.chat_tab.append_chat("STEWARD", f"[Undo] {result}")

    def redo_last(self):
        result = self.file_agent.redo_last()
        self._display_result(f"[Redo] {result}\n")
        if hasattr(self.gui, 'chat_tab'):
            self.gui.chat_tab.append_chat("STEWARD", f"[Redo] {result}")

    def start_daemon(self):
        if self.daemon_running:
            messagebox.showinfo("Daemon", "Daemon is already running.")
            return
        watch_path = self.gui.settings_tab.watched_var.get()
        dest_path = self.gui.settings_tab.dest_var.get()
        if not os.path.exists(watch_path):
            messagebox.showerror("Error", f"Watched folder does not exist: {watch_path}")
            return

        event_handler = FileCreationHandler(self.file_agent, dest_path, self.gui.root)
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

    def find_duplicates(self):
        dest = self.gui.settings_tab.dest_var.get()
        if not os.path.exists(dest):
            messagebox.showerror("Error", "Destination folder does not exist.")
            return
        from agent.tools import find_duplicates
        result = find_duplicates(dest)
        self._display_result(f"[Duplicates]\n{result}\n")

    def clean_empty_folders(self):
        dest = self.gui.settings_tab.dest_var.get()
        if not os.path.exists(dest):
            messagebox.showerror("Error", "Destination folder does not exist.")
            return
        from agent.tools import cleanup_empty_folders
        result = cleanup_empty_folders(dest)
        self._display_result(f"[Clean Empty Folders]\n{result}\n")

    def clean_temp_files(self):
        dest = self.gui.settings_tab.dest_var.get()
        if not os.path.exists(dest):
            messagebox.showerror("Error", "Destination folder does not exist.")
            return
        from agent.tools import cleanup_temp_files
        result = cleanup_temp_files(dest)
        self._display_result(f"[Clean Temp Files]\n{result}\n")

    def find_large_files(self):
        dest = self.gui.settings_tab.dest_var.get()
        if not os.path.exists(dest):
            messagebox.showerror("Error", "Destination folder does not exist.")
            return
        from agent.tools import find_large_files
        result = find_large_files(dest)
        self._display_result(f"[Large Files]\n{result}\n")

    def suggest_deletions(self):
        dest = self.gui.settings_tab.dest_var.get()
        if not os.path.exists(dest):
            messagebox.showerror("Error", "Destination folder does not exist.")
            return
        from agent.tools import suggest_deletions
        result = suggest_deletions(dest)
        self._display_result(f"[Deletion Suggestions]\n{result}\n")

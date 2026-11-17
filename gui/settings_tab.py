import tkinter as tk
from tkinter import ttk, filedialog, messagebox
import os


class SettingsTab:
    def __init__(self, parent, agent, gui):
        self.agent = agent
        self.gui = gui
        self.frame = ttk.Frame(parent)
        self.provider_var = tk.StringVar(value="auto")
        self.watched_var = tk.StringVar(value=os.path.join(os.getcwd(), "Incoming"))
        self.dest_var = tk.StringVar(value=os.path.join(os.getcwd(), "Sorted"))
        self.dry_run_var = tk.BooleanVar(value=True)
        self.build()

    def build(self):
        frame = self.frame
        frame.pack(fill=tk.BOTH, expand=True, padx=20, pady=20)

        # LLM Provider selection
        ttk.Label(frame, text="LLM Provider:").grid(row=0, column=0, sticky=tk.W, pady=5)
        provider_combo = ttk.Combobox(
            frame,
            textvariable=self.provider_var,
            values=["auto", "gemini", "groq", "openrouter"],
            state="readonly",
            width=15,
        )
        provider_combo.grid(row=0, column=1, sticky=tk.W, padx=10)
        ttk.Label(
            frame,
            text="auto = fallback chain (Gemini -> Groq -> OpenRouter)",
            font=("Arial", 8, "italic"),
        ).grid(row=0, column=2, sticky=tk.W, padx=10)

        # Dry run default
        ttk.Checkbutton(
            frame,
            text="Default to dry-run preview",
            variable=self.dry_run_var,
        ).grid(row=1, column=0, columnspan=3, sticky=tk.W, pady=5)

        ttk.Label(frame, text="Watched folder:").grid(row=2, column=0, sticky=tk.W, pady=5)
        ttk.Entry(frame, textvariable=self.watched_var, width=50).grid(row=2, column=1, padx=10)
        ttk.Button(frame, text="Browse", command=self.browse_watched).grid(row=2, column=2)

        ttk.Label(frame, text="Destination folder:").grid(row=3, column=0, sticky=tk.W, pady=5)
        ttk.Entry(frame, textvariable=self.dest_var, width=50).grid(row=3, column=1, padx=10)
        ttk.Button(frame, text="Browse", command=self.browse_dest).grid(row=3, column=2)

        ttk.Button(frame, text="Apply", command=self.apply_settings).grid(row=4, column=1, pady=10)

    def browse_watched(self):
        folder = filedialog.askdirectory(initialdir=self.watched_var.get())
        if folder:
            self.watched_var.set(folder)

    def browse_dest(self):
        folder = filedialog.askdirectory(initialdir=self.dest_var.get())
        if folder:
            self.dest_var.set(folder)

    def apply_settings(self):
        provider = self.provider_var.get()
        dry_run = self.dry_run_var.get()

        # Update file agent dry_run setting
        if hasattr(self.gui, 'file_agent'):
            self.gui.file_agent.dry_run = dry_run

        # Update legacy agent model
        if hasattr(self.agent, 'model'):
            self.agent.model = provider

        msg = f"Settings applied.\nProvider: {provider}\nDry-run default: {dry_run}"
        messagebox.showinfo("Settings", msg)
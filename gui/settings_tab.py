import tkinter as tk
from tkinter import ttk, filedialog, messagebox
import os

class SettingsTab:
    def __init__(self, parent, agent, gui):
        self.agent = agent
        self.gui = gui
        self.frame = ttk.Frame(parent)
        self.model_var = tk.StringVar(value="qwen2.5:7b")
        self.watched_var = tk.StringVar(value=os.path.join(os.getcwd(), "Incoming"))
        self.dest_var = tk.StringVar(value=os.path.join(os.getcwd(), "Sorted"))
        self.build()

    def build(self):
        frame = self.frame
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
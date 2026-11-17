import tkinter as tk
from tkinter import ttk, scrolledtext, messagebox
import json          # <-- add this line
import threading

class ChatTab:
    def __init__(self, parent, agent):
        self.agent = agent
        self.frame = ttk.Frame(parent)
        self.build()

    def build(self):
        self.chat_display = scrolledtext.ScrolledText(self.frame, height=20, state=tk.DISABLED)
        self.chat_display.pack(fill=tk.BOTH, expand=True, padx=10, pady=5)

        frame = ttk.Frame(self.frame)
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
            self.frame.after(0, lambda: self.append_chat("STEWARD", response))

        threading.Thread(target=process, daemon=True).start()

    def append_chat(self, sender, message):
        self.chat_display.config(state=tk.NORMAL)
        self.chat_display.insert(tk.END, f"{sender}: {message}\n")
        self.chat_display.see(tk.END)
        self.chat_display.config(state=tk.DISABLED)
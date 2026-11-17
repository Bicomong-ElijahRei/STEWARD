import tkinter as tk
from tkinter import ttk, scrolledtext, messagebox
import json
import threading
import logging

from agents.supervisor import (
    AGENT_FILE_OP, AGENT_PC_CONTROL, AGENT_RAG, AGENT_CODING, AGENT_UNKNOWN
)

logger = logging.getLogger(__name__)


class ChatTab:
    def __init__(self, parent, supervisor, file_agent):
        self.supervisor = supervisor
        self.file_agent = file_agent
        self.frame = ttk.Frame(parent)
        self.build()

    def build(self):
        self.chat_display = scrolledtext.ScrolledText(self.frame, height=20, state=tk.DISABLED)
        self.chat_display.pack(fill=tk.BOTH, expand=True, padx=10, pady=5)

        frame = ttk.Frame(self.frame)
        frame.pack(fill=tk.X, padx=10, pady=5)
        self.chat_entry = ttk.Entry(frame)
        self.chat_entry.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(0, 5))
        self.chat_entry.bind("<Return>", lambda e: self.send_chat())
        ttk.Button(frame, text="Send", command=self.send_chat).pack(side=tk.RIGHT)

    def send_chat(self):
        user_msg = self.chat_entry.get().strip()
        if not user_msg:
            return
        self.chat_entry.delete(0, tk.END)
        self.append_chat("You", user_msg)

        def process():
            try:
                # Step 1: Supervisor routes the request
                routing = self.supervisor.route(user_msg)
                agent_type = routing.get("agent", "UNKNOWN")
                action = routing.get("action", user_msg)

                self.frame.after(0, lambda: self.append_chat(
                    "STEWARD", f"[Router] Routing to {agent_type}: {action}"
                ))

                if agent_type == AGENT_FILE_OP:
                    # Step 2: Dry-run preview first
                    self.frame.after(0, lambda: self.append_chat(
                        "STEWARD", "[FileAgent] Generating dry-run preview..."
                    ))

                    def confirm_callback(tool_name, args):
                        preview = f"Tool: {tool_name}\nArguments: {json.dumps(args, indent=2)}"
                        return messagebox.askyesno(
                            "Confirm File Operation",
                            f"DRY RUN PREVIEW:\n{preview}\n\nExecute this operation?"
                        )

                    # First pass: dry_run=True to get preview
                    preview_result = self.file_agent.run(
                        user_msg, dry_run=True, confirm_callback=confirm_callback
                    )
                    self.frame.after(0, lambda: self.append_chat("STEWARD", preview_result))

                    # Ask user if they want to execute
                    if messagebox.askyesno("Execute?", "The above is a dry-run preview.\nExecute these operations?"):
                        # Second pass: dry_run=False to execute
                        exec_result = self.file_agent.run(
                            user_msg, dry_run=False, confirm_callback=confirm_callback
                        )
                        self.frame.after(0, lambda: self.append_chat("STEWARD", exec_result))
                    else:
                        self.frame.after(0, lambda: self.append_chat(
                            "STEWARD", "Execution cancelled by user."
                        ))

                elif agent_type == AGENT_PC_CONTROL:
                    self.frame.after(0, lambda: self.append_chat(
                        "STEWARD", f"[PCAgent] PC control requested: {action}\n(PCAgent is a skeleton - not yet implemented)"
                    ))
                elif agent_type == AGENT_RAG:
                    self.frame.after(0, lambda: self.append_chat(
                        "STEWARD", f"[RAGAgent] Semantic search requested: {action}\n(RAGAgent is a skeleton - not yet implemented)"
                    ))
                elif agent_type == AGENT_CODING:
                    self.frame.after(0, lambda: self.append_chat(
                        "STEWARD", f"[CodingAgent] Coding task requested: {action}\n(CodingAgent is a skeleton - not yet implemented)"
                    ))
                else:
                    self.frame.after(0, lambda: self.append_chat(
                        "STEWARD", f"[Supervisor] Could not classify request: {user_msg}"
                    ))

            except Exception as e:
                logger.error(f"Chat processing error: {e}")
                self.frame.after(0, lambda: self.append_chat("STEWARD", f"Error: {e}"))

        threading.Thread(target=process, daemon=True).start()

    def append_chat(self, sender, message):
        self.chat_display.config(state=tk.NORMAL)
        self.chat_display.insert(tk.END, f"{sender}: {message}\n")
        self.chat_display.see(tk.END)
        self.chat_display.config(state=tk.DISABLED)

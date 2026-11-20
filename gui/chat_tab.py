"""
ChatTab - Left panel chat interface for Mission Control.

Routes user messages through SupervisorAgent, executes via FileAgent,
and emits real-time events to the LiveFeedWidget.
"""

import customtkinter as ctk
from tkinter import messagebox
import json
import threading
import logging

from agents.supervisor import (
    AGENT_FILE_OP, AGENT_PC_CONTROL, AGENT_RAG, AGENT_CODING, AGENT_UNKNOWN,
)
from core.theme import (
    BG_INPUT, TEXT_BRIGHT, TEXT_MUTED, NEON_PURPLE, NEON_CYAN,
    NEON_LIME, NEON_BLUE, NEON_ORANGE, FONT_ROUNDED, FONT_MONO, CORNER_RADIUS,
)
from agents.agent_config import AGENT_CONFIG, AGENT_ROUTING_KEYS
from gui.live_feed import LiveFeedWidget

logger = logging.getLogger(__name__)

AGENT_COLOR_MAP = {
    "Cortex": NEON_PURPLE,
    "Foldy": NEON_CYAN,
    "Click": NEON_LIME,
    "Scout": NEON_BLUE,
    "Syntax": NEON_ORANGE,
}


class ChatTab(ctk.CTkFrame):
    def __init__(self, parent, supervisor, file_agent, live_feed=None):
        super().__init__(parent, fg_color="transparent")
        self.supervisor = supervisor
        self.file_agent = file_agent
        self.live_feed = live_feed
        self.build()

    def build(self):
        header = ctk.CTkFrame(self, fg_color="transparent", height=50)
        header.pack(fill="x", padx=16, pady=(16, 8))
        header.pack_propagate(False)

        title = ctk.CTkLabel(
            header,
            text="💬 STEWARD Chat",
            font=("Nunito", 16, "bold"),
            text_color=TEXT_BRIGHT,
        )
        title.pack(side="left")

        # Split container: chat (left) + live feed (right)
        self.split_container = ctk.CTkFrame(self, fg_color="transparent")
        self.split_container.pack(fill="both", expand=True, padx=16, pady=(0, 16))

        # Left: Chat display
        self.chat_panel = ctk.CTkFrame(
            self.split_container, fg_color="#2A2A35", corner_radius=CORNER_RADIUS
        )
        self.chat_panel.pack(side="left", fill="both", expand=True, padx=(0, 8))

        self.chat_display = ctk.CTkScrollableFrame(
            self.chat_panel, fg_color="transparent", corner_radius=CORNER_RADIUS
        )
        self.chat_display.pack(fill="both", expand=True, padx=10, pady=10)

        # Right: Live Feed
        self.feed_panel = ctk.CTkFrame(
            self.split_container, fg_color="#2A2A35", corner_radius=CORNER_RADIUS, width=320
        )
        self.feed_panel.pack(side="right", fill="y", padx=(8, 0))
        self.feed_panel.pack_propagate(False)

        feed_title = ctk.CTkLabel(
            self.feed_panel,
            text="📡 Live Feed",
            font=("Nunito", 14, "bold"),
            text_color=NEON_PURPLE,
        )
        feed_title.pack(pady=(14, 8), padx=10, anchor="w")

        if self.live_feed is None:
            self.live_feed = LiveFeedWidget(self.feed_panel, width=300)
        self.live_feed.pack(fill="both", expand=True, padx=8, pady=(0, 10))

        self.live_feed.agent_idle("Cortex")
        self.live_feed.agent_idle("Foldy")

        # Input area
        input_frame = ctk.CTkFrame(self, fg_color="transparent", height=60)
        input_frame.pack(fill="x", padx=16, pady=(0, 16))
        input_frame.pack_propagate(False)

        self.chat_entry = ctk.CTkEntry(
            input_frame,
            placeholder_text="Ask STEWARD to organize files, move items, or run tasks…",
            font=FONT_ROUNDED,
            height=36,
            corner_radius=CORNER_RADIUS,
            fg_color=BG_INPUT,
            border_color="#4A4A5A",
        )
        self.chat_entry.pack(side="left", fill="both", expand=True, padx=(0, 8))
        self.chat_entry.bind("<Return>", lambda e: self.send_chat())

        self.send_btn = ctk.CTkButton(
            input_frame,
            text="Send",
            width=80,
            height=36,
            corner_radius=CORNER_RADIUS,
            font=("Nunito", 12, "bold"),
            fg_color=NEON_PURPLE,
            hover_color="#A56EEA",
            command=self.send_chat,
        )
        self.send_btn.pack(side="right")

    def send_chat(self):
        user_msg = self.chat_entry.get().strip()
        if not user_msg:
            return
        self.chat_entry.delete(0, "end")
        self._add_bubble("You", user_msg, TEXT_BRIGHT, align="right")

        def process():
            try:
                routing = self.supervisor.route(user_msg)
                agent_type = routing.get("agent", "UNKNOWN")
                action = routing.get("action", user_msg)

                agent_name = AGENT_ROUTING_KEYS.get(agent_type, "Cortex")
                color = AGENT_CONFIG.get(agent_name, {}).get("color", TEXT_MUTED)

                self.after(0, lambda: self._add_bubble(
                    "STEWARD", f"[{agent_name}] Routing: {action}",
                    color, align="left",
                ))

                if self.live_feed:
                    self.after(0, lambda: self.live_feed.agent_working(
                        agent_name, f"Routing: {action}"
                    ))

                if agent_type == AGENT_FILE_OP:
                    self.after(0, lambda: self._add_bubble(
                        "STEWARD", "[Foldy] Generating dry-run preview…",
                        NEON_CYAN, align="left",
                    ))

                    def confirm_callback(tool_name, args):
                        preview = f"Tool: {tool_name}\nArguments: {json.dumps(args, indent=2)}"
                        return messagebox.askyesno(
                            "Confirm File Operation",
                            f"DRY RUN PREVIEW:\n{preview}\n\nExecute this operation?",
                        )

                    preview_result = self.file_agent.run(
                        user_msg, dry_run=True, confirm_callback=confirm_callback
                    )
                    self.after(0, lambda: self._add_bubble(
                        "STEWARD", preview_result, NEON_CYAN, align="left",
                    ))

                    if self.live_feed:
                        self.after(0, lambda: self.live_feed.agent_done(
                            "Foldy", "Dry-run preview generated"
                        ))

                    if messagebox.askyesno(
                        "Execute?",
                        "The above is a dry-run preview.\nExecute these operations?",
                    ):
                        exec_result = self.file_agent.run(
                            user_msg, dry_run=False, confirm_callback=confirm_callback
                        )
                        self.after(0, lambda: self._add_bubble(
                            "STEWARD", exec_result, NEON_CYAN, align="left",
                        ))
                        if self.live_feed:
                            self.after(0, lambda: self.live_feed.agent_done(
                                "Foldy", "Operations executed"
                            ))
                    else:
                        self.after(0, lambda: self._add_bubble(
                            "STEWARD", "Execution cancelled by user.",
                            TEXT_MUTED, align="left",
                        ))

                elif agent_type == AGENT_PC_CONTROL:
                    self.after(0, lambda: self._add_bubble(
                        "STEWARD",
                        f"[Click] PC control requested: {action}\n(Coming soon)",
                        NEON_LIME, align="left",
                    ))
                    if self.live_feed:
                        self.after(0, lambda: self.live_feed.agent_done("Click"))
                elif agent_type == AGENT_RAG:
                    self.after(0, lambda: self._add_bubble(
                        "STEWARD",
                        f"[Scout] Semantic search: {action}\n(Coming soon)",
                        NEON_BLUE, align="left",
                    ))
                    if self.live_feed:
                        self.after(0, lambda: self.live_feed.agent_done("Scout"))
                elif agent_type == AGENT_CODING:
                    self.after(0, lambda: self._add_bubble(
                        "STEWARD",
                        f"[Syntax] Coding task: {action}\n(Coming soon)",
                        NEON_ORANGE, align="left",
                    ))
                    if self.live_feed:
                        self.after(0, lambda: self.live_feed.agent_done("Syntax"))
                else:
                    self.after(0, lambda: self._add_bubble(
                        "STEWARD",
                        f"[Cortex] I'm not sure how to help with: {user_msg}",
                        NEON_PURPLE, align="left",
                    ))
                    if self.live_feed:
                        self.after(0, lambda: self.live_feed.agent_done("Cortex"))

            except Exception as e:
                logger.error(f"Chat processing error: {e}")
                self.after(0, lambda: self._add_bubble(
                    "STEWARD", f"Error: {e}", "#FF5555", align="left",
                ))

        threading.Thread(target=process, daemon=True).start()

    def _add_bubble(self, sender, message, color, align="left"):
        bubble = ctk.CTkFrame(self.chat_display, fg_color="#353545", corner_radius=12)
        bubble.pack(fill="x", padx=10, pady=4, anchor="e" if align == "right" else "w")

        sender_label = ctk.CTkLabel(
            bubble,
            text=sender,
            font=("Nunito", 10, "bold"),
            text_color=color,
            anchor="w",
        )
        sender_label.pack(fill="x", padx=10, pady=(6, 0))

        msg_label = ctk.CTkLabel(
            bubble,
            text=message,
            font=FONT_MONO,
            text_color=TEXT_BRIGHT,
            anchor="w",
            justify="left",
            wraplength=500,
        )
        msg_label.pack(fill="x", padx=10, pady=(0, 6))

        self.after_idle(self._scroll_chat)

    def _scroll_chat(self):
        self.chat_display._parent_canvas.yview_moveto(1.0)

    def append_chat(self, sender, message):
        self._add_bubble(sender, message, TEXT_BRIGHT, align="left")



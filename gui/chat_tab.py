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
import math

from agents.supervisor import (
    AGENT_FILE_OP, AGENT_PC_CONTROL, AGENT_RAG, AGENT_CODING, AGENT_UNKNOWN,
)
from core.theme import (
    BG_INPUT, TEXT_BRIGHT, TEXT_MUTED, NEON_PURPLE, NEON_CYAN,
    NEON_LIME, NEON_BLUE, NEON_ORANGE, FONT_ROUNDED, FONT_MONO, CORNER_RADIUS,
)
from agents.agent_config import AGENT_CONFIG, AGENT_ROUTING_KEYS
from gui.live_feed import LiveFeedWidget
from gui.anim import SafeTick, lerp_color

logger = logging.getLogger(__name__)

AGENT_COLOR_MAP = {
    "Cortex": NEON_PURPLE,
    "Foldy": NEON_CYAN,
    "Click": NEON_LIME,
    "Scout": NEON_BLUE,
    "Syntax": NEON_ORANGE,
}

class HandoffCanvas(ctk.CTkCanvas):
    """Animated glowing arc that triggers on agent handoffs."""
    def __init__(self, parent):
        super().__init__(parent, bg="#2A2A35", highlightthickness=0, height=40)
        self.arc_id = None
        self._tick = None

    def trigger_handoff(self, from_agent, to_agent):
        if self._tick:
            self._tick.cancel()
        self.delete("all")
        # Draw initial straight line
        self.arc_id = self.create_line(40, 20, 260, 20, width=3, fill=NEON_PURPLE, smooth=True)
        
        step = [0]
        def on_tick():
            step[0] += 1
            t = step[0] / 20.0
            if t >= 1.0:
                self.delete("all")
                return False  # Stop the tick
            
            # Sine wave arc animation
            offset = math.sin(t * math.pi) * 25
            self.coords(self.arc_id, 40, 20, 150, 20 - offset, 260, 20)
            self.itemconfig(self.arc_id, fill=lerp_color(NEON_PURPLE, NEON_CYAN, t))
            return True
            
        self._tick = SafeTick(self, 30, on_tick).start()

class ChatBubble(ctk.CTkFrame):
    """Animated chat bubble supporting THINKING, TOOL_USE, STREAMING, DONE, ERROR states."""
    def __init__(self, parent, sender, message, color, align="left", state="NORMAL"):
        super().__init__(parent, fg_color="#353545", corner_radius=12)
        self.sender = sender
        self.color = color
        self.align = align
        self._tick = None
        self._base_color = "#353545"
        self.build(message)
        self.update_state(state)

    def build(self, message):
        self.pack(fill="x", padx=10, pady=4, anchor="e" if self.align == "right" else "w")
        
        header = ctk.CTkFrame(self, fg_color="transparent")
        header.pack(fill="x", padx=10, pady=(6, 0))
        
        self.sender_label = ctk.CTkLabel(
            header, text=self.sender, font=("Nunito", 10, "bold"),
            text_color=self.color, anchor="w",
        )
        self.sender_label.pack(side="left")
        
        self.icon_label = ctk.CTkLabel(
            header, text="", font=("Nunito", 12), text_color=self.color, anchor="e",
        )
        self.icon_label.pack(side="right")
        
        self.msg_label = ctk.CTkLabel(
            self, text=message, font=FONT_MONO, text_color=TEXT_BRIGHT,
            anchor="w", justify="left", wraplength=500,
        )
        self.msg_label.pack(fill="x", padx=10, pady=(0, 6))

    def update_state(self, state):
        if self._tick:
            self._tick.cancel()
            self._tick = None
            
        if state == "THINKING":
            self.icon_label.configure(text="⚙️")
            self._start_pulse()
        elif state == "TOOL_USE":
            self.icon_label.configure(text="🔧")
            self.configure(fg_color=self._base_color)
        elif state == "STREAMING":
            self.icon_label.configure(text="⌨️")
            self._start_pulse()
        elif state == "DONE":
            self.icon_label.configure(text="✅")
            self.configure(fg_color=self._base_color)
        elif state == "ERROR":
            self.icon_label.configure(text="❌")
            self.configure(fg_color="#452525")
        else:
            self.icon_label.configure(text="")
            self.configure(fg_color=self._base_color)

    def _start_pulse(self):
        step = [0]
        def on_tick():
            step[0] += 1
            t = (step[0] % 20) / 20.0
            self.configure(fg_color=lerp_color(self._base_color, "#45455A", t))
            return True
        self._tick = SafeTick(self, 50, on_tick).start()

    def set_message(self, message):
        self.msg_label.configure(text=message)

class ChatTab(ctk.CTkFrame):
    def __init__(self, parent, supervisor, file_agent, live_feed=None,
                 provider_callback=None):
        super().__init__(parent, fg_color="transparent")
        self.supervisor = supervisor
        self.file_agent = file_agent
        self.live_feed = live_feed
        self.provider_callback = provider_callback
        self._processing = False
        self.dialog_timeout = 600
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

        self.handoff_canvas = HandoffCanvas(self.chat_panel)
        self.handoff_canvas.pack(fill="x", padx=10, pady=(10, 0))

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

    def _is_alive(self):
        try:
            return bool(self.winfo_exists())
        except Exception:
            return False

    def _safe_after(self, callback):
        """Schedule on Tk only while this tab still exists."""
        if not self._is_alive():
            return
        try:
            self.after(0, callback)
        except Exception:
            pass

    def _restore_return_key(self):
        self.chat_entry.bind("<Return>", lambda e: self.send_chat())
        self._processing = False

    def send_chat(self):
        if self._processing:
            return
        user_msg = self.chat_entry.get().strip()
        if not user_msg:
            return
        self._processing = True
        self.chat_entry.delete(0, "end")
        self._add_bubble("You", user_msg, TEXT_BRIGHT, align="right")
        # Prevent concurrent submissions while a preview/approval is in flight.
        self.send_btn.configure(state="disabled")
        self.chat_entry.unbind("<Return>")

        def process():
            try:
                routing = self.supervisor.route(user_msg)
                self._report_provider("Cortex")
                agent_type = routing.get("agent", "UNKNOWN")
                action = routing.get("action", user_msg)

                agent_name = AGENT_ROUTING_KEYS.get(agent_type, "Cortex")
                color = AGENT_CONFIG.get(agent_name, {}).get("color", TEXT_MUTED)

                # Trigger visual handoff animation
                if agent_type != AGENT_UNKNOWN:
                    self._safe_after(lambda: self.handoff_canvas.trigger_handoff("Cortex", agent_name))

                self._safe_after(lambda: self._add_bubble(
                    "STEWARD", f"[{agent_name}] Routing: {action}",
                    color, align="left",
                ))

                if self.live_feed:
                    self._safe_after(lambda: self.live_feed.agent_working(
                        agent_name, f"Routing: {action}"
                    ))

                if agent_type == AGENT_FILE_OP:
                    foldy_bubble = [None]
                    self._safe_after(lambda: foldy_bubble.__setitem__(0, self._add_bubble(
                        "STEWARD", "Generating dry-run preview…",
                        NEON_CYAN, align="left", state="THINKING",
                    )))

                    dialog_timeout = getattr(self, "dialog_timeout", 600)
                    confirm_timed_out = [False]

                    def confirm_callback(tool_name, args):
                        preview = f"Tool: {tool_name}\nArguments: {json.dumps(args, indent=2)}"
                        evt = threading.Event()
                        user_choice = [False]
                        def ask():
                            user_choice[0] = messagebox.askyesno(
                                "Confirm File Operation",
                                f"The agent wants to execute:\n{preview}\n\nExecute?",
                            )
                            evt.set()
                        self._safe_after(ask)
                        if not evt.wait(timeout=dialog_timeout):
                            confirm_timed_out[0] = True
                            return False
                        return user_choice[0]

                    preview_result = self.file_agent.run(
                        user_msg, dry_run=True, confirm_callback=confirm_callback
                    )
                    if confirm_timed_out[0]:
                        self.file_agent.discard_pending_plan()
                        logger.info("[Chat] approval dialog timed out; input restored")
                        if foldy_bubble[0]:
                            self._safe_after(lambda: foldy_bubble[0].update_state("ERROR"))
                        return

                    self._pending_plan_id = self.file_agent.get_pending_plan_id()
                    foldy_detail = self._report_provider("Foldy")
                    preview_message = preview_result
                    if foldy_detail:
                        preview_message += f"\n\nHandled by {foldy_detail}"
                    
                    if foldy_bubble[0]:
                        self._safe_after(lambda: foldy_bubble[0].set_message(preview_message))
                        self._safe_after(lambda: foldy_bubble[0].update_state("DONE"))
                    else:
                        self._safe_after(lambda: self._add_bubble(
                            "STEWARD", preview_message, NEON_CYAN, align="left", state="DONE",
                        ))

                    if self.live_feed:
                        self._safe_after(lambda: self.live_feed.agent_done(
                            "Foldy", foldy_detail or "Dry-run preview generated"
                        ))

                    if self._pending_plan_id is None:
                        logger.info("[Chat] No tool plan produced; awaiting user reply")
                        return

                    exec_evt = threading.Event()
                    exec_choice = [False]
                    def ask_exec():
                        exec_choice[0] = messagebox.askyesno(
                            "Execute Operations?",
                            "The above is a dry-run preview.\nExecute these operations?",
                        )
                        exec_evt.set()
                    self._safe_after(ask_exec)
                    if not exec_evt.wait(timeout=dialog_timeout):
                        self.file_agent.discard_pending_plan()
                        logger.info("[Chat] approval dialog timed out; input restored")
                        return

                    if exec_choice[0]:
                        exec_bubble = [None]
                        self._safe_after(lambda: exec_bubble.__setitem__(0, self._add_bubble(
                            "STEWARD", "Executing operations…", NEON_CYAN, align="left", state="TOOL_USE",
                        )))
                        try:
                            exec_result = self.file_agent.execute_pending_plan(
                                self._pending_plan_id
                            )
                        except Exception as exc:
                            exec_result = f"Error: {exc}"
                        
                        if exec_bubble[0]:
                            self._safe_after(lambda: exec_bubble[0].set_message(exec_result))
                            self._safe_after(lambda: exec_bubble[0].update_state("DONE" if not exec_result.startswith("Error") else "ERROR"))
                        else:
                            self._safe_after(lambda: self._add_bubble(
                                "STEWARD", exec_result, NEON_CYAN, align="left", 
                                state="DONE" if not exec_result.startswith("Error") else "ERROR",
                            ))
                            
                        if self.live_feed:
                            self._safe_after(lambda: self.live_feed.agent_done(
                                "Foldy", foldy_detail or "Operations executed"
                            ))
                    else:
                        self.file_agent.discard_pending_plan()
                        self._safe_after(lambda: self._add_bubble(
                            "STEWARD", "Execution cancelled by user.",
                            TEXT_MUTED, align="left", state="DONE",
                        ))

                elif agent_type == AGENT_PC_CONTROL:
                    self._safe_after(lambda: self._add_bubble(
                        "STEWARD",
                        f"[Click] PC control requested: {action}\n(Coming soon)",
                        NEON_LIME, align="left",
                    ))
                    if self.live_feed:
                        self._safe_after(lambda: self.live_feed.agent_done("Click"))
                elif agent_type == AGENT_RAG:
                    self._safe_after(lambda: self._add_bubble(
                        "STEWARD",
                        f"[Scout] Semantic search: {action}\n(Coming soon)",
                        NEON_BLUE, align="left",
                    ))
                    if self.live_feed:
                        self._safe_after(lambda: self.live_feed.agent_done("Scout"))
                elif agent_type == AGENT_CODING:
                    self._safe_after(lambda: self._add_bubble(
                        "STEWARD",
                        f"[Syntax] Coding task: {action}\n(Coming soon)",
                        NEON_ORANGE, align="left",
                    ))
                    if self.live_feed:
                        self._safe_after(lambda: self.live_feed.agent_done("Syntax"))
                else:
                    self._safe_after(lambda: self._add_bubble(
                        "STEWARD",
                        f"[Cortex] I'm not sure how to help with: {user_msg}",
                        NEON_PURPLE, align="left",
                    ))
                    if self.live_feed:
                        self._safe_after(lambda: self.live_feed.agent_done("Cortex"))

            except Exception as e:
                logger.error(f"Chat processing error: {e}")
                self._safe_after(lambda e=e: self._add_bubble(
                    "STEWARD", f"Error: {e}", "#FF5555", align="left",
                ))
            finally:
                # Always re-enable input once preview/approval is complete,
                # regardless of which agent branch ran or whether it errored.
                self._safe_after(lambda: self.send_btn.configure(state="normal"))
                self._safe_after(self._restore_return_key)

        threading.Thread(target=process, daemon=True).start()

    def _report_provider(self, agent_name):
        """Publish router metadata and return a short UI status string."""
        source = self.supervisor if agent_name == "Cortex" else self.file_agent
        provider_info = getattr(source, "last_provider", None)
        if not provider_info:
            return ""
        provider = provider_info.get("provider", "Unknown")
        model = provider_info.get("model", "default")
        if self.provider_callback:
            self.provider_callback(agent_name, provider_info)
        if self.live_feed:
            for failover in provider_info.get("failovers", []):
                failed = failover.get("failed_provider", "Unknown")
                fallback = failover.get("fallback_provider", "Unknown")
                self._safe_after(
                    lambda failed=failed, fallback=fallback:
                    self.live_feed.provider_failover(failed, fallback),
                )
        return f"{provider} / {model}"

    def _add_bubble(self, sender, message, color, align="left", state="NORMAL"):
        bubble = ChatBubble(self.chat_display, sender, message, color, align, state)
        self.after_idle(self._scroll_chat)
        return bubble

    def _scroll_chat(self):
        try:
            if hasattr(self.chat_display, '_parent_canvas'):
                self.chat_display._parent_canvas.yview_moveto(1.0)
        except Exception:
            pass  # Widget may have been destroyed

    def append_chat(self, sender, message):
        self._add_bubble(sender, message, TEXT_BRIGHT, align="left")



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
import os
import re

from agents.supervisor import (
    AGENT_FILE_OP, AGENT_PC_CONTROL, AGENT_RAG, AGENT_CODING, AGENT_UNKNOWN,
    AGENT_GENERAL_CHAT,
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


def strip_markdown(text: str) -> str:
    """Convert basic Markdown syntax to readable plain text for chat display."""
    text = str(text or "")

    # Fenced blocks must be handled before inline-code backticks, otherwise
    # the inline pattern consumes the fence markers and leaves raw code.
    text = re.sub(r"```[\s\S]*?```", "[Code block]", text)

    # Images precede links because an image also contains link-like syntax.
    text = re.sub(r"!\[(.+?)\]\(.+?\)", r"[Image: \1]", text)
    text = re.sub(r"\[(.+?)\]\(.+?\)", r"\1", text)

    text = re.sub(r"^#{1,6}\s+", "", text, flags=re.MULTILINE)
    text = re.sub(r"^>\s+", "", text, flags=re.MULTILINE)
    text = re.sub(r"^[-*_]{3,}\s*$", "---", text, flags=re.MULTILINE)
    text = re.sub(r"\*\*(.+?)\*\*", r"\1", text)
    text = re.sub(r"__(.+?)__", r"\1", text)
    text = re.sub(r"\*(.+?)\*", r"\1", text)
    text = re.sub(r"_(.+?)_", r"\1", text)
    text = re.sub(r"`(.+?)`", r"\1", text)
    return text.strip()


def render_markdown_text(message):
    """Compatibility wrapper for callers using the original helper name."""
    return strip_markdown(message)

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

    def destroy(self):
        """Cancel the handoff animation before destroying the canvas."""
        if self._tick:
            self._tick.cancel()
            self._tick = None
        super().destroy()


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
        
        # A Text widget wraps at word boundaries and grows with its content,
        # avoiding the fixed-width clipping caused by CTkLabel's wraplength.
        self.msg_text = ctk.CTkTextbox(
            self,
            font=FONT_MONO,
            text_color=TEXT_BRIGHT,
            fg_color="transparent",
            border_width=0,
            wrap="word",
            state="disabled",
        )
        self.msg_text.pack(fill="both", expand=True, padx=10, pady=(0, 6))
        self.msg_text.configure(state="normal")
        self.msg_text.insert("1.0", render_markdown_text(message))
        self.msg_text.configure(state="disabled")
        self.msg_text.bind("<Configure>", self._schedule_message_fit)
        self.msg_text.after_idle(self._fit_message_textbox)

    def _schedule_message_fit(self, event=None):
        """Recalculate the textbox height after its available width changes."""
        try:
            self.after_idle(self._fit_message_textbox)
        except Exception:
            self._fit_message_textbox()

    def _fit_message_textbox(self):
        """Size the textbox to all wrapped lines so the bubble can grow."""
        try:
            textbox = self.msg_text._textbox
            line_count = textbox.count("1.0", "end-1c", "displaylines")
            if isinstance(line_count, (tuple, list)):
                line_count = line_count[0] if line_count else 1
            line_info = textbox.dlineinfo("1.0")
            if not line_info:
                return
            line_height = max(1, int(line_info[3]))
            scaling = max(1.0, float(self.msg_text._get_widget_scaling()))
            desired_height = max(1, math.ceil((line_count * line_height + 24) / scaling))
            if self.msg_text._desired_height != desired_height:
                self.msg_text.configure(height=desired_height)
        except Exception:
            pass  # Widget may not be realized yet or may have been destroyed

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
        self.msg_text.configure(state="normal")
        self.msg_text.delete("1.0", "end")
        self.msg_text.insert("1.0", render_markdown_text(message))
        self.msg_text.configure(state="disabled")
        self._fit_message_textbox()

    def destroy(self):
        """Cancel bubble animation before Tk destroys the widget tree."""
        if self._tick:
            self._tick.cancel()
            self._tick = None
        super().destroy()

class ChatTab(ctk.CTkFrame):
    MAX_CHAT_TURNS = 6
    MAX_CHAT_CONTEXT_CHARS = 12000
    MAX_CHAT_MESSAGE_CHARS = 4000

    def __init__(self, parent, supervisor, file_agent, live_feed=None,
                 provider_callback=None, coding_agent=None):
        super().__init__(parent, fg_color="transparent")
        self.supervisor = supervisor
        self.file_agent = file_agent
        self.coding_agent = coding_agent
        self.rag_agent = None
        self.live_feed = live_feed
        self.provider_callback = provider_callback
        self._processing = False
        self._general_chat_history = []
        self._conversation_epoch = 0
        self.dialog_timeout = 600
        self._register_swarm_handlers()
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
        self._update_chat_scrollregion()

        # Right: Live Feed
        self.feed_panel = ctk.CTkFrame(
            self.split_container, fg_color="#2A2A35", corner_radius=CORNER_RADIUS, width=320
        )
        self.feed_panel.pack(side="right", fill="y", padx=(8, 0))
        self.feed_panel.pack_propagate(False)

        feed_header = ctk.CTkFrame(
            self.feed_panel, fg_color="transparent"
        )
        feed_header.pack(fill="x", padx=10, pady=(14, 8))

        feed_title = ctk.CTkLabel(
            feed_header,
            text="📡 Live Feed",
            font=("Nunito", 14, "bold"),
            text_color=NEON_PURPLE,
        )
        feed_title.pack(side="left")

        self.btn_clear_feed = ctk.CTkButton(
            feed_header,
            text="Clear",
            width=58,
            height=26,
            corner_radius=8,
            font=("Nunito", 11, "bold"),
            fg_color="#4A4A5A",
            hover_color="#5A5A6A",
            command=self._clear_live_feed,
        )
        self.btn_clear_feed.pack(side="right")

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

        self.clear_btn = ctk.CTkButton(
            input_frame,
            text="Clear",
            width=60,
            height=36,
            corner_radius=CORNER_RADIUS,
            font=("Nunito", 12, "bold"),
            fg_color="#4A4A5A",
            hover_color="#5A5A6A",
            command=self.clear_chat,
        )
        self.clear_btn.pack(side="right", padx=(0, 8))

    def clear_chat(self):
        """Remove visible chat bubbles and the bounded Cortex conversation."""
        self._conversation_epoch = getattr(self, "_conversation_epoch", 0) + 1
        self._general_chat_history = []
        for widget in self.chat_display.winfo_children():
            widget.destroy()

    def _remember_general_chat(self, role, content):
        """Append one bounded message to the in-memory Cortex conversation."""
        text = str(content or "")
        if len(text) > self.MAX_CHAT_MESSAGE_CHARS:
            text = text[-self.MAX_CHAT_MESSAGE_CHARS:]
        history = getattr(self, "_general_chat_history", None)
        if history is None:
            history = []
            self._general_chat_history = history
        history.append({"role": role, "content": text})
        max_messages = self.MAX_CHAT_TURNS * 2
        if len(history) > max_messages:
            del history[:-max_messages]
        while history and sum(
            len(message["content"]) for message in history
        ) > self.MAX_CHAT_CONTEXT_CHARS:
            history.pop(0)

    def _clear_live_feed(self):
        """Clear visible live-feed activity cards from the chat header."""
        if self.live_feed:
            self.live_feed.clear()

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

    def _restore_input(self, message):
        """Restore an unfinished request without overwriting newer typing."""
        try:
            if not self.chat_entry.get().strip():
                self.chat_entry.insert(0, message)
        except Exception:
            pass

    def send_chat(self):
        if self._processing:
            return
        user_msg = self.chat_entry.get().strip()
        if not user_msg:
            return
        request_epoch = getattr(self, "_conversation_epoch", 0)
        self._processing = True
        restore_input = [False]
        self.chat_entry.delete(0, "end")
        self._add_bubble("You", user_msg, TEXT_BRIGHT, align="right")
        # Prevent concurrent submissions while a preview/approval is in flight.
        self.send_btn.configure(state="disabled")
        self.chat_entry.unbind("<Return>")

        def process():
            try:
                routing = self.supervisor.route(user_msg)
                if request_epoch != getattr(self, "_conversation_epoch", 0):
                    logger.info("[Chat] discarded stale request after conversation clear")
                    return
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
                        action, dry_run=True, confirm_callback=confirm_callback
                    )
                    if confirm_timed_out[0]:
                        restore_input[0] = True
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
                        restore_input[0] = True
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
                    action_lower = action.lower()
                    is_ingest = any(kw in action_lower for kw in (
                        "ingest", "index", "learn", "remember", "scan",
                        "process", "read all", "add to knowledge base",
                    ))

                    scout_bubble = [None]
                    if is_ingest:
                        self._safe_after(lambda: scout_bubble.__setitem__(0, self._add_bubble(
                            "STEWARD", "Scout is ingesting documents...", NEON_BLUE,
                            align="left", state="THINKING",
                        )))
                    else:
                        self._safe_after(lambda: scout_bubble.__setitem__(0, self._add_bubble(
                            "STEWARD", "Scout is searching the archives...", NEON_BLUE,
                            align="left", state="THINKING",
                        )))

                    def finish_scout(message, state="DONE"):
                        bubble = scout_bubble[0]
                        if bubble:
                            bubble.set_message(message)
                            bubble.update_state(state)
                        else:
                            self._add_bubble(
                                "STEWARD", message, NEON_BLUE, align="left", state=state,
                            )

                    try:
                        rag_agent = self._get_rag_agent()
                        if is_ingest:
                            folder_name = "Incoming" if "incoming" in action_lower else "Sorted"
                            folder_path = os.path.join(self.file_agent.root_path, folder_name)
                            result = rag_agent.ingest_directory(folder_path)
                            msg = (
                                f"Ingested {result.get('files_processed', 0)} files, "
                                f"created {result.get('chunks_created', 0)} chunks."
                            )
                            self._safe_after(lambda: finish_scout(msg))
                        else:
                            results = rag_agent.search(action, n_results=5)
                            if results:
                                chunks_text = "\n\n".join([
                                    f"Source: {result.get('source', 'Unknown')}\n"
                                    f"Content: {result.get('content', '')}"
                                    for result in results
                                ])
                                synthesis_messages = [
                                    {
                                        "role": "system",
                                        "content": (
                                            "You are Scout, a document research assistant. "
                                            "Based on the provided document excerpts, answer "
                                            "the user's question clearly and concisely. Cite "
                                            "the source file for each claim. If the excerpts "
                                            "don't contain relevant information, say so."
                                        ),
                                    },
                                    {
                                        "role": "user",
                                        "content": (
                                            f"Question: {action}\n\n"
                                            f"Document Excerpts:\n{chunks_text}"
                                        ),
                                    },
                                ]

                                try:
                                    synthesis_response = self.supervisor.api_manager.route_request(
                                        messages=synthesis_messages,
                                        agent_name="Scout",
                                        require_tools=False,
                                    )
                                    answer = synthesis_response["choices"][0]["message"].get(
                                        "content", ""
                                    ).strip()
                                    if not answer:
                                        raise ValueError("Scout returned an empty synthesis")

                                    source_list = "\n".join([
                                        f"- {self._rag_source_name(result.get('source'))}"
                                        for result in results
                                    ])
                                    formatted_answer = (
                                        f"📚 **Answer:**\n\n{answer}\n\n"
                                        f"**Sources:**\n{source_list}"
                                    )
                                    self._safe_after(lambda: finish_scout(formatted_answer))
                                except Exception as synth_error:
                                    logger.warning(
                                        "Synthesis failed, falling back to raw results: %s",
                                        synth_error,
                                    )
                                    formatted = "🔍 **Search Results:**\n\n"
                                    for index, result in enumerate(results, 1):
                                        source = self._rag_source_name(result.get("source"))
                                        content = " ".join(
                                            str(result.get("content", "")).split()
                                        )[:300]
                                        formatted += (
                                            f"{index}. **{source}**\n{content}...\n\n"
                                        )
                                    self._safe_after(lambda: finish_scout(formatted))
                            else:
                                self._safe_after(lambda: finish_scout(
                                    "No relevant documents found in the knowledge base."
                                ))
                    except Exception as exc:
                        logger.error("RAG error: %s", exc)
                        self._safe_after(lambda: finish_scout(f"RAG Error: {exc}", "ERROR"))

                    if self.live_feed:
                        self._safe_after(lambda: self.live_feed.agent_done(
                            "Scout", "Ingestion/Search complete"
                        ))
                elif agent_type == AGENT_CODING:
                    syntax_bubble = [None]
                    self._safe_after(lambda: syntax_bubble.__setitem__(0, self._add_bubble(
                        "STEWARD", "Syntax is working on your request...",
                        NEON_ORANGE, align="left", state="THINKING",
                    )))
                    try:
                        syntax_response = self._get_coding_agent().generate_code(action)
                        syntax_detail = self._report_provider("Syntax")
                        if syntax_bubble[0]:
                            self._safe_after(lambda: syntax_bubble[0].set_message(syntax_response))
                            self._safe_after(lambda: syntax_bubble[0].update_state("DONE"))
                        else:
                            self._safe_after(lambda: self._add_bubble(
                                "STEWARD", syntax_response, NEON_ORANGE,
                                align="left", state="DONE",
                            ))
                        if self.live_feed:
                            self._safe_after(lambda: self.live_feed.agent_done(
                                "Syntax", syntax_detail or "Coding assistance generated"
                            ))
                    except Exception as exc:
                        logger.error("Syntax coding error: %s", exc)
                        error_message = f"Syntax could not complete the coding request: {exc}"
                        if syntax_bubble[0]:
                            self._safe_after(lambda: syntax_bubble[0].set_message(error_message))
                            self._safe_after(lambda: syntax_bubble[0].update_state("ERROR"))
                        else:
                            self._safe_after(lambda: self._add_bubble(
                                "STEWARD", error_message, NEON_ORANGE,
                                align="left", state="ERROR",
                            ))
                elif agent_type == AGENT_GENERAL_CHAT:
                    # Send to Cortex for natural conversation.
                    cortex_bubble = [None]
                    self._safe_after(lambda: cortex_bubble.__setitem__(0, self._add_bubble(
                        "STEWARD", "Thinking...",
                        NEON_PURPLE, align="left", state="THINKING",
                    )))

                    try:
                        messages = [
                            {
                                "role": "system",
                                "content": (
                                    "You are Cortex, the supervisor AI of STEWARD. "
                                    "You are helpful, friendly, and knowledgeable "
                                    "about the STEWARD system. Answer questions "
                                    "naturally and conversationally. If asked about "
                                    "system capabilities, explain what STEWARD can "
                                    "do (file organization, document search, provider "
                                    "management). Keep responses concise and helpful."
                                ),
                            },
                            *list(getattr(self, "_general_chat_history", [])),
                            {"role": "user", "content": user_msg},
                        ]

                        response = self.supervisor.api_manager.route_request(
                            messages=messages,
                            agent_name="Cortex",
                            require_tools=False,
                        )

                        cortex_response = response["choices"][0]["message"].get("content", "")
                        if request_epoch != getattr(self, "_conversation_epoch", 0):
                            logger.info("[Chat] discarded stale Cortex conversation response")
                            return

                        self._remember_general_chat("user", user_msg)
                        self._remember_general_chat("assistant", cortex_response)

                        def finish_conversation():
                            bubble = cortex_bubble[0]
                            if bubble:
                                bubble.set_message(cortex_response)
                                bubble.update_state("DONE")
                            else:
                                self._add_bubble(
                                    "STEWARD", cortex_response,
                                    NEON_PURPLE, align="left", state="DONE",
                                )

                        self._safe_after(finish_conversation)
                        if self.live_feed:
                            self._safe_after(
                                lambda: self.live_feed.agent_done(
                                    "Cortex", "Response generated"
                                )
                            )
                    except Exception as e:
                        logger.error(f"Cortex conversation error: {e}")
                        error_message = f"Sorry, I encountered an error: {e}"

                        def finish_with_error():
                            bubble = cortex_bubble[0]
                            if bubble:
                                bubble.set_message(error_message)
                                bubble.update_state("ERROR")
                            else:
                                self._add_bubble(
                                    "STEWARD", error_message,
                                    NEON_PURPLE, align="left", state="ERROR",
                                )

                        self._safe_after(finish_with_error)
                else:
                    feed = self.live_feed
                    if feed:
                        self._safe_after(lambda feed=feed: feed.agent_working(
                            "Cortex", "Delegating complex task"
                        ))
                    delegation_result = self.supervisor.delegate_task(
                        user_msg, ["Foldy", "Scout", "Click", "Syntax"]
                    )
                    delegated_response = str(
                        delegation_result.get("response")
                        or delegation_result.get("final_response")
                        or "The delegated tasks returned no result."
                    ).strip()
                    delegation_state = (
                        "ERROR" if delegation_result.get("error") else "DONE"
                    )
                    self._safe_after(lambda response=delegated_response,
                                    state=delegation_state: self._add_bubble(
                        "STEWARD", response, NEON_PURPLE, align="left", state=state,
                    ))
                    delegation_results = delegation_result.get("results") or []
                    for result in delegation_results:
                        agent_name = result.get("agent", "Cortex")
                        detail = str(result.get("result", "Task complete"))
                        if feed:
                            self._safe_after(
                                lambda feed=feed, agent_name=agent_name,
                                detail=detail: feed.agent_done(agent_name, detail)
                            )
                    if feed:
                        self._safe_after(lambda feed=feed: feed.agent_done(
                            "Cortex", "Hierarchical delegation complete"
                        ))

            except Exception as e:
                restore_input[0] = True
                logger.error(f"Chat processing error: {e}")
                self._safe_after(lambda e=e: self._add_bubble(
                    "STEWARD", f"Error: {e}", "#FF5555", align="left",
                ))
            finally:
                # Always re-enable input once preview/approval is complete,
                # regardless of which agent branch ran or whether it errored.
                self._safe_after(lambda: self.send_btn.configure(state="normal"))
                if restore_input[0]:
                    self._safe_after(lambda: self._restore_input(user_msg))
                self._safe_after(self._restore_return_key)

        threading.Thread(target=process, daemon=True).start()

    def _register_swarm_handlers(self):
        """Bind local specialist APIs to Cortex's delegation workflow."""
        register = getattr(self.supervisor, "register_sub_agent", None)
        if not callable(register):
            return
        register("Foldy", self._delegate_file_task)
        register("Scout", self._delegate_scout_task)
        register("Syntax", self._delegate_syntax_task)

    def _delegate_file_task(self, task):
        """Delegate file work as a non-mutating preview for later approval."""
        return self.file_agent.run(task, dry_run=True)

    def _delegate_scout_task(self, task):
        """Delegate document research to the persistent RAG index."""
        results = self._get_rag_agent().search(task, n_results=5)
        return self._format_rag_results(task, results)

    def _delegate_syntax_task(self, task):
        """Delegate coding work to the provider-backed, text-only Syntax agent."""
        return self._get_coding_agent().generate_code(task)

    def _get_coding_agent(self):
        """Return the injected Syntax agent or create one from the shared router."""
        if getattr(self, "coding_agent", None) is None:
            from agents.coding_agent import CodingAgent
            self.coding_agent = CodingAgent(api_manager=self.supervisor.api_manager)
        return self.coding_agent

    def _get_rag_agent(self):
        """Create the persistent RAG index lazily on the first Scout query."""
        if getattr(self, "rag_agent", None) is None:
            from agents.rag_agent import RAGAgent
            self.rag_agent = RAGAgent()
        return self.rag_agent

    @staticmethod
    def _rag_source_name(source):
        """Return a source filename from either POSIX or Windows paths."""
        value = str(source or "Unknown").replace("\\", "/").rstrip("/")
        return value.rsplit("/", 1)[-1] or "Unknown"

    @staticmethod
    def _format_rag_results(query, results):
        """Format flat RAG records for a readable chat bubble."""
        if not results:
            return "No relevant documents found in the knowledge base."
        lines = [f"🔍 **Search Results for [{query}]:**", ""]
        for index, result in enumerate(results, start=1):
            source = str(result.get("source") or "Unknown source")
            content = " ".join(str(result.get("content") or "").split())
            snippet = content[:500] + ("…" if len(content) > 500 else "")
            lines.append(f"{index}. [{source}]")
            lines.append(f"   {snippet}")
            lines.append("")
        return "\n".join(lines).rstrip()

    def _report_provider(self, agent_name):
        """Publish router metadata and return a short UI status string."""
        if agent_name == "Cortex":
            source = self.supervisor
        elif agent_name == "Syntax":
            source = self._get_coding_agent()
        else:
            source = self.file_agent
        provider_info = getattr(source, "last_provider", None)
        if not provider_info:
            return ""
        provider = provider_info.get("provider", "Unknown")
        model = provider_info.get("model", "default")
        if self.provider_callback:
            self._safe_after(
                lambda agent_name=agent_name, provider_info=provider_info:
                self.provider_callback(agent_name, provider_info)
            )
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
        clean_message = strip_markdown(message)
        bubble = ChatBubble(
            self.chat_display, sender, clean_message, color, align, state
        )
        self.after_idle(self._update_chat_scrollregion)
        self.after_idle(self._scroll_chat)
        return bubble

    def _update_chat_scrollregion(self):
        """Keep the scrollable canvas region aligned with its content."""
        try:
            canvas = self.chat_display._parent_canvas
            bbox = canvas.bbox("all")
            if bbox:
                canvas.configure(scrollregion=bbox)
        except Exception:
            pass  # Widget may not be realized yet or may have been destroyed

    def _scroll_chat(self):
        try:
            if hasattr(self.chat_display, '_parent_canvas'):
                self.chat_display._parent_canvas.yview_moveto(1.0)
        except Exception:
            pass  # Widget may have been destroyed

    def append_chat(self, sender, message):
        """Append a chat bubble and make rule-based categorization explicit."""
        if (
            getattr(self.file_agent, "last_categorized_by_rule", False)
            and "[Rule]" not in str(message)
        ):
            message = f"[Rule] {message}"
        self._add_bubble(sender, message, TEXT_BRIGHT, align="left")



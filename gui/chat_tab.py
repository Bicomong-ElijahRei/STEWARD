"""
ChatTab - Left panel chat interface for Mission Control.

Routes user messages through SupervisorAgent, executes via FileAgent,
and emits real-time events to the LiveFeedWidget.
"""

import customtkinter as ctk
from tkinter import filedialog, messagebox
import json
import queue
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
                 provider_callback=None, coding_agent=None, plan_agent=None,
                 patch_review_manager=None):
        super().__init__(parent, fg_color="transparent")
        self.supervisor = supervisor
        self.file_agent = file_agent
        self.coding_agent = coding_agent
        self.plan_agent = plan_agent
        self.patch_review_manager = patch_review_manager
        self.plan_first_var = ctk.BooleanVar(master=self, value=False)
        self.rag_agent = None
        self.live_feed = live_feed
        self.provider_callback = provider_callback
        self._processing = False
        self._general_chat_history = []
        self._conversation_epoch = 0
        self._delegation_context = threading.local()
        self._conversation_lock = threading.RLock()
        self._code_index_agent = None
        self._code_index_epoch = 0
        self._code_index_cancel = threading.Event()
        self._code_index_thread = None
        self._code_index_job_token = None
        self._code_index_results = queue.Queue()
        self._code_index_status_label = None
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

        self.code_index_btn = ctk.CTkButton(
            header,
            text="Code Index",
            width=96,
            height=28,
            corner_radius=8,
            font=("Nunito", 11, "bold"),
            fg_color="#4A4A5A",
            hover_color="#5A5A6A",
            command=self._show_code_index_dialog,
        )
        self.code_index_btn.pack(side="right", padx=(0, 8))

        self.patch_review_btn = ctk.CTkButton(
            header,
            text="Patch Review",
            width=108,
            height=28,
            corner_radius=8,
            font=("Nunito", 11, "bold"),
            fg_color="#4A4A5A",
            hover_color="#5A5A6A",
            command=self._show_patch_review_dialog,
        )
        self.patch_review_btn.pack(side="right")

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

        self.plan_first_check = ctk.CTkCheckBox(
            input_frame,
            text="Plan first",
            variable=self.plan_first_var,
            width=92,
            font=("Nunito", 11),
            fg_color=NEON_PURPLE,
            hover_color="#A56EEA",
        )
        self.plan_first_check.pack(side="right", padx=(0, 8))

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

    def _code_index_is_current(self, index_epoch, request_epoch):
        """Return whether an index result still belongs to the active chat."""
        return (
            index_epoch == getattr(self, "_code_index_epoch", 0)
            and request_epoch == getattr(self, "_conversation_epoch", 0)
        )

    def _get_code_index_agent(self):
        """Return the lazily-created CODE collection agent."""
        agent = getattr(self, "_code_index_agent", None)
        if agent is None:
            from agents.code_index_agent import CodeIndexAgent

            agent = CodeIndexAgent()
            self._code_index_agent = agent
        return agent

    def _show_patch_review_dialog(self):
        """Open the C3 review surface for the most recent reviewed plan."""
        existing = getattr(self, "_patch_review_dialog", None)
        if existing is not None:
            try:
                if existing.winfo_exists():
                    existing.lift()
                    return
            except Exception:
                pass
            self._patch_review_dialog = None
        manager = getattr(self, "patch_review_manager", None)
        plan_agent = getattr(self, "plan_agent", None)
        if manager is None or plan_agent is None:
            messagebox.showinfo(
                "Patch Review",
                "Patch review is not available in this session.",
            )
            return
        plan_ids = plan_agent.reviewed_plan_ids()
        if not plan_ids:
            messagebox.showinfo(
                "Patch Review",
                "Approve a plan first before generating a patch preview.",
            )
            return
        plan_id = plan_ids[-1]
        epoch = getattr(self, "_conversation_epoch", 0)

        def is_current():
            return self._is_current_conversation_epoch(epoch)

        dialog = None

        def on_close():
            if getattr(self, "_patch_review_dialog", None) is dialog:
                self._patch_review_dialog = None

        from gui.patch_review_dialog import PatchReviewDialog

        dialog = PatchReviewDialog(
            self,
            manager,
            plan_id,
            epoch,
            live_feed=self.live_feed,
            is_current=is_current,
            on_close=on_close,
            schedule_if_epoch=self._safe_after_if_epoch,
        )
        self._patch_review_dialog = dialog

    def _show_code_index_dialog(self):
        """Show explicit root selection and index/status/clear controls."""
        dialog = ctk.CTkToplevel(self)
        dialog.title("STEWARD Code Index")
        dialog.geometry("620x260")
        root_var = ctk.StringVar(value="")
        path_entry = ctk.CTkEntry(
            dialog, textvariable=root_var, placeholder_text="Select a project folder"
        )
        path_entry.pack(fill="x", padx=16, pady=(16, 8))
        disclosure = ctk.CTkLabel(
            dialog,
            text=(
                "Retrieved code snippets are sent to your configured provider "
                "(cloud-first). The local code index stores plaintext snippets."
            ),
            text_color=TEXT_MUTED,
            wraplength=570,
            justify="left",
        )
        disclosure.pack(fill="x", padx=16, pady=(0, 8))
        self._code_index_status_label = ctk.CTkLabel(
            dialog, text="No code indexing operation is running.", text_color=TEXT_MUTED
        )
        self._code_index_status_label.pack(fill="x", padx=16, pady=(0, 4))

        def choose_root():
            selected = filedialog.askdirectory(title="Select project folder")
            if selected:
                root_var.set(selected)

        def start_index():
            root = root_var.get().strip()
            if not root:
                messagebox.showwarning("Code Index", "Select a project folder first.")
                return
            if getattr(self, "_code_index_status_label", None) is not None:
                self._code_index_status_label.configure(
                    text="Indexing project code..."
                )
            self._start_code_index(root, dialog)

        def show_status():
            try:
                status = self._get_code_index_agent().status()
                messagebox.showinfo(
                    "Code Index",
                    f"Files: {status.get('files', 0)}\nChunks: {status.get('chunks', 0)}",
                )
            except Exception as exc:
                messagebox.showerror("Code Index", str(exc))

        def clear_index():
            try:
                cancel_event = getattr(self, "_code_index_cancel", None)
                if cancel_event is not None:
                    cancel_event.set()
                self._code_index_epoch = getattr(self, "_code_index_epoch", 0) + 1
                self._code_index_job_token = None
                self._code_index_thread = None
                self._get_code_index_agent().clear()
                messagebox.showinfo("Code Index", "Code index cleared.")
            except Exception as exc:
                messagebox.showerror("Code Index", str(exc))

        ctk.CTkButton(dialog, text="Choose folder", command=choose_root).pack(
            side="left", padx=(16, 6), pady=4
        )
        ctk.CTkButton(dialog, text="Index", command=start_index).pack(
            side="left", padx=6, pady=4
        )
        ctk.CTkButton(dialog, text="Status", command=show_status).pack(
            side="left", padx=6, pady=4
        )
        ctk.CTkButton(dialog, text="Clear", command=clear_index).pack(
            side="left", padx=6, pady=4
        )
        ctk.CTkButton(dialog, text="Close", command=dialog.destroy).pack(
            side="right", padx=16, pady=4
        )

    def _start_code_index(self, root, dialog=None):
        """Index a selected root in a worker and marshal results to Tk."""
        previous = getattr(self, "_code_index_cancel", None)
        if previous is not None:
            previous.set()
        cancel_event = threading.Event()
        self._code_index_cancel = cancel_event
        self._code_index_epoch = getattr(self, "_code_index_epoch", 0) + 1
        index_epoch = self._code_index_epoch
        request_epoch = getattr(self, "_conversation_epoch", 0)

        job_token = object()
        self._code_index_job_token = job_token

        def worker():
            try:
                summary = self._get_code_index_agent().index_project(
                    root, cancel_event=cancel_event
                )
                self._code_index_results.put(
                    (job_token, index_epoch, request_epoch, summary, None)
                )
            except Exception as exc:
                self._code_index_results.put(
                    (job_token, index_epoch, request_epoch, None, exc)
                )

        thread = threading.Thread(target=worker, name="steward-code-index", daemon=True)
        self._code_index_thread = thread
        if self.live_feed:
            self.live_feed.agent_working("Scout", "Indexing project code")
        thread.start()
        self._poll_code_index_results()

    def _poll_code_index_results(self):
        """Consume worker results on the Tk thread."""
        current_result_consumed = False
        try:
            while True:
                job_token, index_epoch, request_epoch, summary, error = (
                    self._code_index_results.get_nowait()
                )
                if job_token is not getattr(self, "_code_index_job_token", None):
                    continue
                if not self._code_index_is_current(index_epoch, request_epoch):
                    continue
                current_result_consumed = True
                if error is not None:
                    messagebox.showerror("Code Index", str(error))
                elif summary is not None:
                    status = (
                        f"Indexed {summary.get('files_processed', 0)} files; "
                        f"{summary.get('chunks_created', 0)} chunks"
                    )
                    if summary.get("cancelled"):
                        status = "Code indexing cancelled."
                    label = getattr(self, "_code_index_status_label", None)
                    if label is not None:
                        try:
                            label.configure(text=status)
                        except Exception:
                            pass
                    if self.live_feed:
                        self.live_feed.agent_done("Scout", status)
        except queue.Empty:
            pass
        if current_result_consumed:
            self._code_index_thread = None
            self._code_index_job_token = None
            return
        if getattr(self, "_code_index_thread", None) is not None:
            self.after(100, self._poll_code_index_results)

    def _code_index_context(self, query):
        """Retrieve bounded CODE context for Syntax, without changing no-index behavior."""
        agent = getattr(self, "_code_index_agent", None)
        if agent is None:
            return []
        try:
            return agent.search(query, n_results=5)
        except Exception as exc:
            logger.warning("Code context retrieval failed: %s", exc)
            return []

    def clear_chat(self):
        """Remove visible chat bubbles and the bounded Cortex conversation.

        Clearing creates a new conversation generation.  The old provider
        request may still be running, but it no longer owns input controls or
        conversation state and a new request can be admitted immediately.
        """
        cancel_event = getattr(self, "_code_index_cancel", None)
        if cancel_event is not None:
            cancel_event.set()
        self._code_index_epoch = getattr(self, "_code_index_epoch", 0) + 1
        self._code_index_job_token = None
        self._code_index_thread = None
        with self._conversation_state_lock():
            self._conversation_epoch = getattr(self, "_conversation_epoch", 0) + 1
            self._general_chat_history = []
            self._processing = False
            # Invalidate a pending or in-flight preview in the same critical
            # section that publishes the new conversation generation. This
            # prevents a newer preview started immediately after Clear from
            # being discarded by this cleanup.
            file_agent = getattr(self, "file_agent", None)
            discard_pending_plan = getattr(file_agent, "discard_pending_plan", None)
            if callable(discard_pending_plan):
                discard_pending_plan()
            plan_agent = getattr(self, "plan_agent", None)
            invalidate_pending_plan = getattr(
                plan_agent, "invalidate_pending_plan", None
            )
            if callable(invalidate_pending_plan):
                invalidate_pending_plan()
            patch_manager = getattr(self, "patch_review_manager", None)
            invalidate_pending_patch = getattr(
                patch_manager, "invalidate_pending_patch", None
            )
            if callable(invalidate_pending_patch):
                invalidate_pending_patch()
            patch_dialog = getattr(self, "_patch_review_dialog", None)
            if patch_dialog is not None:
                try:
                    patch_dialog.destroy()
                except Exception:
                    pass
                self._patch_review_dialog = None
        for widget in self.chat_display.winfo_children():
            widget.destroy()
        # The cleared generation has no active request, so restore the input
        # controls for the new epoch.  Stale workers cannot perform this
        # restoration because their cleanup is guarded by the old epoch.
        send_btn = getattr(self, "send_btn", None)
        if send_btn is not None:
            send_btn.configure(state="normal")
        chat_entry = getattr(self, "chat_entry", None)
        if chat_entry is not None:
            chat_entry.bind("<Return>", lambda e: self.send_chat())

    def _conversation_state_lock(self):
        """Return the lock protecting Cortex epoch and conversation history."""
        lock = getattr(self, "_conversation_lock", None)
        if lock is None:
            lock = threading.RLock()
            self._conversation_lock = lock
        return lock

    def _is_current_conversation_epoch(self, epoch):
        """Return whether a request still belongs to the active conversation."""
        with self._conversation_state_lock():
            return epoch == getattr(self, "_conversation_epoch", 0)

    def _conversation_messages(self, user_msg, epoch):
        """Return a locked history snapshot if the request is still current."""
        with self._conversation_state_lock():
            if epoch != getattr(self, "_conversation_epoch", 0):
                return None
            return [
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

    def _remember_general_chat(self, role, content):
        """Append one bounded message to the in-memory Cortex conversation."""
        with self._conversation_state_lock():
            self._remember_general_chat_locked(role, content)

    def _remember_general_chat_locked(self, role, content):
        """Append one message while the conversation lock is held."""
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

    def _remember_general_chat_turn(self, epoch, user_content, assistant_content):
        """Atomically append a Cortex turn if its conversation is still current."""
        with self._conversation_state_lock():
            if epoch != getattr(self, "_conversation_epoch", 0):
                return False
            self._remember_general_chat_locked("user", user_content)
            self._remember_general_chat_locked("assistant", assistant_content)
            return True

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
        """Schedule on Tk only while this tab still exists.

        Returns ``True`` when the callback was scheduled. Callers that wait
        for a UI acknowledgement can use this to release their event when the
        widget has already been destroyed.
        """
        if not self._is_alive():
            return False
        try:
            self.after(0, callback)
            return True
        except Exception:
            return False

    def _safe_after_if_epoch(self, callback, epoch):
        """Schedule UI work only if the owning conversation is still current."""
        def guarded_callback():
            if not self._is_current_conversation_epoch(epoch):
                return
            callback()
        self._safe_after(guarded_callback)

    def _restore_return_key(self, epoch=None):
        """Restore controls only when the finishing request still owns them."""
        with self._conversation_state_lock():
            if epoch is not None and epoch != getattr(self, "_conversation_epoch", 0):
                return
            self.chat_entry.bind("<Return>", lambda e: self.send_chat())
            if epoch is None or epoch == getattr(self, "_conversation_epoch", 0):
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
        with self._conversation_state_lock():
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
                cortex_provider = {}
                routing = self.supervisor.route(
                    user_msg,
                    provider_callback=cortex_provider.update,
                )
                if request_epoch != getattr(self, "_conversation_epoch", 0):
                    logger.info("[Chat] discarded stale request after conversation clear")
                    return
                self._report_provider(
                    "Cortex", request_epoch, provider_info=cortex_provider
                )
                agent_type = routing.get("agent", "UNKNOWN")
                action = routing.get("action", user_msg)

                agent_name = AGENT_ROUTING_KEYS.get(agent_type, "Cortex")
                color = AGENT_CONFIG.get(agent_name, {}).get("color", TEXT_MUTED)

                if agent_type == AGENT_CODING and self._plan_first_enabled():
                    self._run_plan_first_workflow(
                        user_msg,
                        request_epoch=request_epoch,
                        action=action,
                    )
                    return

                # Trigger visual handoff animation
                if agent_type != AGENT_UNKNOWN:
                    self._safe_after_if_epoch(
                        lambda: self.handoff_canvas.trigger_handoff("Cortex", agent_name),
                        request_epoch,
                    )

                self._safe_after_if_epoch(
                    lambda: self._add_bubble(
                        "STEWARD", f"[{agent_name}] Routing: {action}",
                        color, align="left",
                    ),
                    request_epoch,
                )

                if self.live_feed:
                    self._safe_after_if_epoch(
                        lambda: self.live_feed.agent_working(
                            agent_name, f"Routing: {action}"
                        ),
                        request_epoch,
                    )

                if agent_type == AGENT_FILE_OP:
                    foldy_bubble = [None]
                    self._safe_after_if_epoch(
                        lambda: foldy_bubble.__setitem__(0, self._add_bubble(
                            "STEWARD", "Generating dry-run preview…",
                            NEON_CYAN, align="left", state="THINKING",
                        )),
                        request_epoch,
                    )

                    dialog_timeout = getattr(self, "dialog_timeout", 600)
                    confirm_timed_out = [False]

                    def confirm_callback(tool_name, args):
                        preview = f"Tool: {tool_name}\nArguments: {json.dumps(args, indent=2)}"
                        evt = threading.Event()
                        user_choice = [False]
                        def ask():
                            if not self._is_current_conversation_epoch(request_epoch):
                                evt.set()
                                return
                            user_choice[0] = messagebox.askyesno(
                                "Confirm File Operation",
                                f"The agent wants to execute:\n{preview}\n\nExecute?",
                            )
                            evt.set()
                        if not self._safe_after(ask):
                            evt.set()
                        if not evt.wait(timeout=dialog_timeout):
                            confirm_timed_out[0] = True
                            return False
                        return user_choice[0]

                    pending_plan_id = [None]
                    foldy_provider = {}
                    preview_result = self.file_agent.run(
                        action,
                        dry_run=True,
                        confirm_callback=confirm_callback,
                        plan_id_callback=lambda plan_id: pending_plan_id.__setitem__(0, plan_id),
                        provider_callback=foldy_provider.update,
                    )
                    if not self._is_current_conversation_epoch(request_epoch):
                        logger.info("[Chat] discarded stale file preview after conversation clear")
                        return
                    if confirm_timed_out[0]:
                        restore_input[0] = True
                        self.file_agent.discard_pending_plan()
                        logger.info("[Chat] approval dialog timed out; input restored")
                        if foldy_bubble[0]:
                            self._safe_after_if_epoch(
                                lambda: foldy_bubble[0].update_state("ERROR"),
                                request_epoch,
                            )
                        return

                    foldy_detail = self._report_provider(
                        "Foldy", request_epoch, provider_info=foldy_provider
                    )
                    preview_message = preview_result
                    if foldy_detail:
                        preview_message += f"\n\nHandled by {foldy_detail}"
                    
                    if foldy_bubble[0]:
                        self._safe_after_if_epoch(
                            lambda: foldy_bubble[0].set_message(preview_message),
                            request_epoch,
                        )
                        self._safe_after_if_epoch(
                            lambda: foldy_bubble[0].update_state("DONE"),
                            request_epoch,
                        )
                    else:
                        self._safe_after_if_epoch(
                            lambda: self._add_bubble(
                                "STEWARD", preview_message, NEON_CYAN, align="left", state="DONE",
                            ),
                            request_epoch,
                        )

                    if self.live_feed:
                        self._safe_after_if_epoch(
                            lambda: self.live_feed.agent_done(
                                "Foldy", foldy_detail or "Dry-run preview generated"
                            ),
                            request_epoch,
                        )

                    if pending_plan_id[0] is None:
                        logger.info("[Chat] No tool plan produced; awaiting user reply")
                        return

                    exec_evt = threading.Event()
                    exec_choice = [False]
                    def ask_exec():
                        if not self._is_current_conversation_epoch(request_epoch):
                            exec_evt.set()
                            return
                        exec_choice[0] = messagebox.askyesno(
                            "Execute Operations?",
                            "The above is a dry-run preview.\nExecute these operations?",
                        )
                        exec_evt.set()
                    if not self._safe_after(ask_exec):
                        exec_evt.set()
                    if not exec_evt.wait(timeout=dialog_timeout):
                        restore_input[0] = True
                        self.file_agent.discard_pending_plan()
                        logger.info("[Chat] approval dialog timed out; input restored")
                        return
                    if not self._is_current_conversation_epoch(request_epoch):
                        logger.info("[Chat] discarded stale file approval after conversation clear")
                        return

                    if exec_choice[0]:
                        exec_bubble = [None]
                        self._safe_after_if_epoch(
                            lambda: exec_bubble.__setitem__(0, self._add_bubble(
                                "STEWARD", "Executing operations…", NEON_CYAN, align="left", state="TOOL_USE",
                            )),
                            request_epoch,
                        )
                        try:
                            # Serialize the final epoch check with the plan claim.
                            # Clear takes the same lock before invalidating the
                            # pending plan, so a cleared conversation cannot pass
                            # the check and then begin a filesystem mutation.
                            with self._conversation_state_lock():
                                if not self._is_current_conversation_epoch(request_epoch):
                                    logger.info(
                                        "[Chat] discarded stale file execution after conversation clear"
                                    )
                                    return
                                exec_result = self.file_agent.execute_pending_plan(
                                    pending_plan_id[0]
                                )
                        except Exception as exc:
                            exec_result = f"Error: {exc}"

                        if exec_bubble[0]:
                            self._safe_after_if_epoch(
                                lambda: exec_bubble[0].set_message(exec_result),
                                request_epoch,
                            )
                            self._safe_after_if_epoch(
                                lambda: exec_bubble[0].update_state(
                                    "DONE" if not exec_result.startswith("Error") else "ERROR"
                                ),
                                request_epoch,
                            )
                        else:
                            self._safe_after_if_epoch(
                                lambda: self._add_bubble(
                                    "STEWARD", exec_result, NEON_CYAN, align="left",
                                    state="DONE" if not exec_result.startswith("Error") else "ERROR",
                                ),
                                request_epoch,
                            )

                        if self.live_feed:
                            self._safe_after_if_epoch(
                                lambda: self.live_feed.agent_done(
                                    "Foldy", foldy_detail or "Operations executed"
                                ),
                                request_epoch,
                            )
                    else:
                        self.file_agent.discard_pending_plan()
                        self._safe_after_if_epoch(
                            lambda: self._add_bubble(
                                "STEWARD", "Execution cancelled by user.",
                                TEXT_MUTED, align="left", state="DONE",
                            ),
                            request_epoch,
                        )

                elif agent_type == AGENT_PC_CONTROL:
                    self._safe_after_if_epoch(lambda: self._add_bubble(
                        "STEWARD",
                        f"[Click] PC control requested: {action}\n(Coming soon)",
                        NEON_LIME, align="left",
                    ), request_epoch)
                    if self.live_feed:
                        self._safe_after_if_epoch(
                            lambda: self.live_feed.agent_done("Click"),
                            request_epoch,
                        )
                elif agent_type == AGENT_RAG:
                    action_lower = action.lower()
                    is_ingest = any(kw in action_lower for kw in (
                        "ingest", "index", "learn", "remember", "scan",
                        "process", "read all", "add to knowledge base",
                    ))

                    scout_bubble = [None]
                    if is_ingest:
                        self._safe_after_if_epoch(lambda: scout_bubble.__setitem__(0, self._add_bubble(
                            "STEWARD", "Scout is ingesting documents...", NEON_BLUE,
                            align="left", state="THINKING",
                        )), request_epoch)
                    else:
                        self._safe_after_if_epoch(lambda: scout_bubble.__setitem__(0, self._add_bubble(
                            "STEWARD", "Scout is searching the archives...", NEON_BLUE,
                            align="left", state="THINKING",
                        )), request_epoch)

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
                            self._safe_after_if_epoch(
                                lambda: finish_scout(msg), request_epoch
                            )
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
                                    self._safe_after_if_epoch(
                                        lambda: finish_scout(formatted_answer), request_epoch
                                    )
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
                                    self._safe_after_if_epoch(
                                        lambda: finish_scout(formatted), request_epoch
                                    )
                            else:
                                self._safe_after_if_epoch(lambda: finish_scout(
                                    "No relevant documents found in the knowledge base."
                                ), request_epoch)
                    except Exception as exc:
                        logger.error("RAG error: %s", exc)
                        self._safe_after_if_epoch(
                            lambda: finish_scout(f"RAG Error: {exc}", "ERROR"),
                            request_epoch,
                        )

                    if self.live_feed:
                        self._safe_after_if_epoch(lambda: self.live_feed.agent_done(
                            "Scout", "Ingestion/Search complete"
                        ), request_epoch)
                elif agent_type == AGENT_CODING:
                    syntax_bubble = [None]
                    self._safe_after_if_epoch(lambda: syntax_bubble.__setitem__(0, self._add_bubble(
                        "STEWARD", "Syntax is working on your request...",
                        NEON_ORANGE, align="left", state="THINKING",
                    )), request_epoch)
                    try:
                        syntax_provider = {}
                        syntax_context = self._code_index_context(action)
                        syntax_kwargs = {
                            "original_request": user_msg,
                            "provider_callback": syntax_provider.update,
                        }
                        if syntax_context:
                            syntax_kwargs["code_context"] = syntax_context
                        syntax_response = self._get_coding_agent().handle_request(
                            action,
                            **syntax_kwargs,
                        )
                        syntax_detail = self._report_provider(
                            "Syntax", request_epoch, provider_info=syntax_provider
                        )
                        if syntax_bubble[0]:
                            self._safe_after_if_epoch(
                                lambda: syntax_bubble[0].set_message(syntax_response),
                                request_epoch,
                            )
                            self._safe_after_if_epoch(
                                lambda: syntax_bubble[0].update_state("DONE"),
                                request_epoch,
                            )
                        else:
                            self._safe_after_if_epoch(lambda: self._add_bubble(
                                "STEWARD", syntax_response, NEON_ORANGE,
                                align="left", state="DONE",
                            ), request_epoch)
                        if self.live_feed:
                            self._safe_after_if_epoch(lambda: self.live_feed.agent_done(
                                "Syntax", syntax_detail or "Coding assistance generated"
                            ), request_epoch)
                    except Exception as exc:
                        logger.error("Syntax coding error: %s", exc)
                        error_message = f"Syntax could not complete the coding request: {exc}"
                        if syntax_bubble[0]:
                            self._safe_after_if_epoch(
                                lambda: syntax_bubble[0].set_message(error_message),
                                request_epoch,
                            )
                            self._safe_after_if_epoch(
                                lambda: syntax_bubble[0].update_state("ERROR"),
                                request_epoch,
                            )
                        else:
                            self._safe_after_if_epoch(lambda: self._add_bubble(
                                "STEWARD", error_message, NEON_ORANGE,
                                align="left", state="ERROR",
                            ), request_epoch)
                elif agent_type == AGENT_GENERAL_CHAT:
                    # Send to Cortex for natural conversation.
                    cortex_bubble = [None]
                    self._safe_after_if_epoch(
                        lambda: cortex_bubble.__setitem__(0, self._add_bubble(
                            "STEWARD", "Thinking...",
                            NEON_PURPLE, align="left", state="THINKING",
                        )),
                        request_epoch,
                    )

                    try:
                        messages = self._conversation_messages(user_msg, request_epoch)
                        if messages is None:
                            logger.info("[Chat] discarded stale Cortex conversation request")
                            return

                        response = self.supervisor.api_manager.route_request(
                            messages=messages,
                            agent_name="Cortex",
                            require_tools=False,
                        )

                        cortex_response = response["choices"][0]["message"].get("content", "")
                        if not self._remember_general_chat_turn(
                            request_epoch, user_msg, cortex_response
                        ):
                            logger.info("[Chat] discarded stale Cortex conversation response")
                            return

                        def finish_conversation():
                            if not self._is_current_conversation_epoch(request_epoch):
                                return
                            bubble = cortex_bubble[0]
                            if bubble:
                                bubble.set_message(cortex_response)
                                bubble.update_state("DONE")
                            else:
                                self._add_bubble(
                                    "STEWARD", cortex_response,
                                    NEON_PURPLE, align="left", state="DONE",
                                )

                        self._safe_after_if_epoch(finish_conversation, request_epoch)
                        if self.live_feed:
                            self._safe_after_if_epoch(
                                lambda: self.live_feed.agent_done(
                                    "Cortex", "Response generated"
                                ),
                                request_epoch,
                            )
                    except Exception as e:
                        logger.error(f"Cortex conversation error: {e}")
                        error_message = f"Sorry, I encountered an error: {e}"

                        def finish_with_error():
                            if not self._is_current_conversation_epoch(request_epoch):
                                return
                            bubble = cortex_bubble[0]
                            if bubble:
                                bubble.set_message(error_message)
                                bubble.update_state("ERROR")
                            else:
                                self._add_bubble(
                                    "STEWARD", error_message,
                                    NEON_PURPLE, align="left", state="ERROR",
                                )

                        self._safe_after_if_epoch(finish_with_error, request_epoch)
                else:
                    feed = self.live_feed
                    if feed:
                        self._safe_after_if_epoch(lambda feed=feed: feed.agent_working(
                            "Cortex", "Delegating complex task"
                        ), request_epoch)
                    delegation_context = getattr(self, "_delegation_context", None)
                    if delegation_context is None:
                        delegation_context = threading.local()
                        self._delegation_context = delegation_context
                    previous_delegation_request = getattr(
                        delegation_context, "original_request", None
                    )
                    delegation_context.original_request = user_msg
                    try:
                        delegation_result = self.supervisor.delegate_task(
                            user_msg, ["Foldy", "Scout", "Click", "Syntax"]
                        )
                    finally:
                        delegation_context.original_request = previous_delegation_request
                    delegated_response = str(
                        delegation_result.get("response")
                        or delegation_result.get("final_response")
                        or "The delegated tasks returned no result."
                    ).strip()
                    delegation_state = (
                        "ERROR" if delegation_result.get("error") else "DONE"
                    )
                    self._safe_after_if_epoch(lambda response=delegated_response,
                                    state=delegation_state: self._add_bubble(
                        "STEWARD", response, NEON_PURPLE, align="left", state=state,
                    ), request_epoch)
                    delegation_results = delegation_result.get("results") or []
                    for result in delegation_results:
                        agent_name = result.get("agent", "Cortex")
                        detail = str(result.get("result", "Task complete"))
                        if feed:
                            self._safe_after_if_epoch(
                                lambda feed=feed, agent_name=agent_name,
                                detail=detail: feed.agent_done(agent_name, detail),
                                request_epoch,
                            )
                    if feed:
                        self._safe_after_if_epoch(lambda feed=feed: feed.agent_done(
                            "Cortex", "Hierarchical delegation complete"
                        ), request_epoch)

            except Exception as e:
                restore_input[0] = True
                logger.error(f"Chat processing error: {e}")
                self._safe_after_if_epoch(
                    lambda e=e: self._add_bubble(
                        "STEWARD", f"Error: {e}", "#FF5555", align="left",
                    ),
                    request_epoch,
                )
            finally:
                # Cleanup belongs to the request epoch.  A request that was
                # superseded by Clear must not re-enable controls or restore
                # text that now belong to the new conversation generation.
                self._safe_after_if_epoch(
                    lambda: self.send_btn.configure(state="normal"),
                    request_epoch,
                )
                if restore_input[0]:
                    self._safe_after_if_epoch(
                        lambda: self._restore_input(user_msg),
                        request_epoch,
                    )
                self._safe_after_if_epoch(
                    lambda: self._restore_return_key(request_epoch),
                    request_epoch,
                )

        threading.Thread(target=process, daemon=True).start()

    @staticmethod
    def _is_plan_first_request(agent_type):
        """Return whether a validated supervisor category may use Plan first."""
        return agent_type == AGENT_CODING

    def _plan_first_enabled(self):
        variable = getattr(self, "plan_first_var", None)
        if variable is None:
            return False
        try:
            return bool(variable.get())
        except Exception:
            return False

    def _get_plan_agent(self):
        """Return the injected plan agent or create one from the shared router."""
        if getattr(self, "plan_agent", None) is None:
            from agents.plan_agent import PlanAgent
            self.plan_agent = PlanAgent(api_manager=self.supervisor.api_manager)
        return self.plan_agent

    def _run_plan_first_workflow(self, user_msg, request_epoch, action):
        """Run Cortex architect work and publish a reviewable artifact."""
        try:
            self._safe_after_if_epoch(
                lambda: self._add_bubble(
                    "STEWARD", "Cortex is drafting a reviewable plan…",
                    NEON_PURPLE, align="left", state="THINKING",
                ),
                request_epoch,
            )
            if self.live_feed:
                self._safe_after_if_epoch(
                    lambda: self.live_feed.agent_working(
                        "Cortex", "Architecting implementation plan"
                    ),
                    request_epoch,
                )
            context = self._code_index_context(action)
            provider_info = {}
            created = self._get_plan_agent().architect(
                action,
                code_context=context,
                provider_callback=provider_info.update,
                is_current=lambda: self._is_current_conversation_epoch(request_epoch),
            )
            if not self._is_current_conversation_epoch(request_epoch):
                return
            self._report_provider(
                "Cortex", request_epoch, provider_info=provider_info
            )
            if self.live_feed:
                self._safe_after_if_epoch(
                    lambda: self.live_feed.agent_done(
                        "Cortex", f"Plan {created['plan_id']} ready for review"
                    ),
                    request_epoch,
                )
            self._safe_after_if_epoch(
                lambda: self._show_plan_review(
                    created["plan_id"], created["blueprint"], request_epoch
                ),
                request_epoch,
            )
        except Exception as exc:
            logger.error("Cortex architect error: %s", exc)
            self._safe_after_if_epoch(
                lambda exc=exc: self._add_bubble(
                    "STEWARD", f"Plan creation failed: {exc}",
                    "#FF5555", align="left", state="ERROR",
                ),
                request_epoch,
            )

    def _show_plan_review(self, plan_id, blueprint, request_epoch):
        """Render the plan and explicit approval controls on the UI thread."""
        self._add_bubble(
            "STEWARD", self._format_plan_review(plan_id, blueprint),
            NEON_PURPLE, align="left", state="DONE",
        )
        controls = ctk.CTkFrame(self.chat_display, fg_color="transparent")
        controls.pack(fill="x", padx=10, pady=4, anchor="w")

        def approve():
            if not self._is_current_conversation_epoch(request_epoch):
                return
            try:
                self._get_plan_agent().approve_plan(plan_id)
            except Exception as exc:
                self._add_bubble(
                    "STEWARD", f"Plan approval failed: {exc}",
                    "#FF5555", align="left", state="ERROR",
                )
                return
            approve_btn.configure(state="disabled")
            decline_btn.configure(state="disabled")
            threading.Thread(
                target=self._run_approved_plan_builder,
                args=(plan_id, request_epoch),
                daemon=True,
            ).start()

        def decline():
            if not self._is_current_conversation_epoch(request_epoch):
                return
            self._get_plan_agent().decline_plan(plan_id)
            approve_btn.configure(state="disabled")
            decline_btn.configure(state="disabled")
            self._add_bubble(
                "STEWARD", "Plan declined. No builder request was sent.",
                TEXT_MUTED, align="left", state="DONE",
            )

        approve_btn = ctk.CTkButton(
            controls, text="Approve", width=90, height=30,
            fg_color=NEON_LIME, hover_color="#8BD44C", command=approve,
        )
        approve_btn.pack(side="left", padx=(0, 8))
        decline_btn = ctk.CTkButton(
            controls, text="Decline", width=90, height=30,
            fg_color="#4A4A5A", hover_color="#5A5A6A", command=decline,
        )
        decline_btn.pack(side="left")

    @staticmethod
    def _format_plan_review(plan_id, blueprint):
        """Render a readable review summary without treating targets as paths."""
        lines = [f"Plan {plan_id}", f"Goal: {blueprint['goal']}", "Steps:"]
        for index, step in enumerate(blueprint["steps"], start=1):
            lines.append(f"{index}. {step['title']} — {step['detail']}")
            if step["targets"]:
                lines.append(
                    "   Informational targets: " + ", ".join(step["targets"])
                )
        lines.append("Risks: " + ("; ".join(blueprint["risks"]) or "None"))
        lines.append(
            "Validation: " + ("; ".join(blueprint["validation"]) or "None")
        )
        lines.append("Review this plan before any text-only builder request.")
        return "\n".join(lines)

    def _run_approved_plan_builder(self, plan_id, request_epoch):
        """Run the separate Syntax builder request after explicit approval."""
        if not self._is_current_conversation_epoch(request_epoch):
            return
        try:
            if self.live_feed:
                self._safe_after_if_epoch(
                    lambda: self.live_feed.agent_working(
                        "Syntax", f"Building reviewed plan {plan_id}"
                    ),
                    request_epoch,
                )
            provider_info = {}
            response = self._get_plan_agent().build_plan(
                plan_id, provider_callback=provider_info.update
            )
            self._report_provider(
                "Syntax", request_epoch, provider_info=provider_info
            )
            if not self._is_current_conversation_epoch(request_epoch):
                return
            self._safe_after_if_epoch(
                lambda: self._add_bubble(
                    "STEWARD", response, NEON_ORANGE, align="left", state="DONE",
                ),
                request_epoch,
            )
            if self.live_feed:
                self._safe_after_if_epoch(
                    lambda: self.live_feed.agent_done(
                        "Syntax", f"Reviewed plan {plan_id} elaborated as text"
                    ),
                    request_epoch,
                )
        except Exception as exc:
            logger.error("Syntax builder error: %s", exc)
            self._safe_after_if_epoch(
                lambda exc=exc: self._add_bubble(
                    "STEWARD", f"Builder failed: {exc}",
                    "#FF5555", align="left", state="ERROR",
                ),
                request_epoch,
            )

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
        delegation_context = getattr(self, "_delegation_context", None)
        original_request = (
            getattr(delegation_context, "original_request", None)
            if delegation_context is not None
            else None
        ) or getattr(self, "_delegation_original_request", "") or task
        syntax_kwargs = {"original_request": original_request}
        code_context = self._code_index_context(task)
        if code_context:
            syntax_kwargs["code_context"] = code_context
        return self._get_coding_agent().handle_request(task, **syntax_kwargs)

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

    def _report_provider(self, agent_name, epoch=None, provider_info=None):
        """Publish router metadata and return a short UI status string.

        ``provider_info`` is request-local metadata captured by the owning
        operation. The shared-agent fallback keeps direct helper calls and
        third-party integrations backward compatible.
        """
        if provider_info is None:
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
        schedule = (
            (lambda callback: self._safe_after_if_epoch(callback, epoch))
            if epoch is not None
            else self._safe_after
        )
        if self.provider_callback:
            schedule(
                lambda agent_name=agent_name, provider_info=provider_info:
                self.provider_callback(agent_name, provider_info)
            )
        if self.live_feed:
            for failover in provider_info.get("failovers", []):
                failed = failover.get("failed_provider", "Unknown")
                fallback = failover.get("fallback_provider", "Unknown")
                schedule(
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



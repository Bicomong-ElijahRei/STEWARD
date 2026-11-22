"""
OrganizerTab - Safety UI & Undo Slider (Phase 5).

Features:
- Visual dry-run preview table with per-file checkboxes
- Big glowing "Execute Changes" button
- Undo Slider timeline reading from steward_operations.json
"""

import customtkinter as ctk
from tkinter import messagebox
import os
import json
import threading
import logging

from agent.daemon import FileCreationHandler
from watchdog.observers import Observer
from gui.anim import SafeTick, lerp_color
from utils.helpers import sanitize_category

from core.theme import (
    BG_INPUT, TEXT_BRIGHT, TEXT_MUTED, BORDER_COLOR,
    NEON_PURPLE, NEON_CYAN, FONT_ROUNDED, FONT_MONO, CORNER_RADIUS,
)

logger = logging.getLogger(__name__)


class FilePreviewRow(ctk.CTkFrame):
    def __init__(self, parent, filename, source, destination, on_toggle, *args, **kwargs):
        super().__init__(
            parent,
            fg_color="#2A2A35",
            corner_radius=10,
            border_width=1,
            border_color=BORDER_COLOR,
            *args, **kwargs,
        )
        self.filename = filename
        self.source = source
        self.destination = destination
        self.selected = ctk.BooleanVar(value=True)
        self.on_toggle = on_toggle
        self.build()

    def build(self):
        self.checkbox = ctk.CTkCheckBox(
            self,
            text="",
            variable=self.selected,
            command=self._on_toggle,
            width=20,
            fg_color=NEON_CYAN,
            hover_color=NEON_CYAN,
        )
        self.checkbox.pack(side="left", padx=12, pady=8)

        name_label = ctk.CTkLabel(
            self, text=self.filename, font=FONT_ROUNDED, text_color=TEXT_BRIGHT, width=180
        )
        name_label.pack(side="left", padx=8)

        arrow = ctk.CTkLabel(self, text="→", font=FONT_MONO, text_color=TEXT_MUTED, width=20)
        arrow.pack(side="left")

        dest_label = ctk.CTkLabel(
            self, text=self.destination, font=FONT_MONO, text_color=TEXT_MUTED, anchor="w"
        )
        dest_label.pack(side="left", padx=8, fill="x", expand=True)

        src_label = ctk.CTkLabel(
            self, text=self.source, font=("Consolas", 9), text_color="#6E6E80", anchor="w"
        )
        src_label.pack(side="right", padx=12)

    def _on_toggle(self):
        if self.on_toggle:
            self.on_toggle(self.filename, self.selected.get())

    def is_selected(self):
        return self.selected.get()


class OrganizerTab(ctk.CTkFrame):
    def __init__(self, parent, file_agent, gui):
        super().__init__(parent, fg_color="transparent")
        self.file_agent = file_agent
        self.gui = gui
        self.observer = None
        self.daemon_handler = None
        self.daemon_running = False
        self.watched_var = ctk.StringVar(value=os.path.join(os.getcwd(), "Incoming"))
        self.dest_var = ctk.StringVar(value=os.path.join(os.getcwd(), "Sorted"))
        self.preview_rows = []
        self.pending_operations = []
        self._preview_generation = 0
        self.build()
        self.watched_var.trace_add("write", self._on_preview_paths_changed)
        self.dest_var.trace_add("write", self._on_preview_paths_changed)

    def build(self):
        header = ctk.CTkFrame(self, fg_color="transparent", height=50)
        header.pack(fill="x", padx=16, pady=(16, 8))
        header.pack_propagate(False)

        title = ctk.CTkLabel(
            header,
            text="📁 File Organizer",
            font=("Nunito", 16, "bold"),
            text_color=TEXT_BRIGHT,
        )
        title.pack(side="left")

        btn_row = ctk.CTkFrame(self, fg_color="transparent")
        btn_row.pack(fill="x", padx=16, pady=(0, 8))

        self.btn_preview = ctk.CTkButton(
            btn_row,
            text="Preview Incoming",
            width=130,
            height=36,
            corner_radius=10,
            font=FONT_ROUNDED,
            fg_color=NEON_PURPLE,
            hover_color="#A56EEA",
            command=self.preview_incoming,
        )
        self.btn_preview.pack(side="left", padx=(0, 8))

        self.btn_execute = ctk.CTkButton(
            btn_row,
            text="Execute Changes",
            width=130,
            height=36,
            corner_radius=10,
            font=("Nunito", 13, "bold"),
            fg_color="#00C853",
            hover_color="#00E676",
            command=self.execute_selected,
            state="disabled",
        )
        self.btn_execute.pack(side="left", padx=(0, 8))

        self.btn_undo = ctk.CTkButton(
            btn_row,
            text="Undo Last",
            width=100,
            height=36,
            corner_radius=10,
            font=FONT_ROUNDED,
            fg_color="#4A4A5A",
            hover_color="#5A5A6A",
            command=self.undo_last,
        )
        self.btn_undo.pack(side="left", padx=(0, 8))

        self.btn_redo = ctk.CTkButton(
            btn_row,
            text="Redo Last",
            width=100,
            height=36,
            corner_radius=10,
            font=FONT_ROUNDED,
            fg_color="#4A4A5A",
            hover_color="#5A5A6A",
            command=self.redo_last,
        )
        self.btn_redo.pack(side="left", padx=(0, 16))

        self.btn_rules = ctk.CTkButton(
            btn_row,
            text="Rules",
            width=90,
            height=36,
            corner_radius=10,
            font=FONT_ROUNDED,
            fg_color="#4A4A5A",
            hover_color="#5A5A6A",
            command=self.show_rules,
        )
        self.btn_rules.pack(side="left", padx=(0, 16))

        self.btn_start_daemon = ctk.CTkButton(
            btn_row,
            text="Start Daemon",
            width=110,
            height=36,
            corner_radius=10,
            font=FONT_ROUNDED,
            fg_color="#0284C7",
            hover_color="#0369A1",
            command=self.start_daemon,
        )
        self.btn_start_daemon.pack(side="left", padx=(0, 6))

        self.btn_stop_daemon = ctk.CTkButton(
            btn_row,
            text="Stop Daemon",
            width=110,
            height=36,
            corner_radius=10,
            font=FONT_ROUNDED,
            fg_color="#DC2626",
            hover_color="#B91C1C",
            command=self.stop_daemon,
        )
        self.btn_stop_daemon.pack(side="left", padx=(0, 12))

        self.daemon_status_label = ctk.CTkLabel(
            btn_row,
            text="Daemon: STOPPED",
            font=("Nunito", 11, "bold"),
            text_color="#9CA3AF",
        )
        self.daemon_status_label.pack(side="left")

        self.preview_container = ctk.CTkScrollableFrame(
            self, fg_color="#2A2A35", corner_radius=CORNER_RADIUS
        )
        self.preview_container.pack(fill="both", expand=True, padx=16, pady=(0, 8))

        table_header = ctk.CTkFrame(self.preview_container, fg_color="transparent")
        table_header.pack(fill="x", padx=10, pady=(10, 4))

        ctk.CTkLabel(table_header, text="✓", font=FONT_MONO, width=20).pack(side="left", padx=12)
        ctk.CTkLabel(table_header, text="File", font=("Nunito", 11, "bold"), text_color=TEXT_MUTED, width=180).pack(side="left", padx=8)
        ctk.CTkLabel(table_header, text="→", font=FONT_MONO, text_color=TEXT_MUTED, width=20).pack(side="left")
        ctk.CTkLabel(table_header, text="Destination", font=("Nunito", 11, "bold"), text_color=TEXT_MUTED).pack(side="left", padx=8)
        ctk.CTkLabel(table_header, text="Source", font=("Nunito", 11, "bold"), text_color=TEXT_MUTED).pack(side="right", padx=12)

        self.output = ctk.CTkTextbox(
            self, height=100, font=FONT_MONO, fg_color=BG_INPUT,
            border_color=BORDER_COLOR, corner_radius=10,
        )
        self.output.pack(fill="x", padx=16, pady=(0, 8))

        self.undo_slider_frame = ctk.CTkFrame(
            self, fg_color="#2A2A35", corner_radius=CORNER_RADIUS, height=80
        )
        self.undo_slider_frame.pack(fill="x", padx=16, pady=(0, 16))
        self.undo_slider_frame.pack_propagate(False)

        slider_label = ctk.CTkLabel(
            self.undo_slider_frame,
            text="⏪ Undo Timeline (drag backward to reverse actions)",
            font=FONT_ROUNDED,
            text_color=TEXT_MUTED,
        )
        slider_label.pack(pady=(10, 4))

        self.undo_slider = ctk.CTkSlider(
            self.undo_slider_frame,
            from_=0,
            to=100,
            number_of_steps=100,
        )
        self.undo_slider.bind("<ButtonRelease-1>", lambda e: self._on_undo_slider(self.undo_slider.get()))
        self.undo_slider.set(100)
        self.undo_slider.pack(fill="x", padx=20, pady=(0, 10))

    def _on_preview_paths_changed(self, *_args):
        """Invalidate any preview whose source or destination is now stale."""
        self._preview_generation = getattr(self, "_preview_generation", 0) + 1
        for row in self.preview_rows:
            row.destroy()
        self.preview_rows.clear()
        self.pending_operations.clear()
        self.btn_execute.configure(state="disabled")

    def preview_incoming(self):
        incoming = self.watched_var.get()
        dest = self.dest_var.get()
        self._preview_generation = getattr(self, "_preview_generation", 0) + 1
        generation = self._preview_generation

        if not os.path.exists(incoming):
            self._log(f"Incoming folder not found: {incoming}")
            return

        files = [f for f in os.listdir(incoming) if os.path.isfile(os.path.join(incoming, f))]
        if not files:
            self._log("No files in Incoming folder.")
            return

        for row in self.preview_rows:
            row.destroy()
        self.preview_rows.clear()
        self.pending_operations.clear()

        def process():
            planned = []
            from utils.rules_engine import RulesEngine

            rules_path = getattr(self.file_agent, "rules_path", None)
            rules_engine = None
            if isinstance(rules_path, (str, os.PathLike)):
                rules_engine = RulesEngine(rules_path)
            for f in files:
                filepath = os.path.join(incoming, f)
                category = None
                if rules_engine is not None:
                    category = rules_engine.match_rule(os.path.basename(filepath))
                if category is None:
                    content = self.file_agent.read_file_content(filepath)
                    messages = [
                        {"role": "system", "content": self.file_agent.system_prompt},
                        {"role": "user", "content": f"Categorise this file: {filepath}\nContent preview: {content[:500]}\nSuggest a category folder name."},
                    ]
                    try:
                        resp = self.file_agent.api_manager.route_request(
                            messages=messages, agent_name="Foldy"
                        )
                        category = sanitize_category(
                            resp["choices"][0]["message"]["content"], filepath
                        )
                    except Exception:
                        category = "Other"
                else:
                    category = sanitize_category(category, filepath)
                planned.append((f, filepath, os.path.join(dest, category, f)))
            self.after(0, lambda: self._render_preview(planned, generation=generation))

        threading.Thread(target=process, daemon=True).start()

    def _render_preview(self, planned, generation=None):
        if generation is not None and generation != getattr(
            self, "_preview_generation", generation
        ):
            self.btn_execute.configure(state="disabled")
            return
        for row in self.preview_rows:
            row.destroy()
        self.preview_rows.clear()
        self.pending_operations.clear()
        for filename, source, dest_path in planned:
            row = FilePreviewRow(
                self.preview_container,
                filename=filename,
                source=source,
                destination=dest_path,
                on_toggle=self._on_row_toggle,
            )
            row.pack(fill="x", padx=10, pady=3)
            self.preview_rows.append(row)
            self.pending_operations.append({
                "filename": filename,
                "source": source,
                "destination": dest_path,
                "selected": True,
            })
        self._log(f"Dry-run preview: {len(planned)} files ready to organize.")
        self.btn_execute.configure(state="normal")

    def _on_row_toggle(self, filename, selected):
        for op in self.pending_operations:
            if op["filename"] == filename:
                op["selected"] = selected
                break
        selected_count = sum(1 for op in self.pending_operations if op["selected"])
        self._log(f"Selected {selected_count}/{len(self.pending_operations)} files for execution.")

    def _pulse_execute_success(self):
        """Animate the execute button to bright green and back to signal success."""
        start_color = "#00C853"  # Normal success green
        end_color = "#00E676"    # Bright green pulse
        duration_ms = 400
        steps = 20
        interval = duration_ms // steps
        step = [0]

        def on_tick():
            step[0] += 1
            t = step[0] / steps
            # Pulse out and back: t goes 0 -> 1 -> 0
            pulse_t = 1.0 - abs(2.0 * t - 1.0) if t <= 1.0 else 0.0
            if pulse_t <= 0.0:
                self.btn_execute.configure(fg_color=start_color)
                return False  # Stop the tick
            
            current_color = lerp_color(start_color, end_color, pulse_t)
            self.btn_execute.configure(fg_color=current_color)
            return True

        SafeTick(self.btn_execute, interval, on_tick).start()

    def execute_selected(self):
        selected_ops = [op for op in self.pending_operations if op["selected"]]
        if not selected_ops:
            messagebox.showinfo("Nothing Selected", "Please select at least one file to execute.")
            return

        confirmed = messagebox.askyesno(
            "Execute Changes",
            f"Execute {len(selected_ops)} file operation(s)?\nThis will move files to their destinations.",
        )
        if not confirmed:
            self._log("Execution cancelled by user.")
            return

        self.btn_execute.configure(state="disabled")

        def process():
            success_count = 0
            for op in selected_ops:
                try:
                    result = self.file_agent.move_file(op["source"], op["destination"])
                    self.after(0, lambda r=result: self._log(f"[Execute] {r}"))
                    if isinstance(result, str) and result.startswith("Error"):
                        continue
                    if self.gui:
                        self.after(0, lambda op=op: self.gui.feed_agent_done("Foldy", f"Moved {op['filename']}"))
                    success_count += 1
                except Exception as e:
                    self.after(0, lambda e=e: self._log(f"[Execute] Error: {e}"))
            
            # Trigger animation on the main thread if anything succeeded
            if success_count > 0:
                self.after(0, self._pulse_execute_success)
                
            self.after(0, lambda: self._log(f"Execution complete. {success_count} files moved."))
            self.after(0, lambda: self.btn_execute.configure(state="normal"))

        threading.Thread(target=process, daemon=True).start()

    def show_rules(self):
        """Display the current deterministic categorization rules."""
        from utils.rules_engine import RulesEngine

        try:
            rules = RulesEngine(self.file_agent.rules_path).get_all_rules()
        except Exception as exc:
            messagebox.showerror("Rules Error", f"Could not load rules: {exc}")
            return

        if not rules:
            messagebox.showinfo(
                "Learning Rules",
                "No rules yet. STEWARD will learn from user overrides.",
            )
            return

        lines = []
        for rule in sorted(
            rules,
            key=lambda item: item.get("priority", 100),
            reverse=True,
        ):
            lines.append(
                f"Priority {rule.get('priority', 100)}: "
                f"{rule.get('pattern', '')} → {rule.get('target', '')}"
            )
        messagebox.showinfo("Learning Rules", "\n".join(lines))

    def undo_last(self):
        result = self.file_agent.undo_last()
        self._log(f"[Undo] {result}")
        self._refresh_slider()

    def redo_last(self):
        result = self.file_agent.redo_last()
        self._log(f"[Redo] {result}")
        self._refresh_slider()

    def _refresh_slider(self):
        log_path = self.file_agent.OPERATION_LOG_PATH
        if os.path.exists(log_path):
            try:
                with open(log_path, "r") as f:
                    log = json.load(f)
                total = len(log)
                undone = sum(1 for e in log if e.get("undone", False))
                if total > 0:
                    self.undo_slider.configure(to=total)
                    self.undo_slider.set(total - undone)
            except Exception:
                pass

    def _on_undo_slider(self, value):
        """When the undo slider moves, undo operations to match the slider position."""
        value = int(value)
        log_path = self.file_agent.OPERATION_LOG_PATH
        if not os.path.exists(log_path):
            return
        try:
            with open(log_path, "r") as f:
                log = json.load(f)
        except Exception:
            return

        total = len(log)
        undone = sum(1 for e in log if e.get("undone", False))
        active = total - undone

        # If slider moved backward (lower value), undo more operations
        if value < active:
            diff = active - value
            for _ in range(diff):
                result = self.file_agent.undo_last()
                self._log(f"[Undo Slider] {result}")
            self._refresh_slider()
        # If slider moved forward (higher value), redo operations
        elif value > active:
            diff = value - active
            for _ in range(diff):
                result = self.file_agent.redo_last()
                self._log(f"[Redo Slider] {result}")
            self._refresh_slider()

    def _log(self, message):
        self.output.insert("end", message + "\n")
        self.output.see("end")

    def start_daemon(self):
        if self.daemon_running:
            return
        watch_path = self.watched_var.get()
        dest_path = self.dest_var.get()
        if not os.path.exists(watch_path):
            messagebox.showerror("Error", f"Watched folder does not exist: {watch_path}")
            return

        event_handler = FileCreationHandler(self.file_agent, dest_path, self.gui)
        self.observer = Observer()
        self.observer.schedule(event_handler, watch_path, recursive=False)
        self.observer.start()
        self.daemon_handler = event_handler
        self.daemon_running = True
        self.daemon_status_label.configure(text="Daemon: RUNNING", text_color="#10B981")
        self._log(f"Daemon started. Watching: {watch_path}")

    def stop_daemon(self):
        if self.observer and self.daemon_running:
            self.observer.stop()
            self.observer.join()
            self.observer = None
        if self.daemon_handler is not None:
            self.daemon_handler.stop()
            self.daemon_handler = None
        if self.daemon_running:
            self.daemon_running = False
            self.daemon_status_label.configure(text="Daemon: STOPPED", text_color="#9CA3AF")
            self._log("Daemon stopped.")
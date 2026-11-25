"""Exact-diff review and guarded apply dialog for C3 patches."""

import os
import threading
import tkinter as tk
from tkinter import filedialog

import customtkinter as ctk

from agents.patch_review import PatchRefusal


class PatchReviewDialog(ctk.CTkToplevel):
    """Review one immutable patch artifact and apply it only after approval."""

    FEED_STATES = (
        "preview ready", "approved", "applying", "completed", "refused",
        "failed", "uncertain", "undone", "redone",
    )

    def __init__(
        self,
        master,
        manager,
        plan_id,
        epoch,
        live_feed=None,
        is_current=None,
        on_close=None,
        schedule_if_epoch=None,
    ):
        super().__init__(master)
        self.manager = manager
        self.plan_id = plan_id
        self.epoch = epoch
        self.live_feed = live_feed
        self.is_current = is_current or (lambda: True)
        self.on_close = on_close
        if schedule_if_epoch is None:
            raise ValueError("Patch Review requires an epoch-aware UI scheduler")
        self._epoch_scheduler = schedule_if_epoch
        self._closed = False
        self._request_in_flight = False
        self._propose_in_flight = False
        self._apply_in_flight = False
        self.preview = None
        self.approval = None
        self.last_result = None
        self.workspace_root = None
        self.targets = []
        self.title("Patch Review")
        self.geometry("980x700")
        self.minsize(800, 560)
        self._build()
        self.protocol("WM_DELETE_WINDOW", self.close)

    def _build(self):
        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(3, weight=1)
        heading = ctk.CTkLabel(
            self, text="Patch Review", font=("Nunito", 20, "bold")
        )
        heading.grid(row=0, column=0, sticky="w", padx=18, pady=(14, 6))
        selection = ctk.CTkFrame(self, fg_color="transparent")
        selection.grid(row=1, column=0, sticky="ew", padx=18, pady=6)
        selection.grid_columnconfigure(1, weight=1)
        self.workspace_var = tk.StringVar()
        self.target_var = tk.StringVar()
        self.choose_workspace_button = ctk.CTkButton(
            selection, text="Choose workspace", command=self._choose_workspace
        )
        self.choose_workspace_button.grid(row=0, column=0, padx=(0, 8))
        self.workspace_entry = ctk.CTkEntry(
            selection, textvariable=self.workspace_var, placeholder_text="Workspace"
        )
        self.workspace_entry.grid(row=0, column=1, sticky="ew", padx=(0, 8))
        self.targets_menu = ctk.CTkOptionMenu(
            selection, variable=self.target_var, values=["No targets"]
        )
        self.targets_menu.grid(row=0, column=2, sticky="ew")
        self.intent_entry = ctk.CTkEntry(
            self, placeholder_text="Describe one bounded structural change"
        )
        self.intent_entry.grid(row=2, column=0, sticky="ew", padx=18, pady=8)
        self.diff_text = ctk.CTkTextbox(self, font=("Consolas", 10), wrap="none")
        self.diff_text.grid(row=3, column=0, sticky="nsew", padx=18, pady=8)
        self.diff_text.configure(state="disabled")
        actions = ctk.CTkFrame(self, fg_color="transparent")
        actions.grid(row=4, column=0, sticky="ew", padx=18, pady=(8, 14))
        self.propose_button = ctk.CTkButton(
            actions, text="Generate preview", command=self._propose
        )
        self.propose_button.pack(side="left", padx=(0, 6))
        self.approve_button = ctk.CTkButton(
            actions, text="Approve", command=self._approve, state="disabled"
        )
        self.approve_button.pack(side="left", padx=6)
        self.apply_button = ctk.CTkButton(
            actions, text="Apply", command=self._apply, state="disabled"
        )
        self.apply_button.pack(side="left", padx=6)
        self.decline_button = ctk.CTkButton(
            actions, text="Decline", command=self._decline, state="disabled"
        )
        self.decline_button.pack(side="left", padx=6)
        self.cancel_button = ctk.CTkButton(
            actions, text="Cancel", command=self._cancel, state="disabled"
        )
        self.cancel_button.pack(side="left", padx=6)
        self.undo_button = ctk.CTkButton(
            actions, text="Undo", command=self._undo, state="disabled"
        )
        self.undo_button.pack(side="left", padx=6)
        self.redo_button = ctk.CTkButton(
            actions, text="Redo", command=self._redo, state="disabled"
        )
        self.redo_button.pack(side="left", padx=6)
        self.status_var = tk.StringVar(value="Select a workspace and target.")
        ctk.CTkLabel(
            self, textvariable=self.status_var, anchor="w", justify="left"
        ).grid(row=5, column=0, sticky="ew", padx=18, pady=(0, 14))

    @staticmethod
    def _emit_state(owner, state, detail=""):
        """Emit one truthful C3 state to the shared Live Feed."""
        if state not in PatchReviewDialog.FEED_STATES:
            raise ValueError("Unknown patch review state")
        owner.live_feed.add_event("Patch", state, detail=detail)

    def _current(self):
        return not self._closed and self.is_current()

    def _publish_if_current(self, epoch, callback):
        """Publish one worker result only while its conversation is current."""
        def guarded_callback():
            if not self._current():
                return
            callback()

        self._epoch_scheduler(guarded_callback, epoch)

    def _start_worker(self, operation, epoch, on_success, on_refused, on_failed):
        """Run one bounded manager request on a daemon worker thread."""
        def worker():
            try:
                result = operation()
            except PatchRefusal as exc:
                outcome = ("refused", exc)
            except Exception as exc:
                outcome = ("failed", exc)
            else:
                outcome = ("success", result)
            self._publish_if_current(
                epoch,
                lambda outcome=outcome: self._publish_worker_outcome(
                    outcome, on_success, on_refused, on_failed
                ),
            )

        threading.Thread(
            target=worker,
            name="patch-review-worker",
            daemon=True,
        ).start()

    def _publish_worker_outcome(self, outcome, on_success, on_refused, on_failed):
        kind, value = outcome
        if kind == "success":
            on_success(value)
        elif kind == "refused":
            on_refused(value)
        else:
            on_failed(value)

    def _restore_proposal_controls(self):
        """Restore controls after a proposal request ends."""
        self.propose_button.configure(state="normal")
        self.choose_workspace_button.configure(state="normal")
        self.workspace_entry.configure(state="normal")
        self.targets_menu.configure(state="normal")
        self.intent_entry.configure(state="normal")

    def _disable_request_inputs(self):
        """Disable controls whose values are captured by a request."""
        self.propose_button.configure(state="disabled")
        self.choose_workspace_button.configure(state="disabled")
        self.workspace_entry.configure(state="disabled")
        self.targets_menu.configure(state="disabled")
        self.intent_entry.configure(state="disabled")

    def _invalidate_local_state(self):
        """Discard dialog-owned pending state without touching the workspace."""
        self.preview = None
        self.approval = None

    def _choose_workspace(self):
        selected = filedialog.askdirectory(title="Select code workspace")
        if not selected:
            return
        self.workspace_root = os.path.realpath(selected)
        self.workspace_var.set(self.workspace_root)
        try:
            self.targets = self.manager.list_targets(self.workspace_root)
        except PatchRefusal:
            self.targets = []
        if self.targets:
            self.target_var.set(self.targets[0])
            self.targets_menu.configure(values=self.targets)
        else:
            self.target_var.set("")
            self.targets_menu.configure(values=["No admitted targets"])

    def _disable_all_actions(self):
        """Put the dialog in a terminal, non-mutating state."""
        for button in (
            self.choose_workspace_button,
            self.propose_button,
            self.approve_button,
            self.apply_button,
            self.decline_button,
            self.cancel_button,
            self.undo_button,
            self.redo_button,
        ):
            button.configure(state="disabled")
        self.workspace_entry.configure(state="disabled")
        self.targets_menu.configure(state="disabled")
        self.intent_entry.configure(state="disabled")

    def _set_status(self, state, detail):
        self.status_var.set(f"{state}: {detail}")
        if self.live_feed is not None:
            self._emit_state(self, state, detail)

    def _show_diff(self, diff_bytes):
        text = diff_bytes.decode("utf-8", errors="replace")
        self.diff_text.configure(state="normal")
        self.diff_text.delete("1.0", "end")
        self.diff_text.insert("1.0", text)
        self.diff_text.configure(state="disabled")

    def _propose(self):
        if not self._current() or not self.workspace_root or not self.target_var.get():
            self._set_status("refused", "Select a current workspace and admitted target.")
            return
        if self._request_in_flight:
            return
        workspace_root = self.workspace_root
        relative_path = self.target_var.get()
        intent = self.intent_entry.get()
        self._request_in_flight = True
        self._propose_in_flight = True
        self._disable_request_inputs()
        self.approve_button.configure(state="disabled")
        self.apply_button.configure(state="disabled")
        self.decline_button.configure(state="disabled")
        self.cancel_button.configure(state="disabled")

        def operation():
            return self.manager.propose_patch(
                plan_id=self.plan_id,
                workspace_root=workspace_root,
                relative_path=relative_path,
                intent=intent,
                epoch=self.epoch,
                is_current=self._current,
            )

        def succeeded(preview):
            self._propose_in_flight = False
            self._request_in_flight = False
            self.preview = preview
            self._restore_proposal_controls()
            self._show_diff(preview["diff_bytes"])
            self.approve_button.configure(state="normal")
            self.decline_button.configure(state="normal")
            self.cancel_button.configure(state="normal")
            self._set_status(
                "preview ready",
                f"{preview['patch_id']} — source {preview['source_sha256']} "
                f"output {preview['output_sha256']}",
            )

        def refused(_exc):
            self._propose_in_flight = False
            self._request_in_flight = False
            self.preview = None
            self.approval = None
            self._restore_proposal_controls()
            self.approve_button.configure(state="disabled")
            self.apply_button.configure(state="disabled")
            self.decline_button.configure(state="disabled")
            self.cancel_button.configure(state="disabled")
            self._set_status("refused", "Patch request was refused.")

        def failed(exc):
            self._propose_in_flight = False
            self._request_in_flight = False
            self.preview = None
            self.approval = None
            self._restore_proposal_controls()
            self.approve_button.configure(state="disabled")
            self.apply_button.configure(state="disabled")
            self.decline_button.configure(state="disabled")
            self.cancel_button.configure(state="disabled")
            self._set_status("failed", str(exc))

        self._start_worker(
            operation,
            self.epoch,
            succeeded,
            refused,
            failed,
        )

    def _approve(self):
        if not self.preview or not self._current():
            return
        try:
            self.approval = self.manager.approve_patch(
                self.preview["patch_id"], epoch=self.epoch
            )
        except PatchRefusal:
            self._set_status("refused", "Patch request was refused.")
            return
        self.approve_button.configure(state="disabled")
        self.apply_button.configure(state="normal")
        self._set_status("approved", self.approval["approval_id"])

    def _decline(self):
        if self.preview:
            try:
                self.manager.decline_patch(self.preview["patch_id"], epoch=self.epoch)
            except PatchRefusal:
                pass
        self.preview = None
        self.approval = None
        self._disable_all_actions()
        self._set_status("refused", "Proposal declined; no file was changed.")

    def _cancel(self):
        if self.preview:
            try:
                self.manager.cancel_patch(self.preview["patch_id"], epoch=self.epoch)
            except PatchRefusal:
                pass
        self.preview = None
        self.approval = None
        self._disable_all_actions()
        self._set_status("refused", "Proposal cancelled; no file was changed.")

    def _apply(self):
        if not self.approval or not self._current():
            return
        if self._request_in_flight or self._apply_in_flight:
            return
        approval_id = self.approval["approval_id"]
        self._request_in_flight = True
        self._apply_in_flight = True
        self._disable_request_inputs()
        self.apply_button.configure(state="disabled")
        self.approve_button.configure(state="disabled")
        self.decline_button.configure(state="disabled")
        self.cancel_button.configure(state="disabled")
        self._set_status("applying", "Applying the approved artifact.")

        def operation():
            return self.manager.apply_patch(approval_id, epoch=self.epoch)

        def succeeded(result):
            self._apply_in_flight = False
            self._request_in_flight = False
            self.last_result = result
            self.preview = None
            self.approval = None
            self.apply_button.configure(state="disabled")
            if result["state"] == "uncertain":
                self._disable_all_actions()
                self._set_status(
                    "uncertain",
                    f"source {result['source_sha256']} output {result['output_sha256']} "
                    f"backup {result['backup_reference']}. {result['guidance']}",
                )
                return
            self.approve_button.configure(state="disabled")
            self.decline_button.configure(state="disabled")
            self.cancel_button.configure(state="disabled")
            self._restore_proposal_controls()
            self.undo_button.configure(state="normal")
            self.redo_button.configure(state="normal")
            self._set_status(
                "completed",
                f"output {result['output_sha256']} backup {result['backup_reference']}",
            )

        def refused(_exc):
            self._apply_in_flight = False
            self._request_in_flight = False
            self.preview = None
            self.approval = None
            self._disable_all_actions()
            self._set_status("refused", "Patch request was refused.")

        def failed(exc):
            self._apply_in_flight = False
            self._request_in_flight = False
            self.preview = None
            self.approval = None
            self._disable_all_actions()
            self._set_status("failed", str(exc))

        self._start_worker(
            operation,
            self.epoch,
            succeeded,
            refused,
            failed,
        )

    def _undo(self):
        if not self.workspace_root or not self._current():
            return
        try:
            self.manager.undo_last(self.workspace_root, epoch=self.epoch)
        except PatchRefusal:
            self._set_status("refused", "Patch request was refused.")
            return
        self._set_status("undone", "The guarded pre-image was restored.")

    def _redo(self):
        if not self.workspace_root or not self._current():
            return
        try:
            self.manager.redo_last(self.workspace_root, epoch=self.epoch)
        except PatchRefusal:
            self._set_status("refused", "Patch request was refused.")
            return
        self._set_status("redone", "The guarded post-image was restored.")

    def close(self):
        """Invalidate pending review state before closing the dialog."""
        self._closed = True
        if self.preview:
            try:
                self.manager.cancel_patch(
                    self.preview["patch_id"], epoch=self.epoch
                )
            except PatchRefusal:
                pass
        try:
            self.manager.invalidate_pending_patch()
        except Exception:
            pass
        self._invalidate_local_state()
        if self.on_close:
            self.on_close()
        self.destroy()

    def destroy(self):
        """Invalidate local review state whenever Tk destroys the dialog."""
        self._closed = True
        self._invalidate_local_state()
        super().destroy()

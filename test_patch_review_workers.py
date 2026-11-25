"""Focused HYG-1 tests for Patch Review worker-thread lifecycle guards."""

import threading
import unittest
from unittest import mock

from agents.patch_review import PatchRefusal


class BlockingManager:
    """Manager double that records worker identity and blocks until released."""

    def __init__(self):
        self.propose_started = threading.Event()
        self.propose_release = threading.Event()
        self.apply_started = threading.Event()
        self.apply_release = threading.Event()
        self.propose_calls = 0
        self.apply_calls = 0
        self.propose_thread = None
        self.apply_thread = None
        self.cancel_calls = []
        self.invalidate_calls = 0

    def propose_patch(self, **kwargs):
        self.propose_calls += 1
        self.propose_thread = threading.current_thread()
        self.propose_started.set()
        self.propose_release.wait(3)
        return {
            "patch_id": "patch-1",
            "diff_bytes": b"--- a/sample.py\n+++ b/sample.py\n",
            "source_sha256": "source-hash",
            "output_sha256": "output-hash",
        }

    def apply_patch(self, approval_id, epoch):
        self.apply_calls += 1
        self.apply_thread = threading.current_thread()
        self.apply_started.set()
        self.apply_release.wait(3)
        return {
            "state": "completed",
            "source_sha256": "source-hash",
            "output_sha256": "output-hash",
            "backup_reference": "backup-1",
        }

    def cancel_patch(self, patch_id, epoch):
        self.cancel_calls.append((patch_id, epoch))

    def invalidate_pending_patch(self):
        self.invalidate_calls += 1


class RecordingFeed:
    def __init__(self):
        self.events = []

    def add_event(self, agent, status, progress=0.0, detail=""):
        self.events.append((agent, status, detail))


class PatchReviewWorkerTests(unittest.TestCase):
    """Exercise the dialog without constructing real Tk widgets."""

    def make_dialog(self, manager, current=None):
        from gui.patch_review_dialog import PatchReviewDialog

        dialog = PatchReviewDialog.__new__(PatchReviewDialog)
        dialog.manager = manager
        dialog.plan_id = "plan-1"
        dialog.epoch = 7
        dialog.live_feed = RecordingFeed()
        dialog.is_current = current or (lambda: True)
        dialog.on_close = None
        dialog.preview = None
        dialog.approval = None
        dialog.last_result = None
        dialog.workspace_root = "C:\\workspace"
        dialog.targets = ["sample.py"]
        dialog.target_var = mock.Mock()
        dialog.target_var.get.return_value = "sample.py"
        dialog.workspace_var = mock.Mock()
        dialog.intent_entry = mock.Mock()
        dialog.intent_entry.get.return_value = "Change the sample"
        dialog.status_var = mock.Mock()
        dialog.diff_text = mock.Mock()
        for name in (
            "choose_workspace_button",
            "propose_button",
            "approve_button",
            "apply_button",
            "decline_button",
            "cancel_button",
            "undo_button",
            "redo_button",
            "workspace_entry",
            "targets_menu",
        ):
            setattr(dialog, name, mock.Mock())
        dialog._closed = False
        dialog._request_in_flight = False
        dialog._propose_in_flight = False
        dialog._apply_in_flight = False
        scheduled = []
        scheduled_event = threading.Event()

        def schedule_if_epoch(callback, epoch):
            scheduled.append((callback, epoch))
            scheduled_event.set()

        dialog._epoch_scheduler = schedule_if_epoch
        return dialog, scheduled, scheduled_event

    def test_propose_runs_off_main_and_marshals_all_result_updates(self):
        manager = BlockingManager()
        dialog, scheduled, scheduled_event = self.make_dialog(manager)

        dialog._propose()

        self.assertTrue(manager.propose_started.wait(1))
        self.assertIsNot(manager.propose_thread, threading.current_thread())
        dialog.propose_button.configure.assert_called_with(state="disabled")
        dialog.diff_text.configure.assert_not_called()
        manager.propose_release.set()
        self.assertTrue(scheduled_event.wait(1))
        scheduled[0][0]()

        dialog.diff_text.insert.assert_called()
        self.assertEqual(
            ("Patch", "preview ready", mock.ANY),
            dialog.live_feed.events[-1],
        )

    def test_apply_runs_off_main_and_marshals_all_result_updates(self):
        manager = BlockingManager()
        dialog, scheduled, scheduled_event = self.make_dialog(manager)
        dialog.preview = {"patch_id": "patch-1"}
        dialog.approval = {"approval_id": "approval-1"}

        dialog._apply()

        self.assertTrue(manager.apply_started.wait(1))
        self.assertIsNot(manager.apply_thread, threading.current_thread())
        dialog.apply_button.configure.assert_called_with(state="disabled")
        self.assertIsNone(dialog.last_result)
        manager.apply_release.set()
        self.assertTrue(scheduled_event.wait(1))
        scheduled[0][0]()

        self.assertEqual("completed", dialog.last_result["state"])
        self.assertEqual(
            ("Patch", "completed", mock.ANY),
            dialog.live_feed.events[-1],
        )

    def test_stale_proposal_result_publishes_nothing(self):
        manager = BlockingManager()
        current = [True]
        dialog, scheduled, scheduled_event = self.make_dialog(
            manager, current=lambda: current[0]
        )

        dialog._propose()
        self.assertTrue(manager.propose_started.wait(1))
        manager.propose_release.set()
        self.assertTrue(scheduled_event.wait(1))
        current[0] = False
        scheduled[0][0]()

        self.assertIsNone(dialog.preview)
        self.assertIsNone(dialog.approval)
        dialog.diff_text.insert.assert_not_called()
        self.assertEqual([], dialog.live_feed.events)

    def test_stale_apply_result_publishes_no_result_approval_or_feed(self):
        manager = BlockingManager()
        current = [True]
        dialog, scheduled, scheduled_event = self.make_dialog(
            manager, current=lambda: current[0]
        )
        original_approval = {"approval_id": "approval-1"}
        dialog.preview = {"patch_id": "patch-1"}
        dialog.approval = original_approval

        dialog._apply()
        self.assertTrue(manager.apply_started.wait(1))
        manager.apply_release.set()
        self.assertTrue(scheduled_event.wait(1))
        current[0] = False
        scheduled[0][0]()

        self.assertIsNone(dialog.last_result)
        self.assertIs(original_approval, dialog.approval)
        self.assertEqual(
            [("Patch", "applying", "Applying the approved artifact.")],
            dialog.live_feed.events,
        )

    def test_second_apply_click_during_flight_is_refused_by_gui_guard(self):
        manager = BlockingManager()
        dialog, scheduled, scheduled_event = self.make_dialog(manager)
        dialog.preview = {"patch_id": "patch-1"}
        dialog.approval = {"approval_id": "approval-1"}

        dialog._apply()
        self.assertTrue(manager.apply_started.wait(1))
        dialog._apply()

        self.assertEqual(1, manager.apply_calls)
        manager.apply_release.set()
        self.assertTrue(scheduled_event.wait(1))
        scheduled[0][0]()

    def test_close_during_apply_invalidates_manager_and_discards_late_result(self):
        manager = BlockingManager()
        dialog, scheduled, scheduled_event = self.make_dialog(manager)
        dialog.preview = {"patch_id": "patch-1"}
        dialog.approval = {"approval_id": "approval-1"}
        dialog.destroy = mock.Mock()

        dialog._apply()
        self.assertTrue(manager.apply_started.wait(1))
        dialog.close()
        manager.apply_release.set()
        self.assertTrue(scheduled_event.wait(1))
        scheduled[0][0]()

        self.assertEqual([("patch-1", 7)], manager.cancel_calls)
        self.assertEqual(1, manager.invalidate_calls)
        self.assertIsNone(dialog.last_result)
        self.assertFalse(any(event[1] == "completed" for event in dialog.live_feed.events))

    def test_clear_during_proposal_invalidates_manager_and_discards_result(self):
        from gui.chat_tab import ChatTab

        manager = BlockingManager()
        chat = ChatTab.__new__(ChatTab)
        chat._conversation_epoch = 0
        chat._conversation_lock = threading.RLock()
        chat._general_chat_history = []
        chat._processing = False
        chat._code_index_epoch = 0
        chat._code_index_job_token = None
        chat._code_index_thread = None
        chat.chat_display = mock.Mock()
        chat.chat_display.winfo_children.return_value = []
        chat.file_agent = mock.Mock()
        chat.plan_agent = mock.Mock()
        chat.patch_review_manager = manager
        epoch = chat._conversation_epoch
        dialog, scheduled, scheduled_event = self.make_dialog(
            manager,
            current=lambda: chat._is_current_conversation_epoch(epoch),
        )
        chat._patch_review_dialog = dialog

        dialog._propose()
        self.assertTrue(manager.propose_started.wait(1))
        chat.clear_chat()
        manager.propose_release.set()
        self.assertTrue(scheduled_event.wait(1))
        scheduled[0][0]()

        self.assertEqual(1, manager.invalidate_calls)
        self.assertIsNone(dialog.preview)
        dialog.diff_text.insert.assert_not_called()
        self.assertEqual([], dialog.live_feed.events)

    def test_proposal_refusal_restores_propose_control(self):
        manager = mock.Mock()
        thread_ids = []

        def refuse(**kwargs):
            thread_ids.append(threading.current_thread())
            raise PatchRefusal("refused")

        manager.propose_patch.side_effect = refuse
        dialog, scheduled, scheduled_event = self.make_dialog(manager)

        dialog._propose()

        self.assertTrue(scheduled_event.wait(1))
        scheduled[0][0]()
        self.assertIsNot(thread_ids[0], threading.current_thread())
        dialog.propose_button.configure.assert_called_with(state="normal")
        self.assertIsNone(dialog.preview)
        self.assertEqual(
            ("Patch", "refused", "Patch request was refused."),
            dialog.live_feed.events[-1],
        )

    def test_apply_failure_restores_terminal_control_state(self):
        manager = mock.Mock()
        thread_ids = []

        def fail(approval_id, epoch):
            thread_ids.append(threading.current_thread())
            raise RuntimeError("apply failed")

        manager.apply_patch.side_effect = fail
        dialog, scheduled, scheduled_event = self.make_dialog(manager)
        dialog.preview = {"patch_id": "patch-1"}
        dialog.approval = {"approval_id": "approval-1"}

        dialog._apply()

        self.assertTrue(scheduled_event.wait(1))
        scheduled[0][0]()
        self.assertIsNot(thread_ids[0], threading.current_thread())
        self.assertIsNone(dialog.preview)
        self.assertIsNone(dialog.approval)
        dialog.apply_button.configure.assert_called_with(state="disabled")
        self.assertEqual(
            ("Patch", "failed", "apply failed"),
            dialog.live_feed.events[-1],
        )

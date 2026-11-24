"""C3-I3 acceptance tests for proposal, approval, GUI, and recovery."""

import ast
import base64
import dataclasses
import hashlib
import json
import os
import subprocess
import sys
import tempfile
import threading
import unittest
from unittest import mock

from agents.patch_review import (
    PATCH_REFUSAL_ERROR,
    PatchRefusal,
    PatchReviewManager,
)


SOURCE = b"# keep this comment\r\ndef alpha():\r\n    return 1\r\n"
PLAN_ID = "22222222-2222-4222-8222-222222222222"


def _sha256(value):
    return hashlib.sha256(value).hexdigest()


def _provider_response(content, tool_calls=None):
    message = {"content": content}
    if tool_calls is not None:
        message["tool_calls"] = tool_calls
    return {
        "choices": [{"message": message}],
        "_steward": {
            "provider": "TestProvider",
            "model": "test-model",
            "agent_name": "Syntax",
            "failovers": [],
        },
    }


def _proposal(relative_path="sample.py"):
    return {
        "relative_path": relative_path,
        "edits": [
            {
                "op": "replace_node",
                "anchor": {
                    "node_kind": "FunctionDef",
                    "qualified_name": "Module.alpha",
                    "occurrence": 0,
                },
                "replacement": "def alpha():\n    return 2",
            }
        ],
    }


class PatchReviewTestCase(unittest.TestCase):
    """Every mutable path is isolated under a temporary directory."""

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="steward_c3_i3_")
        self.base = os.path.realpath(self.temp.name)
        self.workspace = os.path.join(self.base, "workspace")
        self.incoming = os.path.join(self.base, "Incoming")
        self.sorted = os.path.join(self.base, "Sorted")
        self.patches = os.path.join(self.base, "appdata", "patches")
        self.backups = os.path.join(self.base, "appdata", "c3_backups")
        self.journal = os.path.join(self.base, "appdata", "steward_operations.json")
        os.makedirs(self.workspace)
        os.makedirs(self.incoming)
        os.makedirs(self.sorted)
        self.target = os.path.join(self.workspace, "sample.py")
        with open(self.target, "wb") as handle:
            handle.write(SOURCE)
        self.api = mock.Mock()
        self.api.route_request.return_value = _provider_response(
            json.dumps(_proposal())
        )
        self.plan_agent = mock.Mock()
        self.plan_agent.is_reviewed_plan.return_value = True
        self.plan_agent.reviewed_plan_ids.return_value = [PLAN_ID]
        self.manager = self.make_manager()

    def tearDown(self):
        self.temp.cleanup()

    def make_manager(self):
        return PatchReviewManager(
            api_manager=self.api,
            plan_agent=self.plan_agent,
            incoming_root=self.incoming,
            sorted_root=self.sorted,
            patches_dir=self.patches,
            backup_root=self.backups,
            operation_log_path=self.journal,
        )

    def propose(self, epoch=7):
        return self.manager.propose_patch(
            plan_id=PLAN_ID,
            workspace_root=self.workspace,
            relative_path="sample.py",
            intent="Change alpha to return 2",
            epoch=epoch,
        )

    def approve(self, preview, epoch=7):
        return self.manager.approve_patch(preview["patch_id"], epoch=epoch)

    def apply(self, preview, epoch=7):
        approval = self.approve(preview, epoch=epoch)
        return self.manager.apply_patch(approval["approval_id"], epoch=epoch)

    def target_bytes(self):
        with open(self.target, "rb") as handle:
            return handle.read()


class ProposalAndArtifactTests(PatchReviewTestCase):
    """Criteria 1, 2, 3, 5, 6, 8, 9, 13: safe proposal and artifact."""

    def test_criterion_1_real_file_application_and_approved_output_hash(self):
        preview = self.propose()
        result = self.apply(preview)
        expected = b"# keep this comment\r\ndef alpha():\r\n    return 2\r\n"
        self.assertEqual(expected, self.target_bytes())
        ast.parse(self.target_bytes().decode("utf-8"))
        self.assertEqual("committed", result["state"])
        self.assertEqual(_sha256(expected), result["output_sha256"])
        self.assertEqual(preview["output_sha256"], result["output_sha256"])

    def test_criterion_2_unrelated_bytes_and_comments_are_preserved(self):
        before = self.propose()
        self.apply(before)
        after = self.target_bytes()
        self.assertEqual(
            b"# keep this comment\r\ndef alpha():\r\n    return 2\r\n",
            after,
        )
        self.assertEqual(before["source_sha256"], _sha256(SOURCE))

    def test_criterion_3_malformed_oversized_and_tool_bearing_responses_are_rejected(self):
        cases = [
            "not json",
            json.dumps({"relative_path": "sample.py"}),
            json.dumps({**_proposal(), "tool_calls": []}),
            json.dumps({**_proposal(), "command": "python sample.py"}),
            "x" * (64 * 1024 + 1),
        ]
        for content in cases:
            with self.subTest(content=content[:30]):
                self.api.route_request.return_value = _provider_response(content)
                with self.assertRaises(PatchRefusal):
                    self.propose()
                self.assertEqual(SOURCE, self.target_bytes())
                self.assertFalse(
                    os.path.isdir(self.patches) and os.listdir(self.patches)
                )
        self.api.route_request.return_value = _provider_response(
            None, tool_calls=[{"type": "function", "function": {"name": "write"}}]
        )
        with self.assertRaises(PatchRefusal):
            self.propose()

    def test_criterion_5_provider_path_cannot_escape_or_select_absolute_path(self):
        for relative_path in (
            "/outside.py",
            "C:/outside.py",
            "../outside.py",
            "sub/../../outside.py",
        ):
            with self.subTest(relative_path=relative_path):
                self.api.route_request.return_value = _provider_response(
                    json.dumps(_proposal(relative_path))
                )
                with self.assertRaises(PatchRefusal):
                    self.propose()
                self.assertEqual(SOURCE, self.target_bytes())

    def test_criterion_6_artifact_is_immutable_complete_and_exactly_bound(self):
        preview = self.propose()
        artifact_path = os.path.join(self.patches, f"{preview['patch_id']}.json")
        with open(artifact_path, "rb") as handle:
            artifact_bytes = handle.read()
        artifact = json.loads(artifact_bytes.decode("utf-8"))
        self.assertEqual(preview["artifact_sha256"], _sha256(artifact_bytes))
        self.assertEqual(PLAN_ID, artifact["plan_id"])
        self.assertEqual(preview["workspace_fingerprint"], artifact["workspace_fingerprint"])
        self.assertEqual(preview["source_sha256"], artifact["source_hashes"][0])
        self.assertEqual(preview["output_sha256"], artifact["output_hashes"][0])
        self.assertEqual(
            preview["diff_bytes"],
            base64.b64decode(artifact["unified_diff_base64"]),
        )
        self.assertEqual(preview["diff_sha256"], _sha256(preview["diff_bytes"]))
        self.assertEqual(artifact["diff_sha256"], preview["diff_sha256"])
        self.assertIn("files", artifact["patch"])
        self.assertEqual(1, len(artifact["patch"]["files"]))

        approval = self.approve(preview)
        with open(artifact_path, "ab") as handle:
            handle.write(b"\n")
        with self.assertRaises(PatchRefusal):
            self.manager.apply_patch(approval["approval_id"], epoch=7)
        self.assertEqual(SOURCE, self.target_bytes())

    def test_criterion_6_staged_diff_must_equal_the_displayed_artifact_diff(self):
        preview = self.propose()
        approval = self.approve(preview)
        from agents import patch_applier as patch_applier_module

        real_stage = patch_applier_module.stage_patch

        def stage_with_different_diff(*args, **kwargs):
            staged = real_stage(*args, **kwargs)
            return dataclasses.replace(
                staged, unified_diff=staged.unified_diff + b"tampered diff\n"
            )

        with mock.patch(
            "agents.patch_applier.stage_patch", side_effect=stage_with_different_diff
        ):
            with self.assertRaises(PatchRefusal):
                self.manager.apply_patch(approval["approval_id"], epoch=7)
        self.assertEqual(SOURCE, self.target_bytes())

    def test_criterion_8_one_file_and_bounds_are_enforced(self):
        self.api.route_request.return_value = _provider_response(
            json.dumps({**_proposal(), "edits": [_proposal()["edits"][0]] * 21})
        )
        with self.assertRaises(PatchRefusal):
            self.propose()
        self.assertEqual(SOURCE, self.target_bytes())

    def test_criterion_4_organizer_roots_remain_unchanged(self):
        incoming_marker = os.path.join(self.incoming, "keep.txt")
        sorted_marker = os.path.join(self.sorted, "keep.txt")
        for marker in (incoming_marker, sorted_marker):
            with open(marker, "wb") as handle:
                handle.write(b"unchanged")
        preview = self.propose()
        self.apply(preview)
        for marker in (incoming_marker, sorted_marker):
            with open(marker, "rb") as handle:
                self.assertEqual(b"unchanged", handle.read())

    def test_criterion_9_provider_request_is_text_only_and_target_is_never_executed(self):
        self.propose()
        request = self.api.route_request.call_args.kwargs
        self.assertFalse(request["require_tools"])
        self.assertNotIn("tools", request)
        self.assertNotIn("subprocess", request["messages"][0]["content"])
        self.assertNotIn("execute", request["messages"][0]["content"].lower())

    def test_criterion_3_invalid_utf8_target_is_refused_without_provider_call(self):
        with open(self.target, "wb") as handle:
            handle.write(b"\xff\xfeinvalid")
        with self.assertRaises(PatchRefusal):
            self.propose()
        self.api.route_request.assert_not_called()
        self.assertEqual(b"\xff\xfeinvalid", self.target_bytes())

    def test_criterion_13_bom_and_crlf_are_preserved_outside_edited_span(self):
        with open(self.target, "wb") as handle:
            handle.write(b"\xef\xbb\xbf" + SOURCE)
        preview = self.propose()
        self.apply(preview)
        expected = (
            b"\xef\xbb\xbf# keep this comment\r\n"
            b"def alpha():\r\n    return 2\r\n"
        )
        self.assertEqual(expected, self.target_bytes())
        ast.parse(self.target_bytes().decode("utf-8-sig"))


class ApprovalAndRefusalTests(PatchReviewTestCase):
    """Criteria 6, 7, 10, 15: exact single-use epoch-bound approval."""

    def test_criterion_6_approval_receipt_binds_all_required_values(self):
        preview = self.propose()
        approval = self.approve(preview)
        self.assertEqual(preview["patch_id"], approval["patch_id"])
        self.assertEqual(preview["artifact_sha256"], approval["artifact_sha256"])
        self.assertEqual(PLAN_ID, approval["plan_id"])
        self.assertEqual(preview["workspace_fingerprint"], approval["workspace_fingerprint"])
        self.assertEqual(["sample.py"], approval["relative_paths"])
        self.assertEqual([preview["source_sha256"]], approval["source_hashes"])
        self.assertEqual([preview["output_sha256"]], approval["output_hashes"])
        self.assertEqual(preview["diff_sha256"], approval["diff_sha256"])
        self.assertNotEqual(preview["patch_id"], approval["approval_id"])
        self.assertGreaterEqual(len(approval["approval_id"]), 16)
        self.assertEqual(7, approval["epoch"])

    def test_criterion_7_unknown_stale_replayed_declined_cleared_and_wrong_epoch_refuse(self):
        with self.assertRaisesRegex(PatchRefusal, PATCH_REFUSAL_ERROR):
            self.manager.approve_patch(str(__import__("uuid").uuid4()), epoch=7)

        preview = self.propose()
        with self.assertRaisesRegex(PatchRefusal, PATCH_REFUSAL_ERROR):
            self.manager.approve_patch(preview["patch_id"], epoch=8)
        approval = self.approve(preview)
        self.manager.apply_patch(approval["approval_id"], epoch=7)
        with self.assertRaisesRegex(PatchRefusal, PATCH_REFUSAL_ERROR):
            self.manager.apply_patch(approval["approval_id"], epoch=7)

        declined = self.propose()
        self.manager.decline_patch(declined["patch_id"], epoch=7)
        with self.assertRaisesRegex(PatchRefusal, PATCH_REFUSAL_ERROR):
            self.manager.approve_patch(declined["patch_id"], epoch=7)

        cleared = self.propose()
        self.manager.invalidate_pending_patch()
        with self.assertRaisesRegex(PatchRefusal, PATCH_REFUSAL_ERROR):
            self.manager.approve_patch(cleared["patch_id"], epoch=7)

    def test_criterion_7_changed_source_artifact_or_workspace_is_refused(self):
        preview = self.propose()
        with open(self.target, "wb") as handle:
            handle.write(SOURCE + b"# external\n")
        with self.assertRaisesRegex(PatchRefusal, PATCH_REFUSAL_ERROR):
            self.approve(preview)

        with open(self.target, "wb") as handle:
            handle.write(SOURCE)
        preview = self.propose()
        artifact_path = os.path.join(self.patches, f"{preview['patch_id']}.json")
        with open(artifact_path, "ab") as handle:
            handle.write(b"x")
        with self.assertRaisesRegex(PatchRefusal, PATCH_REFUSAL_ERROR):
            self.approve(preview)

    def test_criterion_7_workspace_identity_change_is_refused(self):
        preview = self.propose()
        moved = self.workspace + "-moved"
        os.rename(self.workspace, moved)
        os.makedirs(self.workspace)
        with open(self.target, "wb") as handle:
            handle.write(SOURCE)
        with self.assertRaisesRegex(PatchRefusal, PATCH_REFUSAL_ERROR):
            self.manager.apply_patch(
                self.approve(preview)["approval_id"], epoch=7
            )
        self.assertEqual(SOURCE, self.target_bytes())

    def test_criterion_7_revoked_plan_review_is_refused_before_mutation(self):
        preview = self.propose()
        approval = self.approve(preview)
        self.plan_agent.is_reviewed_plan.return_value = False
        with self.assertRaisesRegex(PatchRefusal, PATCH_REFUSAL_ERROR):
            self.manager.apply_patch(approval["approval_id"], epoch=7)
        self.assertEqual(SOURCE, self.target_bytes())

    def test_criterion_7_revoked_plan_review_is_refused_before_approval(self):
        preview = self.propose()
        self.plan_agent.is_reviewed_plan.return_value = False
        with self.assertRaisesRegex(PatchRefusal, PATCH_REFUSAL_ERROR):
            self.approve(preview)
        self.assertEqual(SOURCE, self.target_bytes())

    def test_criterion_7_apply_with_wrong_epoch_is_refused(self):
        preview = self.propose()
        approval = self.approve(preview)
        with self.assertRaisesRegex(PatchRefusal, PATCH_REFUSAL_ERROR):
            self.manager.apply_patch(approval["approval_id"], epoch=8)
        self.assertEqual(SOURCE, self.target_bytes())

    def test_criterion_15_cancel_before_apply_invalidates_without_mutation(self):
        preview = self.propose()
        self.manager.cancel_patch(preview["patch_id"], epoch=7)
        with self.assertRaises(PatchRefusal):
            self.manager.approve_patch(preview["patch_id"], epoch=7)
        self.assertEqual(SOURCE, self.target_bytes())

    def test_lifecycle_unapproved_proposal_can_be_replaced(self):
        first = self.propose()
        second = self.propose()
        self.assertNotEqual(first["patch_id"], second["patch_id"])
        with self.assertRaises(PatchRefusal):
            self.manager.approve_patch(first["patch_id"], epoch=7)
        approval = self.approve(second)
        self.assertEqual(second["patch_id"], approval["patch_id"])

    def test_lifecycle_approved_proposal_cannot_be_replaced(self):
        preview = self.propose()
        self.approve(preview)
        with self.assertRaises(PatchRefusal):
            self.propose()
        self.assertEqual(SOURCE, self.target_bytes())

    def test_lifecycle_concurrent_approval_cannot_be_stranded_by_proposal(self):
        first = self.propose()
        original_route = self.api.route_request

        def route_and_approve(**kwargs):
            self.manager.approve_patch(first["patch_id"], epoch=7)
            return original_route(**kwargs)

        self.api.route_request.side_effect = route_and_approve
        with self.assertRaises(PatchRefusal):
            self.propose()
        self.assertIsNotNone(self.manager._approval)
        self.assertEqual(first["patch_id"], self.manager._approval["patch_id"])

    def test_lifecycle_failed_apply_clears_pending_and_approval(self):
        preview = self.propose()
        approval = self.approve(preview)
        with open(self.target, "wb") as handle:
            handle.write(SOURCE + b"# external\n")
        with self.assertRaises(PatchRefusal):
            self.manager.apply_patch(approval["approval_id"], epoch=7)
        with self.assertRaises(PatchRefusal):
            self.manager.approve_patch(preview["patch_id"], epoch=7)
        with self.assertRaises(PatchRefusal):
            self.manager.apply_patch(approval["approval_id"], epoch=7)

    def test_lifecycle_epoch_invalidation_during_generation_writes_no_pending_state(self):
        current = [True]
        self.api.route_request.side_effect = lambda **kwargs: (
            current.__setitem__(0, False)
            or _provider_response(json.dumps(_proposal()))
        )
        with self.assertRaises(PatchRefusal):
            self.manager.propose_patch(
                plan_id=PLAN_ID,
                workspace_root=self.workspace,
                relative_path="sample.py",
                intent="Change alpha to return 2",
                epoch=7,
                is_current=lambda: current[0],
            )
        self.assertIsNone(self.manager._pending)
        self.assertIsNone(self.manager._approval)
        self.assertEqual(SOURCE, self.target_bytes())

    def test_criterion_10_apply_intent_precedes_mutation_and_completion_follows(self):
        preview = self.propose()
        self.apply(preview)
        with open(self.journal, "r", encoding="utf-8") as handle:
            entries = json.load(handle)
        content = [e for e in entries if e.get("operation") == "content_edit"]
        self.assertEqual(1, len(content))
        self.assertEqual("committed", content[0]["state"])
        self.assertEqual(preview["patch_id"], content[0]["patch_id"])
        self.assertEqual(preview["output_sha256"], content[0]["post_sha256"])


class RecoveryAndGuiTests(PatchReviewTestCase):
    """Criteria 11, 12, 14, 15, 16: recovery and honest UI contract."""

    def test_criterion_11_undo_is_scoped_to_the_selected_workspace(self):
        first = self.propose()
        self.apply(first)

        other_workspace = os.path.join(self.base, "other_workspace")
        os.makedirs(other_workspace)
        other_target = os.path.join(other_workspace, "sample.py")
        other_source = b"def beta():\r\n    return 1\r\n"
        with open(other_target, "wb") as handle:
            handle.write(other_source)
        other_proposal = {
            "relative_path": "sample.py",
            "edits": [{
                "op": "replace_node",
                "anchor": {
                    "node_kind": "FunctionDef",
                    "qualified_name": "Module.beta",
                    "occurrence": 0,
                },
                "replacement": "def beta():\r\n    return 2",
            }],
        }
        self.api.route_request.return_value = _provider_response(
            json.dumps(other_proposal)
        )
        other_manager = PatchReviewManager(
            api_manager=self.api,
            plan_agent=self.plan_agent,
            incoming_root=self.incoming,
            sorted_root=self.sorted,
            patches_dir=os.path.join(self.base, "other_patches"),
            backup_root=self.backups,
            operation_log_path=self.journal,
        )
        other_preview = other_manager.propose_patch(
            plan_id=PLAN_ID,
            workspace_root=other_workspace,
            relative_path="sample.py",
            intent="Change beta to return 2",
            epoch=7,
        )
        other_manager.apply_patch(
            other_manager.approve_patch(other_preview["patch_id"], epoch=7)[
                "approval_id"
            ],
            epoch=7,
        )

        self.manager.undo_last(self.workspace, epoch=7)
        self.assertEqual(SOURCE, self.target_bytes())
        with open(other_target, "rb") as handle:
            self.assertEqual(
                b"def beta():\r\n    return 2\r\n", handle.read()
            )

    def test_criterion_11_undo_redo_are_hash_guarded(self):
        preview = self.propose()
        self.apply(preview)
        self.manager.undo_last(self.workspace, epoch=7)
        self.assertEqual(SOURCE, self.target_bytes())
        self.manager.redo_last(self.workspace, epoch=7)
        self.assertNotEqual(SOURCE, self.target_bytes())

        with open(self.target, "ab") as handle:
            handle.write(b"# external\n")
        with self.assertRaises(PatchRefusal):
            self.manager.undo_last(self.workspace, epoch=7)

    def test_criterion_12_uncertain_state_exposes_hashes_backup_and_no_force_action(self):
        preview = self.propose()
        approval = self.approve(preview)

        def fail_complete(*args, **kwargs):
            raise OSError("simulated journal completion failure")

        with mock.patch.object(self.manager, "_complete_mutation", fail_complete):
            result = self.manager.apply_patch(approval["approval_id"], epoch=7)
        self.assertEqual("uncertain", result["state"])
        self.assertIn("backup_reference", result)
        self.assertIn("source_sha256", result)
        self.assertIn("output_sha256", result)
        self.assertNotIn("force", result)
        self.assertFalse(hasattr(self.manager, "force_overwrite"))

    def test_criterion_14_cross_process_lock_path_is_used_by_apply_and_recovery(self):
        preview = self.propose()
        self.apply(preview)
        with mock.patch(
            "agents.patch_review.operation_journal_lock"
        ) as lock:
            self.manager.undo_last(self.workspace, epoch=7)
        lock.assert_called_once()
        self.assertEqual(self.journal, lock.call_args.args[0])

    def test_criterion_14_separate_processes_cannot_both_apply_the_same_target(self):
        preview = self.propose()
        artifact_path = os.path.join(self.patches, f"{preview['patch_id']}.json")
        script = (
            "import base64,json,sys;"
            "from agents.patch_applier import PatchApplier,PatchApplyError;"
            "a=PatchApplier(workspace_root=sys.argv[1], incoming_root=sys.argv[2], "
            "sorted_root=sys.argv[3], operation_log_path=sys.argv[4], "
            "backup_root=sys.argv[5]);"
            "artifact=json.load(open(sys.argv[6],encoding='utf-8'));"
            "encoded=base64.b64decode(artifact['patch_base64']);"
            "result=a.apply_patch(artifact['patch'],encoded);"
            "print(result.state)"
        )
        command = [
            sys.executable,
            "-c",
            script,
            self.workspace,
            self.incoming,
            self.sorted,
            self.journal,
            self.backups,
            artifact_path,
        ]
        processes = [
            subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            for _ in range(2)
        ]
        outcomes = [process.communicate(timeout=20) for process in processes]
        successes = sum(
            process.returncode == 0 and b"committed" in stdout
            for process, (stdout, _) in zip(processes, outcomes)
        )
        refusals = sum(
            process.returncode != 0 and b"PatchApplyError" in stderr
            for process, (_, stderr) in zip(processes, outcomes)
        )
        self.assertEqual(1, successes)
        self.assertEqual(1, refusals)
        self.assertEqual(
            b"# keep this comment\r\ndef alpha():\r\n    return 2\r\n",
            self.target_bytes(),
        )

    def test_criterion_14_journal_lock_contention_fails_closed_and_clears_state(self):
        from agent.journal_lock import JournalLockError

        preview = self.propose()
        approval = self.approve(preview)
        with mock.patch(
            "agents.patch_review.operation_journal_lock",
            side_effect=JournalLockError("held by another process"),
        ):
            with self.assertRaises(PatchRefusal):
                self.manager.apply_patch(approval["approval_id"], epoch=7)
        self.assertEqual(SOURCE, self.target_bytes())
        self.assertIsNone(self.manager._pending)
        self.assertIsNone(self.manager._approval)

    def test_criterion_15_gui_states_and_text_are_truthful(self):
        from gui.patch_review_dialog import PatchReviewDialog

        allowed = {
            "preview ready", "approved", "applying", "completed", "refused",
            "failed", "uncertain", "undone", "redone",
        }
        self.assertEqual(allowed, set(PatchReviewDialog.FEED_STATES))

        class Feed:
            def __init__(self):
                self.events = []

            def add_event(self, agent, status, progress=0.0, detail=""):
                self.events.append((agent, status, detail))

        fake = mock.Mock()
        fake.live_feed = Feed()
        PatchReviewDialog._emit_state(fake, "completed", "hash abc")
        self.assertEqual(("Patch", "completed", "hash abc"), fake.live_feed.events[-1])

    def test_criterion_15_decline_and_cancel_disable_every_action(self):
        from gui.patch_review_dialog import PatchReviewDialog

        for action in ("_decline", "_cancel"):
            with self.subTest(action=action):
                dialog = PatchReviewDialog.__new__(PatchReviewDialog)
                dialog.manager = mock.Mock()
                dialog.preview = {"patch_id": "patch"}
                dialog.approval = {"approval_id": "approval"}
                dialog.epoch = 7
                dialog.live_feed = None
                dialog.status_var = mock.Mock()
                action_names = (
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
                    "intent_entry",
                )
                for name in action_names:
                    setattr(dialog, name, mock.Mock())
                getattr(dialog, action)()
                for name in action_names:
                    getattr(dialog, name).configure.assert_called_with(
                        state="disabled"
                    )

    def test_criterion_15_closing_dialog_invalidates_pending_approval(self):
        from gui.patch_review_dialog import PatchReviewDialog

        dialog = PatchReviewDialog.__new__(PatchReviewDialog)
        dialog.manager = mock.Mock()
        dialog.preview = {"patch_id": "patch"}
        dialog.approval = {"approval_id": "approval"}
        dialog.epoch = 7
        dialog.on_close = mock.Mock()
        dialog.destroy = mock.Mock()
        dialog.close()
        dialog.manager.cancel_patch.assert_called_once_with("patch", epoch=7)
        dialog.on_close.assert_called_once_with()
        dialog.destroy.assert_called_once_with()

    def test_criterion_15_chat_clear_invalidates_patch_state_and_closes_dialog(self):
        from gui.chat_tab import ChatTab

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
        chat.patch_review_manager = mock.Mock()
        dialog = mock.Mock()
        chat._patch_review_dialog = dialog

        chat.clear_chat()

        self.assertEqual(1, chat._conversation_epoch)
        chat.patch_review_manager.invalidate_pending_patch.assert_called_once_with()
        dialog.destroy.assert_called_once_with()
        self.assertIsNone(chat._patch_review_dialog)

    def test_criterion_15_patch_button_uses_latest_reviewed_plan_and_epoch(self):
        from gui.chat_tab import ChatTab

        chat = ChatTab.__new__(ChatTab)
        chat.plan_agent = mock.Mock()
        chat.plan_agent.reviewed_plan_ids.return_value = ["old", PLAN_ID]
        chat.patch_review_manager = mock.Mock()
        chat.live_feed = None
        chat._conversation_epoch = 9
        chat._is_current_conversation_epoch = mock.Mock(return_value=True)
        dialog = mock.Mock()
        with mock.patch(
            "gui.patch_review_dialog.PatchReviewDialog", return_value=dialog
        ) as dialog_type:
            chat._show_patch_review_dialog()
        dialog_type.assert_called_once()
        kwargs = dialog_type.call_args.kwargs
        self.assertEqual(PLAN_ID, dialog_type.call_args.args[2])
        self.assertEqual(9, dialog_type.call_args.args[3])
        self.assertTrue(kwargs["is_current"]())
        self.assertIs(dialog, chat._patch_review_dialog)

    def test_criterion_16_source_contract_has_no_target_execution_or_subprocess(self):
        for module_name in ("agents.patch_review", "gui.patch_review_dialog"):
            module = __import__(module_name, fromlist=["*"])
            with open(module.__file__, "r", encoding="utf-8") as handle:
                tree = ast.parse(handle.read(), filename=module.__file__)
            called = {
                node.func.id
                for node in ast.walk(tree)
                if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
            }
            self.assertNotIn("exec", called)
            self.assertNotIn("eval", called)
            self.assertNotIn("compile", called)
            self.assertNotIn("__import__", called)


if __name__ == "__main__":
    unittest.main()

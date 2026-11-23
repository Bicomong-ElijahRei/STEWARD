"""Regression tests for filesystem mutation and operation-journal hardening."""

import os
import tempfile
import unittest
from unittest.mock import Mock, patch

from agents.file_agent import FileAgent


class FilesystemJournalHardeningTests(unittest.TestCase):
    def make_agent(self, root):
        log_path = os.path.join(root, "operations.json")
        with patch.object(FileAgent, "OPERATION_LOG_PATH", log_path):
            agent = FileAgent(api_manager=Mock(), root_path=root)
        agent.OPERATION_LOG_PATH = log_path
        return agent

    @staticmethod
    def write_file(path, content="content"):
        with open(path, "w", encoding="utf-8") as handle:
            handle.write(content)

    def prepare_workspace(self, root):
        incoming = os.path.join(root, "Incoming")
        sorted_dir = os.path.join(root, "Sorted")
        os.makedirs(incoming)
        os.makedirs(sorted_dir)
        return incoming, sorted_dir

    def test_existing_folder_is_not_claimed_as_owned(self):
        with tempfile.TemporaryDirectory(prefix="steward_folder_") as root:
            incoming, _ = self.prepare_workspace(root)
            existing = os.path.join(incoming, "Existing")
            os.makedirs(existing)
            self.write_file(os.path.join(existing, "keep.txt"), "keep")
            agent = self.make_agent(root)

            result = agent.create_folder("Incoming/Existing")

            self.assertIn("already exists", result)
            self.assertTrue(os.path.isfile(os.path.join(existing, "keep.txt")))
            self.assertFalse(any(
                entry.get("success") and entry.get("operation") == "create_folder"
                for entry in agent._operation_log
            ))

    def test_move_collision_preserves_both_files(self):
        with tempfile.TemporaryDirectory(prefix="steward_move_collision_") as root:
            incoming, sorted_dir = self.prepare_workspace(root)
            source = os.path.join(incoming, "source.txt")
            destination = os.path.join(sorted_dir, "destination.txt")
            self.write_file(source, "source")
            self.write_file(destination, "destination")
            agent = self.make_agent(root)

            result = agent.move_file("Incoming/source.txt", "Sorted/destination.txt")

            self.assertIn("already exists", result)
            with open(source, encoding="utf-8") as handle:
                self.assertEqual(handle.read(), "source")
            with open(destination, encoding="utf-8") as handle:
                self.assertEqual(handle.read(), "destination")
            self.assertFalse(any(entry.get("success") for entry in agent._operation_log))

    def test_whole_plan_rejects_destination_collision_before_first_mutation(self):
        with tempfile.TemporaryDirectory(prefix="steward_plan_collision_") as root:
            incoming, sorted_dir = self.prepare_workspace(root)
            first = os.path.join(incoming, "first.txt")
            second = os.path.join(incoming, "second.txt")
            occupied = os.path.join(sorted_dir, "occupied.txt")
            self.write_file(first)
            self.write_file(second)
            self.write_file(occupied, "occupied")
            agent = self.make_agent(root)
            plan = [
                {"function": {"name": "move_file", "arguments": {
                    "source": first, "destination": os.path.join(sorted_dir, "first.txt"),
                }}},
                {"function": {"name": "move_file", "arguments": {
                    "source": second, "destination": occupied,
                }}},
            ]

            results = agent._execute_tool_plan(plan, dry_run=False)

            self.assertTrue(any("Plan conflict" in result for result in results))
            self.assertTrue(os.path.exists(first))
            self.assertTrue(os.path.exists(second))
            with open(occupied, encoding="utf-8") as handle:
                self.assertEqual(handle.read(), "occupied")
            self.assertFalse(any(entry.get("success") for entry in agent._operation_log))

    def test_whole_plan_rejects_two_operations_targeting_same_destination(self):
        with tempfile.TemporaryDirectory(prefix="steward_plan_duplicate_") as root:
            incoming, sorted_dir = self.prepare_workspace(root)
            first = os.path.join(incoming, "first.txt")
            second = os.path.join(incoming, "second.txt")
            destination = os.path.join(sorted_dir, "same.txt")
            self.write_file(first)
            self.write_file(second)
            agent = self.make_agent(root)
            plan = [
                {"function": {"name": "move_file", "arguments": {
                    "source": first, "destination": destination,
                }}},
                {"function": {"name": "move_file", "arguments": {
                    "source": second, "destination": destination,
                }}},
            ]

            results = agent._execute_tool_plan(plan, dry_run=False)

            self.assertTrue(any("Plan conflict" in result for result in results))
            self.assertTrue(os.path.exists(first))
            self.assertTrue(os.path.exists(second))
            self.assertFalse(os.path.exists(destination))

    def test_late_collision_is_refused_without_overwrite(self):
        with tempfile.TemporaryDirectory(prefix="steward_late_collision_") as root:
            incoming, sorted_dir = self.prepare_workspace(root)
            source = os.path.join(incoming, "source.txt")
            destination = os.path.join(sorted_dir, "destination.txt")
            self.write_file(source, "source")
            agent = self.make_agent(root)

            def collide(_func_name, _safe_args):
                self.write_file(destination, "late collision")

            agent._mutation_hook = collide
            plan = [{"function": {"name": "move_file", "arguments": {
                "source": source, "destination": destination,
            }}}]

            results = agent._execute_tool_plan(plan, dry_run=False)

            self.assertTrue(any("already exists" in result for result in results))
            self.assertTrue(os.path.exists(source))
            with open(destination, encoding="utf-8") as handle:
                self.assertEqual(handle.read(), "late collision")

    def test_journal_failure_before_mutation_prevents_filesystem_change(self):
        with tempfile.TemporaryDirectory(prefix="steward_journal_before_") as root:
            incoming, sorted_dir = self.prepare_workspace(root)
            source = os.path.join(incoming, "source.txt")
            destination = os.path.join(sorted_dir, "destination.txt")
            self.write_file(source)
            agent = self.make_agent(root)
            with patch.object(
                agent, "_save_operation_log", side_effect=OSError("disk full")
            ):
                result = agent.move_file("Incoming/source.txt", "Sorted/destination.txt")

            self.assertIn("operation was not started", result)
            self.assertTrue(os.path.exists(source))
            self.assertFalse(os.path.exists(destination))

    def test_journal_failure_after_mutation_leaves_reloadable_uncertain_history(self):
        with tempfile.TemporaryDirectory(prefix="steward_journal_after_") as root:
            incoming, sorted_dir = self.prepare_workspace(root)
            source = os.path.join(incoming, "source.txt")
            destination = os.path.join(sorted_dir, "destination.txt")
            self.write_file(source)
            agent = self.make_agent(root)
            original_save = agent._save_operation_log
            calls = 0

            def fail_completion():
                nonlocal calls
                calls += 1
                if calls == 2:
                    raise OSError("journal write failed")
                return original_save()

            with patch.object(agent, "_save_operation_log", side_effect=fail_completion):
                result = agent.move_file("Incoming/source.txt", "Sorted/destination.txt")

            self.assertIn("could not be finalized", result)
            self.assertFalse(os.path.exists(source))
            self.assertTrue(os.path.exists(destination))
            reloaded = self.make_agent(root)
            self.assertEqual(reloaded._operation_log[-1]["state"], "uncertain")
            self.assertIn("manual reconciliation", reloaded._operation_log[-1]["result"])
            self.assertIn("Undo blocked", reloaded.undo_last())

    def test_intent_is_persisted_before_mutation_and_completion_after(self):
        with tempfile.TemporaryDirectory(prefix="steward_intent_order_") as root:
            incoming, sorted_dir = self.prepare_workspace(root)
            source = os.path.join(incoming, "source.txt")
            destination = os.path.join(sorted_dir, "destination.txt")
            self.write_file(source)
            agent = self.make_agent(root)
            original_save = agent._save_operation_log
            snapshots = []

            def capture_state():
                snapshots.append((os.path.exists(source), os.path.exists(destination)))
                return original_save()

            with patch.object(agent, "_save_operation_log", side_effect=capture_state):
                result = agent.move_file("Incoming/source.txt", "Sorted/destination.txt")

            self.assertIn("Moved", result)
            self.assertGreaterEqual(len(snapshots), 2)
            self.assertEqual(snapshots[0], (True, False))
            self.assertEqual(snapshots[-1], (False, True))

    def test_undo_refuses_to_overwrite_recreated_source(self):
        with tempfile.TemporaryDirectory(prefix="steward_undo_collision_") as root:
            incoming, sorted_dir = self.prepare_workspace(root)
            source = os.path.join(incoming, "source.txt")
            destination = os.path.join(sorted_dir, "destination.txt")
            self.write_file(source, "original")
            agent = self.make_agent(root)
            agent.move_file("Incoming/source.txt", "Sorted/destination.txt")
            self.write_file(source, "replacement")

            result = agent.undo_last()

            self.assertIn("refusing to overwrite", result)
            with open(source, encoding="utf-8") as handle:
                self.assertEqual(handle.read(), "replacement")
            with open(destination, encoding="utf-8") as handle:
                self.assertEqual(handle.read(), "original")

    def test_known_undo_refusal_can_be_retried_after_collision_is_cleared(self):
        with tempfile.TemporaryDirectory(prefix="steward_undo_retry_") as root:
            incoming, sorted_dir = self.prepare_workspace(root)
            source = os.path.join(incoming, "source.txt")
            destination = os.path.join(sorted_dir, "destination.txt")
            self.write_file(source, "original")
            agent = self.make_agent(root)
            agent.move_file("Incoming/source.txt", "Sorted/destination.txt")
            self.write_file(source, "replacement")

            first = agent.undo_last()
            self.assertIn("refusing to overwrite", first)
            os.remove(source)
            second = agent.undo_last()

            self.assertIn("Undid move", second)
            self.assertTrue(os.path.exists(source))
            self.assertFalse(os.path.exists(destination))

    def test_legacy_folder_undo_is_refused(self):
        with tempfile.TemporaryDirectory(prefix="steward_legacy_folder_") as root:
            incoming, _ = self.prepare_workspace(root)
            folder = os.path.join(incoming, "Legacy")
            os.makedirs(folder)
            agent = self.make_agent(root)
            agent._operation_log = [{
                "id": "legacy-1", "timestamp": "legacy", "operation": "create_folder",
                "source": folder, "destination": None, "result": "Created folder",
                "success": True, "undone": False,
            }]

            result = agent.undo_last()

            self.assertIn("no ownership evidence", result)
            self.assertTrue(os.path.isdir(folder))

    def test_same_name_rename_is_not_successful_history(self):
        with tempfile.TemporaryDirectory(prefix="steward_noop_rename_") as root:
            incoming, sorted_dir = self.prepare_workspace(root)
            source = os.path.join(incoming, "source.txt")
            destination = os.path.join(sorted_dir, "destination.txt")
            self.write_file(source, "original")
            agent = self.make_agent(root)

            moved = agent.move_file("Incoming/source.txt", "Sorted/destination.txt")
            renamed = agent.rename_file(
                "Sorted/destination.txt", os.path.basename(destination)
            )

            self.assertIn("Moved", moved)
            self.assertIn("No-op", renamed)
            with open(destination, encoding="utf-8") as handle:
                self.assertEqual(handle.read(), "original")
            self.assertFalse(any(
                entry.get("operation") == "rename" and entry.get("success")
                for entry in agent._operation_log
            ))
            self.assertIn("Undid move", agent.undo_last())
            self.assertTrue(os.path.exists(source))
            self.assertFalse(os.path.exists(destination))

    def test_move_source_removal_failure_with_verified_rollback_is_failed(self):
        with tempfile.TemporaryDirectory(prefix="steward_move_rollback_") as root:
            incoming, sorted_dir = self.prepare_workspace(root)
            source = os.path.join(incoming, "source.txt")
            destination = os.path.join(sorted_dir, "destination.txt")
            self.write_file(source, "original")
            agent = self.make_agent(root)
            original_remove = os.remove

            def fail_source_remove(path):
                if os.path.normcase(os.path.abspath(path)) == os.path.normcase(source):
                    raise PermissionError("source removal failed")
                return original_remove(path)

            with patch("agent.tools.os.remove", side_effect=fail_source_remove):
                result = agent.move_file(
                    "Incoming/source.txt", "Sorted/destination.txt"
                )

            self.assertIn("Error", result)
            self.assertTrue(os.path.exists(source))
            self.assertFalse(os.path.exists(destination))
            self.assertEqual(agent._operation_log[-1]["state"], "failed")
            self.assertFalse(agent._operation_log[-1]["success"])

    def test_move_source_removal_and_cleanup_failure_is_uncertain(self):
        with tempfile.TemporaryDirectory(prefix="steward_move_uncertain_") as root:
            incoming, sorted_dir = self.prepare_workspace(root)
            source = os.path.join(incoming, "source.txt")
            destination = os.path.join(sorted_dir, "destination.txt")
            self.write_file(source, "original")
            agent = self.make_agent(root)
            original_remove = os.remove

            def fail_source_and_cleanup(path):
                normalized = os.path.normcase(os.path.abspath(path))
                if normalized in {
                    os.path.normcase(source), os.path.normcase(destination),
                }:
                    raise PermissionError("source and cleanup removal failed")
                return original_remove(path)

            with patch("agent.tools.os.remove", side_effect=fail_source_and_cleanup):
                result = agent.move_file(
                    "Incoming/source.txt", "Sorted/destination.txt"
                )

            self.assertIn("Error", result)
            self.assertTrue(os.path.exists(source))
            self.assertTrue(os.path.exists(destination))
            self.assertEqual(agent._operation_log[-1]["state"], "uncertain")
            self.assertFalse(agent._operation_log[-1]["success"])
            self.assertIn("Undo blocked", agent.undo_last())

    def test_rename_source_removal_failure_with_verified_rollback_is_failed(self):
        with tempfile.TemporaryDirectory(prefix="steward_rename_rollback_") as root:
            incoming, _ = self.prepare_workspace(root)
            source = os.path.join(incoming, "source.txt")
            destination = os.path.join(incoming, "renamed.txt")
            self.write_file(source, "original")
            agent = self.make_agent(root)
            original_remove = os.remove

            def fail_source_remove(path):
                if os.path.normcase(os.path.abspath(path)) == os.path.normcase(source):
                    raise PermissionError("source removal failed")
                return original_remove(path)

            with patch("agent.tools.os.remove", side_effect=fail_source_remove):
                result = agent.rename_file("Incoming/source.txt", "renamed.txt")

            self.assertIn("Error", result)
            self.assertTrue(os.path.exists(source))
            self.assertFalse(os.path.exists(destination))
            self.assertEqual(agent._operation_log[-1]["state"], "failed")
            self.assertFalse(agent._operation_log[-1]["success"])

    def test_rename_source_removal_and_cleanup_failure_is_uncertain(self):
        with tempfile.TemporaryDirectory(prefix="steward_rename_uncertain_") as root:
            incoming, _ = self.prepare_workspace(root)
            source = os.path.join(incoming, "source.txt")
            destination = os.path.join(incoming, "renamed.txt")
            self.write_file(source, "original")
            agent = self.make_agent(root)
            original_remove = os.remove

            def fail_source_and_cleanup(path):
                normalized = os.path.normcase(os.path.abspath(path))
                if normalized in {
                    os.path.normcase(source), os.path.normcase(destination),
                }:
                    raise PermissionError("source and cleanup removal failed")
                return original_remove(path)

            with patch("agent.tools.os.remove", side_effect=fail_source_and_cleanup):
                result = agent.rename_file("Incoming/source.txt", "renamed.txt")

            self.assertIn("Error", result)
            self.assertTrue(os.path.exists(source))
            self.assertTrue(os.path.exists(destination))
            self.assertEqual(agent._operation_log[-1]["state"], "uncertain")
            self.assertFalse(agent._operation_log[-1]["success"])
            self.assertIn("Undo blocked", agent.undo_last())

    def test_folder_failure_before_change_is_ordinary_failed_history(self):
        with tempfile.TemporaryDirectory(prefix="steward_folder_no_change_") as root:
            incoming, _ = self.prepare_workspace(root)
            target = os.path.join(incoming, "New", "Child")
            agent = self.make_agent(root)

            with patch("agent.tools.os.mkdir", side_effect=PermissionError("mkdir failed")):
                result = agent.create_folder("Incoming/New/Child")

            self.assertIn("Error", result)
            self.assertFalse(os.path.exists(os.path.join(incoming, "New")))
            self.assertFalse(os.path.exists(target))
            self.assertEqual(agent._operation_log[-1]["state"], "failed")
            self.assertFalse(agent._operation_log[-1]["success"])
            self.assertFalse(agent._operation_log[-1].get("created_paths"))

    def test_partial_folder_creation_preserves_evidence_and_is_uncertain(self):
        with tempfile.TemporaryDirectory(prefix="steward_folder_partial_") as root:
            incoming, _ = self.prepare_workspace(root)
            parent = os.path.join(incoming, "New")
            target = os.path.join(parent, "Child")
            agent = self.make_agent(root)
            original_mkdir = os.mkdir

            def fail_child_mkdir(path, *args, **kwargs):
                if os.path.normcase(os.path.abspath(path)) == os.path.normcase(target):
                    raise PermissionError("child mkdir failed")
                return original_mkdir(path, *args, **kwargs)

            with patch("agent.tools.os.mkdir", side_effect=fail_child_mkdir):
                result = agent.create_folder("Incoming/New/Child")

            self.assertIn("Error", result)
            self.assertTrue(os.path.isdir(parent))
            self.assertFalse(os.path.exists(target))
            entry = agent._operation_log[-1]
            self.assertEqual(entry["state"], "uncertain")
            self.assertFalse(entry["success"])
            self.assertEqual(entry.get("created_paths"), [parent])
            ownership = entry.get("folder_ownership")
            self.assertEqual(len(ownership), 1)
            self.assertEqual(ownership[0]["path"], parent)
            self.assertIn("Undo blocked", agent.undo_last())

    def _assert_folder_move_conflict_is_rejected(self, folder_first):
        with tempfile.TemporaryDirectory(prefix="steward_folder_move_conflict_") as root:
            incoming, sorted_dir = self.prepare_workspace(root)
            source = os.path.join(incoming, "source.txt")
            target = os.path.join(sorted_dir, "Category")
            self.write_file(source, "original")
            agent = self.make_agent(root)
            folder_call = {"function": {"name": "create_folder", "arguments": {
                "path": target,
            }}}
            move_call = {"function": {"name": "move_file", "arguments": {
                "source": source, "destination": target,
            }}}
            plan = [folder_call, move_call] if folder_first else [move_call, folder_call]

            agent._pending_plan = plan
            agent._pending_plan_id = "folder-move-conflict"
            results = agent.execute_pending_plan("folder-move-conflict")

            self.assertIn("Plan conflict", results)
            self.assertTrue(os.path.exists(source))
            self.assertFalse(os.path.exists(target))
            self.assertFalse(any(entry.get("success") for entry in agent._operation_log))

    def test_whole_plan_rejects_folder_move_conflict_folder_first(self):
        self._assert_folder_move_conflict_is_rejected(folder_first=True)

    def test_whole_plan_rejects_folder_move_conflict_move_first(self):
        self._assert_folder_move_conflict_is_rejected(folder_first=False)

    def _assert_folder_rename_conflict_is_rejected(self, folder_first):
        with tempfile.TemporaryDirectory(prefix="steward_folder_rename_conflict_") as root:
            incoming, _ = self.prepare_workspace(root)
            source = os.path.join(incoming, "source.txt")
            target = os.path.join(incoming, "renamed.txt")
            self.write_file(source, "original")
            agent = self.make_agent(root)
            folder_call = {"function": {"name": "create_folder", "arguments": {
                "path": target,
            }}}
            rename_call = {"function": {"name": "rename_file", "arguments": {
                "old_path": source, "new_name": "renamed.txt",
            }}}
            plan = [folder_call, rename_call] if folder_first else [rename_call, folder_call]

            agent._pending_plan = plan
            agent._pending_plan_id = "folder-rename-conflict"
            results = agent.execute_pending_plan("folder-rename-conflict")

            self.assertIn("Plan conflict", results)
            self.assertTrue(os.path.exists(source))
            self.assertFalse(os.path.exists(target))
            self.assertFalse(any(entry.get("success") for entry in agent._operation_log))

    def test_whole_plan_rejects_folder_rename_conflict_folder_first(self):
        self._assert_folder_rename_conflict_is_rejected(folder_first=True)

    def test_whole_plan_rejects_folder_rename_conflict_rename_first(self):
        self._assert_folder_rename_conflict_is_rejected(folder_first=False)

    def test_whole_plan_allows_folder_parent_and_file_child(self):
        with tempfile.TemporaryDirectory(prefix="steward_folder_child_") as root:
            incoming, _ = self.prepare_workspace(root)
            source = os.path.join(incoming, "source.txt")
            folder = os.path.join(incoming, "Category")
            destination = os.path.join(folder, "source.txt")
            self.write_file(source, "original")
            agent = self.make_agent(root)
            plan = [
                {"function": {"name": "create_folder", "arguments": {"path": folder}}},
                {"function": {"name": "move_file", "arguments": {
                    "source": source, "destination": destination,
                }}},
            ]

            results = agent._execute_tool_plan(plan, dry_run=False)

            self.assertFalse(any("Plan conflict" in result for result in results))
            self.assertTrue(os.path.isdir(folder))
            self.assertTrue(os.path.exists(destination))
            self.assertFalse(os.path.exists(source))


if __name__ == "__main__":
    unittest.main()


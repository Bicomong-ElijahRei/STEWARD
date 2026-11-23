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


if __name__ == "__main__":
    unittest.main()


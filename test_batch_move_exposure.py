import os
import tempfile
import unittest
from unittest.mock import patch
from agent import batch_move_core as core
from agents.file_agent import FileAgent

class BatchMoveExposureTests(unittest.TestCase):
    def make_agent(self, root):
        with patch.object(FileAgent, "OPERATION_LOG_PATH", os.path.join(root, "operations.json")):
            agent = FileAgent(api_manager=object(), root_path=root)
        agent.OPERATION_LOG_PATH = os.path.join(root, "operations.json")
        return agent
    def write(self, root, name, content=b"x"):
        path = os.path.join(root, name); os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "wb") as handle: handle.write(content)
        return path
    def bind(self, agent, pattern="*.txt", destination="Sorted"):
        return agent._bind_cleanup_calls([{"function": {"name": "batch_move", "arguments": {"source_pattern": pattern, "destination_folder": destination}}}])[0]
    def test_schema_and_negative_dispatch(self):
        with tempfile.TemporaryDirectory() as tmp:
            os.makedirs(os.path.join(tmp, "Incoming")); os.makedirs(os.path.join(tmp, "Sorted")); agent = self.make_agent(tmp)
            names = {item["function"]["name"] for item in agent._get_tool_definitions()}; self.assertEqual(len(names), 13); self.assertIn("batch_move", names)
            result = agent._execute_tool_plan([{"function": {"name": "nope", "arguments": {}}}], dry_run=False); self.assertIn("Unapproved tool", result[0])
    def test_pattern_refusals_and_recursive_refusal(self):
        with tempfile.TemporaryDirectory() as tmp:
            agent = self.make_agent(tmp)
            for pattern in (os.path.abspath("*.txt"), "C:\\Windows\\*.txt", "\\\\server\\share\\*.txt", "..\\*.txt", "**/*.txt", "x" * (core.MAX_PATTERN_LENGTH + 1)):
                with self.assertRaises(core.BatchMoveRefusal): core.enumerate_and_bind(pattern, os.path.join(tmp, "Sorted"), agent.allowed_roots)
    def test_preview_and_exact_moves(self):
        with tempfile.TemporaryDirectory() as tmp:
            incoming = os.path.join(tmp, "Incoming"); sorted_dir = os.path.join(tmp, "Sorted"); os.makedirs(incoming); os.makedirs(sorted_dir); self.write(incoming, "a.txt"); self.write(incoming, "b.txt")
            agent = self.make_agent(tmp); call = self.bind(agent); preview = agent._execute_tool_plan([call], dry_run=True)[0]; self.assertIn("a.txt", preview); self.assertIn("b.txt", preview); self.assertIn("omitted: 0", preview); self.assertFalse(os.path.isfile(os.path.join(sorted_dir, "a.txt")))
            agent._pending_plan = [call]; agent._pending_plan_id = "p"; result = agent.execute_pending_plan("p"); self.assertIn("Moved 2", result); self.assertTrue(os.path.isfile(os.path.join(sorted_dir, "a.txt")))
    def test_drift_refuses_zero_moves(self):
        with tempfile.TemporaryDirectory() as tmp:
            incoming = os.path.join(tmp, "Incoming"); os.makedirs(incoming); os.makedirs(os.path.join(tmp, "Sorted")); self.write(incoming, "a.txt"); agent = self.make_agent(tmp); call = self.bind(agent); self.write(incoming, "b.txt")
            agent._pending_plan = [call]; agent._pending_plan_id = "p"; result = agent.execute_pending_plan("p"); self.assertIn("refused", result.lower()); self.assertTrue(os.path.isfile(os.path.join(incoming, "a.txt")))
    def test_existing_destination_refuses_zero_moves(self):
        with tempfile.TemporaryDirectory() as tmp:
            incoming = os.path.join(tmp, "Incoming"); sorted_dir = os.path.join(tmp, "Sorted"); os.makedirs(incoming); os.makedirs(sorted_dir); self.write(incoming, "a.txt"); self.write(sorted_dir, "a.txt"); agent = self.make_agent(tmp); call = self.bind(agent)
            agent._pending_plan = [call]; agent._pending_plan_id = "p"; result = agent.execute_pending_plan("p"); self.assertIn("conflict", result.lower()); self.assertTrue(os.path.isfile(os.path.join(incoming, "a.txt")))
    def test_per_move_undo(self):
        with tempfile.TemporaryDirectory() as tmp:
            incoming = os.path.join(tmp, "Incoming"); sorted_dir = os.path.join(tmp, "Sorted"); os.makedirs(incoming); os.makedirs(sorted_dir); self.write(incoming, "a.txt"); agent = self.make_agent(tmp); call = self.bind(agent); agent._pending_plan = [call]; agent._pending_plan_id = "p"; agent.execute_pending_plan("p"); self.assertIn("Undid move", agent.undo_last()); self.assertTrue(os.path.isfile(os.path.join(incoming, "a.txt")))
    def test_exact_tool_set_and_model_path_list_refusal(self):
        with tempfile.TemporaryDirectory() as tmp:
            os.makedirs(os.path.join(tmp, "Incoming")); os.makedirs(os.path.join(tmp, "Sorted")); agent = self.make_agent(tmp)
            expected = {"list_directory", "read_file_content", "get_file_info", "find_duplicates", "find_large_files", "suggest_deletions", "cleanup_temp_files", "cleanup_empty_folders", "batch_move", "move_file", "rename_file", "delete_file", "create_folder"}
            self.assertEqual({item["function"]["name"] for item in agent._get_tool_definitions()}, expected)
            with self.assertRaises(ValueError):
                agent._bind_cleanup_calls([{"function": {"name": "batch_move", "arguments": {"paths": ["a.txt"], "destination_folder": "Sorted"}}}])

    def test_match_limit_boundary_and_over_limit(self):
        with tempfile.TemporaryDirectory() as tmp:
            incoming = os.path.join(tmp, "Incoming"); os.makedirs(incoming); os.makedirs(os.path.join(tmp, "Sorted"))
            for index in range(core.MAX_MATCHED_FILES):
                self.write(incoming, f"f{index}.txt")
            agent = self.make_agent(tmp)
            binding = core.enumerate_and_bind("*.txt", os.path.join(tmp, "Sorted"), agent.allowed_roots)
            self.assertEqual(len(binding.entries), core.MAX_MATCHED_FILES)
            self.write(incoming, "overflow.txt")
            with self.assertRaises(core.BatchMoveRefusal):
                core.enumerate_and_bind("*.txt", os.path.join(tmp, "Sorted"), agent.allowed_roots)

    def test_forged_binding_is_refused(self):
        with tempfile.TemporaryDirectory() as tmp:
            incoming = os.path.join(tmp, "Incoming"); os.makedirs(incoming); os.makedirs(os.path.join(tmp, "Sorted")); self.write(incoming, "a.txt")
            agent = self.make_agent(tmp); binding = core.enumerate_and_bind("*.txt", os.path.join(tmp, "Sorted"), agent.allowed_roots)
            changed = list(binding.entries); changed[0] = core.BatchMoveEntry(changed[0].source, changed[0].destination + ".forged", changed[0].size, changed[0].mtime_ns, changed[0].device, changed[0].inode)
            with self.assertRaises(core.BatchMoveRefusal): core.BatchMoveBinding(binding.root, tuple(changed), binding.binding_hash)

    def test_journal_failure_prevents_all_moves(self):
        with tempfile.TemporaryDirectory() as tmp:
            incoming = os.path.join(tmp, "Incoming"); os.makedirs(incoming); os.makedirs(os.path.join(tmp, "Sorted")); self.write(incoming, "a.txt"); self.write(incoming, "b.txt")
            agent = self.make_agent(tmp); call = self.bind(agent); agent._pending_plan = [call]; agent._pending_plan_id = "p"
            with patch.object(agent, "_save_operation_log", side_effect=OSError("disk full")):
                result = agent.execute_pending_plan("p")
            self.assertIn("error", result.lower()); self.assertTrue(os.path.isfile(os.path.join(incoming, "a.txt"))); self.assertTrue(os.path.isfile(os.path.join(incoming, "b.txt")))

    def test_file_directory_conflicts_in_either_order(self):
        for reverse in (False, True):
            with self.subTest(reverse=reverse), tempfile.TemporaryDirectory() as tmp:
                incoming = os.path.join(tmp, "Incoming"); os.makedirs(incoming); os.makedirs(os.path.join(tmp, "Sorted")); self.write(incoming, "a.txt")
                agent = self.make_agent(tmp); move = self.bind(agent); folder = {"function": {"name": "create_folder", "arguments": {"path": os.path.join(tmp, "Sorted", "a.txt")}}}
                plan = [folder, move] if reverse else [move, folder]
                result = agent._execute_tool_plan(plan, dry_run=False)
                self.assertIn("conflict", result[0].lower()); self.assertTrue(os.path.isfile(os.path.join(incoming, "a.txt")))




if __name__ == "__main__": unittest.main()

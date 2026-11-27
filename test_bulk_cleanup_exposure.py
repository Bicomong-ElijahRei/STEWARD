import ast
import inspect
import os
import shutil
import tempfile
import unittest
from unittest.mock import Mock, patch

from agent import bulk_deletion_core as core
from agents.file_agent import FileAgent


TWELVE_TOOLS = {
    "move_file", "delete_file", "rename_file", "create_folder",
    "list_directory", "read_file_content", "get_file_info",
    "find_duplicates", "find_large_files", "suggest_deletions",
    "cleanup_temp_files", "cleanup_empty_folders",
}


class BulkCleanupExposureTests(unittest.TestCase):
    def make_agent(self, root):
        log_path = os.path.join(root, "operations.json")
        with patch.object(FileAgent, "OPERATION_LOG_PATH", log_path):
            agent = FileAgent(api_manager=object(), root_path=root)
        agent.OPERATION_LOG_PATH = log_path
        return agent

    def write(self, root, name, content=b"x"):
        path = os.path.join(root, name)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "wb") as handle:
            handle.write(content)
        return path

    def bind(self, agent, name, directory, extra=None):
        arguments = {"directory": directory}
        if extra:
            arguments.update(extra)
        call = {"function": {"name": name, "arguments": arguments}}
        return agent._bind_cleanup_calls([call])[0]

    def pending(self, agent, call):
        agent._pending_plan = [call]
        agent._pending_plan_id = "bound-plan"
        return agent.execute_pending_plan("bound-plan")

    def test_schema_allowlist_is_exactly_twelve_and_negative_dispatch_refused(self):
        with tempfile.TemporaryDirectory(prefix="steward_bulk_schema_") as tmp:
            os.makedirs(os.path.join(tmp, "Incoming"))
            os.makedirs(os.path.join(tmp, "Sorted"))
            agent = self.make_agent(tmp)
            names = {item["function"]["name"] for item in agent._get_tool_definitions()}
            self.assertEqual(names, TWELVE_TOOLS)
            self.assertEqual(len(names), 12)
            legacy = Mock(return_value="moved")
            with patch("agents.file_agent._legacy_tool_functions", {"batch_move": legacy}):
                result = agent._execute_tool_plan(
                    [{"function": {"name": "batch_move", "arguments": {}}}],
                    dry_run=False,
                )
            legacy.assert_not_called()
            self.assertIn("Unapproved tool", result[0])

    def test_suffix_policy_excludes_log_and_backup(self):
        self.assertNotIn(".log", core.TEMPORARY_FILE_SUFFIXES)
        self.assertNotIn(".bak", core.TEMPORARY_FILE_SUFFIXES)

    def test_preview_enumerates_every_path_and_ignores_model_paths(self):
        with tempfile.TemporaryDirectory(prefix="steward_bulk_preview_") as tmp:
            incoming = os.path.join(tmp, "Incoming")
            self.write(incoming, "a.tmp")
            self.write(incoming, "nested/b.temp")
            agent = self.make_agent(tmp)
            call = self.bind(agent, "cleanup_temp_files", incoming)
            output = agent._execute_tool_plan([call], dry_run=True)[0]
            self.assertIn("a.tmp", output)
            self.assertIn("b.temp", output)
            self.assertIn("omitted: 0", output)
            self.assertIn("cannot be undone", output.lower())
            with self.assertRaises(ValueError):
                self.bind(
                    agent, "cleanup_temp_files", incoming,
                    {"paths": ["outside.txt"], "candidates": ["victim.txt"]},
                )


    def test_each_drift_refuses_whole_plan_with_zero_removals(self):
        cases = ("added", "removed", "identity", "reordered", "root", "policy", "hash")
        for drift in cases:
            with self.subTest(drift=drift), tempfile.TemporaryDirectory(prefix="steward_bulk_drift_") as tmp:
                incoming = os.path.join(tmp, "Incoming")
                self.write(incoming, "a.tmp")
                self.write(incoming, "b.tmp")
                agent = self.make_agent(tmp)
                call = self.bind(agent, "cleanup_temp_files", incoming)
                data = call["function"]["arguments"]["_bound_cleanup"]
                binding = core.BoundCandidateSet(
                    root=data["root"],
                    candidates=tuple(
                        core.CandidateEntry(
                            path=item["path"],
                            kind=core.CandidateKind(item["kind"]),
                            size=item["size"],
                            mtime_ns=item["mtime_ns"],
                        )
                        for item in data["candidates"]
                    ),
                    binding_hash=data["binding_hash"],
                    identity_policy=data["identity_policy"],
                    candidate_policy=data["candidate_policy"],
                )
                if drift == "added":
                    self.write(incoming, "c.tmp")
                elif drift == "removed":
                    os.remove(os.path.join(incoming, "a.tmp"))
                elif drift == "identity":
                    path = os.path.join(incoming, "a.tmp")
                    stat = os.stat(path)
                    os.utime(path, ns=(stat.st_atime_ns, stat.st_mtime_ns + 1_000_000_000))
                elif drift == "reordered":
                    binding = core.BoundCandidateSet(
                        binding.root, tuple(reversed(binding.candidates)),
                        binding.binding_hash, binding.identity_policy, binding.candidate_policy,
                    )
                elif drift == "root":
                    os.makedirs(os.path.join(tmp, "Sorted"), exist_ok=True)
                    binding = core.BoundCandidateSet(
                        os.path.join(tmp, "Sorted"), binding.candidates,
                        binding.binding_hash, binding.identity_policy, binding.candidate_policy,
                    )
                elif drift == "policy":
                    binding = core.BoundCandidateSet(
                        binding.root, binding.candidates, binding.binding_hash,
                        binding.identity_policy, "changed-policy",
                    )
                else:
                    binding = core.BoundCandidateSet(
                        binding.root, binding.candidates, "0" * 64,
                        binding.identity_policy, binding.candidate_policy,
                    )
                call["function"]["arguments"]["_bound_cleanup"] = agent._serialize_binding(binding)
                with patch("send2trash.send2trash") as trash:
                    result = self.pending(agent, call)
                trash.assert_not_called()
                self.assertIn("refused", result.lower())

    def test_live_suffix_policy_change_refuses_whole_plan(self):
        with tempfile.TemporaryDirectory(prefix="steward_bulk_policy_") as tmp:
            incoming = os.path.join(tmp, "Incoming")
            self.write(incoming, "a.tmp")
            agent = self.make_agent(tmp)
            call = self.bind(agent, "cleanup_temp_files", incoming)
            with patch.object(
                core, "TEMPORARY_FILE_SUFFIXES", core.TEMPORARY_FILE_SUFFIXES + (".new",)
            ), patch("send2trash.send2trash") as trash:
                result = self.pending(agent, call)
            trash.assert_not_called()
            self.assertIn("refused", result.lower())

    def test_send2trash_only_and_deepest_first(self):
        with tempfile.TemporaryDirectory(prefix="steward_bulk_trash_") as tmp:
            incoming = os.path.join(tmp, "Incoming")
            self.write(incoming, "a.tmp")
            os.makedirs(os.path.join(incoming, "empty", "nested"))
            agent = self.make_agent(tmp)
            temp_call = self.bind(agent, "cleanup_temp_files", incoming)
            dir_call = self.bind(agent, "cleanup_empty_folders", incoming)
            plan = [temp_call, dir_call]
            agent._pending_plan = plan
            agent._pending_plan_id = "ordered-plan"
            with patch("send2trash.send2trash") as trash, patch("os.remove") as remove, \
                    patch("os.unlink") as unlink, patch("shutil.rmtree") as rmtree:
                result = agent.execute_pending_plan("ordered-plan")
            trash.assert_called()
            remove.assert_not_called()
            unlink.assert_not_called()
            rmtree.assert_not_called()
            paths = [call.args[0] for call in trash.call_args_list]
            self.assertIn(os.path.join(incoming, "empty", "nested"), paths)
            self.assertLess(paths.index(os.path.join(incoming, "empty", "nested")), paths.index(os.path.join(incoming, "empty")))
            self.assertIn("cannot be undone", result.lower())

    def test_bulk_cleanup_journal_entry_cannot_undo_an_earlier_operation(self):
        with tempfile.TemporaryDirectory(prefix="steward_bulk_undo_") as tmp:
            agent = self.make_agent(tmp)
            entry = agent._begin_mutation("bulk_cleanup", tmp)
            agent._complete_mutation(entry, "cleanup completed", {"undoable": False})
            result = agent.undo_last()
            self.assertIn("cannot undo bulk cleanup", result.lower())

    def test_bulk_cleanup_refuses_without_undoing_an_earlier_move(self):
        with tempfile.TemporaryDirectory(prefix="steward_bulk_undo_move_") as tmp:
            incoming = os.path.join(tmp, "Incoming")
            sorted_dir = os.path.join(tmp, "Sorted")
            os.makedirs(incoming)
            os.makedirs(sorted_dir)
            source = self.write(incoming, "keep.txt")
            destination = os.path.join(sorted_dir, "keep.txt")
            agent = self.make_agent(tmp)

            self.assertTrue(agent.move_file(source, destination).startswith("Moved"))
            entry = agent._begin_mutation("bulk_cleanup", tmp)
            agent._complete_mutation(
                entry, "cleanup completed", {"undoable": False}
            )

            result = agent.undo_last()

            self.assertIn("cannot undo bulk cleanup", result.lower())
            self.assertTrue(os.path.isfile(destination))
            self.assertFalse(os.path.exists(source))

    def test_execution_ast_has_no_permanent_removal_primitive(self):
        from agent import bulk_cleanup_execution
        tree = ast.parse(inspect.getsource(bulk_cleanup_execution))
        forbidden = {"remove", "unlink", "rmtree", "rmdir", "removedirs"}
        for node in ast.walk(tree):
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
                self.assertNotIn(node.func.attr, forbidden)


    def test_hostile_cleanup_plans_are_refused(self):
        hostile = ("..\\outside", "C:\\Windows\\Temp", os.path.abspath(os.sep))
        for directory in hostile:
            for tool in ("cleanup_temp_files", "cleanup_empty_folders"):
                with self.subTest(directory=directory, tool=tool), tempfile.TemporaryDirectory(prefix="steward_bulk_hostile_") as tmp:
                    agent = self.make_agent(tmp)
                    with patch("send2trash.send2trash") as trash:
                        result = self.pending(agent, {"function": {"name": tool, "arguments": {"directory": directory}}})
                    trash.assert_not_called()
                    self.assertIn("Error", result)

    def test_journal_records_intent_before_removal_and_failure_prevents_removal(self):
        with tempfile.TemporaryDirectory(prefix="steward_bulk_journal_") as tmp:
            incoming = os.path.join(tmp, "Incoming")
            self.write(incoming, "a.tmp")
            agent = self.make_agent(tmp)
            call = self.bind(agent, "cleanup_temp_files", incoming)
            order = []
            original_save = agent._save_operation_log
            def save():
                order.append("journal")
                return original_save()
            with patch.object(agent, "_save_operation_log", side_effect=save), patch("send2trash.send2trash", side_effect=lambda path: order.append("remove")):
                agent._pending_plan = [call]
                agent._pending_plan_id = "journal-plan"
                agent.execute_pending_plan("journal-plan")
            self.assertEqual(order[0], "journal")
            self.assertIn("remove", order)
            with patch.object(agent, "_save_operation_log", side_effect=OSError("journal failed")), patch("send2trash.send2trash") as trash:
                agent._pending_plan = [call]
                agent._pending_plan_id = "journal-fail"
                result = agent.execute_pending_plan("journal-fail")
            trash.assert_not_called()
            self.assertIn("Error", result)


if __name__ == "__main__":
    unittest.main()

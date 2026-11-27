import ast
import hashlib
import inspect
import os
import shutil
import tempfile
import unittest
from dataclasses import replace
from unittest.mock import Mock, patch

from agent import bulk_deletion_core as core
from agents.file_agent import FileAgent


class BulkDeletionCoreTests(unittest.TestCase):
    """The future bulk-removal mechanism is pure, bounded, and non-mutating."""

    def _write(self, root, name, content=b"content"):
        path = os.path.join(root, name)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "wb") as handle:
            handle.write(content)
        return path

    def _enumerate(self, root, kind=core.CandidateKind.TEMPORARY_FILE):
        return core.enumerate_candidates(
            root,
            allowed_roots=(root,),
            kind=kind,
        )

    def test_core_bounds_and_suffix_policy_exclude_diagnostic_and_backup_files(self):
        from agent import tools

        self.assertEqual(core.MAX_FILES_VISITED, tools.REPORT_MAX_FILES_VISITED)
        self.assertEqual(
            core.MAX_DIRECTORY_DEPTH,
            tools.REPORT_MAX_DIRECTORY_DEPTH,
        )
        self.assertEqual(core.MAX_PATH_LENGTH, tools.REPORT_MAX_DIRECTORY_PATH_LENGTH)
        self.assertEqual(
            core.TEMPORARY_FILE_SUFFIXES,
            (
                ".tmp", ".temp", ".cache", ".swp",
                "thumbs.db", "desktop.ini",
            ),
        )
        self.assertNotIn(".log", core.TEMPORARY_FILE_SUFFIXES)
        self.assertNotIn(".bak", core.TEMPORARY_FILE_SUFFIXES)

    def test_candidate_records_and_binding_are_immutable(self):
        with tempfile.TemporaryDirectory(prefix="steward_bulk_immutable_") as tmp:
            self._write(tmp, "one.tmp", b"same")
            enumeration = self._enumerate(tmp)
            binding = core.bind_candidates(enumeration)

            self.assertIsInstance(enumeration.candidates, tuple)
            self.assertIsInstance(binding.candidates, tuple)
            with self.assertRaises((AttributeError, TypeError)):
                enumeration.candidates[0].path = "changed.tmp"
            with self.assertRaises((AttributeError, TypeError)):
                binding.candidates = ()
            with self.assertRaises((AttributeError, TypeError)):
                binding.binding_hash = "0" * 64

    def test_enumeration_is_deterministic_across_repeated_runs(self):
        with tempfile.TemporaryDirectory(prefix="steward_bulk_deterministic_") as tmp:
            self._write(tmp, "z.tmp", b"z")
            self._write(tmp, "a.tmp", b"a")
            self._write(tmp, "nested/m.tmp", b"m")
            self._write(tmp, "ignored.txt", b"ignored")

            first = self._enumerate(tmp)
            second = self._enumerate(tmp)

            self.assertEqual(first, second)
            self.assertEqual(
                [os.path.basename(entry.path) for entry in first.candidates],
                ["a.tmp", "m.tmp", "z.tmp"],
            )
            self.assertEqual(
                core.binding_hash(first.root, first.candidates),
                core.binding_hash(second.root, second.candidates),
            )

    def test_empty_directory_enumeration_includes_only_removable_folders(self):
        with tempfile.TemporaryDirectory(prefix="steward_bulk_empty_dirs_") as tmp:
            os.makedirs(os.path.join(tmp, "empty", "nested"))
            os.makedirs(os.path.join(tmp, "occupied"))
            self._write(tmp, "occupied/file.txt")

            candidates = self._enumerate(
                tmp, core.CandidateKind.EMPTY_DIRECTORY
            ).candidates

            self.assertEqual(
                [os.path.relpath(entry.path, tmp) for entry in candidates],
                [os.path.join("empty", "nested"), "empty"],
            )

    def test_enumeration_refuses_inaccessible_traversal(self):
        with tempfile.TemporaryDirectory(prefix="steward_bulk_io_error_") as tmp:
            self._write(tmp, "candidate.tmp", b"content")

            def inaccessible_walk(*args, **kwargs):
                kwargs["onerror"](PermissionError("denied"))
                return iter(())

            with patch("agent.bulk_deletion_core.os.walk", side_effect=inaccessible_walk):
                with self.assertRaises(core.EnumerationRefusal) as caught:
                    self._enumerate(tmp)

            self.assertEqual(caught.exception.code, core.RefusalCode.IO_ERROR)

    def test_canonical_root_path_length_is_bounded(self):
        with tempfile.TemporaryDirectory(prefix="steward_bulk_canonical_path_") as tmp:
            with patch.object(
                core, "_canonical_path", return_value="x" * (core.MAX_PATH_LENGTH + 1)
            ):
                with self.assertRaises(core.EnumerationRefusal) as caught:
                    self._enumerate(tmp)
            self.assertEqual(
                caught.exception.code,
                core.RefusalCode.PATH_LENGTH_EXCEEDED,
            )

    def test_enumeration_canonicalizes_junction_roots_and_allowed_roots(self):
        with tempfile.TemporaryDirectory(prefix="steward_bulk_canonical_root_") as tmp:
            target = os.path.join(tmp, "target")
            alias = os.path.join(tmp, "alias")
            os.makedirs(target)
            if os.name == "nt":
                import subprocess
                completed = subprocess.run(
                    ["cmd.exe", "/c", "mklink", "/J", alias, target],
                    capture_output=True,
                    text=True,
                )
                self.assertEqual(completed.returncode, 0, completed.stderr)
            else:
                os.symlink(target, alias, target_is_directory=True)
            self._write(target, "candidate.tmp", b"content")

            result = core.enumerate_candidates(
                alias,
                allowed_roots=(alias,),
                kind=core.CandidateKind.TEMPORARY_FILE,
            )

            self.assertEqual(result.root, os.path.realpath(target))
            self.assertEqual(
                [os.path.basename(entry.path) for entry in result.candidates],
                ["candidate.tmp"],
            )

    def test_enumeration_refuses_root_outside_sandbox(self):
        with tempfile.TemporaryDirectory(prefix="steward_bulk_sandbox_") as tmp:
            sandbox = os.path.join(tmp, "sandbox")
            outside = os.path.join(tmp, "outside")
            os.makedirs(sandbox)
            os.makedirs(outside)
            self._write(outside, "candidate.tmp")

            with self.assertRaises(core.EnumerationRefusal) as caught:
                core.enumerate_candidates(
                    outside,
                    allowed_roots=(sandbox,),
                    kind=core.CandidateKind.TEMPORARY_FILE,
                )

            self.assertEqual(
                caught.exception.code,
                core.RefusalCode.SANDBOX_VIOLATION,
            )
            self.assertLess(len(str(caught.exception)), 256)

    def test_enumeration_excludes_link_like_entries_before_containment_filtering(self):
        with tempfile.TemporaryDirectory(prefix="steward_bulk_link_exclusion_") as tmp:
            self._write(tmp, "candidate.tmp", b"content")

            with patch("agent.bulk_deletion_core.os.path.islink", return_value=True):
                candidates = self._enumerate(tmp).candidates

            self.assertEqual(candidates, ())

    def test_enumeration_refuses_junction_traversal(self):
        with tempfile.TemporaryDirectory(prefix="steward_bulk_junction_") as tmp:
            sandbox = os.path.join(tmp, "sandbox")
            outside = os.path.join(tmp, "outside")
            os.makedirs(sandbox)
            os.makedirs(outside)
            self._write(outside, "candidate.tmp")
            junction = os.path.join(sandbox, "junction")
            if os.name == "nt":
                import subprocess
                completed = subprocess.run(
                    ["cmd.exe", "/c", "mklink", "/J", junction, outside],
                    capture_output=True,
                    text=True,
                )
                self.assertEqual(completed.returncode, 0, completed.stderr)
            else:
                os.symlink(outside, junction, target_is_directory=True)

            candidates = self._enumerate(sandbox).candidates

            self.assertEqual(candidates, ())

    def test_file_count_bound_passes_at_limit_and_refuses_at_limit_plus_one(self):
        with tempfile.TemporaryDirectory(prefix="steward_bulk_file_count_") as tmp:
            self._write(tmp, "one.txt")
            self._write(tmp, "two.txt")
            with patch.object(core, "MAX_FILES_VISITED", 2):
                self._enumerate(tmp)
            self._write(tmp, "three.txt")
            with patch.object(core, "MAX_FILES_VISITED", 2):
                with self.assertRaises(core.EnumerationRefusal) as caught:
                    self._enumerate(tmp)
            self.assertEqual(
                caught.exception.code,
                core.RefusalCode.FILE_COUNT_EXCEEDED,
            )

    def test_depth_bound_passes_at_limit_and_refuses_at_limit_plus_one(self):
        with tempfile.TemporaryDirectory(prefix="steward_bulk_depth_") as tmp:
            self._write(tmp, "level-one/file.txt")
            with patch.object(core, "MAX_DIRECTORY_DEPTH", 1):
                self._enumerate(tmp)
            self._write(tmp, "level-one/level-two/file.txt")
            with patch.object(core, "MAX_DIRECTORY_DEPTH", 1):
                with self.assertRaises(core.EnumerationRefusal) as caught:
                    self._enumerate(tmp)
            self.assertEqual(
                caught.exception.code,
                core.RefusalCode.DEPTH_EXCEEDED,
            )

    def test_path_length_bound_passes_at_limit_and_refuses_at_limit_plus_one(self):
        with tempfile.TemporaryDirectory(prefix="steward_bulk_path_length_") as tmp:
            candidate_path = self._write(tmp, "candidate.tmp")
            with patch.object(core, "MAX_PATH_LENGTH", len(candidate_path)):
                self._enumerate(tmp)
            with patch.object(core, "MAX_PATH_LENGTH", len(candidate_path) - 1):
                with self.assertRaises(core.EnumerationRefusal) as caught:
                    self._enumerate(tmp)
            self.assertEqual(
                caught.exception.code,
                core.RefusalCode.PATH_LENGTH_EXCEEDED,
            )

    def test_root_path_length_is_bounded_before_traversal(self):
        with tempfile.TemporaryDirectory(prefix="steward_bulk_root_path_") as tmp:
            with patch.object(core, "MAX_PATH_LENGTH", len(tmp) - 1), patch.object(
                core, "_walk_entries", return_value=([], [])
            ):
                with self.assertRaises(core.EnumerationRefusal) as caught:
                    self._enumerate(tmp)
            self.assertEqual(
                caught.exception.code,
                core.RefusalCode.PATH_LENGTH_EXCEEDED,
            )

    def test_nested_candidate_path_length_is_bounded(self):
        with tempfile.TemporaryDirectory(prefix="steward_bulk_nested_path_") as tmp:
            self._write(tmp, "nested/candidate.tmp")
            nested_path = os.path.join(tmp, "nested", "candidate.tmp")
            with patch.object(core, "MAX_PATH_LENGTH", len(nested_path) - 1):
                with self.assertRaises(core.EnumerationRefusal) as caught:
                    self._enumerate(tmp)
            self.assertEqual(
                caught.exception.code,
                core.RefusalCode.PATH_LENGTH_EXCEEDED,
            )

    def test_candidate_count_bound_passes_at_limit_and_refuses_at_limit_plus_one(self):
        with tempfile.TemporaryDirectory(prefix="steward_bulk_candidate_count_") as tmp:
            self._write(tmp, "one.tmp")
            self._write(tmp, "two.tmp")
            with patch.object(core, "MAX_CANDIDATES_VISITED", 2):
                self._enumerate(tmp)
            self._write(tmp, "three.tmp")
            with patch.object(core, "MAX_CANDIDATES_VISITED", 2):
                with self.assertRaises(core.EnumerationRefusal) as caught:
                    self._enumerate(tmp)
            self.assertEqual(
                caught.exception.code,
                core.RefusalCode.CANDIDATE_COUNT_EXCEEDED,
            )

    def test_reverification_refuses_added_entry(self):
        with tempfile.TemporaryDirectory(prefix="steward_bulk_added_") as tmp:
            self._write(tmp, "one.tmp", b"same")
            enumeration = self._enumerate(tmp)
            binding = core.bind_candidates(enumeration)
            self._write(tmp, "two.tmp", b"same")

            result = core.reverify_binding(binding, self._enumerate(tmp))

            self.assertFalse(result.accepted)
            self.assertIn(
                core.RefusalCode.ADDED_ENTRY,
                [reason.code for reason in result.reasons],
            )

    def test_reverification_refuses_removed_entry(self):
        with tempfile.TemporaryDirectory(prefix="steward_bulk_removed_") as tmp:
            first = self._write(tmp, "one.tmp", b"same")
            self._write(tmp, "two.tmp", b"same")
            enumeration = self._enumerate(tmp)
            binding = core.bind_candidates(enumeration)
            os.remove(first)

            result = core.reverify_binding(binding, self._enumerate(tmp))

            self.assertFalse(result.accepted)
            self.assertIn(
                core.RefusalCode.REMOVED_ENTRY,
                [reason.code for reason in result.reasons],
            )

    def test_reverification_refuses_changed_identity(self):
        with tempfile.TemporaryDirectory(prefix="steward_bulk_changed_") as tmp:
            path = self._write(tmp, "one.tmp", b"same")
            enumeration = self._enumerate(tmp)
            binding = core.bind_candidates(enumeration)
            stat_result = os.stat(path)
            os.utime(
                path,
                ns=(stat_result.st_atime_ns, stat_result.st_mtime_ns + 1_000_000_000),
            )

            result = core.reverify_binding(binding, self._enumerate(tmp))

            self.assertFalse(result.accepted)
            self.assertIn(
                core.RefusalCode.IDENTITY_CHANGED,
                [reason.code for reason in result.reasons],
            )

    def test_reverification_refuses_reordered_path_set(self):
        with tempfile.TemporaryDirectory(prefix="steward_bulk_reordered_") as tmp:
            self._write(tmp, "one.tmp")
            self._write(tmp, "two.tmp")
            enumeration = self._enumerate(tmp)
            binding = core.bind_candidates(enumeration)

            result = core.reverify_binding(
                binding,
                replace(enumeration, candidates=tuple(reversed(enumeration.candidates))),
            )

            self.assertFalse(result.accepted)
            self.assertIn(
                core.RefusalCode.PATH_ORDER_CHANGED,
                [reason.code for reason in result.reasons],
            )

    def test_reverification_refuses_changed_root(self):
        with tempfile.TemporaryDirectory(prefix="steward_bulk_root_changed_") as tmp:
            self._write(tmp, "one.tmp", b"same")
            enumeration = self._enumerate(tmp)
            binding = core.bind_candidates(enumeration)

            result = core.reverify_binding(
                binding,
                replace(enumeration, root=os.path.join(tmp, "other")),
            )

            self.assertFalse(result.accepted)
            self.assertIn(
                core.RefusalCode.ROOT_CHANGED,
                [reason.code for reason in result.reasons],
            )

    def test_reverification_refuses_corrupt_binding_hash(self):
        with tempfile.TemporaryDirectory(prefix="steward_bulk_corrupt_hash_") as tmp:
            self._write(tmp, "one.tmp", b"same")
            enumeration = self._enumerate(tmp)
            binding = core.bind_candidates(enumeration)

            result = core.reverify_binding(
                replace(binding, binding_hash="0" * 64),
                enumeration,
            )

            self.assertFalse(result.accepted)
            self.assertIn(
                core.RefusalCode.BINDING_HASH_MISMATCH,
                [reason.code for reason in result.reasons],
            )

    def test_reverification_refuses_changed_identity_policy(self):
        with tempfile.TemporaryDirectory(prefix="steward_bulk_policy_") as tmp:
            self._write(tmp, "one.tmp", b"same")
            enumeration = self._enumerate(tmp)
            binding = core.bind_candidates(enumeration)

            result = core.reverify_binding(
                replace(binding, identity_policy="path-only-v0"),
                enumeration,
            )

            self.assertFalse(result.accepted)
            self.assertIn(
                core.RefusalCode.IDENTITY_POLICY_CHANGED,
                [reason.code for reason in result.reasons],
            )

    def test_binding_hash_covers_order_and_identity(self):
        with tempfile.TemporaryDirectory(prefix="steward_bulk_hash_") as tmp:
            self._write(tmp, "one.tmp", b"same")
            self._write(tmp, "two.tmp", b"same")
            enumeration = self._enumerate(tmp)
            original = core.binding_hash(enumeration.root, enumeration.candidates)
            reordered = core.binding_hash(
                enumeration.root,
                tuple(reversed(enumeration.candidates)),
            )
            changed = tuple(
                replace(entry, mtime_ns=entry.mtime_ns + 1)
                for entry in enumeration.candidates
            )

            self.assertNotEqual(original, reordered)
            self.assertNotEqual(original, core.binding_hash(enumeration.root, changed))

    def test_reverification_refuses_tampered_candidate_entry(self):
        with tempfile.TemporaryDirectory(prefix="steward_bulk_tampered_") as tmp:
            self._write(tmp, "one.tmp", b"same")
            enumeration = self._enumerate(tmp)
            binding = core.bind_candidates(enumeration)
            tampered = replace(
                binding,
                candidates=(
                    replace(binding.candidates[0], mtime_ns=binding.candidates[0].mtime_ns + 1),
                ),
            )

            result = core.reverify_binding(tampered, enumeration)

            self.assertFalse(result.accepted)
            self.assertIn(
                core.RefusalCode.BINDING_HASH_MISMATCH,
                [reason.code for reason in result.reasons],
            )

    def test_core_never_mutates_filesystem_and_spies_prove_no_removal(self):
        with tempfile.TemporaryDirectory(prefix="steward_bulk_nonmutation_") as tmp:
            self._write(tmp, "one.tmp", b"same")
            self._write(tmp, "nested/two.tmp", b"same")

            def snapshot():
                state = {}
                for current, directories, files in os.walk(tmp):
                    directories.sort()
                    files.sort()
                    for name in directories:
                        path = os.path.join(current, name)
                        state[os.path.relpath(path, tmp)] = ("directory",)
                    for name in files:
                        path = os.path.join(current, name)
                        with open(path, "rb") as handle:
                            digest = hashlib.sha256(handle.read()).hexdigest()
                        state[os.path.relpath(path, tmp)] = ("file", digest)
                return state

            before = snapshot()
            with patch("os.remove") as remove_spy, patch(
                "os.rename"
            ) as rename_spy, patch(
                "os.replace"
            ) as replace_spy, patch(
                "shutil.rmtree"
            ) as rmtree_spy, patch("send2trash.send2trash") as trash_spy:
                enumeration = self._enumerate(tmp)
                binding = core.bind_candidates(enumeration)
                core.reverify_binding(binding, enumeration)

            remove_spy.assert_not_called()
            rename_spy.assert_not_called()
            replace_spy.assert_not_called()
            rmtree_spy.assert_not_called()
            trash_spy.assert_not_called()
            self.assertEqual(snapshot(), before)

    def test_ast_inspection_proves_no_mutation_primitives(self):
        source = inspect.getsource(core)
        tree = ast.parse(source)
        forbidden_calls = {
            "chmod",
            "lchmod",
            "mkdir",
            "makedirs",
            "remove",
            "removedirs",
            "rename",
            "replace",
            "rmdir",
            "rmtree",
            "send2trash",
            "truncate",
            "unlink",
            "utime",
            "write",
            "write_bytes",
            "write_text",
        }
        for node in ast.walk(tree):
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
                self.assertNotIn(node.func.attr, forbidden_calls)
            if isinstance(node, ast.Import):
                for alias in node.names:
                    self.assertNotIn(alias.name, {"send2trash", "shutil"})
            if isinstance(node, ast.ImportFrom):
                self.assertNotIn(node.module, {"send2trash", "shutil"})

    def test_active_dispatch_allowlist_is_exactly_thirteen_tools(self):
        expected = {
            "move_file", "delete_file", "rename_file", "create_folder",
            "list_directory", "read_file_content", "get_file_info",
            "find_duplicates", "find_large_files", "suggest_deletions",
            "cleanup_temp_files", "cleanup_empty_folders", "batch_move",
        }
        with tempfile.TemporaryDirectory(prefix="steward_bulk_allowlist_") as tmp:
            os.makedirs(os.path.join(tmp, "Incoming"))
            os.makedirs(os.path.join(tmp, "Sorted"))
            with patch.object(
                FileAgent,
                "OPERATION_LOG_PATH",
                os.path.join(tmp, "operations.json"),
            ):
                agent = FileAgent(api_manager=object(), root_path=tmp)
            definitions = agent._get_tool_definitions()
            names = {item["function"]["name"] for item in definitions}
            self.assertEqual(names, expected)
            self.assertEqual(len(names), 13)

            approved_dispatch = Mock(return_value="listed")
            unapproved_dispatch = Mock(return_value="removed")
            with patch(
                "agents.file_agent._legacy_tool_functions",
                {"list_directory": approved_dispatch},
            ):
                approved_result = agent._execute_tool_plan(
                    [{
                        "function": {
                            "name": "list_directory",
                            "arguments": {"directory": "Incoming"},
                        }
                    }],
                    dry_run=False,
                )
            with patch(
                "agents.file_agent._legacy_tool_functions",
                {"unapproved_tool": unapproved_dispatch},
            ):
                unapproved_result = agent._execute_tool_plan(
                    [{
                        "function": {
                            "name": "unapproved_tool",
                            "arguments": {},
                        }
                    }],
                    dry_run=False,
                )

            approved_dispatch.assert_called_once_with(
                directory=os.path.join(tmp, "Incoming")
            )
            unapproved_dispatch.assert_not_called()
            self.assertTrue(any("listed" in line for line in approved_result))
            self.assertIn("Unapproved tool", unapproved_result[0])
            self.assertIn("unapproved_tool", unapproved_result[0])


if __name__ == "__main__":
    unittest.main()

"""Safety tests for C3-I2 admitted content replacement and recovery."""

import ast
import builtins
import copy
import hashlib
import json
import os
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

from agent.content_replace import (
    ContentReplaceError,
    replace_content,
    stage_content,
)
from agents.patch_applier import (
    PatchAdmissionError,
    PatchApplyError,
    PatchRecoveryError,
    PatchApplier,
    admit_workspace,
)


SOURCE = b"# keep this comment\ndef alpha():\n    return 1\n"


def _sha256(value):
    return hashlib.sha256(value).hexdigest()


def _anchor(source, qualified_name="Module.alpha"):
    text = source.decode("utf-8-sig")
    tree = ast.parse(text)
    node = tree.body[0]
    lines = text.splitlines(keepends=True)
    start = sum(len(line) for line in lines[: node.lineno - 1]) + node.col_offset
    end = sum(len(line) for line in lines[: node.end_lineno - 1]) + node.end_col_offset
    return {
        "node_kind": "FunctionDef",
        "qualified_name": qualified_name,
        "occurrence": 0,
        "source_start": start,
        "source_end": end,
    }


def _make_patch(source, fingerprint, relative_path="sample.py"):
    anchor = _anchor(source)
    replacement = "def alpha():\n    return 2"
    edit = {
        "op": "replace_node",
        "anchor": anchor,
        "replacement": replacement,
        "expected_sha256": _sha256(source[anchor["source_start"] : anchor["source_end"]]),
    }
    patch = {
        "schema_version": 1,
        "patch_id": "11111111-1111-4111-8111-111111111111",
        "plan_id": "22222222-2222-4222-8222-222222222222",
        "workspace_fingerprint": fingerprint,
        "files": [
            {
                "relative_path": relative_path,
                "source_sha256": _sha256(source),
                "source_bytes": len(source),
                "encoding": "utf-8",
                "bom": False,
                "newline": "lf",
                "edits": [edit],
            }
        ],
        "created_utc": "2026-11-24T00:00:00Z",
    }
    artifact = json.dumps(
        patch, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")
    return patch, artifact


class PatchApplierTestCase(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="steward_c3_i2_")
        self.base = os.path.realpath(self.temp.name)
        self.workspace = os.path.join(self.base, "workspace")
        self.incoming = os.path.join(self.base, "Incoming")
        self.sorted = os.path.join(self.base, "Sorted")
        self.backups = os.path.join(self.base, "appdata", "c3_backups")
        self.journal = os.path.join(self.base, "appdata", "steward_operations.json")
        os.makedirs(self.workspace)
        os.makedirs(self.incoming)
        os.makedirs(self.sorted)
        self.target = os.path.join(self.workspace, "sample.py")
        with open(self.target, "wb") as handle:
            handle.write(SOURCE)
        self.workspace_admission = admit_workspace(
            self.workspace, self.incoming, self.sorted
        )
        self.patch, self.artifact = _make_patch(
            SOURCE, self.workspace_admission.fingerprint
        )

    def tearDown(self):
        self.temp.cleanup()

    def make_applier(self):
        return PatchApplier(
            workspace_root=self.workspace,
            incoming_root=self.incoming,
            sorted_root=self.sorted,
            operation_log_path=self.journal,
            backup_root=self.backups,
        )

    def journal_entries(self):
        with open(self.journal, "r", encoding="utf-8") as handle:
            return json.load(handle)

    def write_target(self, value):
        with open(self.target, "wb") as handle:
            handle.write(value)

    def assert_target(self, value):
        with open(self.target, "rb") as handle:
            self.assertEqual(value, handle.read())


class WorkspaceAdmissionTests(PatchApplierTestCase):
    def test_root_overlap_ancestry_and_descendency_are_refused(self):
        cases = (
            self.incoming,
            self.sorted,
            self.base,
            os.path.join(self.incoming, "child"),
            os.path.join(self.sorted, "child"),
        )
        for candidate in cases:
            with self.subTest(candidate=candidate):
                with self.assertRaises(PatchAdmissionError):
                    admit_workspace(candidate, self.incoming, self.sorted)

    def test_drive_home_and_appdata_roots_are_refused(self):
        drive, _ = os.path.splitdrive(os.path.abspath(self.workspace))
        candidates = [drive + os.sep, os.path.realpath(os.path.expanduser("~"))]
        app_data = os.environ.get("APPDATA")
        if app_data:
            candidates.extend(
                [os.path.realpath(app_data), os.path.join(os.path.realpath(app_data), "STEWARD")]
            )
        for candidate in candidates:
            with self.subTest(candidate=candidate):
                with self.assertRaises(PatchAdmissionError):
                    admit_workspace(candidate, self.incoming, self.sorted)

    def test_every_write_denylist_name_is_refused(self):
        denied_directories = (
            ".git", ".hg", ".svn", "__pycache__", "venv", ".venv", "node_modules",
            "rag_index", "media", ".tox", ".nox", ".pytest_cache", ".mypy_cache",
        )
        for name in denied_directories:
            with self.subTest(name=name):
                directory = os.path.join(self.workspace, name)
                os.makedirs(directory)
                target = os.path.join(directory, "sample.py")
                with open(target, "wb") as handle:
                    handle.write(SOURCE)
                with self.assertRaises(PatchAdmissionError):
                    self.make_applier().admit_target(f"{name}/sample.py")

        denied_files = (
            ".env", ".env.local", "private.key", "private.pem", "private.p12",
            "private.pfx", "private.db", "secret.key", "steward_operations.json",
            "credentials.json", ".npmrc", ".pypirc",
        )
        for name in denied_files:
            with self.subTest(name=name):
                target = os.path.join(self.workspace, name)
                with open(target, "wb") as handle:
                    handle.write(SOURCE)
                with self.assertRaises(PatchAdmissionError):
                    self.make_applier().admit_target(name)

    def test_symlink_component_is_refused(self):
        outside = os.path.join(self.base, "outside")
        os.makedirs(outside)
        target = os.path.join(outside, "sample.py")
        with open(target, "wb") as handle:
            handle.write(SOURCE)
        link = os.path.join(self.workspace, "linked")
        try:
            os.symlink(outside, link, target_is_directory=True)
        except (OSError, NotImplementedError) as exc:
            self.skipTest(f"symlink creation unavailable: {exc}")
        with self.assertRaises(PatchAdmissionError):
            self.make_applier().admit_target("linked/sample.py")

    def test_junction_component_is_refused(self):
        outside = os.path.join(self.base, "junction_target")
        os.makedirs(outside)
        target = os.path.join(outside, "sample.py")
        with open(target, "wb") as handle:
            handle.write(SOURCE)
        link = os.path.join(self.workspace, "junction")
        completed = subprocess.run(
            ["cmd", "/c", "mklink", "/J", link, outside],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        if completed.returncode != 0:
            self.skipTest("junction creation unavailable")
        with self.assertRaises(PatchAdmissionError):
            self.make_applier().admit_target("junction/sample.py")

    def test_non_python_absolute_traversal_and_unc_paths_are_refused(self):
        text = os.path.join(self.workspace, "notes.txt")
        with open(text, "wb") as handle:
            handle.write(b"text")
        for relative in (
            "notes.txt", "/absolute.py", "C:/absolute.py", "C:\\absolute.py",
            "\\\\server\\share\\absolute.py", "../escape.py", "dir/../escape.py",
        ):
            with self.subTest(relative=relative):
                with self.assertRaises(PatchAdmissionError):
                    self.make_applier().admit_target(relative)

    def test_reserved_names_and_trailing_space_or_dot_are_refused(self):
        for relative in ("CON.py", "aux.txt", "name .py", "name..py"):
            with self.subTest(relative=relative):
                with self.assertRaises(PatchAdmissionError):
                    self.make_applier().admit_target(relative)

    def test_target_over_one_mebibyte_is_refused(self):
        with open(self.target, "wb") as handle:
            handle.write(b"x" * (1024 * 1024 + 1))
        with self.assertRaises(PatchAdmissionError):
            self.make_applier().admit_target("sample.py")

    def test_backup_root_overlapping_workspace_is_refused(self):
        with self.assertRaises(PatchAdmissionError):
            PatchApplier(
                workspace_root=self.workspace,
                incoming_root=self.incoming,
                sorted_root=self.sorted,
                operation_log_path=self.journal,
                backup_root=os.path.join(self.workspace, "backups"),
            )

    def test_admission_and_read_do_not_modify_files(self):
        before = (self.target, os.stat(self.target).st_mtime_ns, os.stat(self.target).st_size)
        applier = self.make_applier()
        admitted = applier.admit_target("sample.py")
        self.assertEqual(SOURCE, applier.read_target(admitted))
        after = (self.target, os.stat(self.target).st_mtime_ns, os.stat(self.target).st_size)
        self.assertEqual(before, after)

    def test_workspace_fingerprint_changes_with_identity(self):
        first = admit_workspace(self.workspace, self.incoming, self.sorted)
        second = admit_workspace(self.workspace, self.incoming, self.sorted)
        other_workspace = os.path.join(self.base, "other_workspace")
        os.makedirs(other_workspace)
        other = admit_workspace(other_workspace, self.incoming, self.sorted)
        self.assertEqual(first.fingerprint, second.fingerprint)
        self.assertNotEqual(first.fingerprint, other.fingerprint)
        self.assertRegex(first.fingerprint, r"^[0-9a-f]{64}$")


class ApplyAndProofTests(PatchApplierTestCase):
    def test_real_engine_round_trip_applies_approved_bytes(self):
        applier = self.make_applier()
        result = applier.apply_patch(self.patch, self.artifact)
        expected = b"# keep this comment\ndef alpha():\n    return 2\n"
        self.assert_target(expected)
        self.assertEqual("committed", result.state)
        self.assertEqual(_sha256(expected), result.post_sha256)

    def test_tampered_engine_outside_range_proof_is_rejected_with_zero_write(self):
        applier = self.make_applier()
        real_result = applier.stage(self.patch, self.artifact)
        tampered = copy.deepcopy(real_result)
        tampered.proof["output_outside_sha256"] = "0" * 64
        with mock.patch("agents.patch_applier.stage_patch", return_value=tampered):
            with self.assertRaises(PatchApplyError):
                applier.apply_patch(self.patch, self.artifact)
        self.assert_target(SOURCE)
        self.assertFalse(os.path.exists(self.journal))

    def test_engine_outside_byte_equality_proof_is_required(self):
        applier = self.make_applier()
        real_result = applier.stage(self.patch, self.artifact)
        tampered = copy.deepcopy(real_result)
        tampered.proof["outside_bytes_equal"] = False
        with mock.patch("agents.patch_applier.stage_patch", return_value=tampered):
            with self.assertRaises(PatchApplyError) as raised:
                applier.apply_patch(self.patch, self.artifact)
        self.assertIn("outside-range", str(raised.exception))
        self.assert_target(SOURCE)
        self.assertFalse(os.path.exists(self.journal))

    def test_patch_workspace_fingerprint_mismatch_is_rejected(self):
        patch, artifact = _make_patch(SOURCE, "wrong-fingerprint")
        with self.assertRaises(PatchApplyError):
            self.make_applier().apply_patch(patch, artifact)
        self.assert_target(SOURCE)

    def test_source_changed_between_staging_and_replace_refuses(self):
        applier = self.make_applier()
        original_stage = applier.stage
        changed = False

        def stage_then_change(patch, artifact):
            nonlocal changed
            result = original_stage(patch, artifact)
            self.write_target(b"# externally changed\ndef alpha():\n    return 3\n")
            changed = True
            return result

        with mock.patch.object(applier, "stage", side_effect=stage_then_change):
            with self.assertRaises(PatchApplyError):
                applier.apply_patch(self.patch, self.artifact)
        self.assertTrue(changed)
        with open(self.target, "rb") as handle:
            self.assertEqual(b"# externally changed\ndef alpha():\n    return 3\n", handle.read())

    def test_source_revalidation_precedes_atomic_replace(self):
        applier = self.make_applier()
        original_stage = applier.stage
        original_replace = applier.replace_content
        calls = []

        def stage_then_change(patch, artifact):
            result = original_stage(patch, artifact)
            self.write_target(b"# externally changed\ndef alpha():\n    return 3\n")
            return result

        def observe_replace(target, staged, expected_pre, expected_post):
            calls.append("replace")
            return original_replace(target, staged, expected_pre, expected_post)

        with mock.patch.object(applier, "stage", side_effect=stage_then_change):
            with mock.patch.object(applier, "replace_content", side_effect=observe_replace):
                with self.assertRaises(PatchApplyError):
                    applier.apply_patch(self.patch, self.artifact)
        self.assertEqual([], calls)

    def test_engine_failure_does_not_write_target_or_journal(self):
        with mock.patch("agents.patch_applier.stage_patch", side_effect=ValueError("bad")):
            with self.assertRaises(PatchApplyError):
                self.make_applier().apply_patch(self.patch, self.artifact)
        self.assert_target(SOURCE)
        self.assertFalse(os.path.exists(self.journal))

    def test_no_execution_of_target_content(self):
        applier = self.make_applier()
        forbidden = mock.Mock(side_effect=AssertionError("target executed"))
        with mock.patch("subprocess.Popen", forbidden), mock.patch(
            "subprocess.run", forbidden
        ), mock.patch("os.system", forbidden), mock.patch("builtins.exec", forbidden):
            applier.apply_patch(self.patch, self.artifact)
        forbidden.assert_not_called()


class JournalAndBackupTests(PatchApplierTestCase):
    def test_intent_precedes_mutation_and_completion_follows(self):
        applier = self.make_applier()
        original_replace = applier.replace_content
        observed = []

        def observe(target, staged, expected_pre, expected_post):
            entries = self.journal_entries()
            observed.append((entries[-1]["state"], entries[-1]["operation"]))
            return original_replace(target, staged, expected_pre, expected_post)

        with mock.patch.object(applier, "replace_content", side_effect=observe):
            applier.apply_patch(self.patch, self.artifact)
        self.assertEqual([("intent", "content_edit")], observed)
        entries = self.journal_entries()
        self.assertEqual("committed", entries[-1]["state"])
        self.assertEqual("content_edit", entries[-1]["operation"])

    def test_journal_failure_before_mutation_causes_zero_writes(self):
        applier = self.make_applier()
        with mock.patch.object(applier, "begin_mutation", side_effect=OSError("journal down")):
            with self.assertRaises(PatchApplyError):
                applier.apply_patch(self.patch, self.artifact)
        self.assert_target(SOURCE)
        self.assertFalse(os.path.exists(self.backups))

    def test_completion_failure_after_replacement_is_uncertain_and_blocks_undo(self):
        applier = self.make_applier()
        with mock.patch.object(applier, "complete_mutation", side_effect=OSError("disk full")):
            result = applier.apply_patch(self.patch, self.artifact)
        self.assertEqual("uncertain", result.state)
        self.assertTrue(os.path.isdir(self.backups))
        with self.assertRaises(PatchRecoveryError):
            applier.undo_last()
        with self.assertRaises(PatchRecoveryError):
            applier.redo_last()

    def test_backup_failure_prevents_replacement(self):
        applier = self.make_applier()
        with mock.patch.object(applier, "write_backup", side_effect=OSError("backup full")):
            with self.assertRaises(PatchApplyError):
                applier.apply_patch(self.patch, self.artifact)
        self.assert_target(SOURCE)

    def test_pre_and_post_images_are_hash_verified_outside_workspace(self):
        applier = self.make_applier()
        result = applier.apply_patch(self.patch, self.artifact)
        backup = result.backup_reference
        self.assertEqual(
            os.path.normcase(os.path.commonpath([self.backups, backup])),
            os.path.normcase(self.backups),
        )
        self.assertNotEqual(
            os.path.normcase(os.path.commonpath([self.workspace, backup])),
            os.path.normcase(self.workspace),
        )
        with open(os.path.join(backup, "pre_image.bin"), "rb") as handle:
            self.assertEqual(SOURCE, handle.read())
        with open(os.path.join(backup, "post_image.bin"), "rb") as handle:
            post = handle.read()
        self.assertEqual(result.post_sha256, _sha256(post))
        with open(os.path.join(backup, "manifest.json"), encoding="utf-8") as handle:
            manifest = json.load(handle)
        self.assertEqual(result.pre_sha256, manifest["pre_sha256"])
        self.assertEqual(result.post_sha256, manifest["post_sha256"])

    def test_journal_never_contains_source_content(self):
        applier = self.make_applier()
        applier.apply_patch(self.patch, self.artifact)
        with open(self.journal, "rb") as handle:
            raw = handle.read()
        self.assertNotIn(b"return 1", raw)
        self.assertNotIn(b"return 2", raw)


class UndoRedoTests(PatchApplierTestCase):
    def test_undo_and_redo_restore_exact_bytes(self):
        applier = self.make_applier()
        applier.apply_patch(self.patch, self.artifact)
        expected_post = b"# keep this comment\ndef alpha():\n    return 2\n"
        applier.undo_last()
        self.assert_target(SOURCE)
        applier.redo_last()
        self.assert_target(expected_post)

    def test_undo_refuses_after_external_edit_without_overwriting(self):
        applier = self.make_applier()
        applier.apply_patch(self.patch, self.artifact)
        external = b"# external edit\ndef alpha():\n    return 9\n"
        self.write_target(external)
        with self.assertRaises(PatchRecoveryError):
            applier.undo_last()
        self.assert_target(external)
        entry = self.journal_entries()[-1]
        self.assertEqual("committed", entry["state"])
        self.assertEqual("failed", entry["transition"]["state"])

    def test_safe_undo_refusal_remains_retryable(self):
        applier = self.make_applier()
        applier.apply_patch(self.patch, self.artifact)
        external = b"# external edit\ndef alpha():\n    return 9\n"
        self.write_target(external)
        with self.assertRaises(PatchRecoveryError):
            applier.undo_last()
        self.write_target(b"# keep this comment\ndef alpha():\n    return 2\n")
        applier.undo_last()
        self.assert_target(SOURCE)

    def test_redo_refuses_when_target_is_neither_pre_image(self):
        applier = self.make_applier()
        applier.apply_patch(self.patch, self.artifact)
        applier.undo_last()
        external = b"# external edit\ndef alpha():\n    return 9\n"
        self.write_target(external)
        with self.assertRaises(PatchRecoveryError):
            applier.redo_last()
        self.assert_target(external)

    def test_uncertain_content_edit_blocks_blind_undo_and_redo(self):
        applier = self.make_applier()
        with mock.patch.object(applier, "complete_mutation", side_effect=OSError("disk full")):
            applier.apply_patch(self.patch, self.artifact)
        with self.assertRaises(PatchRecoveryError) as undo_error:
            applier.undo_last()
        self.assertIn("uncertain", str(undo_error.exception))
        with self.assertRaises(PatchRecoveryError) as redo_error:
            applier.redo_last()
        self.assertIn("uncertain", str(redo_error.exception))

    def test_journal_records_fingerprint_and_hashes_without_content(self):
        applier = self.make_applier()
        applier.apply_patch(self.patch, self.artifact)
        entry = self.journal_entries()[-1]
        self.assertEqual(
            self.workspace_admission.fingerprint,
            entry["workspace_fingerprint"],
        )
        self.assertEqual(_sha256(SOURCE), entry["pre_sha256"])
        with open(self.target, "rb") as handle:
            applied = handle.read()
        self.assertEqual(entry["post_sha256"], _sha256(applied))

    def test_separate_processes_cannot_both_claim_undo(self):
        applier = self.make_applier()
        applier.apply_patch(self.patch, self.artifact)
        script = (
            "import sys;"
            "from agents.patch_applier import PatchApplier;"
            "a=PatchApplier(workspace_root=sys.argv[1], incoming_root=sys.argv[2], "
            "sorted_root=sys.argv[3], operation_log_path=sys.argv[4], "
            "backup_root=sys.argv[5]);"
            "a.undo_last();print('claimed')"
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
        ]
        processes = [subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE) for _ in range(2)]
        outcomes = [process.communicate(timeout=20) for process in processes]
        successes = sum(
            process.returncode == 0 and b"claimed" in stdout
            for process, (stdout, _) in zip(processes, outcomes)
        )
        self.assertEqual(1, successes)
        self.assert_target(SOURCE)


class ContentReplacePrimitiveTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="steward_c3_content_")
        self.directory = os.path.realpath(self.temp.name)
        self.target = os.path.join(self.directory, "target.py")
        with open(self.target, "wb") as handle:
            handle.write(b"before")

    def tearDown(self):
        self.temp.cleanup()

    def test_staged_content_is_same_directory_and_hash_verified(self):
        content = b"after"
        staged = stage_content(self.target, content, _sha256(content))
        self.addCleanup(lambda: os.path.exists(staged) and os.remove(staged))
        self.assertEqual(
            os.path.normcase(os.path.dirname(staged)),
            os.path.normcase(self.directory),
        )
        with open(staged, "rb") as handle:
            self.assertEqual(content, handle.read())

    def test_staging_does_not_create_missing_target_directory(self):
        missing = os.path.join(self.directory, "missing")
        with self.assertRaises(ContentReplaceError):
            stage_content(os.path.join(missing, "target.py"), b"after", _sha256(b"after"))
        self.assertFalse(os.path.exists(missing))

    def test_replace_overwrites_only_hash_guarded_existing_target(self):
        content = b"after"
        staged = stage_content(self.target, content, _sha256(content))
        replace_content(self.target, staged, _sha256(b"before"), _sha256(content))
        with open(self.target, "rb") as handle:
            self.assertEqual(content, handle.read())

    def test_replace_uses_atomic_os_replace(self):
        content = b"after"
        staged = stage_content(self.target, content, _sha256(content))
        with mock.patch("agent.content_replace.os.replace", wraps=os.replace) as atomic:
            replace_content(self.target, staged, _sha256(b"before"), _sha256(content))
        atomic.assert_called_once_with(staged, self.target)

    def test_replace_refuses_changed_target_without_overwriting(self):
        content = b"after"
        staged = stage_content(self.target, content, _sha256(content))
        self.addCleanup(lambda: os.path.exists(staged) and os.remove(staged))
        with open(self.target, "wb") as handle:
            handle.write(b"external")
        with self.assertRaises(ContentReplaceError):
            replace_content(self.target, staged, _sha256(b"before"), _sha256(content))
        with open(self.target, "rb") as handle:
            self.assertEqual(b"external", handle.read())

    def test_replace_refuses_non_regular_target(self):
        content = b"after"
        staged = stage_content(self.target, content, _sha256(content))
        self.addCleanup(lambda: os.path.exists(staged) and os.remove(staged))
        directory = os.path.join(self.directory, "target-directory.py")
        os.makedirs(directory)
        with self.assertRaises(ContentReplaceError):
            replace_content(directory, staged, _sha256(b"before"), _sha256(content))

    def test_replace_refuses_staged_file_outside_target_directory(self):
        content = b"after"
        outside = tempfile.TemporaryDirectory(prefix="steward_c3_outside_")
        self.addCleanup(outside.cleanup)
        staged = os.path.join(outside.name, "staged.py")
        with open(staged, "wb") as handle:
            handle.write(content)
        with self.assertRaises(ContentReplaceError):
            replace_content(self.target, staged, _sha256(b"before"), _sha256(content))
        with open(self.target, "rb") as handle:
            self.assertEqual(b"before", handle.read())

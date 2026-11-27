import os
import tempfile
import unittest
from unittest.mock import patch

from agent import tools


class DuplicateHashReadBudgetTests(unittest.TestCase):
    """Duplicate hashing has finite per-file and cumulative read budgets."""

    def _write_file(self, root, name, content):
        path = os.path.join(root, name)
        with open(path, "wb") as handle:
            handle.write(content)
        return path

    def test_per_file_limit_passes_and_limit_plus_one_is_reported_skipped(self):
        with tempfile.TemporaryDirectory(prefix="steward_hash_file_limit_") as tmp:
            self._write_file(tmp, "a.bin", b"12345678")
            self._write_file(tmp, "b.bin", b"12345678")
            oversized = self._write_file(tmp, "c.bin", b"123456789")

            with patch.object(
                tools, "REPORT_MAX_HASH_FILE_BYTES", 8, create=True
            ), patch.object(
                tools, "REPORT_MAX_HASH_TOTAL_BYTES", 64, create=True
            ), patch(
                "builtins.open", wraps=open
            ) as open_spy:
                report = tools.find_duplicates(tmp)

            self.assertIn("a.bin", report)
            self.assertIn("b.bin", report)
            self.assertIn("Skipped 1 oversized file(s)", report)
            opened_paths = [call.args[0] for call in open_spy.call_args_list]
            self.assertNotIn(oversized, opened_paths)

    def test_file_changed_during_hashing_is_skipped_not_treated_as_unique(self):
        with tempfile.TemporaryDirectory(prefix="steward_hash_changed_") as tmp:
            self._write_file(tmp, "changed.bin", b"12345678")
            real_fstat = os.fstat
            fstat_calls = 0

            def changed_fstat(file_descriptor):
                nonlocal fstat_calls
                fstat_calls += 1
                stat_result = real_fstat(file_descriptor)
                if fstat_calls == 1:
                    return stat_result
                return type(
                    "ChangedStat",
                    (),
                    {
                        "st_size": stat_result.st_size,
                        "st_mtime_ns": stat_result.st_mtime_ns + 1,
                        "st_dev": stat_result.st_dev,
                        "st_ino": stat_result.st_ino,
                    },
                )()

            with patch.object(
                tools, "REPORT_MAX_HASH_FILE_BYTES", 64, create=True
            ), patch.object(
                tools, "REPORT_MAX_HASH_TOTAL_BYTES", 64, create=True
            ), patch(
                "agent.tools.os.fstat", side_effect=changed_fstat
            ):
                report = tools.find_duplicates(tmp)

            self.assertIn("Skipped 1 changed file(s)", report)
            self.assertNotIn("duplicate of", report)

    def test_replacement_between_initial_stat_and_open_is_skipped(self):
        with tempfile.TemporaryDirectory(prefix="steward_hash_replaced_") as tmp:
            path = self._write_file(tmp, "replaced.bin", b"12345678")
            real_stat = os.stat(path)
            replaced_stat = type(
                "ReplacedStat",
                (),
                {
                    "st_size": real_stat.st_size,
                    "st_mtime_ns": real_stat.st_mtime_ns,
                    "st_dev": real_stat.st_dev,
                    "st_ino": real_stat.st_ino + 1,
                },
            )()

            with patch.object(
                tools, "REPORT_MAX_HASH_FILE_BYTES", 64, create=True
            ), patch.object(
                tools, "REPORT_MAX_HASH_TOTAL_BYTES", 64, create=True
            ), patch(
                "agent.tools.os.stat", return_value=replaced_stat
            ):
                digest, bytes_read, skip_reason = (
                    tools._hash_file_within_budget(path, 64)
                )

            self.assertIsNone(digest)
            self.assertEqual(bytes_read, 0)
            self.assertEqual(skip_reason, "changed")

    def test_file_growing_during_hashing_is_skipped_without_reading_past_limit(self):
        with tempfile.TemporaryDirectory(prefix="steward_hash_grew_") as tmp:
            self._write_file(tmp, "grew.bin", b"12345678")
            real_fstat = os.fstat
            real_open = open
            fstat_calls = 0
            read_sizes = []

            def changed_fstat(file_descriptor):
                nonlocal fstat_calls
                fstat_calls += 1
                stat_result = real_fstat(file_descriptor)
                if fstat_calls == 1:
                    return stat_result
                return type(
                    "ChangedStat",
                    (),
                    {
                        "st_size": stat_result.st_size + 1,
                        "st_mtime_ns": stat_result.st_mtime_ns,
                        "st_dev": stat_result.st_dev,
                        "st_ino": stat_result.st_ino,
                    },
                )()

            class TrackingReader:
                def __init__(self, handle):
                    self._handle = handle

                def __enter__(self):
                    return self

                def __exit__(self, *args):
                    return self._handle.__exit__(*args)

                def fileno(self):
                    return self._handle.fileno()

                def read(self, size=-1):
                    read_sizes.append(size)
                    return self._handle.read(size)

            def tracking_open(path, mode):
                return TrackingReader(real_open(path, mode))

            with patch.object(
                tools, "REPORT_MAX_HASH_FILE_BYTES", 8, create=True
            ), patch.object(
                tools, "REPORT_MAX_HASH_TOTAL_BYTES", 8, create=True
            ), patch(
                "agent.tools.os.fstat", side_effect=changed_fstat
            ), patch(
                "builtins.open", side_effect=tracking_open
            ):
                report = tools.find_duplicates(tmp)

            self.assertIn("Skipped 1 changed file(s)", report)
            self.assertTrue(read_sizes)
            self.assertLessEqual(max(read_sizes), 8)

    def test_inaccessible_file_is_reported_skipped(self):
        with tempfile.TemporaryDirectory(prefix="steward_hash_inaccessible_") as tmp:
            self._write_file(tmp, "locked.bin", b"12345678")

            with patch.object(
                tools, "REPORT_MAX_HASH_FILE_BYTES", 64, create=True
            ), patch.object(
                tools, "REPORT_MAX_HASH_TOTAL_BYTES", 64, create=True
            ), patch(
                "builtins.open", side_effect=PermissionError("denied")
            ):
                report = tools.find_duplicates(tmp)

            self.assertIn("Skipped 1 inaccessible file(s)", report)
            self.assertNotIn("duplicate of", report)

    def test_cumulative_limit_passes_and_limit_plus_one_is_reported_skipped(self):
        with tempfile.TemporaryDirectory(prefix="steward_hash_total_limit_") as tmp:
            self._write_file(tmp, "a.bin", b"1234")
            self._write_file(tmp, "b.bin", b"1234")
            over_budget = self._write_file(tmp, "c.bin", b"5")

            with patch.object(
                tools, "REPORT_MAX_HASH_FILE_BYTES", 64, create=True
            ), patch.object(
                tools, "REPORT_MAX_HASH_TOTAL_BYTES", 8, create=True
            ), patch(
                "builtins.open", wraps=open
            ) as open_spy:
                report = tools.find_duplicates(tmp)

            self.assertIn("a.bin", report)
            self.assertIn("b.bin", report)
            self.assertIn("cumulative hashing read-byte limit", report)
            opened_paths = [call.args[0] for call in open_spy.call_args_list]
            self.assertNotIn(over_budget, opened_paths)


if __name__ == "__main__":
    unittest.main()

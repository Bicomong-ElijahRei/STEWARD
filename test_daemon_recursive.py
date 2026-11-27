"""Regression coverage for bounded opt-in recursive daemon monitoring."""

import os
import subprocess
import tempfile
import threading
import time
import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

from agent.daemon import (
    FileCreationHandler,
    RecursiveScopeRefusal,
    build_monitor_scope,
)


class RecursiveMonitorScopeTests(unittest.TestCase):
    """Recursive coverage is explicit, bounded, deterministic, and link-free."""

    def test_default_scope_is_non_recursive_and_unchanged(self):
        with tempfile.TemporaryDirectory(prefix="steward_scope_default_") as tmp:
            incoming = os.path.join(tmp, "Incoming")
            sorted_dir = os.path.join(tmp, "Sorted")
            os.makedirs(incoming)
            os.makedirs(sorted_dir)
            os.makedirs(os.path.join(incoming, "child"))

            scope = build_monitor_scope(incoming, [sorted_dir], recursive=False)

            self.assertFalse(scope["recursive"])
            self.assertEqual(scope["watched_roots"], (os.path.realpath(incoming),))
            self.assertEqual(scope["bounds"]["max_depth"], 8)
            self.assertEqual(scope["bounds"]["max_directory_count"], 256)

    def test_depth_limit_passes_at_limit_and_refuses_at_limit_plus_one(self):
        with tempfile.TemporaryDirectory(prefix="steward_scope_depth_") as tmp:
            incoming = os.path.join(tmp, "Incoming")
            sorted_dir = os.path.join(tmp, "Sorted")
            os.makedirs(incoming)
            os.makedirs(sorted_dir)
            deep = os.path.join(incoming, "one", "two")
            os.makedirs(deep)

            scope = build_monitor_scope(
                incoming, [sorted_dir], recursive=True, max_depth=2
            )
            self.assertEqual(len(scope["watched_roots"]), 3)

            with self.assertRaises(RecursiveScopeRefusal) as caught:
                build_monitor_scope(
                    incoming, [sorted_dir], recursive=True, max_depth=1
                )
            self.assertEqual(caught.exception.code, "depth_limit_exceeded")

    def test_directory_count_limit_passes_at_limit_and_refuses_at_limit_plus_one(self):
        with tempfile.TemporaryDirectory(prefix="steward_scope_count_") as tmp:
            incoming = os.path.join(tmp, "Incoming")
            sorted_dir = os.path.join(tmp, "Sorted")
            os.makedirs(incoming)
            os.makedirs(sorted_dir)
            for name in ("one", "two", "three"):
                os.makedirs(os.path.join(incoming, name))

            scope = build_monitor_scope(
                incoming, [sorted_dir], recursive=True, max_directory_count=4
            )
            self.assertEqual(len(scope["watched_roots"]), 4)

            with self.assertRaises(RecursiveScopeRefusal) as caught:
                build_monitor_scope(
                    incoming, [sorted_dir], recursive=True, max_directory_count=3
                )
            self.assertEqual(caught.exception.code, "directory_limit_exceeded")

    def test_sorted_and_destination_roots_are_excluded(self):
        with tempfile.TemporaryDirectory(prefix="steward_scope_exclude_") as tmp:
            incoming = os.path.join(tmp, "Incoming")
            sorted_dir = os.path.join(tmp, "Sorted")
            destination = os.path.join(tmp, "Destination")
            os.makedirs(incoming)
            os.makedirs(sorted_dir)
            os.makedirs(destination)
            os.makedirs(os.path.join(incoming, "allowed"))
            os.makedirs(os.path.join(incoming, "Sorted"))
            os.makedirs(os.path.join(incoming, "Destination"))

            scope = build_monitor_scope(
                tmp, [sorted_dir, destination], recursive=True
            )

            roots = {os.path.normcase(path) for path in scope["watched_roots"]}
            self.assertNotIn(os.path.normcase(sorted_dir), roots)
            self.assertNotIn(os.path.normcase(destination), roots)
            self.assertIn(os.path.normcase(incoming), roots)
            self.assertIn(os.path.normcase(os.path.join(incoming, "allowed")), roots)

    def test_denylisted_directory_names_are_excluded_like_code_index(self):
        from agents.code_index_agent import CodeIndexAgent

        with tempfile.TemporaryDirectory(prefix="steward_scope_deny_") as tmp:
            incoming = os.path.join(tmp, "Incoming")
            sorted_dir = os.path.join(tmp, "Sorted")
            os.makedirs(incoming)
            os.makedirs(sorted_dir)
            denied = os.path.join(incoming, "node_modules")
            os.makedirs(denied)

            scope = build_monitor_scope(incoming, [sorted_dir], recursive=True)

            self.assertEqual(
                set(scope["denied_directories"]), set(CodeIndexAgent.DENIED_DIRECTORIES)
            )
            self.assertNotIn(
                os.path.normcase(denied),
                {os.path.normcase(path) for path in scope["watched_roots"]},
            )

    @unittest.skipUnless(os.name == "nt", "Windows junction proof requires Windows")
    def test_real_windows_junction_is_not_followed(self):
        with tempfile.TemporaryDirectory(prefix="steward_scope_junction_") as tmp:
            incoming = os.path.join(tmp, "Incoming")
            sorted_dir = os.path.join(tmp, "Sorted")
            outside = os.path.join(tmp, "Outside")
            os.makedirs(incoming)
            os.makedirs(sorted_dir)
            os.makedirs(outside)
            with open(os.path.join(outside, "secret.txt"), "w", encoding="utf-8") as handle:
                handle.write("outside")
            junction = os.path.join(incoming, "linked")
            result = subprocess.run(
                ["cmd", "/c", "mklink", "/J", junction, outside],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                check=False,
            )
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

            scope = build_monitor_scope(incoming, [sorted_dir], recursive=True)

            self.assertNotIn(
                os.path.normcase(outside),
                {os.path.normcase(path) for path in scope["watched_roots"]},
            )
            self.assertNotIn(
                os.path.normcase(junction),
                {os.path.normcase(path) for path in scope["watched_roots"]},
            )


class RecursiveDaemonBehaviorTests(unittest.TestCase):
    """Watcher processing and scheduled scans share one scope contract."""

    def _scope(self, incoming, sorted_dir, recursive=True):
        return build_monitor_scope(incoming, [sorted_dir], recursive=recursive)

    def test_file_in_sorted_produces_no_daemon_work(self):
        with tempfile.TemporaryDirectory(prefix="steward_daemon_exclude_") as tmp:
            incoming = os.path.join(tmp, "Incoming")
            sorted_dir = os.path.join(tmp, "Sorted")
            os.makedirs(incoming)
            os.makedirs(sorted_dir)
            with open(os.path.join(sorted_dir, "output.pdf"), "w", encoding="utf-8") as handle:
                handle.write("output")
            scope = {
                "recursive": True,
                "watched_roots": (os.path.realpath(tmp),),
                "excluded_roots": (os.path.realpath(sorted_dir),),
                "denied_directories": (),
                "bounds": {"max_depth": 8, "max_directory_count": 256},
                "destination_rule": "flatten",
            }
            agent = Mock()
            handler = FileCreationHandler(
                agent, sorted_dir, tmp, scope=scope
            )
            try:
                handler.on_created(SimpleNamespace(
                    is_directory=False,
                    src_path=os.path.join(sorted_dir, "output.pdf"),
                ))
                handler._queue.join()
                agent.categorise_file.assert_not_called()
            finally:
                handler.stop()

    def test_nested_file_destination_is_flattened_into_existing_category(self):
        from agents.file_agent import FileAgent

        with tempfile.TemporaryDirectory(prefix="steward_daemon_flatten_") as tmp:
            incoming = os.path.join(tmp, "Incoming")
            sorted_dir = os.path.join(tmp, "Sorted")
            os.makedirs(os.path.join(incoming, "sub", "deep"))
            os.makedirs(sorted_dir)
            source = os.path.join(incoming, "sub", "deep", "file.pdf")
            with open(source, "w", encoding="utf-8") as handle:
                handle.write("pdf")
            rules_path = os.path.join(tmp, "rules.yaml")
            with open(rules_path, "w", encoding="utf-8") as handle:
                handle.write("rules:\n  - pattern: '.*\\.pdf$'\n    target: Documents\n    priority: 100\n")
            agent = FileAgent(
                api_manager=Mock(),
                root_path=tmp,
                rules_path=rules_path,
            )

            result = agent.categorise_file(source, sorted_dir, dry_run=True)

            destination = os.path.join(sorted_dir, "Documents", "file.pdf")
            self.assertIn(f"move to '{destination}'", result)
            self.assertNotIn(
                os.path.join("sub", "deep", "Documents"),
                result,
            )

    def test_scheduled_scan_and_watcher_agree_on_recursive_scope(self):
        from agent.daemon import ScheduledScanner

        with tempfile.TemporaryDirectory(prefix="steward_scope_parity_") as tmp:
            incoming = os.path.join(tmp, "Incoming")
            sorted_dir = os.path.join(tmp, "Sorted")
            os.makedirs(os.path.join(incoming, "sub"))
            os.makedirs(sorted_dir)
            agent = Mock()
            agent.root_path = tmp
            scanner = ScheduledScanner(
                agent,
                incoming_path=incoming,
                destination_path=sorted_dir,
                recursive=True,
            )
            try:
                scope = scanner._monitor_scope()
                self.assertEqual(
                    scope["watched_roots"],
                    self._scope(incoming, sorted_dir)["watched_roots"],
                )
            finally:
                scanner.stop()

    def test_organizer_reports_actual_watched_roots_and_schedules_each_non_recursively(self):
        from gui.organizer_tab import OrganizerTab

        class Value:
            def __init__(self, value):
                self.value = value

            def get(self):
                return self.value

        with tempfile.TemporaryDirectory(prefix="steward_organizer_scope_") as tmp:
            incoming = os.path.join(tmp, "Incoming")
            sorted_dir = os.path.join(tmp, "Sorted")
            os.makedirs(os.path.join(incoming, "sub"))
            os.makedirs(sorted_dir)
            organizer = OrganizerTab.__new__(OrganizerTab)
            organizer.daemon_running = False
            organizer.observer = None
            organizer.daemon_handler = None
            organizer.file_agent = Mock()
            organizer.file_agent.root_path = tmp
            organizer.gui = Mock()
            organizer.watched_var = Value(incoming)
            organizer.dest_var = Value(sorted_dir)
            organizer.recursive_monitor_var = Value(True)
            organizer.daemon_status_label = Mock()
            organizer._log = Mock()
            observer = Mock()
            with patch("gui.organizer_tab.Observer", return_value=observer):
                result = organizer.start_daemon()
            try:
                self.assertTrue(result["started"])
                self.assertEqual(
                    result["scope"]["watched_roots"],
                    (
                        os.path.realpath(incoming),
                        os.path.realpath(os.path.join(incoming, "sub")),
                    ),
                )
                self.assertEqual(observer.schedule.call_count, 2)
                for call in observer.schedule.call_args_list:
                    self.assertFalse(call.kwargs["recursive"])
            finally:
                organizer.stop_daemon()

    def test_recursive_monitor_preference_defaults_off_and_round_trips(self):
        from gui.organizer_tab import OrganizerTab

        class Value:
            def __init__(self, value=False):
                self.value = value

            def get(self):
                return self.value

            def set(self, value):
                self.value = value

        with tempfile.TemporaryDirectory(prefix="steward_recursive_pref_") as tmp:
            state_path = os.path.join(tmp, "scheduled_scan.json")
            organizer = OrganizerTab.__new__(OrganizerTab)
            organizer._schedule_state_path = state_path
            organizer.schedule_enabled_var = Value(False)
            organizer.schedule_interval_var = Value("1 hr")
            organizer.recursive_monitor_var = Value(False)
            organizer._last_scheduled_scan_time = None
            self.assertTrue(organizer._save_schedule_state())

            restored = OrganizerTab.__new__(OrganizerTab)
            restored._schedule_state_path = state_path
            restored.schedule_enabled_var = Value(False)
            restored.schedule_interval_var = Value("1 hr")
            restored.recursive_monitor_var = Value(False)
            restored._last_scheduled_scan_time = None
            restored._load_schedule_state()
            self.assertFalse(restored.recursive_monitor_var.get())

            restored.recursive_monitor_var.set(True)
            restored._save_schedule_state()
            restored._load_schedule_state()
            self.assertTrue(restored.recursive_monitor_var.get())

    def test_changing_recursive_option_restarts_enabled_scanner(self):
        from gui.organizer_tab import OrganizerTab

        class Value:
            def __init__(self, value):
                self.value = value

            def get(self):
                return self.value

            def set(self, value):
                self.value = value

        with tempfile.TemporaryDirectory(prefix="steward_recursive_change_") as tmp:
            organizer = OrganizerTab.__new__(OrganizerTab)
            organizer.file_agent = Mock()
            organizer.file_agent.root_path = tmp
            organizer.watched_var = Value(os.path.join(tmp, "Incoming"))
            organizer.dest_var = Value(os.path.join(tmp, "Sorted"))
            organizer.schedule_enabled_var = Value(True)
            organizer.schedule_interval_var = Value("1 hr")
            organizer.recursive_monitor_var = Value(False)
            organizer._schedule_state_path = os.path.join(tmp, "scheduled_scan.json")
            organizer._last_scheduled_scan_time = None
            organizer._update_schedule_status = Mock()
            organizer._log = Mock()
            with patch("gui.organizer_tab.ScheduledScanner") as scanner_type:
                scanner = scanner_type.return_value
                scanner.start.return_value = True
                scanner.stop.return_value = True
                organizer.recursive_monitor_var.set(True)
                organizer._on_recursive_monitoring_changed()
            self.assertTrue(scanner_type.call_args.kwargs["recursive"])
            scanner.start.assert_called_once_with()


class DaemonScaleSafetyTests(unittest.TestCase):
    """Dedup eviction and stop remain bounded under recursive event volume."""

    def test_dedup_eviction_is_deterministic_and_never_drops_in_flight_path(self):
        with tempfile.TemporaryDirectory(prefix="steward_dedup_evict_") as tmp:
            agent = Mock()
            handler = FileCreationHandler(agent, os.path.join(tmp, "Sorted"), tmp)
            handler.MAX_TRACKED_FILES = 2
            try:
                first = os.path.join(tmp, "first.txt")
                second = os.path.join(tmp, "second.txt")
                third = os.path.join(tmp, "third.txt")
                with patch.object(
                    FileCreationHandler, "_file_identity", side_effect=[("d", 1), ("d", 2), ("d", 3)]
                ), patch.object(FileCreationHandler, "_process_file", side_effect=lambda path: None):
                    handler.on_created(SimpleNamespace(is_directory=False, src_path=first))
                    handler._queue.join()
                    handler.on_created(SimpleNamespace(is_directory=False, src_path=second))
                    handler.on_created(SimpleNamespace(is_directory=False, src_path=third))
                    handler._queue.join()

                self.assertLessEqual(len(handler.last_processed), 2)
                self.assertIn(second, handler.last_processed)
                self.assertIn(third, handler.last_processed)
                self.assertNotIn(first, handler.last_processed)
            finally:
                handler.stop()

    def test_in_flight_path_is_not_evicted(self):
        with tempfile.TemporaryDirectory(prefix="steward_dedup_inflight_") as tmp:
            agent = Mock()
            handler = FileCreationHandler(agent, os.path.join(tmp, "Sorted"), tmp)
            handler.MAX_TRACKED_FILES = 1
            entered = threading.Event()
            release = threading.Event()

            def blocked(_path):
                entered.set()
                release.wait(timeout=2.0)

            try:
                first = os.path.join(tmp, "first.txt")
                second = os.path.join(tmp, "second.txt")
                with patch.object(
                    FileCreationHandler, "_file_identity", side_effect=[("d", 1), ("d", 2)]
                ), patch.object(FileCreationHandler, "_process_file", side_effect=blocked):
                    handler.on_created(SimpleNamespace(is_directory=False, src_path=first))
                    self.assertTrue(entered.wait(timeout=1.0))
                    accepted = handler.on_created(SimpleNamespace(is_directory=False, src_path=second))
                    self.assertIn(first, handler.last_processed)
                    self.assertNotIn(second, handler.last_processed)
                    self.assertFalse(accepted)
                    release.set()
                    handler._queue.join()
            finally:
                release.set()
                handler.stop()

    def test_stop_is_responsive_while_events_are_queued(self):
        with tempfile.TemporaryDirectory(prefix="steward_daemon_burst_") as tmp:
            agent = Mock()
            handler = FileCreationHandler(agent, os.path.join(tmp, "Sorted"), tmp)
            release = threading.Event()

            def blocked(_path):
                release.wait(timeout=2.0)

            try:
                with patch.object(FileCreationHandler, "_process_file", side_effect=blocked):
                    for index in range(32):
                        handler.on_created(SimpleNamespace(
                            is_directory=False,
                            src_path=os.path.join(tmp, f"file_{index}.txt"),
                        ))
                    started = time.monotonic()
                    handler.stop()
                    latency = time.monotonic() - started
                self.assertLess(latency, 1.5, f"stop latency was {latency:.3f}s")
            finally:
                release.set()
                handler.stop()


if __name__ == "__main__":
    unittest.main()

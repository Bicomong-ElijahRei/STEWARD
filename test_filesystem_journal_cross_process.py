"""Cross-process regression tests for STEWARD's filesystem operation journal."""

import json
import os
import subprocess
import sys
import tempfile
import time
import unittest
from contextlib import contextmanager
from unittest.mock import Mock, patch

from agents.file_agent import FileAgent


class CrossProcessJournalTests(unittest.TestCase):
    """Exercise the journal with real, separate operating-system processes."""

    WORKER_TIMEOUT = 15
    LOCK_TIMEOUT = 1.0

    @staticmethod
    def _worker_source():
        return os.path.abspath(__file__)

    def _spawn_worker(self, mode, root, log_path, **values):
        command = [
            sys.executable,
            self._worker_source(),
            "--journal-worker",
            mode,
            "--root", root,
            "--log", log_path,
        ]
        for key, value in values.items():
            command.extend((f"--{key.replace('_', '-')}", str(value)))
        environment = os.environ.copy()
        environment["PYTHONUNBUFFERED"] = "1"
        environment["PYTHONIOENCODING"] = "utf-8"
        return subprocess.Popen(
            command,
            cwd=os.path.dirname(self._worker_source()),
            env=environment,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )

    def _finish_worker(self, process, label):
        try:
            stdout, stderr = process.communicate(timeout=self.WORKER_TIMEOUT)
        except subprocess.TimeoutExpired as exc:
            process.kill()
            stdout, stderr = process.communicate(timeout=5)
            self.fail(
                f"{label} worker timed out after {self.WORKER_TIMEOUT}s; "
                f"stdout={stdout!r} stderr={stderr!r}"
            )
        self.assertEqual(
            process.returncode, 0,
            f"{label} worker exited {process.returncode}; "
            f"stdout={stdout!r} stderr={stderr!r}",
        )
        return stdout, stderr

    def _wait_for_file(self, path, process, label, timeout=10):
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if os.path.exists(path):
                return
            if process.poll() is not None:
                stdout, stderr = process.communicate(timeout=5)
                self.fail(
                    f"{label} worker exited {process.returncode} before {path}; "
                    f"stdout={stdout!r} stderr={stderr!r}"
                )
            time.sleep(0.02)
        process.kill()
        stdout, stderr = process.communicate(timeout=5)
        self.fail(
            f"timed out waiting for {label} signal {path}; "
            f"stdout={stdout!r} stderr={stderr!r}"
        )

    @staticmethod
    def _read_log(log_path):
        with open(log_path, "r", encoding="utf-8") as handle:
            return json.load(handle)

    @staticmethod
    def _make_workspace(root):
        incoming = os.path.join(root, "Incoming")
        sorted_dir = os.path.join(root, "Sorted")
        os.makedirs(incoming)
        os.makedirs(sorted_dir)
        return incoming, sorted_dir

    def test_concurrent_processes_preserve_all_journal_operations(self):
        with tempfile.TemporaryDirectory(prefix="steward_multiprocess_") as root:
            incoming, sorted_dir = self._make_workspace(root)
            log_path = os.path.join(root, "operations.json")
            start_file = os.path.join(root, "start")
            workers = []
            for index in range(4):
                source = os.path.join(incoming, f"source-{index}.txt")
                destination = os.path.join(sorted_dir, f"destination-{index}.txt")
                with open(source, "w", encoding="utf-8") as handle:
                    handle.write(f"content-{index}")
                workers.append(self._spawn_worker(
                    "move", root, log_path,
                    source=source,
                    destination=destination,
                    ready_file=os.path.join(root, f"ready-{index}"),
                    start_file=start_file,
                ))

            for index, process in enumerate(workers):
                self._wait_for_file(
                    os.path.join(root, f"ready-{index}"), process, f"move-{index}"
                )
            with open(start_file, "w", encoding="utf-8") as handle:
                handle.write("go")

            for index, process in enumerate(workers):
                stdout, stderr = self._finish_worker(process, f"move-{index}")
                self.assertIn("Moved", stdout, stderr)

            entries = self._read_log(log_path)
            self.assertEqual(len(entries), 4)
            self.assertTrue(all(entry.get("success") for entry in entries))
            self.assertEqual(len({entry.get("id") for entry in entries}), 4)
            for index in range(4):
                self.assertFalse(os.path.exists(os.path.join(
                    incoming, f"source-{index}.txt"
                )))
                self.assertTrue(os.path.exists(os.path.join(
                    sorted_dir, f"destination-{index}.txt"
                )))

    def test_competing_undo_claims_allow_only_one_filesystem_mutation(self):
        with tempfile.TemporaryDirectory(prefix="steward_undo_race_") as root:
            incoming, sorted_dir = self._make_workspace(root)
            log_path = os.path.join(root, "operations.json")
            start_file = os.path.join(root, "start")
            source = os.path.join(incoming, "source.txt")
            destination = os.path.join(sorted_dir, "destination.txt")
            with open(source, "w", encoding="utf-8") as handle:
                handle.write("original")

            with patch.object(FileAgent, "OPERATION_LOG_PATH", log_path):
                agent = FileAgent(api_manager=Mock(), root_path=root)
            agent.OPERATION_LOG_PATH = log_path
            moved = agent.move_file(source, destination)
            self.assertIn("Moved", moved)

            workers = [
                self._spawn_worker(
                    "undo", root, log_path,
                    ready_file=os.path.join(root, f"ready-{index}"),
                    start_file=start_file,
                    hold_after_claim=0.5,
                )
                for index in range(2)
            ]
            for index, process in enumerate(workers):
                self._wait_for_file(
                    os.path.join(root, f"ready-{index}"), process, f"undo-{index}"
                )
            with open(start_file, "w", encoding="utf-8") as handle:
                handle.write("go")

            outputs = []
            for index, process in enumerate(workers):
                stdout, stderr = self._finish_worker(process, f"undo-{index}")
                self.assertTrue(
                    "Undid move" in stdout or "Undo failed" in stdout,
                    f"unexpected undo output: stdout={stdout!r} stderr={stderr!r}",
                )
                outputs.append(stdout)

            self.assertEqual(sum("Undid move" in output for output in outputs), 1)
            self.assertTrue(os.path.exists(source))
            self.assertFalse(os.path.exists(destination))
            entries = self._read_log(log_path)
            self.assertEqual(entries[-1].get("state"), "committed")
            self.assertEqual(entries[-1].get("undone"), True)

    def test_competing_redo_claims_allow_only_one_filesystem_mutation(self):
        with tempfile.TemporaryDirectory(prefix="steward_redo_race_") as root:
            incoming, sorted_dir = self._make_workspace(root)
            log_path = os.path.join(root, "operations.json")
            start_file = os.path.join(root, "start")
            source = os.path.join(incoming, "source.txt")
            destination = os.path.join(sorted_dir, "destination.txt")
            with open(source, "w", encoding="utf-8") as handle:
                handle.write("original")

            with patch.object(FileAgent, "OPERATION_LOG_PATH", log_path):
                agent = FileAgent(api_manager=Mock(), root_path=root)
            agent.OPERATION_LOG_PATH = log_path
            self.assertIn("Moved", agent.move_file(source, destination))
            self.assertIn("Undid move", agent.undo_last())

            workers = [
                self._spawn_worker(
                    "redo", root, log_path,
                    ready_file=os.path.join(root, f"ready-{index}"),
                    start_file=start_file,
                    hold_after_claim=0.5,
                )
                for index in range(2)
            ]
            for index, process in enumerate(workers):
                self._wait_for_file(
                    os.path.join(root, f"ready-{index}"), process, f"redo-{index}"
                )
            with open(start_file, "w", encoding="utf-8") as handle:
                handle.write("go")

            outputs = []
            for index, process in enumerate(workers):
                stdout, stderr = self._finish_worker(process, f"redo-{index}")
                self.assertTrue(
                    "Redid move" in stdout or "Redo failed" in stdout,
                    f"unexpected redo output: stdout={stdout!r} stderr={stderr!r}",
                )
                outputs.append(stdout)

            self.assertEqual(sum("Redid move" in output for output in outputs), 1)
            self.assertFalse(os.path.exists(source))
            self.assertTrue(os.path.exists(destination))
            entries = self._read_log(log_path)
            self.assertEqual(entries[-1].get("state"), "committed")
            self.assertEqual(entries[-1].get("undone"), False)

    def test_held_lock_times_out_before_filesystem_mutation(self):
        with tempfile.TemporaryDirectory(prefix="steward_lock_timeout_") as root:
            incoming, sorted_dir = self._make_workspace(root)
            log_path = os.path.join(root, "operations.json")
            source = os.path.join(incoming, "source.txt")
            destination = os.path.join(sorted_dir, "destination.txt")
            with open(source, "w", encoding="utf-8") as handle:
                handle.write("original")

            holder = self._spawn_worker(
                "hold-lock", root, log_path, ready_file=os.path.join(root, "ready")
            )
            self._wait_for_file(os.path.join(root, "ready"), holder, "lock-holder")
            worker = self._spawn_worker(
                "move", root, log_path,
                source=source,
                destination=destination,
                lock_timeout=self.LOCK_TIMEOUT,
            )
            stdout, stderr = self._finish_worker(worker, "timeout")
            self.assertIn("journal lock", stdout.lower())
            self.assertTrue(os.path.exists(source))
            self.assertFalse(os.path.exists(destination))
            self.assertFalse(os.path.exists(log_path))

            holder.terminate()
            holder.communicate(timeout=5)

    def test_process_death_releases_lock_and_persistent_sidecar_remains_reusable(self):
        with tempfile.TemporaryDirectory(prefix="steward_lock_crash_") as root:
            incoming, _ = self._make_workspace(root)
            log_path = os.path.join(root, "operations.json")
            ready_file = os.path.join(root, "ready")
            holder = self._spawn_worker(
                "hold-lock", root, log_path, ready_file=ready_file
            )
            self._wait_for_file(ready_file, holder, "lock-holder")
            holder.kill()
            holder.communicate(timeout=5)

            with patch.object(FileAgent, "OPERATION_LOG_PATH", log_path):
                agent = FileAgent(api_manager=Mock(), root_path=root)
            agent.OPERATION_LOG_PATH = log_path
            result = agent._record_operation("move", "a", "b")

            self.assertIsNone(result)
            self.assertEqual(len(self._read_log(log_path)), 1)
            self.assertTrue(os.path.exists(log_path + ".lock"))

    def test_nested_save_uses_journal_lock_before_agent_lock(self):
        """Direct saves must not invert the global/local lock ordering."""
        with tempfile.TemporaryDirectory(prefix="steward_lock_order_") as root:
            log_path = os.path.join(root, "operations.json")
            with patch.object(FileAgent, "OPERATION_LOG_PATH", log_path):
                agent = FileAgent(api_manager=Mock(), root_path=root)
            agent.OPERATION_LOG_PATH = log_path

            events = []
            original_lock = agent._lock
            original_journal_lock = agent._journal_process_lock

            @contextmanager
            def observed_journal_lock():
                events.append("journal-acquired")
                with original_journal_lock():
                    yield

            class ObservedLock:
                def __enter__(self):
                    events.append("agent-acquired")
                    return original_lock.__enter__()

                def __exit__(self, *args):
                    return original_lock.__exit__(*args)

            agent._lock = ObservedLock()
            agent._journal_process_lock = observed_journal_lock
            agent._save_operation_log()

            self.assertEqual(
                events,
                ["journal-acquired", "agent-acquired"],
            )

    def test_journal_replace_failure_preserves_truthful_recoverable_history(self):
        with tempfile.TemporaryDirectory(prefix="steward_replace_failure_") as root:
            incoming, sorted_dir = self._make_workspace(root)
            log_path = os.path.join(root, "operations.json")
            source = os.path.join(incoming, "source.txt")
            destination = os.path.join(sorted_dir, "destination.txt")
            with open(source, "w", encoding="utf-8") as handle:
                handle.write("original")
            with patch.object(FileAgent, "OPERATION_LOG_PATH", log_path):
                agent = FileAgent(api_manager=Mock(), root_path=root)
            agent.OPERATION_LOG_PATH = log_path

            with patch(
                "agents.file_agent.os.replace",
                side_effect=OSError("replace failed"),
            ):
                result = agent.move_file(source, destination)

            self.assertIn("operation was not started", result)
            self.assertTrue(os.path.exists(source))
            self.assertFalse(os.path.exists(destination))
            self.assertFalse(os.path.exists(log_path))
            self.assertTrue(os.path.exists(log_path + ".lock"))


def _journal_worker_main(argv):
    """Subprocess entry point for deterministic cross-process journal tests."""
    import argparse

    parser = argparse.ArgumentParser()
    parser.add_argument("journal_worker")
    parser.add_argument("--root", required=True)
    parser.add_argument("--log", required=True)
    parser.add_argument("--source")
    parser.add_argument("--destination")
    parser.add_argument("--ready-file")
    parser.add_argument("--start-file")
    parser.add_argument("--hold-after-claim", type=float, default=0)
    parser.add_argument("--lock-timeout", type=float, default=10)
    args = parser.parse_args(argv)

    with patch.object(FileAgent, "OPERATION_LOG_PATH", args.log):
        agent = FileAgent(api_manager=Mock(), root_path=args.root)
    agent.OPERATION_LOG_PATH = args.log
    agent.JOURNAL_LOCK_TIMEOUT_SECONDS = args.lock_timeout

    if args.ready_file:
        with open(args.ready_file, "w", encoding="utf-8") as handle:
            handle.write("ready")
    if args.start_file:
        deadline = time.monotonic() + 10
        while not os.path.exists(args.start_file):
            if time.monotonic() >= deadline:
                raise TimeoutError("start signal did not arrive")
            time.sleep(0.02)

    if args.journal_worker == "move":
        print(agent.move_file(args.source, args.destination))
        return 0
    if args.journal_worker in ("undo", "redo"):
        original_begin = agent._begin_transition
        if args.hold_after_claim:
            def delayed_begin(entry, kind):
                original_begin(entry, kind)
                time.sleep(args.hold_after_claim)
            agent._begin_transition = delayed_begin
        result = agent.undo_last() if args.journal_worker == "undo" else agent.redo_last()
        print(result)
        return 0
    if args.journal_worker == "hold-lock":
        with agent._journal_process_lock():
            time.sleep(30)
        return 0
    raise ValueError(f"Unknown worker mode: {args.journal_worker}")


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "--journal-worker":
        raise SystemExit(_journal_worker_main(sys.argv[2:]))
    unittest.main()

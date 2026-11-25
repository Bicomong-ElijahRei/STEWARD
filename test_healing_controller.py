"""C4-I1 pure healing-controller acceptance tests."""

import ast
import builtins
import inspect
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from agents.healing_controller import (
    ControllerResult,
    ExecutorResult,
    HealingController,
)


class TempAtomicJournal:
    """Test-only durable journal using the repository's atomic write pattern."""

    def __init__(self, root, fail_phase=None, fail_once=False):
        self.path = Path(root) / "healing-journal.json"
        self.records = []
        self.fail_phase = fail_phase
        self.fail_once = fail_once

    def write(self, record):
        phase = record.get("phase")
        if phase == self.fail_phase:
            if self.fail_once:
                self.fail_phase = None
            raise OSError("injected journal failure")
        updated = list(self.records) + [record]
        temporary = self.path.with_name(self.path.name + ".tmp")
        with open(temporary, "x", encoding="utf-8") as handle:
            json.dump(updated, handle, sort_keys=True, separators=(",", ":"))
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, self.path)
        self.records = updated


class ScriptedExecutor:
    """Test-only injected executor; it never launches an operating-system process."""

    def __init__(self, script, journal=None):
        self.script = list(script)
        self.journal = journal
        self.calls = []

    def execute(self, request):
        self.calls.append(request.iteration)
        if self.journal is not None:
            phases = [record["phase"] for record in self.journal.records]
            if "intent" not in phases:
                raise AssertionError("executor ran before durable intent")
        index = min(request.iteration - 1, len(self.script) - 1)
        item = self.script[index]
        if isinstance(item, BaseException):
            raise item
        return item


class RaisingApplier:
    """Test-only fake patch applier; the controller must never reach it."""

    def __init__(self):
        self.calls = 0

    def apply(self, *_args, **_kwargs):
        self.calls += 1
        raise AssertionError("controller reached a patch-application path")


class HealingControllerTests(unittest.TestCase):
    def make_controller(self, executor, journal, **kwargs):
        return HealingController(executor=executor, journal=journal, **kwargs)

    def test_hard_bound_stops_at_exact_configured_maximum(self):
        with tempfile.TemporaryDirectory() as root:
            journal = TempAtomicJournal(root)
            executor = ScriptedExecutor([
                ExecutorResult(status="failure", stdout="one", stderr="one"),
                ExecutorResult(status="failure", stdout="two", stderr="two"),
                ExecutorResult(status="failure", stdout="three", stderr="three"),
            ])
            result = self.make_controller(
                executor, journal, max_iterations=3
            ).run()
            self.assertIsInstance(result, ControllerResult)
            self.assertEqual(result.status, "bound_reached")
            self.assertEqual(result.iterations_completed, 3)
            self.assertEqual(executor.calls, [1, 2, 3])

    def test_success_signal_terminates_immediately(self):
        with tempfile.TemporaryDirectory() as root:
            journal = TempAtomicJournal(root)
            executor = ScriptedExecutor([
                ExecutorResult(status="success", stdout="ok")
            ])
            result = self.make_controller(executor, journal, max_iterations=5).run()
            self.assertEqual(result.status, "success")
            self.assertEqual(result.iterations_completed, 1)
            self.assertEqual(executor.calls, [1])

    def test_unrecoverable_error_result_terminates(self):
        with tempfile.TemporaryDirectory() as root:
            journal = TempAtomicJournal(root)
            executor = ScriptedExecutor([
                ExecutorResult(status="unrecoverable_error", stderr="bad output")
            ])
            result = self.make_controller(executor, journal).run()
            self.assertEqual(result.status, "unrecoverable_error")
            self.assertEqual(result.iterations_completed, 1)
            self.assertEqual(journal.records[-1]["status"], "unrecoverable_error")

    def test_executor_exception_is_truthful_unrecoverable_error(self):
        with tempfile.TemporaryDirectory() as root:
            journal = TempAtomicJournal(root)
            executor = ScriptedExecutor([RuntimeError("executor crashed")])
            result = self.make_controller(executor, journal).run()
            self.assertEqual(result.status, "unrecoverable_error")
            self.assertEqual(result.iterations_completed, 1)
            self.assertEqual(journal.records[-1]["status"], "unrecoverable_error")

    def test_invalid_executor_result_is_unrecoverable_error(self):
        with tempfile.TemporaryDirectory() as root:
            journal = TempAtomicJournal(root)
            executor = ScriptedExecutor([object()])
            result = self.make_controller(executor, journal).run()
            self.assertEqual(result.status, "unrecoverable_error")
            self.assertEqual(executor.calls, [1])

    def test_repeated_identical_failure_terminates_deterministically(self):
        with tempfile.TemporaryDirectory() as root:
            journal = TempAtomicJournal(root)
            executor = ScriptedExecutor([
                ExecutorResult(status="failure", stdout="same", stderr="same")
            ])
            result = self.make_controller(
                executor, journal, max_iterations=5
            ).run()
            self.assertEqual(result.status, "repeated_failure")
            self.assertEqual(result.iterations_completed, 2)
            self.assertEqual(executor.calls, [1, 2])

    def test_repeated_failure_detection_can_be_configured(self):
        with tempfile.TemporaryDirectory() as root:
            journal = TempAtomicJournal(root)
            executor = ScriptedExecutor([
                ExecutorResult(status="failure", stdout="same", stderr="same")
            ])
            result = self.make_controller(
                executor, journal, max_iterations=5, repeated_failure_limit=3
            ).run()
            self.assertEqual(result.status, "repeated_failure")
            self.assertEqual(result.iterations_completed, 3)

    def test_distinct_failures_do_not_trigger_repeated_failure(self):
        with tempfile.TemporaryDirectory() as root:
            journal = TempAtomicJournal(root)
            executor = ScriptedExecutor([
                ExecutorResult(status="failure", stdout="one", stderr="one"),
                ExecutorResult(status="failure", stdout="two", stderr="two"),
                ExecutorResult(status="failure", stdout="three", stderr="three"),
            ])
            result = self.make_controller(
                executor, journal, max_iterations=3
            ).run()
            self.assertEqual(result.status, "bound_reached")
            self.assertEqual(result.iterations_completed, 3)

    def test_journal_records_intent_before_each_iteration_and_outcome_after(self):
        with tempfile.TemporaryDirectory() as root:
            journal = TempAtomicJournal(root)
            executor = ScriptedExecutor([
                ExecutorResult(status="failure", stdout="one", stderr="one"),
                ExecutorResult(status="success", stdout="done"),
            ])
            self.make_controller(executor, journal, max_iterations=3).run()
            phases = [record["phase"] for record in journal.records]
            self.assertEqual(
                phases, ["intent", "outcome", "intent", "outcome", "terminal"]
            )
            intents = [r for r in journal.records if r["phase"] == "intent"]
            outcomes = [r for r in journal.records if r["phase"] == "outcome"]
            self.assertEqual([r["iteration"] for r in intents], [1, 2])
            self.assertEqual([r["iteration"] for r in outcomes], [1, 2])
            self.assertEqual(outcomes[-1]["status"], "success")

    def test_journal_write_failure_before_iteration_prevents_execution(self):
        with tempfile.TemporaryDirectory() as root:
            journal = TempAtomicJournal(root, fail_phase="intent")
            executor = ScriptedExecutor([
                ExecutorResult(status="success", stdout="ok")
            ])
            result = self.make_controller(executor, journal).run()
            self.assertEqual(result.status, "journal_error")
            self.assertEqual(result.iterations_completed, 0)
            self.assertEqual(executor.calls, [])

    def test_journal_write_failure_after_iteration_is_uncertain(self):
        with tempfile.TemporaryDirectory() as root:
            journal = TempAtomicJournal(root, fail_phase="outcome")
            executor = ScriptedExecutor([
                ExecutorResult(status="success", stdout="ok")
            ])
            result = self.make_controller(executor, journal).run()
            self.assertEqual(result.status, "uncertain")
            self.assertEqual(result.iterations_completed, 0)
            self.assertEqual(executor.calls, [1])

    def test_oversized_observation_is_truncated_and_reported(self):
        with tempfile.TemporaryDirectory() as root:
            journal = TempAtomicJournal(root)
            executor = ScriptedExecutor([
                ExecutorResult(status="failure", stdout="A" * 5000, stderr="B" * 100)
            ])
            result = self.make_controller(
                executor, journal, max_observation_chars=256, max_iterations=1
            ).run()
            self.assertEqual(result.status, "bound_reached")
            outcome = [r for r in journal.records if r["phase"] == "outcome"][0]
            stdout = outcome["observation"]["stdout"]
            self.assertTrue(stdout["truncated"])
            self.assertEqual(stdout["original_chars"], 5000)
            self.assertEqual(len(stdout["text"]), 256)
            self.assertEqual(outcome["observation"]["stderr"]["truncated"], False)
            self.assertLessEqual(len(json.dumps(journal.records)), 4000)

    def test_observation_text_is_bounded_in_journal(self):
        with tempfile.TemporaryDirectory() as root:
            journal = TempAtomicJournal(root)
            executor = ScriptedExecutor([
                ExecutorResult(status="failure", stdout="C" * 100000, stderr="D" * 100000)
            ])
            self.make_controller(
                executor, journal, max_observation_chars=512
            ).run()
            outcome = [r for r in journal.records if r["phase"] == "outcome"][0]
            self.assertLessEqual(len(outcome["observation"]["stdout"]["text"]), 512)
            self.assertLessEqual(len(outcome["observation"]["stderr"]["text"]), 512)

    def test_cancellation_between_iterations_stops_at_safe_boundary(self):
        with tempfile.TemporaryDirectory() as root:
            journal = TempAtomicJournal(root)
            cancel = {"value": False}

            class CancellingExecutor:
                def __init__(self):
                    self.calls = 0

                def execute(self, request):
                    self.calls += 1
                    cancel["value"] = True
                    return ExecutorResult(status="failure", stdout="one", stderr="one")

            executor = CancellingExecutor()
            result = self.make_controller(
                executor, journal, max_iterations=5, is_cancelled=lambda: cancel["value"]
            ).run()
            self.assertEqual(result.status, "cancelled")
            self.assertEqual(result.iterations_completed, 1)
            self.assertEqual(executor.calls, 1)
            phases = [record["phase"] for record in journal.records]
            self.assertEqual(phases, ["intent", "outcome", "terminal"])
            terminal = journal.records[-1]
            self.assertEqual(terminal["status"], "cancelled")
            self.assertEqual(terminal["iterations_completed"], 1)

    def test_cancellation_before_first_iteration_starts_nothing(self):
        with tempfile.TemporaryDirectory() as root:
            journal = TempAtomicJournal(root)
            executor = ScriptedExecutor([
                ExecutorResult(status="success", stdout="ok")
            ])
            result = self.make_controller(
                executor, journal, is_cancelled=lambda: True
            ).run()
            self.assertEqual(result.status, "cancelled")
            self.assertEqual(result.iterations_completed, 0)
            self.assertEqual(executor.calls, [])

    def test_no_execution_proof_spies_are_never_called(self):
        with tempfile.TemporaryDirectory() as root:
            journal = TempAtomicJournal(root)

            class DirectExecutionExecutor:
                def execute(self, request):
                    raise AssertionError("controller attempted direct execution")

            executor = DirectExecutionExecutor()
            with mock.patch.object(subprocess, "Popen") as popen, \
                    mock.patch.object(subprocess, "run") as run, \
                    mock.patch.object(os, "system") as system, \
                    mock.patch.object(builtins, "exec") as exec_, \
                    mock.patch.object(builtins, "eval") as eval_:
                self.make_controller(executor, journal, max_iterations=2).run()
            popen.assert_not_called()
            run.assert_not_called()
            system.assert_not_called()
            exec_.assert_not_called()
            eval_.assert_not_called()

    def test_controller_module_has_no_execution_imports_or_calls(self):
        source_path = Path(inspect.getfile(sys.modules["agents.healing_controller"]))
        source = source_path.read_text(encoding="utf-8")
        tree = ast.parse(source)
        forbidden_imports = {"subprocess", "pty", "importlib", "multiprocessing"}
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    self.assertNotIn(alias.name.split(".")[0], forbidden_imports)
            elif isinstance(node, ast.ImportFrom):
                root = (node.module or "").split(".")[0]
                self.assertNotIn(root, forbidden_imports)
            elif isinstance(node, ast.Call):
                func = node.func
                if isinstance(func, ast.Name):
                    self.assertNotIn(func.id, {"exec", "eval", "compile", "__import__"})
                if isinstance(func, ast.Attribute):
                    self.assertNotIn(func.attr, {"system", "popen", "Popen"})

    def test_no_auto_apply_proof_fake_applier_is_never_called(self):
        with tempfile.TemporaryDirectory() as root:
            journal = TempAtomicJournal(root)
            applier = RaisingApplier()
            executor = ScriptedExecutor([
                ExecutorResult(status="failure", stdout="bad", stderr="bad")
            ])

            def proposal_callback(request):
                return None

            controller = self.make_controller(
                executor, journal, max_iterations=2, proposal_callback=proposal_callback
            )
            result = controller.run()
            self.assertEqual(applier.calls, 0)
            self.assertNotIn("applier", inspect.signature(controller.__init__).parameters)

    def test_proposal_callback_receives_request_but_never_applies(self):
        with tempfile.TemporaryDirectory() as root:
            journal = TempAtomicJournal(root)
            requests = []
            executor = ScriptedExecutor([
                ExecutorResult(status="failure", stdout="bad", stderr="bad")
            ])

            def proposal_callback(request):
                requests.append(request)
                return "proposal-id-1"

            result = self.make_controller(
                executor, journal, max_iterations=2, proposal_callback=proposal_callback
            ).run()
            self.assertEqual(len(requests), 1)
            self.assertEqual(requests[0].iteration, 1)
            self.assertEqual(result.status, "repeated_failure")

    def test_determinism_identical_inputs_produce_identical_records(self):
        with tempfile.TemporaryDirectory() as first_root, \
                tempfile.TemporaryDirectory() as second_root:
            first_journal = TempAtomicJournal(first_root)
            second_journal = TempAtomicJournal(second_root)
            script = [
                ExecutorResult(status="failure", stdout="same", stderr="same"),
                ExecutorResult(status="failure", stdout="same", stderr="same"),
            ]
            first = self.make_controller(
                ScriptedExecutor(script), first_journal, max_iterations=4
            ).run()
            second = self.make_controller(
                ScriptedExecutor(script), second_journal, max_iterations=4
            ).run()
            self.assertEqual(first.status, second.status)
            self.assertEqual(first.iterations_completed, second.iterations_completed)
            self.assertEqual(first_journal.records, second_journal.records)

    def test_secret_like_output_is_redacted_before_journaling(self):
        with tempfile.TemporaryDirectory() as root:
            journal = TempAtomicJournal(root)
            executor = ScriptedExecutor([
                ExecutorResult(
                    status="failure",
                    stdout="API_KEY=supersecretvalue",
                    stderr="-----BEGIN PRIVATE KEY-----\nabc\n-----END PRIVATE KEY-----",
                )
            ])
            self.make_controller(executor, journal, max_iterations=1).run()
            outcome = [r for r in journal.records if r["phase"] == "outcome"][0]
            stdout = outcome["observation"]["stdout"]
            stderr = outcome["observation"]["stderr"]
            self.assertNotIn("supersecretvalue", stdout["text"])
            self.assertIn("[REDACTED]", stdout["text"])
            self.assertGreaterEqual(stdout["redactions"], 1)
            self.assertNotIn("BEGIN PRIVATE KEY", stderr["text"])
            self.assertGreaterEqual(stderr["redactions"], 1)
            self.assertNotIn("supersecretvalue", json.dumps(journal.records))

    def test_controller_result_exposes_only_truthful_terminal_fields(self):
        with tempfile.TemporaryDirectory() as root:
            journal = TempAtomicJournal(root)
            executor = ScriptedExecutor([
                ExecutorResult(status="success", stdout="ok")
            ])
            result = self.make_controller(executor, journal).run()
            self.assertEqual(
                set(result.__dataclass_fields__),
                {"status", "iterations_completed", "detail"},
            )

    def test_iteration_timeout_is_enforced_by_the_controller(self):
        with tempfile.TemporaryDirectory() as root:
            journal = TempAtomicJournal(root)
            ticks = iter([0.0, 0.0, 100.0, 100.0, 100.0])
            executor = ScriptedExecutor([
                ExecutorResult(status="failure", stdout="one", stderr="one")
            ])
            result = self.make_controller(
                executor,
                journal,
                max_iterations=5,
                iteration_timeout_seconds=1.0,
                clock=lambda: next(ticks),
            ).run()
            self.assertEqual(result.status, "timeout")
            self.assertEqual(result.iterations_completed, 1)
            self.assertEqual(executor.calls, [1])
            outcome = [r for r in journal.records if r["phase"] == "outcome"][0]
            self.assertEqual(outcome["status"], "timeout")

    def test_total_timeout_stops_before_the_next_iteration(self):
        with tempfile.TemporaryDirectory() as root:
            journal = TempAtomicJournal(root)
            ticks = iter([0.0, 0.0, 0.0, 500.0])
            executor = ScriptedExecutor([
                ExecutorResult(status="failure", stdout="one", stderr="one")
            ])
            result = self.make_controller(
                executor,
                journal,
                max_iterations=5,
                total_timeout_seconds=10.0,
                clock=lambda: next(ticks),
            ).run()
            self.assertEqual(result.status, "timeout")
            self.assertEqual(result.iterations_completed, 1)
            self.assertEqual(executor.calls, [1])
            terminal = journal.records[-1]
            self.assertEqual(terminal["status"], "timeout")

    def test_module_exposes_only_pure_public_surface(self):
        import agents.healing_controller as module
        self.assertTrue(hasattr(module, "HealingController"))
        self.assertTrue(hasattr(module, "ExecutorResult"))
        self.assertTrue(hasattr(module, "ControllerResult"))
        source = Path(inspect.getfile(module)).read_text(encoding="utf-8")
        self.assertNotIn("subprocess", source)
        self.assertNotIn("os.system", source)
        self.assertNotIn("importlib", source)
        self.assertNotIn("pty", source)


if __name__ == "__main__":
    unittest.main()

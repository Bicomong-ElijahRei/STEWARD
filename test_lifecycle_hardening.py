"""Deterministic regressions for follow-up lifecycle and intent hardening."""

import os
import tempfile
import threading
import unittest
from unittest.mock import Mock, patch

from agent.daemon import ScheduledScanner
from agents.coding_agent import CodingAgent
from agents.file_agent import FileAgent
from agents.supervisor import (
    AGENT_CODING,
    AGENT_FILE_OP,
    AGENT_GENERAL_CHAT,
    SupervisorAgent,
)
from gui.chat_tab import ChatTab


REAL_THREAD = threading.Thread


class ScheduledScannerCancellationTests(unittest.TestCase):
    """Cancellation and generation ownership are enforced at commit time."""

    def make_scanner(self, tmp, notifications=None):
        file_agent = Mock()
        file_agent.root_path = tmp
        return ScheduledScanner(
            file_agent,
            interval_minutes=60,
            on_scan=(notifications.append if notifications is not None else None),
            stop_timeout=0.05,
        )

    def assert_no_commit(self, scanner, notifications):
        self.assertEqual(scanner.scan_count, 0)
        self.assertEqual(scanner.files_processed, 0)
        self.assertIsNone(scanner.last_scan_time)
        self.assertIsNone(scanner.last_error)
        self.assertEqual(notifications, [])

    def test_cancellation_before_scan_starts_prevents_commit(self):
        with tempfile.TemporaryDirectory(prefix="steward_scan_cancel_start_") as tmp:
            notifications = []
            scanner = self.make_scanner(tmp, notifications)
            cancelled = threading.Event()
            cancelled.set()

            summary = scanner._scan(cancelled, scanner._generation)

            self.assertTrue(summary["cancelled"])
            self.assertTrue(summary["skipped"])
            self.assertEqual(summary["error"], "scan_cancelled")
            self.assert_no_commit(scanner, notifications)

    def test_cancellation_while_enumeration_is_blocked_prevents_commit(self):
        with tempfile.TemporaryDirectory(prefix="steward_scan_cancel_enum_") as tmp:
            notifications = []
            scanner = self.make_scanner(tmp, notifications)
            os.makedirs(os.path.join(tmp, "Incoming"))
            self.assertTrue(scanner.start())
            enumeration_started = threading.Event()
            release_enumeration = threading.Event()
            result = {}

            def blocked_listdir(_path):
                enumeration_started.set()
                self.assertTrue(release_enumeration.wait(timeout=2.0))
                return []

            def run_scan():
                result["summary"] = scanner._scan()

            with patch("agent.daemon.os.listdir", side_effect=blocked_listdir):
                worker = REAL_THREAD(target=run_scan)
                worker.start()
                self.assertTrue(enumeration_started.wait(timeout=1.0))
                self.assertFalse(scanner.stop())
                release_enumeration.set()
                worker.join(timeout=2.0)

            self.assertFalse(worker.is_alive())
            self.assertTrue(result["summary"]["cancelled"])
            self.assert_no_commit(scanner, notifications)

    def test_cancellation_after_empty_enumeration_prevents_empty_commit(self):
        with tempfile.TemporaryDirectory(prefix="steward_scan_cancel_empty_") as tmp:
            notifications = []
            scanner = self.make_scanner(tmp, notifications)
            self.assertTrue(scanner.start())
            original_commit = scanner._commit_scan

            def cancel_at_commit(summary, generation, cancel_event):
                cancel_event.set()
                return original_commit(summary, generation, cancel_event)

            with patch.object(scanner, "_commit_scan", side_effect=cancel_at_commit):
                summary = scanner._scan()
            scanner.stop()

            self.assertTrue(summary["cancelled"])
            self.assertTrue(summary["skipped"])
            self.assert_no_commit(scanner, notifications)

    def test_cancellation_before_missing_folder_commit_prevents_commit(self):
        with tempfile.TemporaryDirectory(prefix="steward_scan_cancel_missing_") as tmp:
            notifications = []
            scanner = self.make_scanner(tmp, notifications)
            self.assertTrue(scanner.start())

            def cancel_during_check(_path):
                scanner._cancel_event.set()
                return False

            with patch("agent.daemon.os.path.isdir", side_effect=cancel_during_check):
                summary = scanner._scan()
            scanner.stop()

            self.assertTrue(summary["cancelled"])
            self.assert_no_commit(scanner, notifications)

    def test_cancellation_before_filesystem_error_commit_prevents_commit(self):
        with tempfile.TemporaryDirectory(prefix="steward_scan_cancel_error_") as tmp:
            notifications = []
            scanner = self.make_scanner(tmp, notifications)
            os.makedirs(os.path.join(tmp, "Incoming"))
            self.assertTrue(scanner.start())

            def cancel_during_list(_path):
                scanner._cancel_event.set()
                raise OSError("enumeration failed")

            with patch("agent.daemon.os.listdir", side_effect=cancel_during_list):
                summary = scanner._scan()
            scanner.stop()

            self.assertTrue(summary["skipped"])
            self.assertTrue(summary["cancelled"])
            self.assertEqual(summary["error"], "scan_cancelled")
            self.assert_no_commit(scanner, notifications)

    def test_cancellation_during_file_processing_prevents_commit(self):
        with tempfile.TemporaryDirectory(prefix="steward_scan_cancel_file_") as tmp:
            incoming = os.path.join(tmp, "Incoming")
            os.makedirs(incoming)
            source = os.path.join(incoming, "one.txt")
            with open(source, "w", encoding="utf-8") as handle:
                handle.write("one")
            notifications = []
            scanner = self.make_scanner(tmp, notifications)
            self.assertTrue(scanner.start())
            processing_started = threading.Event()
            release_processing = threading.Event()
            result = {}

            def categorise(*_args, **_kwargs):
                processing_started.set()
                self.assertTrue(release_processing.wait(timeout=2.0))
                os.remove(source)
                return "Moved one.txt"

            scanner.file_agent.categorise_file.side_effect = categorise

            def run_scan():
                result["summary"] = scanner._scan()

            worker = threading.Thread(target=run_scan)
            worker.start()
            self.assertTrue(processing_started.wait(timeout=1.0))
            scanner._cancel_event.set()
            release_processing.set()
            worker.join(timeout=2.0)
            scanner.stop()

            self.assertFalse(worker.is_alive())
            self.assertTrue(result["summary"]["cancelled"])
            self.assert_no_commit(scanner, notifications)

    def test_previous_generation_cannot_commit_after_new_generation_starts(self):
        with tempfile.TemporaryDirectory(prefix="steward_scan_new_generation_") as tmp:
            notifications = []
            scanner = self.make_scanner(tmp, notifications)
            self.assertTrue(scanner.start())
            old_generation = scanner._generation
            old_cancel = scanner._cancel_event
            scanner.stop()
            self.assertTrue(scanner.start())
            summary = scanner._skipped_scan("old", cancelled=False)

            committed = scanner._commit_scan(summary, old_generation, old_cancel)
            scanner.stop()

            self.assertFalse(committed)
            self.assertEqual(summary["error"], "stale_generation")
            self.assert_no_commit(scanner, notifications)

    def test_completed_scan_commits_and_notifies(self):
        with tempfile.TemporaryDirectory(prefix="steward_scan_complete_") as tmp:
            notifications = []
            scanner = self.make_scanner(tmp, notifications)
            self.assertTrue(scanner.start())

            summary = scanner._scan()
            scanner.stop()

            self.assertFalse(summary["cancelled"])
            self.assertFalse(summary["skipped"])
            self.assertEqual(scanner.scan_count, 1)
            self.assertEqual(scanner.files_processed, 0)
            self.assertIsNotNone(scanner.last_scan_time)
            self.assertEqual(notifications, [summary])

    def test_restart_does_not_allow_previous_worker_to_mutate_new_generation(self):
        with tempfile.TemporaryDirectory(prefix="steward_scan_restart_owner_") as tmp:
            notifications = []
            scanner = self.make_scanner(tmp, notifications)
            os.makedirs(os.path.join(tmp, "Incoming"))
            self.assertTrue(scanner.start())
            enumeration_started = threading.Event()
            release_enumeration = threading.Event()
            old_result = {}

            def blocked_listdir(_path):
                enumeration_started.set()
                self.assertTrue(release_enumeration.wait(timeout=2.0))
                return []

            def run_old_scan():
                old_result["summary"] = scanner._scan()

            with patch("agent.daemon.os.listdir", side_effect=blocked_listdir):
                worker = REAL_THREAD(target=run_old_scan)
                worker.start()
                self.assertTrue(enumeration_started.wait(timeout=1.0))
                scanner.stop()
                self.assertTrue(scanner.start())
                new_generation = scanner._generation
                release_enumeration.set()
                worker.join(timeout=2.0)

            self.assertFalse(worker.is_alive())
            self.assertTrue(old_result["summary"]["skipped"])
            self.assertEqual(old_result["summary"]["error"], "stale_generation")
            self.assertGreater(new_generation, 1)
            self.assert_no_commit(scanner, notifications)
            scanner.stop()


class FilePlanOwnershipTests(unittest.TestCase):
    """A superseded preview cannot publish a late executable plan."""

    def make_agent(self, root):
        manager = Mock()
        manager.route_request.return_value = {
            "choices": [{
                "message": {
                    "tool_calls": [{
                        "id": "call-1",
                        "type": "function",
                        "function": {
                            "name": "move_file",
                            "arguments": {
                                "source": "Incoming/source.txt",
                                "destination": "Sorted/source.txt",
                            },
                        },
                    }],
                },
            }],
            "_steward": {"provider": "FileProvider", "model": "file-model"},
        }
        agent = FileAgent(api_manager=manager, root_path=root)
        agent.OPERATION_LOG_PATH = os.path.join(root, "operations.json")
        return agent, manager

    def test_discarded_preview_cannot_publish_late_plan(self):
        with tempfile.TemporaryDirectory(prefix="steward_plan_owner_") as tmp:
            agent, manager = self.make_agent(tmp)
            release_final = threading.Event()
            final_entered = threading.Event()

            def route_request(**_kwargs):
                if manager.route_request.call_count == 1:
                    return manager.route_request.return_value
                final_entered.set()
                self.assertTrue(release_final.wait(timeout=2.0))
                return {
                    "choices": [{"message": {"content": "Preview ready"}}],
                    "_steward": {"provider": "FileProvider", "model": "file-model"},
                }

            # The provider blocks after the tool plan is parsed. Discarding the
            # plan while that request is in flight must invalidate publication.
            manager.route_request.side_effect = route_request
            result = {}

            def run_preview():
                result["text"] = agent.run("move source.txt", dry_run=True)

            worker = REAL_THREAD(target=run_preview)
            worker.start()
            self.assertTrue(final_entered.wait(timeout=1.0))
            agent.discard_pending_plan()
            release_final.set()
            worker.join(timeout=2.0)

            self.assertFalse(worker.is_alive())
            self.assertIn("Preview ready", result["text"])
            self.assertIsNone(agent.get_pending_plan_id())
            with self.assertRaisesRegex(RuntimeError, "No previewed execution plan"):
                agent.execute_pending_plan("late-plan")
            self.assertEqual(manager.route_request.call_count, 2)

    def test_plan_id_callback_can_inspect_atomic_published_plan(self):
        with tempfile.TemporaryDirectory(prefix="steward_plan_callback_") as tmp:
            agent, _ = self.make_agent(tmp)
            observed = {}

            def observe_callback(plan_id):
                observed["plan_id"] = plan_id
                observed["published_id"] = agent.get_pending_plan_id()

            agent.run(
                "move source.txt",
                dry_run=True,
                plan_id_callback=observe_callback,
            )

            self.assertEqual(observed["plan_id"], observed["published_id"])
            self.assertIsNotNone(observed["published_id"])

    def test_plan_id_callback_failure_does_not_corrupt_published_plan(self):
        with tempfile.TemporaryDirectory(prefix="steward_plan_callback_") as tmp:
            agent, manager = self.make_agent(tmp)

            def fail_callback(_plan_id):
                raise RuntimeError("observer failed")

            result = agent.run(
                "move source.txt",
                dry_run=True,
                plan_id_callback=fail_callback,
            )

            self.assertIn("[Dry Run]", result)
            plan_id = agent.get_pending_plan_id()
            self.assertIsNotNone(plan_id)
            self.assertEqual(
                agent._pending_plan[0]["function"]["name"], "move_file"
            )

    def test_superseded_generation_plan_id_is_rejected(self):
        with tempfile.TemporaryDirectory(prefix="steward_plan_superseded_") as tmp:
            agent, manager = self.make_agent(tmp)
            first_plan_id = []
            second_plan_id = []

            agent.run(
                "move source.txt",
                dry_run=True,
                plan_id_callback=first_plan_id.append,
            )
            agent.run(
                "move source.txt",
                dry_run=True,
                plan_id_callback=second_plan_id.append,
            )

            self.assertTrue(first_plan_id[0])
            self.assertTrue(second_plan_id[0])
            self.assertNotEqual(first_plan_id[0], second_plan_id[0])
            with self.assertRaisesRegex(RuntimeError, "stale or superseded"):
                agent.execute_pending_plan(first_plan_id[0])
            self.assertEqual(agent.get_pending_plan_id(), second_plan_id[0])

    def test_stale_preview_does_not_overwrite_newer_provider_metadata(self):
        with tempfile.TemporaryDirectory(prefix="steward_plan_provider_owner_") as tmp:
            agent, manager = self.make_agent(tmp)
            first_entered = threading.Event()
            release_first = threading.Event()
            provider_by_call = {
                1: {"provider": "OldProvider", "model": "old-model"},
                2: {"provider": "NewProvider", "model": "new-model"},
                3: {"provider": "NewProvider", "model": "new-model"},
                4: {"provider": "OldProvider", "model": "old-model"},
            }

            def route_request(**_kwargs):
                call_number = manager.route_request.call_count
                if call_number == 1:
                    first_entered.set()
                    self.assertTrue(release_first.wait(timeout=2.0))
                provider = provider_by_call.get(
                    call_number,
                    {"provider": "FileProvider", "model": "file-model"},
                )
                return {
                    "choices": [{"message": {
                        "content": "Preview ready",
                        "tool_calls": [{
                            "id": f"call-{call_number}",
                            "type": "function",
                            "function": {
                                "name": "move_file",
                                "arguments": {
                                    "source": "Incoming/source.txt",
                                    "destination": "Sorted/source.txt",
                                },
                            },
                        }],
                    }}],
                    "_steward": provider,
                }

            manager.route_request.side_effect = route_request

            def run_first_preview():
                agent.run("move source.txt", dry_run=True)

            worker = REAL_THREAD(target=run_first_preview)
            worker.start()
            self.assertTrue(first_entered.wait(timeout=1.0))

            agent.run("move source.txt", dry_run=True)
            self.assertEqual(agent.last_provider["provider"], "NewProvider")

            release_first.set()
            worker.join(timeout=2.0)
            self.assertFalse(worker.is_alive())
            self.assertEqual(agent.last_provider["provider"], "NewProvider")


class SyntaxIntentTests(unittest.TestCase):
    """Syntax chooses explicit intent-specific, text-only instructions."""

    def request_for(self, task, original=None):
        manager = Mock()
        manager.route_request.return_value = {
            "choices": [{"message": {"content": "provider text"}}],
            "_steward": {"provider": "CodeProvider", "model": "code-model"},
        }
        agent = CodingAgent(api_manager=manager)
        result = agent.handle_request(task, original_request=original or task)
        request = manager.route_request.call_args.kwargs
        return result, request, agent

    def test_review_intents_use_review_instruction(self):
        cases = (
            "Review this code for possible bugs",
            "Review this implementation for security concerns",
            "Review this implementation for readability and maintainability",
        )
        for task in cases:
            with self.subTest(task=task):
                result, request, _ = self.request_for(task, "def f():\n    pass")
                instruction = request["messages"][0]["content"].lower()
                self.assertEqual(result, "provider text")
                self.assertIn("review", instruction)
                self.assertIn("do not rewrite", instruction)
                self.assertEqual(request["agent_name"], "Syntax")
                self.assertFalse(request["require_tools"])
                self.assertNotIn("tools", request)

    def test_explanation_intents_do_not_request_code_changes(self):
        cases = (
            "Explain what this function does",
            "Explain why this implementation is incorrect",
        )
        for task in cases:
            with self.subTest(task=task):
                _, request, _ = self.request_for(task, "def f():\n    return 1")
                instruction = request["messages"][0]["content"].lower()
                self.assertIn("explain", instruction)
                self.assertIn("do not assume that code changes are requested", instruction)

    def test_debug_refactor_and_generation_have_distinct_instructions(self):
        cases = (
            ("Debug why this function raises an exception", "debug"),
            ("Refactor this function to simplify it", "refactor"),
            ("Write a function that validates an email address", "write clear"),
        )
        for task, expected in cases:
            with self.subTest(task=task):
                _, request, _ = self.request_for(task)
                instruction = request["messages"][0]["content"].lower()
                self.assertIn(expected, instruction)

    def test_original_request_and_supplied_code_are_preserved(self):
        original = "Please review this safely:\ndef secret():\n    return 42"
        _, request, _ = self.request_for("Review the implementation", original)
        prompt = request["messages"][-1]["content"]
        self.assertIn("Task: Review the implementation", prompt)
        self.assertIn("Please review this safely:", prompt)
        self.assertIn("def secret():", prompt)

    def test_ambiguous_request_defaults_to_generation_without_losing_context(self):
        _, request, _ = self.request_for("Make this better", "def f():\n    pass")
        instruction = request["messages"][0]["content"].lower()
        self.assertIn("write clear", instruction)
        self.assertIn("def f():", request["messages"][-1]["content"])

    def test_malformed_and_tool_bearing_responses_are_rejected(self):
        for response in (
            {},
            {"choices": []},
            {"choices": [{"message": {"content": "  "}}]},
            {"choices": [{"message": {
                "content": "text",
                "tool_calls": [{"type": "function", "function": {"name": "delete"}}],
            }}]},
        ):
            with self.subTest(response=response):
                manager = Mock()
                manager.route_request.return_value = response
                agent = CodingAgent(api_manager=manager)
                with self.assertRaises(ValueError):
                    agent.handle_request("Review this code")



class ProviderAttributionTests(unittest.TestCase):
    """Concurrent requests retain their own provider metadata."""

    def test_concurrent_supervisor_requests_keep_request_local_provider(self):
        manager = Mock()
        first_entered = threading.Event()
        release_first = threading.Event()
        first_started = threading.Event()

        def route_request(**kwargs):
            if kwargs.get("agent_name") != "Cortex":
                raise AssertionError("Unexpected provider request")
            if not first_started.is_set():
                first_started.set()
                first_entered.set()
                self.assertTrue(release_first.wait(timeout=2.0))
                return {
                    "choices": [{"message": {
                        "content": '{"agent":"GENERAL_CHAT","action":"first"}'
                    }}],
                    "_steward": {"provider": "FirstProvider", "model": "first"},
                }
            return {
                "choices": [{"message": {
                    "content": '{"agent":"GENERAL_CHAT","action":"second"}'
                }}],
                "_steward": {"provider": "SecondProvider", "model": "second"},
            }

        manager.route_request.side_effect = route_request
        supervisor = SupervisorAgent(manager)
        first_provider = {}
        second_provider = {}
        first_result = {}

        def first_route():
            first_result["decision"] = supervisor.route(
                "first request", provider_callback=first_provider.update
            )

        worker = REAL_THREAD(target=first_route)
        worker.start()
        self.assertTrue(first_entered.wait(timeout=1.0))

        second_result = supervisor.route(
            "second request", provider_callback=second_provider.update
        )
        release_first.set()
        worker.join(timeout=2.0)

        self.assertFalse(worker.is_alive())
        self.assertEqual(second_result["action"], "second")
        self.assertEqual(first_result["decision"]["action"], "first")
        self.assertEqual(first_provider["provider"], "FirstProvider")
        self.assertEqual(second_provider["provider"], "SecondProvider")


class CortexConversationIsolationTests(unittest.TestCase):
    """Clearing isolates old provider work from the new conversation."""

    class RecordingThread:
        instances = []

        def __init__(self, target, daemon):
            self.target = target
            self.done = threading.Event()
            CortexConversationIsolationTests.RecordingThread.instances.append(self)

        def start(self):
            worker = REAL_THREAD(target=self._run, daemon=True)
            self.worker = worker
            worker.start()

        def _run(self):
            try:
                self.target()
            finally:
                self.done.set()

    def make_chat(self):
        chat = ChatTab.__new__(ChatTab)
        chat._processing = False
        chat._general_chat_history = []
        chat._conversation_epoch = 0
        chat._conversation_lock = threading.RLock()
        chat.winfo_exists = Mock(return_value=True)
        chat.chat_entry = Mock()
        chat.send_btn = Mock()
        chat.chat_display = Mock()
        chat.chat_display.winfo_children.return_value = []
        chat.live_feed = Mock()
        chat.provider_callback = None
        chat._add_bubble = Mock()
        chat._report_provider = Mock(return_value="")
        chat.handoff_canvas = Mock()
        chat.file_agent = Mock()
        chat.file_agent.root_path = os.getcwd()
        chat.file_agent.last_provider = None
        chat.supervisor = Mock()
        chat.supervisor.route.return_value = {
            "agent": AGENT_GENERAL_CHAT,
            "action": "friendly reply",
        }
        chat.supervisor.api_manager = Mock()
        callbacks = []
        chat.after = Mock(
            side_effect=lambda _delay, callback: callbacks.append(callback)
        )
        return chat, callbacks

    @staticmethod
    def provider_response(content):
        return {
            "choices": [{"message": {"content": content}}],
            "_steward": {"provider": "TestProvider", "model": "test-model"},
        }

    def drain(self, callbacks):
        for callback in list(callbacks):
            callback()
        callbacks.clear()

    def visible_messages(self, chat):
        return [
            call.args[1]
            for call in chat._add_bubble.call_args_list
            if len(call.args) > 1 and call.args[0] == "STEWARD"
        ]

    def test_new_request_can_complete_before_old_request_after_clear(self):
        chat, callbacks = self.make_chat()
        chat.chat_entry.get.side_effect = ["old question", "new question"]
        old_entered = threading.Event()
        release_old = threading.Event()
        new_entered = threading.Event()
        release_new = threading.Event()

        def route_request(**_kwargs):
            if not old_entered.is_set():
                old_entered.set()
                self.assertTrue(release_old.wait(timeout=2.0))
                return self.provider_response("old answer")
            new_entered.set()
            self.assertTrue(release_new.wait(timeout=2.0))
            return self.provider_response("new answer")

        chat.supervisor.api_manager.route_request.side_effect = route_request
        self.RecordingThread.instances = []

        with patch("gui.chat_tab.threading.Thread", self.RecordingThread):
            chat.send_chat()
            self.assertTrue(old_entered.wait(timeout=1.0))
            chat.clear_chat()
            chat.send_chat()
            self.assertTrue(new_entered.wait(timeout=1.0))

            release_new.set()
            self.assertTrue(self.RecordingThread.instances[1].done.wait(timeout=2.0))
            self.drain(callbacks)
            self.assertFalse(chat._processing)
            self.assertEqual(chat._general_chat_history, [
                {"role": "user", "content": "new question"},
                {"role": "assistant", "content": "new answer"},
            ])
            self.assertNotIn("old answer", self.visible_messages(chat))

            release_old.set()
            self.assertTrue(self.RecordingThread.instances[0].done.wait(timeout=2.0))
            self.drain(callbacks)

        self.assertFalse(chat._processing)
        self.assertEqual(chat._general_chat_history, [
            {"role": "user", "content": "new question"},
            {"role": "assistant", "content": "new answer"},
        ])
        self.assertNotIn("old answer", self.visible_messages(chat))
        chat.send_btn.configure.assert_called_with(state="normal")
        self.assertTrue(any(
            call.args and call.args[0] == "<Return>"
            for call in chat.chat_entry.bind.call_args_list
        ))


    def test_old_request_can_complete_before_new_request_after_clear(self):
        chat, callbacks = self.make_chat()
        chat.chat_entry.get.side_effect = ["old question", "new question"]
        old_entered = threading.Event()
        release_old = threading.Event()
        new_entered = threading.Event()
        release_new = threading.Event()

        def route_request(**_kwargs):
            if not old_entered.is_set():
                old_entered.set()
                self.assertTrue(release_old.wait(timeout=2.0))
                return self.provider_response("old answer")
            new_entered.set()
            self.assertTrue(release_new.wait(timeout=2.0))
            return self.provider_response("new answer")

        chat.supervisor.api_manager.route_request.side_effect = route_request
        self.RecordingThread.instances = []

        with patch("gui.chat_tab.threading.Thread", self.RecordingThread):
            chat.send_chat()
            self.assertTrue(old_entered.wait(timeout=1.0))
            chat.clear_chat()
            chat.send_chat()
            self.assertTrue(new_entered.wait(timeout=1.0))

            release_old.set()
            self.assertTrue(self.RecordingThread.instances[0].done.wait(timeout=2.0))
            self.drain(callbacks)
            self.assertTrue(chat._processing, "stale cleanup must not release new work")
            self.assertEqual(chat._general_chat_history, [])

            release_new.set()
            self.assertTrue(self.RecordingThread.instances[1].done.wait(timeout=2.0))
            self.drain(callbacks)

        self.assertFalse(chat._processing)
        self.assertEqual(chat._general_chat_history, [
            {"role": "user", "content": "new question"},
            {"role": "assistant", "content": "new answer"},
        ])
        self.assertNotIn("old answer", self.visible_messages(chat))
        self.assertTrue(any(
            call.args and call.args[0] == "<Return>"
            for call in chat.chat_entry.bind.call_args_list
        ))


    def test_clear_during_file_preview_rejects_late_plan_and_execution(self):
        chat, callbacks = self.make_chat()
        chat.supervisor.route.return_value = {
            "agent": AGENT_FILE_OP,
            "action": "organize files",
        }
        preview_started = threading.Event()
        release_preview = threading.Event()

        def run_preview(*_args, **kwargs):
            preview_started.set()
            self.assertTrue(release_preview.wait(timeout=2.0))
            plan_id_callback = kwargs.get("plan_id_callback")
            if plan_id_callback:
                plan_id_callback("stale-plan")
            return "preview ready"

        chat.file_agent.run.side_effect = run_preview
        chat.file_agent.execute_pending_plan.return_value = "should not execute"
        self.RecordingThread.instances = []

        with patch("gui.chat_tab.threading.Thread", self.RecordingThread):
            chat.send_chat()
            self.assertTrue(preview_started.wait(timeout=1.0))
            chat.clear_chat()
            release_preview.set()
            self.assertTrue(self.RecordingThread.instances[0].done.wait(timeout=2.0))
            self.drain(callbacks)

        chat.file_agent.execute_pending_plan.assert_not_called()
        self.assertNotIn(
            "preview ready",
            " ".join(self.visible_messages(chat)),
        )

    def test_stale_error_does_not_display_or_replace_new_state(self):
        chat, callbacks = self.make_chat()
        chat.chat_entry.get.side_effect = ["old question", "new question"]
        old_entered = threading.Event()
        release_old = threading.Event()
        new_entered = threading.Event()

        def route_request(**_kwargs):
            if not old_entered.is_set():
                old_entered.set()
                self.assertTrue(release_old.wait(timeout=2.0))
                raise RuntimeError("old provider failure")
            new_entered.set()
            return self.provider_response("new answer")

        chat.supervisor.api_manager.route_request.side_effect = route_request
        self.RecordingThread.instances = []

        with patch("gui.chat_tab.threading.Thread", self.RecordingThread):
            chat.send_chat()
            self.assertTrue(old_entered.wait(timeout=1.0))
            chat.clear_chat()
            chat.send_chat()
            self.assertTrue(new_entered.wait(timeout=1.0))
            self.assertTrue(self.RecordingThread.instances[1].done.wait(timeout=2.0))
            self.drain(callbacks)
            release_old.set()
            self.assertTrue(self.RecordingThread.instances[0].done.wait(timeout=2.0))
            self.drain(callbacks)

        self.assertFalse(chat._processing)
        self.assertEqual(chat._general_chat_history, [
            {"role": "user", "content": "new question"},
            {"role": "assistant", "content": "new answer"},
        ])
        self.assertNotIn(
            "old provider failure",
            " ".join(self.visible_messages(chat)),
        )

    def test_repeated_clear_and_send_across_epochs_is_safe(self):
        chat, callbacks = self.make_chat()
        chat.chat_entry.get.side_effect = ["first", "second"]
        self.RecordingThread.instances = []

        with patch("gui.chat_tab.threading.Thread", self.RecordingThread):
            chat.clear_chat()
            chat.clear_chat()
            chat.supervisor.api_manager.route_request.return_value = (
                self.provider_response("second answer")
            )
            chat.send_chat()
            self.assertTrue(self.RecordingThread.instances[0].done.wait(timeout=2.0))
            self.drain(callbacks)
            chat.clear_chat()
            chat.send_chat()
            self.assertTrue(self.RecordingThread.instances[1].done.wait(timeout=2.0))
            self.drain(callbacks)

        self.assertEqual(chat._conversation_epoch, 3)
        self.assertFalse(chat._processing)
        self.assertEqual(chat._general_chat_history, [
            {"role": "user", "content": "second"},
            {"role": "assistant", "content": "second answer"},
        ])


class SyntaxRoutingTests(unittest.TestCase):
    """Direct and delegated Syntax requests share intent-aware handling."""

    def make_manager(self):
        manager = Mock()
        manager.route_request.return_value = {
            "choices": [{"message": {"content": "review result"}}],
            "_steward": {"provider": "CodeProvider", "model": "code-model"},
        }
        return manager

    def test_delegated_syntax_uses_thread_local_original_request(self):
        manager = self.make_manager()
        chat = ChatTab.__new__(ChatTab)
        chat.coding_agent = CodingAgent(api_manager=manager)
        chat.supervisor = Mock()
        chat._delegation_context = threading.local()
        chat._delegation_context.original_request = "Review this original request"
        chat._delegation_original_request = "stale shared request"

        result = chat._delegate_syntax_task("Review the supplied implementation")

        self.assertEqual(result, "review result")
        prompt = manager.route_request.call_args.kwargs["messages"][-1]["content"]
        self.assertIn("Original request:\nReview this original request", prompt)
        self.assertNotIn("stale shared request", prompt)

    def test_direct_chat_routes_review_to_text_only_syntax(self):
        manager = self.make_manager()
        chat = ChatTab.__new__(ChatTab)
        chat.coding_agent = CodingAgent(api_manager=manager)
        chat.supervisor = Mock()
        request = "Review this code for security concerns"

        result = chat.coding_agent.handle_request(
            request, original_request=request
        )

        self.assertEqual(result, "review result")
        routed = manager.route_request.call_args.kwargs
        self.assertEqual(routed["agent_name"], "Syntax")
        self.assertFalse(routed["require_tools"])
        self.assertNotIn("tools", routed)
        self.assertIn("review", routed["messages"][0]["content"].lower())

    def test_delegated_syntax_preserves_review_intent_and_original_context(self):
        manager = self.make_manager()
        chat = ChatTab.__new__(ChatTab)
        chat.coding_agent = CodingAgent(api_manager=manager)
        chat.supervisor = Mock()
        original = "Review this implementation for bugs:\ndef f():\n    pass"
        chat._delegation_original_request = original

        result = chat._delegate_syntax_task("Review the supplied implementation")

        self.assertEqual(result, "review result")
        routed = manager.route_request.call_args.kwargs
        self.assertIn("review", routed["messages"][0]["content"].lower())
        self.assertIn("def f():", routed["messages"][-1]["content"])
        self.assertFalse(routed["require_tools"])
        self.assertNotIn("tools", routed)


if __name__ == "__main__":
    unittest.main()

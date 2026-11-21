"""Isolated regression tests for immutable plans and agent-aware routing."""

import json
import os
import sqlite3
import tempfile
import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

from agents.file_agent import FileAgent
from core.database import DatabaseManager
from core.router import APIManager
from gui.chat_tab import ChatTab
from gui.live_feed import LiveFeedWidget


class FakeResponse:
    def __init__(self, status_code=200, payload=None, headers=None):
        self.status_code = status_code
        self._payload = payload or {"choices": [{"message": {"content": "ok"}}]}
        self.headers = headers or {}
        self.text = json.dumps(self._payload)

    def json(self):
        return self._payload


def success_payload(content="ok"):
    return {
        "choices": [{"message": {"content": content}}],
        "usage": {"total_tokens": 3},
    }


class DatabaseAssignmentTests(unittest.TestCase):
    def test_legacy_database_migrates_and_returns_assignment(self):
        with tempfile.TemporaryDirectory(prefix="steward_db_test_") as tmp:
            db_path = os.path.join(tmp, "legacy.db")
            key_path = os.path.join(tmp, "test.key")
            connection = sqlite3.connect(db_path)
            connection.execute("""
                CREATE TABLE providers (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    name TEXT UNIQUE,
                    base_url TEXT,
                    api_key_encrypted BLOB,
                    model_name TEXT,
                    is_local BOOLEAN DEFAULT 0,
                    is_active BOOLEAN DEFAULT 1,
                    speed_score_ms INTEGER DEFAULT 9999,
                    intelligence_tier TEXT DEFAULT 'Unknown',
                    supports_tools BOOLEAN DEFAULT 0,
                    cooldown_until TEXT,
                    failure_count INTEGER DEFAULT 0
                )
            """)
            connection.execute(
                "INSERT INTO providers (name, base_url, api_key_encrypted) "
                "VALUES ('Legacy', 'https://legacy.example/v1', ?)", (b"",),
            )
            connection.commit()
            connection.close()

            db = DatabaseManager(db_path=db_path, key_path=key_path)
            try:
                columns = {
                    row["name"]
                    for row in db._conn.execute("PRAGMA table_info(providers)")
                }
                self.assertIn("assigned_agent", columns)
                self.assertEqual(db.get_provider("Legacy")["assigned_agent"], "Any")
                self.assertEqual(db.get_active_providers()[0]["assigned_agent"], "Any")
                self.assertEqual(db.get_all_providers()[0]["assigned_agent"], "Any")
                db.add_provider(
                    "FoldyKey", "https://foldy.example/v1", "secret",
                    model_name="foldy-model", assigned_agent="Foldy",
                )
                self.assertEqual(db.get_provider("FoldyKey")["assigned_agent"], "Foldy")
                db.update_provider_fields("FoldyKey", assigned_agent="Any")
                self.assertEqual(db.get_provider("FoldyKey")["assigned_agent"], "Any")
            finally:
                db.close()


class RouterAssignmentTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory(prefix="steward_router_test_")
        self.db = DatabaseManager(
            db_path=os.path.join(self.temp_dir.name, "router.db"),
            key_path=os.path.join(self.temp_dir.name, "router.key"),
        )
        self.db_patcher = patch("core.router.get_db", return_value=self.db)
        self.db_patcher.start()
        self.manager = APIManager(timeout=1)

    def tearDown(self):
        self.db_patcher.stop()
        self.db.close()
        self.temp_dir.cleanup()

    def add_provider(self, name, url, key, speed, agent, model=None):
        return self.db.add_provider(
            name=name, base_url=url, api_key=key, model_name=model or name,
            speed_score_ms=speed, intelligence_tier="Fast",
            supports_tools=True, assigned_agent=agent,
        )

    def test_agent_filter_includes_matching_and_any_only(self):
        self.add_provider("Wrong", "https://wrong.example/v1", "wrong", 1, "Foldy")
        self.add_provider("Right", "https://right.example/v1", "right", 2, "Cortex")
        self.add_provider("Shared", "https://shared.example/v1", "shared", 3, "Any")
        with patch("core.router.requests.post", return_value=FakeResponse(payload=success_payload())) as post:
            result = self.manager.route_request([], agent_name="Cortex", required_tier="Fast")
            self.assertEqual(post.call_count, 1)
            self.assertEqual(post.call_args.kwargs["headers"]["Authorization"], "Bearer right")
            self.assertEqual(result["_steward"]["provider"], "Right")
            self.assertEqual(result["_steward"]["model"], "Right")

            shared_result = self.manager.route_request([], agent_name="Scout")
            self.assertEqual(post.call_count, 2)
            self.assertEqual(post.call_args.kwargs["headers"]["Authorization"], "Bearer shared")
            self.assertEqual(shared_result["_steward"]["provider"], "Shared")

    def test_429_immediately_uses_another_key_on_same_endpoint(self):
        endpoint = "https://same.example/v1"
        first_id = self.add_provider("First", endpoint, "key-1", 1, "Foldy")
        second_id = self.add_provider("Second", endpoint + "/", "key-2", 3, "Foldy")
        self.add_provider("Other", "https://other.example/v1", "other", 2, "Foldy")
        responses = [
            FakeResponse(status_code=429, payload={"error": "limited"}, headers={"Retry-After": "30"}),
            FakeResponse(payload=success_payload()),
        ]
        with patch("core.router.requests.post", side_effect=responses) as post:
            result = self.manager.route_request([], agent_name="Foldy")

        self.assertEqual(post.call_count, 2)
        calls = post.call_args_list
        self.assertEqual(calls[0].kwargs["headers"]["Authorization"], "Bearer key-1")
        self.assertEqual(calls[1].kwargs["headers"]["Authorization"], "Bearer key-2")
        self.assertEqual(calls[0].args[0], calls[1].args[0])
        self.assertEqual(result["_steward"]["provider"], "Second")
        self.assertEqual(result["_steward"]["failovers"], [
            {"failed_provider": "First", "fallback_provider": "Second"}
        ])
        self.assertIsNotNone(self.db.get_provider("First")["cooldown_until"])
        usage = self.db._conn.execute(
            "SELECT provider_id, requests_used FROM usage_ledger ORDER BY provider_id"
        ).fetchall()
        self.assertEqual({row["provider_id"]: row["requests_used"] for row in usage},
                         {first_id: 1, second_id: 1})

    def test_5xx_reports_failed_and_fallback_providers(self):
        self.add_provider("Primary", "https://primary.example/v1", "primary", 1, "Cortex")
        self.add_provider("Backup", "https://backup.example/v1", "backup", 2, "Cortex")
        responses = [
            FakeResponse(status_code=503, payload={"error": "unavailable"}),
            FakeResponse(payload=success_payload()),
        ]
        with patch("core.router.requests.post", side_effect=responses):
            result = self.manager.route_request([], agent_name="Cortex")

        self.assertEqual(result["_steward"]["provider"], "Backup")
        self.assertEqual(result["_steward"]["failovers"], [
            {"failed_provider": "Primary", "fallback_provider": "Backup"}
        ])


class ImmutablePlanTests(unittest.TestCase):
    def test_confirmation_executes_saved_arguments_without_more_llm_calls(self):
        with tempfile.TemporaryDirectory(prefix="steward_plan_test_") as tmp:
            args = {"source": "Incoming/approved.txt", "destination": "Sorted/approved.txt"}
            tool_response = {
                "choices": [{"message": {"content": "", "tool_calls": [{
                    "id": "approved-call", "type": "function",
                    "function": {"name": "move_file", "arguments": json.dumps(args)},
                }]}}],
                "_steward": {"provider": "PreviewBrain", "model": "safe-model"},
            }
            api = Mock()
            api.route_request = Mock(side_effect=[tool_response, success_payload("Preview ready")])
            log_path = os.path.join(tmp, "operations.json")
            with patch.object(FileAgent, "OPERATION_LOG_PATH", log_path):
                agent = FileAgent(api_manager=api, root_path=tmp)
            agent._record_operation = Mock()
            move_file = Mock(return_value="Moved approved.txt")
            with patch("agents.file_agent._legacy_tool_functions", {"move_file": move_file}):
                preview = agent.run("move approved.txt", dry_run=True)
                self.assertIn("approved.txt", preview)
                move_file.assert_not_called()

                # Mutating the original provider response must not alter approval.
                tool_response["choices"][0]["message"]["tool_calls"][0]["function"] = {
                    "name": "delete_file", "arguments": json.dumps({"path": "unauthorized.txt"})
                }
                result = agent.execute_pending_plan()

            self.assertIn("Moved approved.txt", result)
            move_file.assert_called_once_with(
                source=os.path.realpath(os.path.join(tmp, args["source"])),
                destination=os.path.realpath(os.path.join(tmp, args["destination"])),
            )
            self.assertEqual(api.route_request.call_count, 2)  # plan + preview summary only
            for call in api.route_request.call_args_list:
                self.assertEqual(call.kwargs["agent_name"], "Foldy")
            self.assertIsNone(agent._pending_plan)
            with self.assertRaises(RuntimeError):
                agent.execute_pending_plan()


class SandboxTests(unittest.TestCase):
    def make_agent(self, root):
        log_path = os.path.join(root, "operations.json")
        with patch.object(FileAgent, "OPERATION_LOG_PATH", log_path):
            agent = FileAgent(api_manager=Mock(), root_path=root)
        agent._record_operation = Mock()
        return agent

    def test_unsafe_pending_plan_aborts_before_any_tool_or_operation_log(self):
        with tempfile.TemporaryDirectory(prefix="steward_sandbox_test_") as tmp:
            outside = os.path.join(tmp, "outside")
            root = os.path.join(tmp, "workspace")
            os.makedirs(os.path.join(root, "Incoming"))
            os.makedirs(outside)
            outside_file = os.path.join(outside, "keep.txt")
            with open(outside_file, "w", encoding="utf-8") as handle:
                handle.write("untouched")
            agent = self.make_agent(root)
            agent._pending_plan = [
                {"function": {"name": "move_file", "arguments": {
                    "source": "Incoming/first.txt", "destination": "Sorted/first.txt",
                }}},
                {"function": {"name": "delete_file", "arguments": {"path": outside_file}}},
            ]
            move_file = Mock(return_value="Moved first.txt")
            delete_file = Mock(return_value="Deleted keep.txt")
            tools = {"move_file": move_file, "delete_file": delete_file}
            with patch("agents.file_agent._legacy_tool_functions", tools):
                result = agent.execute_pending_plan()

            self.assertIn("Error: Sandbox violation", result)
            move_file.assert_not_called()
            delete_file.assert_not_called()
            agent._record_operation.assert_not_called()
            with open(outside_file, "r", encoding="utf-8") as handle:
                self.assertEqual(handle.read(), "untouched")

    def test_direct_move_uses_canonical_paths_and_rejects_escape(self):
        with tempfile.TemporaryDirectory(prefix="steward_move_test_") as tmp:
            incoming = os.path.join(tmp, "Incoming")
            sorted_dir = os.path.join(tmp, "Sorted")
            os.makedirs(incoming)
            source = os.path.join(incoming, "document.txt")
            with open(source, "w", encoding="utf-8") as handle:
                handle.write("contents")
            agent = self.make_agent(tmp)

            result = agent.move_file(
                "Incoming/document.txt", "Sorted/Archive/document.txt"
            )
            destination = os.path.join(sorted_dir, "Archive", "document.txt")
            self.assertTrue(result.startswith("Moved"), result)
            self.assertFalse(os.path.exists(source))
            with open(destination, "r", encoding="utf-8") as handle:
                self.assertEqual(handle.read(), "contents")

            outside = os.path.join(tmp, "outside.txt")
            with open(outside, "w", encoding="utf-8") as handle:
                handle.write("safe")
            rejected = agent.move_file(destination, outside)
            self.assertIn("Error: Sandbox violation", rejected)
            self.assertTrue(os.path.exists(destination))
            with open(outside, "r", encoding="utf-8") as handle:
                self.assertEqual(handle.read(), "safe")


class ProviderVisualizationTests(unittest.TestCase):
    def test_live_feed_flashes_failed_red_and_backup_green(self):
        failed_card = Mock()
        backup_card = Mock()
        feed = SimpleNamespace(
            add_event=Mock(side_effect=[failed_card, backup_card]),
            after=Mock(),
            _restore_card_color=LiveFeedWidget._restore_card_color,
        )
        LiveFeedWidget.provider_failover(feed, "Primary", "Backup")

        self.assertEqual(feed.add_event.call_args_list[0].args[:2], ("Primary", "Provider failed"))
        self.assertEqual(feed.add_event.call_args_list[1].args[:2], ("Backup", "Backup provider active"))
        failed_card.configure.assert_called_with(fg_color="#B91C1C")
        backup_card.configure.assert_called_with(fg_color="#15803D")
        self.assertEqual([call.args[0] for call in feed.after.call_args_list], [1200, 1200])

        failed_card.winfo_exists.return_value = True
        backup_card.winfo_exists.return_value = True
        for call in feed.after.call_args_list:
            call.args[1]()
        failed_card.configure.assert_called_with(fg_color="#2A2A35")
        backup_card.configure.assert_called_with(fg_color="#2A2A35")

    def test_chat_marshals_failover_cards_to_main_thread(self):
        provider_info = {
            "provider": "Backup",
            "model": "model",
            "failovers": [{"failed_provider": "Primary", "fallback_provider": "Backup"}],
        }
        chat = SimpleNamespace(
            supervisor=SimpleNamespace(last_provider=provider_info),
            file_agent=SimpleNamespace(last_provider=None),
            provider_callback=Mock(),
            live_feed=Mock(),
            after=Mock(side_effect=lambda delay, callback: callback()),
        )
        detail = ChatTab._report_provider(chat, "Cortex")

        self.assertEqual(detail, "Backup / model")
        chat.after.assert_called_once()
        self.assertEqual(chat.after.call_args.args[0], 0)
        chat.live_feed.provider_failover.assert_called_once_with("Primary", "Backup")
        chat.provider_callback.assert_called_once_with("Cortex", provider_info)



class ReadSandboxTests(unittest.TestCase):
    """Read operations must respect the same Incoming/Sorted sandbox as writes."""

    def make_agent(self, root):
        log_path = os.path.join(root, "operations.json")
        with patch.object(FileAgent, "OPERATION_LOG_PATH", log_path):
            agent = FileAgent(api_manager=Mock(), root_path=root)
        agent._record_operation = Mock()
        return agent

    def test_list_directory_rejects_path_outside_sandbox(self):
        with tempfile.TemporaryDirectory(prefix="steward_read_sandbox_") as tmp:
            outside = os.path.join(tmp, "outside_dir")
            os.makedirs(outside)
            agent = self.make_agent(tmp)
            result = agent.list_directory(outside)
            self.assertIn("Error: Sandbox violation", result)

    def test_read_file_content_rejects_path_outside_sandbox(self):
        with tempfile.TemporaryDirectory(prefix="steward_read_sandbox_") as tmp:
            outside = os.path.join(tmp, "outside.txt")
            with open(outside, "w", encoding="utf-8") as handle:
                handle.write("sensitive data")
            agent = self.make_agent(tmp)
            result = agent.read_file_content(outside)
            self.assertIn("Error: Sandbox violation", result)

    def test_get_file_info_rejects_path_outside_sandbox(self):
        with tempfile.TemporaryDirectory(prefix="steward_read_sandbox_") as tmp:
            outside = os.path.join(tmp, "outside.txt")
            with open(outside, "w", encoding="utf-8") as handle:
                handle.write("data")
            agent = self.make_agent(tmp)
            result = agent.get_file_info(outside)
            self.assertIn("Error: Sandbox violation", result)

    def test_categorise_file_rejects_filepath_outside_sandbox(self):
        with tempfile.TemporaryDirectory(prefix="steward_read_sandbox_") as tmp:
            outside = os.path.join(tmp, "outside.txt")
            with open(outside, "w", encoding="utf-8") as handle:
                handle.write("data")
            agent = self.make_agent(tmp)
            agent.api_manager = Mock()
            agent.api_manager.route_request = Mock(return_value={
                "choices": [{"message": {"content": "Docs"}}],
                "_steward": {"provider": "Test", "model": "test"},
            })
            result = agent.categorise_file(outside, os.path.join(tmp, "Sorted"))
            self.assertIn("Error: Sandbox violation", result)

    def test_list_directory_allows_path_inside_sandbox(self):
        with tempfile.TemporaryDirectory(prefix="steward_read_sandbox_") as tmp:
            incoming = os.path.join(tmp, "Incoming")
            os.makedirs(incoming)
            agent = self.make_agent(tmp)
            result = agent.list_directory(incoming)
            self.assertNotIn("Error: Sandbox violation", result)

    def test_read_file_content_allows_path_inside_sandbox(self):
        with tempfile.TemporaryDirectory(prefix="steward_read_sandbox_") as tmp:
            incoming = os.path.join(tmp, "Incoming")
            os.makedirs(incoming)
            inside = os.path.join(incoming, "note.txt")
            with open(inside, "w", encoding="utf-8") as handle:
                handle.write("hello")
            agent = self.make_agent(tmp)
            result = agent.read_file_content(inside)
            self.assertEqual(result, "hello")

    def test_get_file_info_allows_path_inside_sandbox(self):
        with tempfile.TemporaryDirectory(prefix="steward_read_sandbox_") as tmp:
            incoming = os.path.join(tmp, "Incoming")
            os.makedirs(incoming)
            inside = os.path.join(incoming, "note.txt")
            with open(inside, "w", encoding="utf-8") as handle:
                handle.write("hello")
            agent = self.make_agent(tmp)
            result = agent.get_file_info(inside)
            self.assertIn("Size:", result)


if __name__ == "__main__":
    unittest.main()

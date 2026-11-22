"""Isolated regression tests for immutable plans and agent-aware routing."""

import json
import os
import sqlite3
import tempfile
import threading
import unittest
from cryptography.fernet import Fernet
from collections import OrderedDict
from types import SimpleNamespace
from unittest.mock import Mock, patch

from agent.daemon import FileCreationHandler
from agents.file_agent import FileAgent
from agents.supervisor import AGENT_FILE_OP, AGENT_PC_CONTROL
import core.database as database_module
from core.database import (
    DatabaseManager,
    normalize_base_url,
    migrate_to_shared_credentials,
    rollback_from_shared_credentials,
    DECRYPTION_ERROR,
)
from core.discovery import DiscoveredModel, upsert_discovered_models
from core.router import APIManager
from gui.chat_tab import ChatTab
from gui.live_feed import LiveFeedWidget
from gui.main_window import StewardGUI
from gui.anim import SafeTick, lerp_color
from gui.organizer_tab import FilePreviewRow, OrganizerTab
from gui.settings_tab import SettingsTab


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


def approve_plan(agent, plan_id="test-plan"):
    """ID and approve a manually constructed pending plan explicitly."""
    agent._pending_plan_id = plan_id
    return agent.execute_pending_plan(plan_id)


class DatabaseAssignmentTests(unittest.TestCase):
    def test_legacy_database_migrates_and_returns_assignment(self):
        with tempfile.TemporaryDirectory(prefix= "steward_db_test_ ") as tmp:
            db_path = os.path.join(tmp,  "legacy.db ")
            key_path = os.path.join(tmp,  "test.key ")
            # Ensure key file exists to bypass fail-fast
            with open(key_path, "wb") as f:
                f.write(Fernet.generate_key())
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


class DatabaseRecoveryTests(unittest.TestCase):
    def setUp(self):
        self.previous_instance = database_module._db_instance
        database_module._db_instance = None

    def tearDown(self):
        current_instance = database_module._db_instance
        if current_instance is not None and current_instance is not self.previous_instance:
            current_instance.close()
        database_module._db_instance = self.previous_instance

    def make_rotated_database(self, tmp):
        db_path = os.path.join(tmp, "providers.db")
        first_key = os.path.join(tmp, "first.key")
        rotated_key = os.path.join(tmp, "rotated.key")
        original = DatabaseManager(db_path=db_path, key_path=first_key)
        original.add_provider(
            "Recoverable", "https://recoverable.example/v1", "original-secret",
            model_name="recoverable-model", assigned_agent="Foldy",
        )
        original.close()
        # Write a DIFFERENT key to the rotated path (simulating real rotation)
        with open(rotated_key, "wb") as f:
            f.write(Fernet.generate_key())
        return DatabaseManager(db_path=db_path, key_path=rotated_key)

    def test_rotated_key_is_recoverable_and_never_routed(self):
        with tempfile.TemporaryDirectory(prefix="steward_key_rotation_") as tmp:
            db = self.make_rotated_database(tmp)
            try:
                self.assertEqual(db.get_active_providers(), [])
                providers = db.get_all_providers()
                self.assertEqual(len(providers), 1)
                self.assertIsNone(providers[0]["api_key"])
                self.assertIn("secret.key", providers[0]["decryption_error"])
                self.assertIsNone(db.get_provider("Recoverable")["api_key"])
                with patch("core.router.get_db", return_value=db):
                    with patch("core.router.requests.post") as post:
                        with self.assertRaisesRegex(RuntimeError, "secret.key"):
                            APIManager().route_request([], agent_name="Foldy")
                post.assert_not_called()
            finally:
                db.close()

    def test_provider_list_renders_rotated_key_as_recoverable(self):
        with tempfile.TemporaryDirectory(prefix="steward_key_rotation_ui_") as tmp:
            db = self.make_rotated_database(tmp)
            tab = SettingsTab.__new__(SettingsTab)
            tab._is_alive = Mock(return_value=True)
            tab.provider_list = Mock()
            tab.provider_list.winfo_children.return_value = []
            tab._pending_activations = set()
            try:
                with patch("gui.settings_tab.get_db", return_value=db):
                    with patch("gui.settings_tab.ctk.CTkFrame") as frame:
                        with patch("gui.settings_tab.ctk.CTkLabel") as label:
                            with patch("gui.settings_tab.ctk.CTkButton"):
                                tab.refresh_provider_list()
                frame.assert_called_once()
                label_text = [
                    call.kwargs.get("text", "") for call in label.call_args_list
                ]
                self.assertTrue(any("Key unavailable" in text for text in label_text))
                self.assertFalse(any("Error loading DB" in text for text in label_text))
            finally:
                db.close()

    def test_init_db_honors_changed_key_path(self):
        with tempfile.TemporaryDirectory(prefix="steward_init_key_") as tmp:
            db_path = os.path.join(tmp, "providers.db")
            first_key = os.path.join(tmp, "first.key")
            second_key = os.path.join(tmp, "second.key")
            first = database_module.init_db(db_path, first_key)
            first.add_provider("P", "https://e/v1", "k", model_name="m")
            first.close()
            
            # Write a DIFFERENT key to second_key so fail-fast doesn't trigger
            with open(second_key, "wb") as f:
                f.write(Fernet.generate_key())
                
            second = database_module.init_db(db_path, second_key)
            self.assertIsNot(second, first)
            second.close()

    def test_close_clears_singleton(self):
        with tempfile.TemporaryDirectory(prefix="steward_close_db_") as tmp:
            db = database_module.init_db(
                db_path=os.path.join(tmp, "providers.db"),
                key_path=os.path.join(tmp, "test.key"),
                force_new=True,
            )
            db.close()
            self.assertIsNone(database_module._db_instance)
            with self.assertRaisesRegex(RuntimeError, "Database not initialized"):
                database_module.get_db()


class SettingsAssignmentTests(unittest.TestCase):
    def test_agent_choices_include_click(self):
        self.assertIn("Click", SettingsTab.AGENT_CHOICES)

    def make_settings(self, db, name="BoundProvider"):
        tab = SettingsTab.__new__(SettingsTab)
        tab._is_alive = Mock(return_value=True)
        tab.verify_btn = Mock()
        tab.status_label = Mock()
        tab.assigned_agent_menu = Mock()
        tab.assigned_agent_menu.get.return_value = "Any"
        tab._assignment_dirty = False
        tab.refresh_provider_list = Mock()
        tab.name_entry = Mock()
        tab.name_entry.get.return_value = name
        self.db_patcher = patch("gui.settings_tab.get_db", return_value=db)
        self.db_patcher.start()
        self.addCleanup(self.db_patcher.stop)
        return tab

    def test_reverification_preserves_untouched_agent_binding(self):
        with tempfile.TemporaryDirectory(prefix="steward_reverify_") as tmp:
            db = DatabaseManager(
                db_path=os.path.join(tmp, "providers.db"),
                key_path=os.path.join(tmp, "test.key"),
            )
            try:
                db.add_provider(
                    "BoundProvider", "https://bound.example/v1", "old-key",
                    model_name="old-model", assigned_agent="Foldy",
                )
                tab = self.make_settings(db)
                result = SimpleNamespace(
                    status="healthy", success=True, error=None, speed_ms=10,
                    intel_tier="Tier 2: Standard", supports_tools=True,
                )
                tab._on_validation_complete(
                    result, "BoundProvider", "https://bound.example/v1",
                    "new-key", "new-model",
                )
                self.assertEqual(db.get_provider("BoundProvider")["assigned_agent"], "Foldy")
            finally:
                db.close()

    def test_existing_provider_name_populates_agent_binding(self):
        with tempfile.TemporaryDirectory(prefix="steward_assignment_form_") as tmp:
            db = DatabaseManager(
                db_path=os.path.join(tmp, "providers.db"),
                key_path=os.path.join(tmp, "test.key"),
            )
            try:
                db.add_provider(
                    "BoundProvider", "https://bound.example/v1", "key",
                    assigned_agent="Foldy",
                )
                tab = self.make_settings(db)
                tab._sync_assignment_to_existing_provider()
                tab.assigned_agent_menu.set.assert_called_once_with("Foldy")
                self.assertFalse(tab._assignment_dirty)
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

    def test_click_binding_and_short_tier_match_stored_label(self):
        db = self.db
        db.add_provider(
            name="ClickBrain", base_url="https://click.example/v1", api_key="click-key",
            model_name="click-model", assigned_agent="Click", speed_score_ms=10,
            intelligence_tier="Tier 1: Genius",
        )
        db.add_provider(
            name="WrongTier", base_url="https://wrong.example/v1", api_key="wrong-key",
            model_name="wrong-model", assigned_agent="Click", speed_score_ms=1,
            intelligence_tier="Tier 3: Fast",
        )
        with patch("core.router.requests.post", return_value=FakeResponse(
            payload=success_payload()
        )) as post:
            result = self.manager.route_request(
                [], agent_name="Click", required_tier="Tier 1"
            )
        post.assert_called_once()
        self.assertEqual(result["_steward"]["provider"], "ClickBrain")

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

    def test_429_failover_attempts_each_provider_once(self):
        endpoint = "https://same.example/v1"
        self.add_provider("First", endpoint, "key-1", 1, "Foldy")
        self.add_provider("Second", endpoint + "/", "key-2", 3, "Foldy")
        self.add_provider("Other", "https://other.example/v1", "other", 2, "Foldy")
        responses = [
            FakeResponse(status_code=429, payload={"error": "limited"}),
            FakeResponse(status_code=503, payload={"error": "unavailable"}),
            FakeResponse(payload=success_payload()),
        ]
        with patch("core.router.requests.post", side_effect=responses) as post:
            result = self.manager.route_request([], agent_name="Foldy")

        attempted_keys = [
            call.kwargs["headers"]["Authorization"]
            for call in post.call_args_list
        ]
        self.assertEqual(attempted_keys, ["Bearer key-1", "Bearer key-2", "Bearer other"])
        self.assertEqual(len(attempted_keys), len(set(attempted_keys)))
        self.assertEqual(result["_steward"]["provider"], "Other")
        failovers = result["_steward"]["failovers"]
        self.assertEqual(len(failovers), len({item["failed_provider"] for item in failovers}))

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
            agent.OPERATION_LOG_PATH = log_path
            agent._record_operation = Mock()
            move_file = Mock(return_value="Moved approved.txt")
            with patch("agents.file_agent._legacy_tool_functions", {"move_file": move_file}):
                preview = agent.run("move approved.txt", dry_run=True)
                self.assertIn("approved.txt", preview)
                move_file.assert_not_called()
                plan_id = agent.get_pending_plan_id()
                self.assertIsNotNone(plan_id)

                # Mutating the original provider response must not alter approval.
                tool_response["choices"][0]["message"]["tool_calls"][0]["function"] = {
                    "name": "delete_file", "arguments": json.dumps({"path": "unauthorized.txt"})
                }
                result = agent.execute_pending_plan(plan_id)

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
                agent.execute_pending_plan(plan_id)


class SandboxTests(unittest.TestCase):
    def make_agent(self, root):
        log_path = os.path.join(root, "operations.json")
        with patch.object(FileAgent, "OPERATION_LOG_PATH", log_path):
            agent = FileAgent(api_manager=Mock(), root_path=root)
        agent.OPERATION_LOG_PATH = log_path
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
                result = approve_plan(agent)

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
            _safe_after=Mock(side_effect=lambda callback: chat.after(0, callback)),
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
        agent.OPERATION_LOG_PATH = log_path
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


class H2DispatchTests(unittest.TestCase):
    """Dispatch path (_execute_tool_plan) must sandbox every path argument
    and reject undeclared tools before any tool function is invoked."""

    def make_agent(self, root):
        log_path = os.path.join(root, "operations.json")
        with patch.object(FileAgent, "OPERATION_LOG_PATH", log_path):
            agent = FileAgent(api_manager=Mock(), root_path=root)
        agent.OPERATION_LOG_PATH = log_path
        agent._record_operation = Mock()
        return agent

    def test_read_file_content_secret_key_rejected_before_invocation(self):
        with tempfile.TemporaryDirectory(prefix="steward_h2_") as tmp:
            secret = os.path.join(tmp, "secret.key")
            with open(secret, "w", encoding="utf-8") as handle:
                handle.write("super-secret")
            agent = self.make_agent(tmp)
            agent._pending_plan = [
                {"function": {"name": "read_file_content",
                              "arguments": {"file_path": secret}}}
            ]
            mock_fn = Mock(return_value="contents")
            with patch("agents.file_agent._legacy_tool_functions",
                       {"read_file_content": mock_fn}):
                result = approve_plan(agent)
            self.assertIn("Error: Sandbox violation", result)
            mock_fn.assert_not_called()

    def test_list_directory_out_of_root_rejected_before_invocation(self):
        with tempfile.TemporaryDirectory(prefix="steward_h2_") as tmp:
            outside = os.path.join(tmp, "outside_dir")
            os.makedirs(outside)
            agent = self.make_agent(tmp)
            agent._pending_plan = [
                {"function": {"name": "list_directory",
                              "arguments": {"directory": outside}}}
            ]
            mock_fn = Mock(return_value="listing")
            with patch("agents.file_agent._legacy_tool_functions",
                       {"list_directory": mock_fn}):
                result = approve_plan(agent)
            self.assertIn("Error: Sandbox violation", result)
            mock_fn.assert_not_called()

    def test_suggest_deletions_out_of_root_rejected_before_invocation(self):
        with tempfile.TemporaryDirectory(prefix="steward_h2_") as tmp:
            outside = os.path.join(tmp, "outside_dir")
            os.makedirs(outside)
            agent = self.make_agent(tmp)
            agent._pending_plan = [
                {"function": {"name": "suggest_deletions",
                              "arguments": {"directory": outside}}}
            ]
            mock_fn = Mock(return_value="report")
            with patch("agents.file_agent._legacy_tool_functions",
                       {"suggest_deletions": mock_fn}):
                result = approve_plan(agent)
            mock_fn.assert_not_called()
            self.assertIn("Error", result)
            self.assertIn("suggest_deletions", result)

    def test_find_duplicates_out_of_root_rejected_before_invocation(self):
        with tempfile.TemporaryDirectory(prefix="steward_h2_") as tmp:
            outside = os.path.join(tmp, "outside_dir")
            os.makedirs(outside)
            agent = self.make_agent(tmp)
            agent._pending_plan = [
                {"function": {"name": "find_duplicates",
                              "arguments": {"directory": outside}}}
            ]
            mock_fn = Mock(return_value="dups")
            with patch("agents.file_agent._legacy_tool_functions",
                       {"find_duplicates": mock_fn}):
                result = approve_plan(agent)
            mock_fn.assert_not_called()
            self.assertIn("Error", result)
            self.assertIn("find_duplicates", result)



class H1MoveTests(unittest.TestCase):
    """move_file into an existing directory must log the ACTUAL post-move file
    path (not the directory) so undo moves exactly one file and never a folder."""

    def make_agent(self, root):
        log_path = os.path.join(root, "operations.json")
        with patch.object(FileAgent, "OPERATION_LOG_PATH", log_path):
            agent = FileAgent(api_manager=Mock(), root_path=root)
        agent.OPERATION_LOG_PATH = log_path
        return agent

    def test_move_into_existing_directory_undo_preserves_directory(self):
        with tempfile.TemporaryDirectory(prefix="steward_h1_") as tmp:
            incoming = os.path.join(tmp, "Incoming")
            sorted_dir = os.path.join(tmp, "Sorted")
            os.makedirs(incoming)
            finance = os.path.join(sorted_dir, "Finance")
            os.makedirs(finance)
            # Populated directory: a sibling file already present
            sibling = os.path.join(finance, "sibling.txt")
            with open(sibling, "w", encoding="utf-8") as handle:
                handle.write("sibling")
            source = os.path.join(incoming, "report.pdf")
            with open(source, "w", encoding="utf-8") as handle:
                handle.write("report")
            agent = self.make_agent(tmp)
            agent._pending_plan = [
                {"function": {"name": "move_file",
                              "arguments": {"source": source,
                                            "destination": finance}}}
            ]
            result = approve_plan(agent)
            actual_dest = os.path.join(finance, "report.pdf")
            self.assertTrue(os.path.exists(actual_dest), result)
            self.assertFalse(os.path.exists(source))
            # Directory intact with sibling
            self.assertTrue(os.path.isdir(finance))
            self.assertTrue(os.path.exists(sibling))
            # Log records actual file path, not the directory
            move_entry = agent._operation_log[-1]
            self.assertEqual(move_entry["operation"], "move")
            self.assertEqual(move_entry["source"], source)
            self.assertEqual(move_entry["destination"], actual_dest)
            # Undo returns exactly that one file; directory and sibling intact
            undo_result = agent.undo_last()
            self.assertTrue(os.path.exists(source), undo_result)
            self.assertFalse(os.path.exists(actual_dest))
            self.assertTrue(os.path.exists(sibling))

    def test_direct_move_undo_preserves_populated_directory(self):
        with tempfile.TemporaryDirectory(prefix="steward_h1_direct_") as tmp:
            incoming = os.path.join(tmp, "Incoming")
            finance = os.path.join(tmp, "Sorted", "Finance")
            os.makedirs(incoming)
            os.makedirs(finance)
            source = os.path.join(incoming, "report.pdf")
            sibling = os.path.join(finance, "sibling.txt")
            with open(source, "w", encoding="utf-8") as handle:
                handle.write("report")
            with open(sibling, "w", encoding="utf-8") as handle:
                handle.write("sibling")
            agent = self.make_agent(tmp)

            result = agent.move_file(source, finance)
            actual_dest = os.path.join(finance, "report.pdf")
            self.assertTrue(result.startswith("Moved"), result)
            self.assertTrue(os.path.isfile(actual_dest))
            self.assertEqual(agent._operation_log[-1]["destination"], actual_dest)

            undo_result = agent.undo_last()
            self.assertTrue(os.path.isfile(source), undo_result)
            self.assertFalse(os.path.exists(actual_dest))
            self.assertTrue(os.path.isdir(finance))
            self.assertTrue(os.path.isfile(sibling))
            with open(sibling, "r", encoding="utf-8") as handle:
                self.assertEqual(handle.read(), "sibling")



class H3UndeclaredTests(unittest.TestCase):
    """Only tools in the declared schema (_get_tool_definitions) may be
    dispatched from a model-issued plan. Permanent-delete and bulk utilities
    are unreachable without a dedicated approval path."""

    def make_agent(self, root):
        log_path = os.path.join(root, "operations.json")
        with patch.object(FileAgent, "OPERATION_LOG_PATH", log_path):
            agent = FileAgent(api_manager=Mock(), root_path=root)
        agent.OPERATION_LOG_PATH = log_path
        agent._record_operation = Mock()
        return agent

    def test_undeclared_tool_name_rejected(self):
        with tempfile.TemporaryDirectory(prefix="steward_h3_") as tmp:
            agent = self.make_agent(tmp)
            agent._pending_plan = [
                {"function": {"name": "nonexistent_tool",
                              "arguments": {"path": "Incoming/x.txt"}}}
            ]
            result = approve_plan(agent)
            self.assertIn("Error", result)
            self.assertIn("nonexistent_tool", result)

    def test_cleanup_temp_files_cannot_execute_via_plan(self):
        with tempfile.TemporaryDirectory(prefix="steward_h3_") as tmp:
            directory = os.path.join(tmp, "Incoming")
            os.makedirs(directory)
            agent = self.make_agent(tmp)
            agent._pending_plan = [
                {"function": {"name": "cleanup_temp_files",
                              "arguments": {"directory": directory}}}
            ]
            mock_fn = Mock(return_value="removed")
            with patch("agents.file_agent._legacy_tool_functions",
                       {"cleanup_temp_files": mock_fn}):
                result = approve_plan(agent)
            mock_fn.assert_not_called()
            self.assertIn("Error", result)
            self.assertIn("cleanup_temp_files", result)

    def test_batch_move_rejected_via_plan(self):
        with tempfile.TemporaryDirectory(prefix="steward_h3_") as tmp:
            agent = self.make_agent(tmp)
            agent._pending_plan = [
                {"function": {"name": "batch_move",
                              "arguments": {"source_pattern": "Incoming/*.txt",
                                            "destination_folder": "Sorted"}}}
            ]
            mock_fn = Mock(return_value="moved")
            with patch("agents.file_agent._legacy_tool_functions",
                       {"batch_move": mock_fn}):
                result = approve_plan(agent)
            mock_fn.assert_not_called()
            self.assertIn("Error", result)
            self.assertIn("batch_move", result)



class H4PlanIdTests(unittest.TestCase):
    """A preview carries a plan identifier; approval executes only that plan.
    Stale/superseded/already-executed plans are refused."""

    def make_agent(self, root):
        log_path = os.path.join(root, "operations.json")
        with patch.object(FileAgent, "OPERATION_LOG_PATH", log_path):
            agent = FileAgent(api_manager=Mock(), root_path=root)
        agent.OPERATION_LOG_PATH = log_path
        agent._record_operation = Mock()
        return agent

    def test_approve_superseded_plan_refused(self):
        with tempfile.TemporaryDirectory(prefix="steward_h4_") as tmp:
            agent = self.make_agent(tmp)
            plan_a = [{"function": {"name": "move_file",
                                    "arguments": {"source": "Incoming/a.txt",
                                                  "destination": "Sorted/a.txt"}}}]
            plan_b = [{"function": {"name": "move_file",
                                    "arguments": {"source": "Incoming/b.txt",
                                                  "destination": "Sorted/b.txt"}}}]
            agent._pending_plan = plan_a
            agent._pending_plan_id = "plan-a"
            agent._pending_plan = plan_b
            agent._pending_plan_id = "plan-b"
            # Approve the superseded plan A -> refused
            with self.assertRaisesRegex(RuntimeError, "plan-a"):
                agent.execute_pending_plan("plan-a")
            # Plan B is still pending
            self.assertEqual(agent._pending_plan_id, "plan-b")

    def test_execute_same_plan_twice_refused(self):
        with tempfile.TemporaryDirectory(prefix="steward_h4_") as tmp:
            agent = self.make_agent(tmp)
            plan = [{"function": {"name": "move_file",
                                  "arguments": {"source": "Incoming/a.txt",
                                                "destination": "Sorted/a.txt"}}}]
            agent._pending_plan = plan
            agent._pending_plan_id = "plan-1"
            mock_fn = Mock(return_value="Moved")
            with patch("agents.file_agent._legacy_tool_functions",
                       {"move_file": mock_fn}):
                result = agent.execute_pending_plan("plan-1")
            mock_fn.assert_called_once()
            self.assertIsNone(agent._pending_plan_id)
            # Re-executing the same plan -> refused
            with self.assertRaises(RuntimeError):
                agent.execute_pending_plan("plan-1")

    def test_missing_none_or_wrong_plan_id_refused(self):
        for supplied_id in ("omitted", None, "wrong-plan"):
            with self.subTest(supplied_id=supplied_id):
                with tempfile.TemporaryDirectory(prefix="steward_h4_required_") as tmp:
                    agent = self.make_agent(tmp)
                    agent._pending_plan = [
                        {"function": {"name": "move_file",
                                      "arguments": {"source": "Incoming/a.txt",
                                                    "destination": "Sorted/a.txt"}}}
                    ]
                    agent._pending_plan_id = "expected-plan"
                    mock_fn = Mock(return_value="Moved")
                    with patch("agents.file_agent._legacy_tool_functions",
                               {"move_file": mock_fn}):
                        if supplied_id == "omitted":
                            with self.assertRaises(TypeError):
                                agent.execute_pending_plan()
                        else:
                            with self.assertRaises(RuntimeError):
                                agent.execute_pending_plan(supplied_id)
                    mock_fn.assert_not_called()
                    self.assertEqual(agent._pending_plan_id, "expected-plan")
                    self.assertIsNotNone(agent._pending_plan)

    def test_plan_refusal_contract_is_uniform(self):
        with tempfile.TemporaryDirectory(prefix="steward_n4_contract_") as tmp:
            agent = self.make_agent(tmp)
            agent._pending_plan = []
            agent._pending_plan_id = "current-plan"
            for supplied_id in (None, "stale-plan", "wrong-plan"):
                with self.subTest(supplied_id=supplied_id):
                    with self.assertRaises(RuntimeError):
                        agent.execute_pending_plan(supplied_id)
                    self.assertEqual(agent._pending_plan_id, "current-plan")
            agent.discard_pending_plan()
            with self.assertRaisesRegex(RuntimeError, "No previewed execution plan"):
                agent.execute_pending_plan("current-plan")


class H2ApprovedReadTests(unittest.TestCase):
    """Declared read tools must still execute on canonical sandbox paths."""

    def execute_read_plan(self, root, func_name, argument_name, path):
        log_path = os.path.join(root, "operations.json")
        with patch.object(FileAgent, "OPERATION_LOG_PATH", log_path):
            agent = FileAgent(api_manager=Mock(), root_path=root)
        agent.OPERATION_LOG_PATH = log_path
        agent._pending_plan = [
            {"function": {"name": func_name,
                          "arguments": {argument_name: path}}}
        ]
        agent._pending_plan_id = "approved-read-plan"
        return agent.execute_pending_plan("approved-read-plan")

    def make_note(self, root):
        incoming = os.path.join(root, "Incoming")
        os.makedirs(incoming)
        note = os.path.join(incoming, "note.txt")
        with open(note, "w", encoding="utf-8") as handle:
            handle.write("sandbox contents")
        return incoming, note

    def test_read_file_content_inside_sandbox_succeeds_via_plan(self):
        with tempfile.TemporaryDirectory(prefix="steward_h2_read_") as tmp:
            _, note = self.make_note(tmp)
            result = self.execute_read_plan(
                tmp, "read_file_content", "file_path", note
            )
            self.assertIn("sandbox contents", result)
            self.assertNotIn("Error", result)

    def test_list_directory_inside_sandbox_succeeds_via_plan(self):
        with tempfile.TemporaryDirectory(prefix="steward_h2_read_") as tmp:
            incoming, _ = self.make_note(tmp)
            result = self.execute_read_plan(
                tmp, "list_directory", "directory", incoming
            )
            self.assertIn("note.txt", result)
            self.assertNotIn("Error", result)

    def test_get_file_info_inside_sandbox_succeeds_via_plan(self):
        with tempfile.TemporaryDirectory(prefix="steward_h2_read_") as tmp:
            _, note = self.make_note(tmp)
            result = self.execute_read_plan(
                tmp, "get_file_info", "file_path", note
            )
            self.assertIn("Size:", result)
            self.assertNotIn("Error", result)


class ChatWorkflowTests(unittest.TestCase):
    """Chat input locking, plan capture, and deferred error rendering."""

    class ImmediateThread:
        def __init__(self, target, daemon):
            self.target = target

        def start(self):
            self.target()

    def make_chat(self, routing=None, route_error=None):
        chat = ChatTab.__new__(ChatTab)
        chat._processing = False
        chat.winfo_exists = Mock(return_value=True)
        chat.chat_entry = Mock()
        chat.chat_entry.get.return_value = "organize this"
        chat.send_btn = Mock()
        chat._add_bubble = Mock()
        chat.live_feed = None
        chat.provider_callback = None
        chat.supervisor = Mock()
        if route_error is None:
            chat.supervisor.route.return_value = routing
        else:
            chat.supervisor.route.side_effect = route_error
        chat.file_agent = Mock()
        chat._report_provider = Mock(return_value="")
        chat.handoff_canvas = Mock()  # Added for B2 handoff animation
        callbacks = []
        chat.after = Mock(
            side_effect=lambda delay, callback: callbacks.append(callback)
        )
        return chat, callbacks

    def assert_input_restored(self, chat):
        chat.send_btn.configure.assert_any_call(state="normal")
        bind_calls = [
            call for call in chat.chat_entry.bind.call_args_list
            if call.args and call.args[0] == "<Return>"
        ]
        self.assertTrue(bind_calls)
        self.assertTrue(callable(bind_calls[-1].args[1]))

    def test_send_chat_rejects_reentry_until_deferred_restore(self):
        chat, callbacks = self.make_chat(
            routing={"agent": AGENT_PC_CONTROL, "action": "open editor"}
        )

        class QueuedThread:
            instances = []

            def __init__(self, target, daemon):
                self.target = target
                self.instances.append(self)

            def start(self):
                pass

        with patch("gui.chat_tab.threading.Thread", QueuedThread):
            chat.send_chat()
            chat.send_chat()
            self.assertEqual(len(QueuedThread.instances), 1)
            chat.supervisor.route.assert_not_called()

            QueuedThread.instances[0].target()
            for callback in callbacks:
                callback()
            self.assertFalse(chat._processing)

            chat.send_chat()
            self.assertEqual(len(QueuedThread.instances), 2)

    def test_destroyed_widget_skips_worker_callbacks_without_raising(self):
        chat, callbacks = self.make_chat(
            routing={"agent": AGENT_PC_CONTROL, "action": "open editor"}
        )
        chat.winfo_exists.return_value = False
        chat.after = Mock(side_effect=RuntimeError("main thread is not in main loop"))
        callback = Mock()

        chat._safe_after(callback)
        with patch("gui.chat_tab.threading.Thread", self.ImmediateThread):
            chat.send_chat()

        callback.assert_not_called()
        chat.after.assert_not_called()
        self.assertEqual(callbacks, [])

    def test_non_file_route_restores_input_in_finally(self):
        chat, callbacks = self.make_chat(
            routing={"agent": AGENT_PC_CONTROL, "action": "open editor"}
        )
        with patch("gui.chat_tab.threading.Thread", self.ImmediateThread):
            chat.send_chat()

        chat.send_btn.configure.assert_any_call(state="disabled")
        chat.chat_entry.unbind.assert_called_once_with("<Return>")
        for callback in callbacks:
            callback()
        self.assert_input_restored(chat)

    def test_exception_callback_renders_error_and_restores_input(self):
        chat, callbacks = self.make_chat(route_error=RuntimeError("router exploded"))
        with self.assertLogs("gui.chat_tab", level="ERROR"):
            with patch("gui.chat_tab.threading.Thread", self.ImmediateThread):
                chat.send_chat()

        # Invoke after the worker and its except block have exited. This is the
        # exact point at which an exception variable captured by lambda is gone.
        for callback in callbacks:
            callback()
        rendered = [
            call.args[1] for call in chat._add_bubble.call_args_list
            if call.args and call.args[0] == "STEWARD"
        ]
        self.assertIn("Error: router exploded", rendered)
        self.assert_input_restored(chat)

    def test_file_approval_uses_plan_id_captured_at_preview(self):
        chat, callbacks = self.make_chat(
            routing={"agent": AGENT_FILE_OP, "action": "move a file"}
        )

        def preview(*args, **kwargs):
            chat.file_agent.get_pending_plan_id.return_value = "preview-plan-id"
            return "Preview ready"

        chat.file_agent.run.side_effect = preview
        chat.file_agent.execute_pending_plan.return_value = "Executed"

        def schedule(delay, callback):
            callbacks.append(callback)
            if callback.__name__ == "ask_exec":
                callback()

        def approve(*args, **kwargs):
            # A later preview must not change what this approval executes.
            chat.file_agent.get_pending_plan_id.return_value = "superseded-plan-id"
            return True

        chat.after.side_effect = schedule
        with patch("gui.chat_tab.threading.Thread", self.ImmediateThread):
            with patch("gui.chat_tab.messagebox.askyesno", side_effect=approve):
                chat.send_chat()

        chat.file_agent.execute_pending_plan.assert_called_once_with(
            "preview-plan-id"
        )
        for callback in callbacks:
            if callback.__name__ != "ask_exec":
                callback()
        self.assert_input_restored(chat)

    def test_dialog_unanswered_times_out_and_restores_input(self):
        chat, callbacks = self.make_chat(
            routing={"agent": AGENT_FILE_OP, "action": "move a file"}
        )
        chat.dialog_timeout = 0.05
        chat.file_agent.run.return_value = "Preview ready"
        chat.file_agent.get_pending_plan_id.return_value = "preview-plan-id"

        worker_thread = None
        orig_thread = threading.Thread

        class CapturedThread(orig_thread):
            def __init__(self, target, daemon=True):
                nonlocal worker_thread
                super().__init__(target=target, daemon=daemon)
                worker_thread = self

        with patch("gui.chat_tab.threading.Thread", CapturedThread):
            with self.assertLogs("gui.chat_tab", level="INFO") as logs:
                chat.send_chat()
                self.assertIsNotNone(worker_thread)
                worker_thread.join(timeout=0.3)
                self.assertFalse(worker_thread.is_alive(), "Worker blocked on unanswered dialog")
                self.assertTrue(any("approval dialog timed out; input restored" in m for m in logs.output))

        chat.file_agent.discard_pending_plan.assert_called_once()
        with patch("gui.chat_tab.messagebox.askyesno", return_value=False):
            for callback in callbacks:
                callback()
        self.assert_input_restored(chat)

class Batch2BTests(unittest.TestCase):
    def make_agent(self, root):
        log_path = os.path.join(root, "operations.json")
        with patch.object(FileAgent, "OPERATION_LOG_PATH", log_path):
            agent = FileAgent(api_manager=Mock(), root_path=root)
        agent.OPERATION_LOG_PATH = log_path
        return agent

    def test_delete_entry_skipped_and_never_marked_undone(self):
        with tempfile.TemporaryDirectory(prefix="steward_2b_") as tmp:
            incoming = os.path.join(tmp, "Incoming"); os.makedirs(incoming)
            sorted_dir = os.path.join(tmp, "Sorted"); os.makedirs(sorted_dir)
            src = os.path.join(incoming, "a.txt")
            with open(src, "w", encoding="utf-8") as fh: fh.write("x")
            agent = self.make_agent(tmp)
            agent.move_file(src, os.path.join(sorted_dir, "a.txt"))
            agent._operation_log.append({
                "id": "d", "timestamp": "d", "operation": "delete",
                "source": src, "destination": None, "result": "",
                "success": True, "undone": False})
            result = agent.undo_last()
            self.assertIn("Undid move", result)
            self.assertFalse(agent._operation_log[-1]["undone"])
            self.assertTrue(agent._operation_log[0]["undone"])

    def test_delete_only_log_reports_limitation(self):
        with tempfile.TemporaryDirectory(prefix="steward_2b_") as tmp:
            agent = self.make_agent(tmp)
            agent._operation_log.append({
                "id": "d", "timestamp": "d", "operation": "delete",
                "source": "Incoming/gone.txt", "destination": None,
                "result": "", "success": True, "undone": False})
            result = agent.undo_last()
            self.assertIn("Cannot undo delete", result)
            self.assertFalse(agent._operation_log[0]["undone"])

    def test_redo_replays_in_original_order(self):
        with tempfile.TemporaryDirectory(prefix="steward_2b_") as tmp:
            incoming = os.path.join(tmp, "Incoming"); os.makedirs(incoming)
            sorted_dir = os.path.join(tmp, "Sorted"); os.makedirs(sorted_dir)
            a, b = os.path.join(incoming, "a.txt"), os.path.join(incoming, "b.txt")
            for p in (a, b):
                with open(p, "w", encoding="utf-8") as fh: fh.write("x")
            agent = self.make_agent(tmp)
            agent.move_file(a, os.path.join(sorted_dir, "a.txt"))
            agent.move_file(b, os.path.join(sorted_dir, "b.txt"))
            agent.undo_last(); agent.undo_last()
            agent.redo_last()
            self.assertTrue(os.path.exists(os.path.join(sorted_dir, "a.txt")))
            self.assertFalse(os.path.exists(os.path.join(sorted_dir, "b.txt")))

    def test_undo_refuses_collision(self):
        with tempfile.TemporaryDirectory(prefix="steward_2b_") as tmp:
            incoming = os.path.join(tmp, "Incoming"); os.makedirs(incoming)
            sorted_dir = os.path.join(tmp, "Sorted"); os.makedirs(sorted_dir)
            s, d = os.path.join(incoming, "a.txt"), os.path.join(sorted_dir, "a.txt")
            for p in (s, d):
                with open(p, "w", encoding="utf-8") as fh: fh.write("keep")
            agent = self.make_agent(tmp)
            agent._operation_log.append({
                "id": "m", "timestamp": "m", "operation": "move",
                "source": s, "destination": d, "result": "",
                "success": True, "undone": False})
            result = agent.undo_last()
            self.assertIn("refusing to overwrite", result)
            self.assertFalse(agent._operation_log[0]["undone"])
            self.assertTrue(os.path.exists(s) and os.path.exists(d))

    def test_corrupt_log_loads_empty(self):
        with tempfile.TemporaryDirectory(prefix="steward_2b_") as tmp:
            with open(os.path.join(tmp, "operations.json"), "w") as fh:
                fh.write("{not a list")
            agent = self.make_agent(tmp)
            self.assertEqual(agent._operation_log, [])

    def test_preview_flags_doomed_plan_without_executing(self):
        with tempfile.TemporaryDirectory(prefix="steward_2b_") as tmp:
            agent = self.make_agent(tmp)
            plan = [{"function": {"name": "cleanup_temp_files",
                                  "arguments": {"directory": os.path.join(tmp, "Incoming")}}}]
            results = agent._execute_tool_plan(plan, dry_run=True)
            self.assertIn("WILL BE REJECTED", "\n".join(results))

    def test_undo_redo_absent_from_declared_schema(self):
        with tempfile.TemporaryDirectory(prefix="steward_2b_") as tmp:
            agent = self.make_agent(tmp)
            names = {t["function"]["name"] for t in agent._get_tool_definitions()}
            self.assertNotIn("undo_last", names)
            self.assertNotIn("redo_last", names)


class Batch3Tests(unittest.TestCase):
    """Batch 3b regressions: daemon stability/dedup, per-call dry_run,
    main-thread preview, categorise dest_base sandbox, shutdown lifecycle."""

    def make_agent(self, root):
        log_path = os.path.join(root, "operations.json")
        with patch.object(FileAgent, "OPERATION_LOG_PATH", log_path):
            agent = FileAgent(api_manager=Mock(), root_path=root)
        agent.OPERATION_LOG_PATH = log_path
        agent._record_operation = Mock()
        return agent

    # M2 stability: _wait_until_stable must exist and report changing vs stable.
    def test_wait_until_stable_exists_and_detects_stability(self):
        handler = FileCreationHandler.__new__(FileCreationHandler)
        handler.root = tempfile.mkdtemp()
        handler.dest_base = os.path.join(handler.root, "Sorted")
        os.makedirs(handler.dest_base)
        filepath = os.path.join(handler.root, "Incoming", "growing.txt")
        os.makedirs(os.path.dirname(filepath))
        with open(filepath, "w", encoding="utf-8") as fh:
            fh.write("a")

        index = [0]

        def fake_getsize(path):
            if path == filepath:
                index[0] += 1
                return index[0]
            return os.path.getsize(path)

        with patch("agent.daemon.os.path.getsize", side_effect=fake_getsize), \
             patch("agent.daemon.time.sleep", return_value=None):
            self.assertFalse(handler._wait_until_stable(filepath, timeout=2.0, interval=0.01))

        with patch("agent.daemon.os.path.getsize", return_value=5), \
             patch("agent.daemon.time.sleep", return_value=None):
            self.assertTrue(handler._wait_until_stable(filepath, timeout=2.0, interval=0.01))

    def test_dedup_keeps_most_recent_after_1001(self):
        with tempfile.TemporaryDirectory(prefix="steward_dedup_") as tmp:
            dest = os.path.join(tmp, "Sorted"); os.makedirs(dest)
            handler = FileCreationHandler(Mock(), dest, None)
            with patch("agent.daemon.threading.Thread"), \
                 patch("agent.daemon.time.sleep", return_value=None), \
                 patch.object(handler, "_process_file"):
                for i in range(1001):
                    handler.on_created(SimpleNamespace(
                        is_directory=False, src_path=os.path.join(tmp, f"file_{i}.txt")))
            self.assertIn(os.path.join(tmp, "file_1000.txt"), handler.last_processed)
            self.assertLessEqual(len(handler.last_processed), 1000)

    # M3 per-call: categorise_file(..., dry_run=False) moves even when agent.dry_run is True.
    def test_categorise_file_per_call_dry_run_overrides_agent_flag(self):
        with tempfile.TemporaryDirectory(prefix="steward_m3_percall_") as tmp:
            incoming = os.path.join(tmp, "Incoming")
            sorted_dir = os.path.join(tmp, "Sorted")
            os.makedirs(incoming)
            os.makedirs(sorted_dir)
            src = os.path.join(incoming, "note.txt")
            with open(src, "w", encoding="utf-8") as fh:
                fh.write("hello world")

            agent = self.make_agent(tmp)
            agent.dry_run = True
            agent.api_manager = Mock()
            agent.api_manager.route_request.return_value = {
                "choices": [{"message": {"content": "Docs"}}]
            }
            agent.read_file_content = Mock(return_value="hello world")
            agent.create_folder = Mock(return_value="Created Docs")
            agent.move_file = Mock(return_value="Moved note.txt -> Sorted/Docs/note.txt")

            result = agent.categorise_file(src, sorted_dir, dry_run=False)
            agent.move_file.assert_called_once()
            self.assertIn("Moved", result)

    # M3 shared flag: execute_selected must not flip agent.dry_run mid-flight.
    def test_execute_selected_keeps_agent_dry_run_true(self):
        organizer = OrganizerTab.__new__(OrganizerTab)
        captured = {}

        def fake_move_file(source, destination):
            captured["dry_run"] = organizer.file_agent.dry_run
            return "Moved"

        organizer.file_agent = Mock()
        organizer.file_agent.dry_run = True
        organizer.file_agent.move_file = fake_move_file
        organizer.gui = None
        organizer.pending_operations = [
            {
                "filename": "a.txt",
                "source": "Incoming/a.txt",
                "destination": "Sorted/a.txt",
                "selected": True,
            }
        ]
        organizer.btn_execute = Mock()
        organizer._log = Mock()
        organizer.after = Mock(side_effect=lambda delay, callback: None)

        class ImmediateThread:
            def __init__(self, target, daemon=None):
                self.target = target

            def start(self):
                self.target()

        with patch("gui.organizer_tab.messagebox.askyesno", return_value=True), \
             patch("gui.organizer_tab.messagebox.showinfo"), \
             patch("gui.organizer_tab.threading.Thread", ImmediateThread):
            organizer.execute_selected()

        self.assertEqual(captured.get("dry_run"), True, captured)

    # N6: categorise_file rejects dest_base outside the sandbox and moves nothing.
    def test_categorise_file_rejects_dest_base_outside_sandbox(self):
        with tempfile.TemporaryDirectory(prefix="steward_n6_") as tmp:
            incoming = os.path.join(tmp, "Incoming")
            sorted_dir = os.path.join(tmp, "Sorted")
            outside = os.path.join(tmp, "Outside")
            os.makedirs(incoming)
            os.makedirs(sorted_dir)
            os.makedirs(outside)
            src = os.path.join(incoming, "note.txt")
            with open(src, "w", encoding="utf-8") as fh:
                fh.write("hello")

            agent = self.make_agent(tmp)
            agent.dry_run = False
            agent.read_file_content = Mock(return_value="hello")
            agent.api_manager = Mock()
            agent.api_manager.route_request.return_value = {
                "choices": [{"message": {"content": "Docs"}}]
            }
            agent.create_folder = Mock()
            agent.move_file = Mock(return_value="Moved")

            result = agent.categorise_file(src, outside)
            self.assertIn("Sandbox violation", result)
            agent.create_folder.assert_not_called()
            agent.move_file.assert_not_called()

    # M8: preview rows must be built on the Tk main thread, never on the worker.
    def test_preview_rows_built_on_main_thread(self):
        recorded = []

        class RecordingRow:
            def __init__(self, parent, filename, source, destination, on_toggle,
                         *args, **kwargs):
                recorded.append(threading.current_thread().name)

            def pack(self, *args, **kwargs):
                pass

            def destroy(self):
                pass

        tmp_in = tempfile.mkdtemp(prefix="m8_in_")
        tmp_dest = tempfile.mkdtemp(prefix="m8_dest_")
        with open(os.path.join(tmp_in, "a.txt"), "w", encoding="utf-8") as fh:
            fh.write("a")

        organizer = OrganizerTab.__new__(OrganizerTab)
        organizer.preview_container = Mock()
        organizer.preview_rows = []
        organizer.pending_operations = []
        organizer.btn_execute = Mock()
        organizer._log = Mock()
        organizer.watched_var = Mock()
        organizer.watched_var.get.return_value = tmp_in
        organizer.dest_var = Mock()
        organizer.dest_var.get.return_value = tmp_dest
        organizer.file_agent = Mock()
        organizer.file_agent.read_file_content = Mock(return_value="content")
        organizer.file_agent.system_prompt = "prompt"
        organizer.file_agent.api_manager = Mock()
        organizer.file_agent.api_manager.route_request.return_value = {
            "choices": [{"message": {"content": "Docs"}}]
        }

        callbacks = []
        organizer.after = Mock(side_effect=lambda delay, callback: callbacks.append(callback))

        with patch("gui.organizer_tab.FilePreviewRow", RecordingRow), \
             patch("gui.organizer_tab.os.listdir", return_value=["a.txt"]):
            thread = threading.Thread(target=organizer.preview_incoming, daemon=True)
            thread.start()
            thread.join()

            for cb in callbacks:
                cb()

        self.assertTrue(recorded, "No FilePreviewRow was constructed")
        self.assertTrue(all(name == "MainThread" for name in recorded), recorded)

    # L3 observer: _perform_shutdown must stop the organizer's daemon.
    def test_perform_shutdown_stops_organizer_daemon(self):
        gui = StewardGUI.__new__(StewardGUI)
        organizer = Mock()
        organizer.daemon_running = True
        gui.tabs = {"organizer": organizer}
        gui.root = Mock()
        gui.tray_icon = Mock()
        gui._perform_shutdown()
        organizer.stop_daemon.assert_called_once()

    # L3 dead path: on_closing must not exist.
    def test_on_closing_removed(self):
        self.assertFalse(hasattr(StewardGUI, "on_closing"))


class CredentialStoreTests(unittest.TestCase):
    """Tests for shared credential store per docs/credential_store_review.md."""

    def test_url_normalization(self):
        cases = [
            ("https://OpenRouter.AI/api/v1/", "https://openrouter.ai/api/v1"),
            ("http://LOCALHOST:11434/v1/", "http://localhost:11434/v1"),
            ("  https://api.openai.com/v1  ", "https://api.openai.com/v1"),
            ("https://generativelanguage.googleapis.com/v1beta/openai/", "https://generativelanguage.googleapis.com/v1beta/openai"),
            ("https://api.groq.com/openai/v1///", "https://api.groq.com/openai/v1"),
            ("", ""),
            (None, ""),
        ]
        for raw, expected in cases:
            with self.subTest(raw=raw):
                self.assertEqual(normalize_base_url(raw), expected)

    def test_credential_crud_round_trip(self):
        with tempfile.TemporaryDirectory(prefix="steward_crud_") as tmp:
            db_path = os.path.join(tmp, "test.db")
            key_path = os.path.join(tmp, "test.key")
            db = DatabaseManager(db_path, key_path)

            # Create
            cred_id = db.set_credential("https://api.test.com/v1/", "sk-secret-123", "Test Endpoint")
            self.assertIsNotNone(cred_id)

            # Read by URL
            by_url = db.get_credential_by_url("https://api.test.com/v1")
            self.assertIsNotNone(by_url)
            self.assertEqual(by_url["api_key"], "sk-secret-123")
            self.assertEqual(by_url["base_url_normalized"], "https://api.test.com/v1")

            # Read by ID
            by_id = db.get_credential_by_id(cred_id)
            self.assertIsNotNone(by_id)
            self.assertEqual(by_id["api_key"], "sk-secret-123")

            # List all
            all_creds = db.get_all_credentials()
            self.assertEqual(len(all_creds), 1)
            self.assertEqual(all_creds[0]["id"], cred_id)

            # Update
            db.set_credential("https://api.test.com/v1", "sk-secret-updated")
            updated = db.get_credential_by_id(cred_id)
            self.assertEqual(updated["api_key"], "sk-secret-updated")

            # Delete
            deleted = db.delete_credential(cred_id)
            self.assertTrue(deleted)
            self.assertIsNone(db.get_credential_by_id(cred_id))
            self.assertIsNone(db.get_credential_by_url("https://api.test.com/v1"))
            db.close()

    def test_dual_read(self):
        with tempfile.TemporaryDirectory(prefix="steward_dual_") as tmp:
            db_path = os.path.join(tmp, "test.db")
            key_path = os.path.join(tmp, "test.key")
            db = DatabaseManager(db_path, key_path)

            # 1. Provider with credential_id reads from credentials
            cred_id = db.set_credential("https://api.endpoint1.com/v1", "key-from-cred", "Endpoint 1")
            db.add_provider(
                name="ProviderWithCred",
                base_url="https://api.endpoint1.com/v1",
                api_key="key-from-cred",
                credential_id=cred_id,
            )
            p1 = db.get_provider("ProviderWithCred")
            self.assertEqual(p1["api_key"], "key-from-cred")
            self.assertEqual(p1["credential_id"], cred_id)

            # 2. Provider with credential_id = NULL reads from legacy api_key_encrypted
            enc_legacy = db._encrypt("legacy-key-value")
            with db._lock:
                cursor = db._conn.cursor()
                cursor.execute("""
                    INSERT INTO providers (name, base_url, api_key_encrypted, model_name, is_local, is_active, credential_id)
                    VALUES (?, ?, ?, ?, ?, ?, NULL)
                """, ("LegacyProvider", "https://api.legacy.com/v1", enc_legacy, "m1", 0, 1))
                db._conn.commit()

            p2 = db.get_provider("LegacyProvider")
            self.assertIsNone(p2["credential_id"])
            self.assertEqual(p2["api_key"], "legacy-key-value")

            # 3. Prefer joined credential if credential_id is set
            db.set_credential("https://api.endpoint1.com/v1", "rotated-key")
            p1_refreshed = db.get_provider("ProviderWithCred")
            self.assertEqual(p1_refreshed["api_key"], "rotated-key")
            db.close()

    def test_migration_idempotency(self):
        with tempfile.TemporaryDirectory(prefix="steward_mig_idem_") as tmp:
            db_path = os.path.join(tmp, "test.db")
            key_path = os.path.join(tmp, "test.key")
            db = DatabaseManager(db_path, key_path)

            # Seed synthetic legacy providers with shared endpoints
            enc1 = db._encrypt("shared-openrouter-key")
            with db._lock:
                cursor = db._conn.cursor()
                cursor.execute("""
                    INSERT INTO providers (name, base_url, api_key_encrypted, model_name, is_local, is_active, speed_score_ms)
                    VALUES ('OR-Model-1', 'https://openrouter.ai/api/v1/', ?, 'model-1', 0, 1, 250)
                """, (enc1,))
                cursor.execute("""
                    INSERT INTO providers (name, base_url, api_key_encrypted, model_name, is_local, is_active, speed_score_ms)
                    VALUES ('OR-Model-2', 'https://openrouter.ai/api/v1', ?, 'model-2', 0, 1, 300)
                """, (enc1,))
                cursor.execute("""
                    INSERT INTO providers (name, base_url, api_key_encrypted, model_name, is_local, is_active)
                    VALUES ('Local-Ollama', 'http://localhost:11434/v1', NULL, 'llama3', 1, 1)
                """)
                db._conn.commit()

            # First migration run
            res1 = migrate_to_shared_credentials(db)
            self.assertGreaterEqual(res1["credentials_created"], 1)

            prov1_first = db.get_provider("OR-Model-1")
            prov2_first = db.get_provider("OR-Model-2")
            local_first = db.get_provider("Local-Ollama")
            self.assertIsNotNone(prov1_first["credential_id"])
            self.assertEqual(prov1_first["credential_id"], prov2_first["credential_id"])
            self.assertIsNone(local_first["credential_id"])
            creds_count_1 = len(db.get_all_credentials())

            # Second migration run (idempotency check)
            res2 = migrate_to_shared_credentials(db)
            self.assertEqual(res2["credentials_created"], 0)

            prov1_second = db.get_provider("OR-Model-1")
            prov2_second = db.get_provider("OR-Model-2")
            creds_count_2 = len(db.get_all_credentials())

            self.assertEqual(prov1_first["credential_id"], prov1_second["credential_id"])
            self.assertEqual(prov2_first["credential_id"], prov2_second["credential_id"])
            self.assertEqual(creds_count_1, creds_count_2)
            self.assertEqual(prov1_second["api_key"], "shared-openrouter-key")
            db.close()

    def test_migration_rollback(self):
        with tempfile.TemporaryDirectory(prefix="steward_rollback_") as tmp:
            db_path = os.path.join(tmp, "test.db")
            key_path = os.path.join(tmp, "test.key")
            db = DatabaseManager(db_path, key_path)

            enc = db._encrypt("pre-migration-key")
            with db._lock:
                cursor = db._conn.cursor()
                cursor.execute("""
                    INSERT INTO providers (name, base_url, api_key_encrypted, model_name, is_local, is_active)
                    VALUES ('Provider1', 'https://api.service.com/v1', ?, 'm1', 0, 1)
                """, (enc,))
                db._conn.commit()

            # Migrate
            migrate_to_shared_credentials(db)
            p_migrated = db.get_provider("Provider1")
            self.assertIsNotNone(p_migrated["credential_id"])
            self.assertEqual(p_migrated["api_key"], "pre-migration-key")

            # Rollback
            res = rollback_from_shared_credentials(db)
            self.assertEqual(res["providers_restored"], 1)

            p_rolled_back = db.get_provider("Provider1")
            self.assertIsNone(p_rolled_back["credential_id"])
            self.assertEqual(p_rolled_back["api_key"], "pre-migration-key")

            # Verify credentials table was NOT dropped
            with db._lock:
                cursor = db._conn.cursor()
                cursor.execute("SELECT COUNT(*) FROM credentials")
                count = cursor.fetchone()[0]
                self.assertGreaterEqual(count, 1)
            db.close()

    def test_hostile_corrupt_credential_payload(self):
        with tempfile.TemporaryDirectory(prefix="steward_corrupt_") as tmp:
            db_path = os.path.join(tmp, "test.db")
            key_path = os.path.join(tmp, "test.key")
            db = DatabaseManager(db_path, key_path)

            cred_id = db.set_credential("https://api.corrupt.com/v1", "valid-key")
            db.add_provider(
                name="CorruptibleProv",
                base_url="https://api.corrupt.com/v1",
                api_key="valid-key",
                credential_id=cred_id,
                is_active=True,
            )

            # Corrupt the credential blob
            with db._lock:
                cursor = db._conn.cursor()
                cursor.execute(
                    "UPDATE credentials SET api_key_encrypted = ? WHERE id = ?",
                    (b"GARBAGE_NOT_FERNET_TOKEN", cred_id),
                )
                db._conn.commit()

            # Provider should enter recoverable state, not crash
            all_provs = db.get_all_providers()
            prov = next(p for p in all_provs if p["name"] == "CorruptibleProv")
            self.assertIsNone(prov["api_key"])
            self.assertEqual(prov["decryption_error"], DECRYPTION_ERROR)

            # Active providers should exclude the corrupted provider
            active_provs = db.get_active_providers()
            self.assertNotIn("CorruptibleProv", [p["name"] for p in active_provs])
            db.close()

    def test_hostile_missing_secret_key_during_migration(self):
        with tempfile.TemporaryDirectory(prefix="steward_missing_key_") as tmp:
            db_path = os.path.join(tmp, "test.db")
            key_path = os.path.join(tmp, "missing.key")

            # Create an existing database first
            conn = sqlite3.connect(db_path)
            conn.execute("CREATE TABLE providers (id INTEGER PRIMARY KEY, name TEXT)")
            conn.commit()
            conn.close()

            # Key file is missing while DB exists -> must fail fast
            with self.assertRaises(RuntimeError) as ctx:
                DatabaseManager(db_path, key_path)
            self.assertIn("Refusing to generate a new key", str(ctx.exception))
            self.assertFalse(os.path.exists(key_path), "secret.key must not be generated!")

    def test_hostile_dangling_credential_id(self):
        with tempfile.TemporaryDirectory(prefix="steward_dangling_") as tmp:
            db_path = os.path.join(tmp, "test.db")
            key_path = os.path.join(tmp, "test.key")
            db = DatabaseManager(db_path, key_path)

            # Insert provider pointing to non-existent credential_id
            # Temporarily disable foreign keys for this hostile setup
            with db._lock:
                cursor = db._conn.cursor()
                cursor.execute("PRAGMA foreign_keys = OFF")
                cursor.execute("""
                    INSERT INTO providers (name, base_url, api_key_encrypted, model_name, is_local, is_active, credential_id)
                    VALUES ('DanglingProv', 'https://api.lost.com/v1', NULL, 'm1', 0, 1, 99999)
                """)
                db._conn.commit()
                cursor.execute("PRAGMA foreign_keys = ON")

            prov = db.get_provider("DanglingProv")
            self.assertIsNotNone(prov)
            self.assertIsNone(prov["api_key"])
            self.assertEqual(prov["decryption_error"], "Credential reference missing or unassigned")

            active = db.get_active_providers()
            self.assertNotIn("DanglingProv", [p["name"] for p in active])
            db.close()

    def test_hostile_conflicting_duplicate_endpoints(self):
        with tempfile.TemporaryDirectory(prefix="steward_conflict_") as tmp:
            db_path = os.path.join(tmp, "test.db")
            key_path = os.path.join(tmp, "test.key")
            db = DatabaseManager(db_path, key_path)

            enc_inactive = db._encrypt("key-inactive-fast")
            enc_active_slow = db._encrypt("key-active-slow")
            enc_active_fast = db._encrypt("key-active-fast")

            with db._lock:
                cursor = db._conn.cursor()
                # Provider 1: inactive, speed=100
                cursor.execute("""
                    INSERT INTO providers (name, base_url, api_key_encrypted, model_name, is_local, is_active, speed_score_ms)
                    VALUES ('P1_Inactive', 'https://openrouter.ai/api/v1', ?, 'm1', 0, 0, 100)
                """, (enc_inactive,))
                # Provider 2: active, speed=500
                cursor.execute("""
                    INSERT INTO providers (name, base_url, api_key_encrypted, model_name, is_local, is_active, speed_score_ms)
                    VALUES ('P2_ActiveSlow', 'https://openrouter.ai/api/v1', ?, 'm2', 0, 1, 500)
                """, (enc_active_slow,))
                # Provider 3: active, speed=200 -> should WIN
                cursor.execute("""
                    INSERT INTO providers (name, base_url, api_key_encrypted, model_name, is_local, is_active, speed_score_ms)
                    VALUES ('P3_ActiveFast', 'https://openrouter.ai/api/v1', ?, 'm3', 0, 1, 200)
                """, (enc_active_fast,))
                db._conn.commit()

            # Run migration
            migrate_to_shared_credentials(db)

            # Canonical credential must have won by P3 (active + lower speed)
            canonical = db.get_credential_by_url("https://openrouter.ai/api/v1")
            self.assertIsNotNone(canonical)
            self.assertEqual(canonical["api_key"], "key-active-fast")

            # All providers retain their own keys via deterministic resolution
            p1 = db.get_provider("P1_Inactive")
            p2 = db.get_provider("P2_ActiveSlow")
            p3 = db.get_provider("P3_ActiveFast")

            self.assertEqual(p3["api_key"], "key-active-fast")
            self.assertEqual(p3["credential_id"], canonical["id"])
            self.assertEqual(p2["api_key"], "key-active-slow")
            self.assertEqual(p1["api_key"], "key-inactive-fast")
            self.assertNotEqual(p2["credential_id"], canonical["id"])
            db.close()

    def test_discovery_activation_works_with_shared_credentials(self):
        with tempfile.TemporaryDirectory(prefix="steward_disc_") as tmp:
            db_path = os.path.join(tmp, "test.db")
            key_path = os.path.join(tmp, "test.key")
            db = DatabaseManager(db_path, key_path)

            # 1. Existing shared credential for OpenRouter
            cred_id = db.set_credential("https://openrouter.ai/api/v1", "shared-or-key", "OpenRouter Main")

            with patch("core.discovery.get_db", return_value=db):
                models = [DiscoveredModel(model_id="org/free-1", display_name="Free Model 1")]
                added, skipped = upsert_discovered_models(models)
                self.assertEqual(added, 1)

            prov = db.get_provider("Free Model 1")
            self.assertIsNotNone(prov)
            self.assertEqual(prov["credential_id"], cred_id)
            self.assertEqual(prov["api_key"], "shared-or-key")

            # 2. Re-activation / toggle
            db.update_provider_fields("Free Model 1", is_active=1)
            active = db.get_active_providers()
            self.assertIn("Free Model 1", [p["name"] for p in active])
            db.close()

class PhaseBAnimTests(unittest.TestCase):
    """gui/anim.py: SafeTick ticks on schedule, stops on False, dies quietly."""

    def make_widget(self, exists=True):
        widget = Mock()
        widget.winfo_exists.return_value = exists
        scheduled = []

        def after(delay, callback):
            scheduled.append((delay, callback))
            return len(scheduled)

        widget.after.side_effect = after
        widget.after_cancel = Mock()
        return widget, scheduled

    def test_tick_runs_until_callback_returns_false(self):
        widget, scheduled = self.make_widget()
        calls = []

        def on_tick():
            calls.append(1)
            return len(calls) < 3

        done = []
        SafeTick(widget, 16, on_tick, on_done=lambda: done.append(True)).start()
        while scheduled:
            _, cb = scheduled.pop(0)
            cb()
        self.assertEqual(len(calls), 3)
        self.assertEqual(done, [True])

    def test_destroyed_widget_finishes_without_raising(self):
        widget, scheduled = self.make_widget(exists=False)
        done = []
        SafeTick(widget, 16, lambda: True, on_done=lambda: done.append(True)).start()
        self.assertEqual(scheduled, [])
        self.assertEqual(done, [True])
        widget.after.assert_not_called()

    def test_cancel_stops_future_ticks(self):
        widget, scheduled = self.make_widget()
        calls = []
        tick = SafeTick(widget, 16, lambda: calls.append(1) or True)
        tick.start()
        tick.cancel()
        self.assertEqual(calls, [])
        widget.after_cancel.assert_called()

    def test_after_error_finishes_quietly(self):
        widget = Mock()
        widget.winfo_exists.return_value = True
        widget.after.side_effect = RuntimeError("main thread is not in main loop")
        done = []
        SafeTick(widget, 16, lambda: True, on_done=lambda: done.append(True)).start()
        self.assertEqual(done, [True])

    def test_lerp_color_endpoints(self):
        self.assertEqual(lerp_color("#000000", "#FFFFFF", 0.0), "#000000")
        self.assertEqual(lerp_color("#000000", "#FFFFFF", 1.0), "#FFFFFF")
        self.assertEqual(lerp_color("#2A2A35", "#2A2A35", 0.5), "#2A2A35")

class CategorySanitizerTests(unittest.TestCase):
    def test_rejects_conversational_reply(self):
        from utils.helpers import sanitize_category
        essay = ("Based on the content preview, a suitable category is:\n\n"
                 "**Folder name:** `Reports_ACES`")
        self.assertEqual(
            sanitize_category(essay, "C:/x/custom_report.pdf"), "Documents")

    def test_accepts_clean_name_and_strips_illegal_chars(self):
        from utils.helpers import sanitize_category
        self.assertEqual(sanitize_category("Resume_CV", "a.pdf"), "Resume_CV")
        self.assertEqual(sanitize_category("A/B:C*D", "a.pdf"), "ABCD")

    def test_falls_back_by_extension(self):
        from utils.helpers import sanitize_category
        self.assertEqual(sanitize_category("", "photo.PNG"), "Images")
        self.assertEqual(sanitize_category("x" * 200, "a.pdf"), "Documents")

class ChatNoPlanTests(unittest.TestCase):
    def test_clarifying_question_does_not_offer_execution(self):
        chat, callbacks = ChatWorkflowTests().make_chat(
            routing={"agent": AGENT_FILE_OP, "action": "reorganize"},
        )
        chat.file_agent.run.return_value = "Which folder would you like?"
        chat.file_agent.get_pending_plan_id.return_value = None
        with patch("gui.chat_tab.threading.Thread",
                   ChatWorkflowTests.ImmediateThread):
            chat.send_chat()
        for cb in callbacks:
            cb()
        chat.file_agent.execute_pending_plan.assert_not_called()
        ChatWorkflowTests().assert_input_restored(chat)

if __name__ == "__main__":
    unittest.main()
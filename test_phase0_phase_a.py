"""Isolated regression tests for immutable plans and agent-aware routing."""

import ast
import hashlib
import json
import os
from pathlib import Path
import sqlite3
import subprocess
import sys
import tempfile
import threading
import unittest
from cryptography.fernet import Fernet
from collections import OrderedDict
from types import SimpleNamespace
from unittest.mock import Mock, patch

from agent.daemon import FileCreationHandler
from agents.file_agent import FileAgent
from agents.supervisor import (
    AGENT_FILE_OP,
    AGENT_PC_CONTROL,
    AGENT_RAG,
    AGENT_GENERAL_CHAT,
    AGENT_UNKNOWN,
    SupervisorAgent,
)
from agents.rag_agent import RAGAgent
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
from tools import migrate_live as migration_cli
from gui.chat_tab import (
    ChatBubble,
    ChatTab,
    HandoffCanvas,
    render_markdown_text,
)
from gui.constellation_view import AGENT_COLORS, ConstellationView
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
        self.assertEqual(chat.after.call_count, 2)
        self.assertTrue(all(call.args[0] == 0 for call in chat.after.call_args_list))
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
        chat.chat_entry.get.side_effect = ["organize this", ""]
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
        chat.chat_entry.insert.assert_called_once_with(0, "organize this")
        self.assert_input_restored(chat)

    def test_unknown_request_uses_hierarchical_delegation(self):
        chat, callbacks = self.make_chat(
            routing={"agent": AGENT_UNKNOWN, "action": "organize this"}
        )
        chat.supervisor.delegate_task.return_value = {
            "response": "Delegated result",
            "error": None,
        }
        with patch("gui.chat_tab.threading.Thread", self.ImmediateThread):
            chat.send_chat()

        chat.supervisor.delegate_task.assert_called_once_with(
            "organize this", ["Foldy", "Scout", "Click", "Syntax"]
        )
        for callback in callbacks:
            callback()
        rendered = [
            call.args[1] for call in chat._add_bubble.call_args_list
            if call.args and call.args[0] == "STEWARD"
        ]
        self.assertTrue(rendered)
        self.assertEqual(rendered[-1], "Delegated result")

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
        chat.chat_entry.get.side_effect = ["organize this", ""]
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
        chat.chat_entry.insert.assert_called_once_with(0, "organize this")
        self.assert_input_restored(chat)

class GUIPresentationTests(unittest.TestCase):
    """Pass 2 regressions for readable, responsive, lifecycle-safe GUI code."""

    def test_markdown_is_rendered_as_readable_plain_text(self):
        rendered = render_markdown_text(
            "## Result\n**Moved** the file\n```json\n{\"ok\": true}\n```"
        )
        self.assertIn("Result", rendered)
        self.assertIn("Moved the file", rendered)
        self.assertIn("[Code block]", rendered)
        self.assertNotIn("**", rendered)
        self.assertNotIn("```", rendered)
        self.assertNotIn('{"ok": true}', rendered)

    def test_chat_animations_cancel_before_destroy(self):
        bubble = ChatBubble.__new__(ChatBubble)
        bubble_tick = Mock()
        bubble._tick = bubble_tick
        with patch("gui.chat_tab.ctk.CTkFrame.destroy"):
            bubble.destroy()
        bubble_tick.cancel.assert_called_once_with()

        handoff = HandoffCanvas.__new__(HandoffCanvas)
        handoff_tick = Mock()
        handoff._tick = handoff_tick
        with patch("gui.chat_tab.ctk.CTkCanvas.destroy"):
            handoff.destroy()
        handoff_tick.cancel.assert_called_once_with()

    def test_provider_status_callback_is_marshalled_to_main_thread(self):
        provider_info = {"provider": "Primary", "model": "model"}
        callbacks = []
        chat = SimpleNamespace(
            supervisor=SimpleNamespace(last_provider=provider_info),
            file_agent=SimpleNamespace(last_provider=None),
            provider_callback=Mock(),
            live_feed=None,
            _safe_after=Mock(side_effect=callbacks.append),
        )

        ChatTab._report_provider(chat, "Cortex")

        chat.provider_callback.assert_not_called()
        self.assertEqual(len(callbacks), 1)
        callbacks[0]()
        chat.provider_callback.assert_called_once_with("Cortex", provider_info)

    def test_activation_failure_keeps_exception_text_after_scope(self):
        settings = SettingsTab.__new__(SettingsTab)
        settings._safe_after = Mock()
        settings._on_activation_failed = Mock()
        with patch(
            "gui.settings_tab.validate_provider",
            side_effect=RuntimeError("provider exploded"),
        ):
            settings._run_provider_activation(
                {"name": "Primary", "base_url": "https://example.test"},
                "key",
                None,
            )

        callback = settings._safe_after.call_args.args[0]
        callback()
        settings._on_activation_failed.assert_called_once_with(
            "Primary", "provider exploded"
        )

    def test_organizer_uses_sanitized_category_and_counts_only_successes(self):
        organizer = OrganizerTab.__new__(OrganizerTab)
        organizer.file_agent = Mock()
        organizer.file_agent.move_file.side_effect = [
            "Error: destination unavailable",
            "Moved file",
        ]
        organizer.gui = None
        organizer.pending_operations = [
            {"filename": "bad.txt", "source": "bad.txt", "destination": "x/bad.txt", "selected": True},
            {"filename": "good.txt", "source": "good.txt", "destination": "x/good.txt", "selected": True},
        ]
        organizer.btn_execute = Mock()
        organizer._log = Mock()
        callbacks = []
        organizer.after = Mock(side_effect=lambda delay, callback: callbacks.append(callback))

        class ImmediateThread:
            def __init__(self, target, daemon=None):
                self.target = target

            def start(self):
                self.target()

        with patch("gui.organizer_tab.messagebox.askyesno", return_value=True), \
             patch("gui.organizer_tab.threading.Thread", ImmediateThread):
            organizer.execute_selected()

        for callback in callbacks:
            callback()
        messages = [call.args[0] for call in organizer._log.call_args_list]
        self.assertTrue(any("1 files moved" in message for message in messages), messages)


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
            with patch.object(FileCreationHandler, "_process_file"):
                handler = FileCreationHandler(Mock(), dest, None)
                try:
                    for i in range(1001):
                        handler.on_created(SimpleNamespace(
                            is_directory=False, src_path=os.path.join(tmp, f"file_{i}.txt")))
                    self.assertIn(os.path.join(tmp, "file_1000.txt"), handler.last_processed)
                    self.assertLessEqual(len(handler.last_processed), 1000)
                finally:
                    handler.stop()

    def test_duplicate_create_event_is_processed_once(self):
        with tempfile.TemporaryDirectory(prefix="steward_dedup_event_") as tmp:
            with patch.object(FileCreationHandler, "_process_file") as process_file:
                handler = FileCreationHandler(Mock(), os.path.join(tmp, "Sorted"), None)
                try:
                    path = os.path.join(tmp, "note.txt")
                    event = SimpleNamespace(is_directory=False, src_path=path)
                    handler.on_created(event)
                    handler.on_created(event)
                    handler._queue.join()
                    self.assertEqual(process_file.call_count, 1)
                finally:
                    handler.stop()

    def test_recreated_path_is_processed_again(self):
        with tempfile.TemporaryDirectory(prefix="steward_recreate_") as tmp:
            with patch.object(FileCreationHandler, "_process_file") as process_file:
                handler = FileCreationHandler(Mock(), os.path.join(tmp, "Sorted"), None)
                try:
                    path = os.path.join(tmp, "note.txt")
                    event = SimpleNamespace(is_directory=False, src_path=path)
                    with patch.object(
                        FileCreationHandler, "_file_identity",
                        side_effect=[("device", 1), ("device", 2)],
                    ):
                        handler.on_created(event)
                        handler.on_created(event)
                    handler._queue.join()
                    self.assertEqual(process_file.call_count, 2)
                finally:
                    handler.stop()

    def test_daemon_has_bounded_worker_and_pending_limits(self):
        self.assertEqual(FileCreationHandler.MAX_WORKERS, 4)
        self.assertEqual(FileCreationHandler.MAX_PENDING_FILES, 32)
        with tempfile.TemporaryDirectory(prefix="steward_daemon_workers_") as tmp:
            handler = FileCreationHandler(Mock(), os.path.join(tmp, "Sorted"), None)
            try:
                self.assertEqual(len(handler._workers), 4)
                self.assertTrue(all(worker.daemon for worker in handler._workers))
                self.assertEqual(handler._queue.maxsize, 32)
            finally:
                handler.stop()

    def test_stop_prevents_new_daemon_work(self):
        with tempfile.TemporaryDirectory(prefix="steward_daemon_stop_") as tmp:
            with patch.object(FileCreationHandler, "_process_file") as process_file:
                handler = FileCreationHandler(Mock(), os.path.join(tmp, "Sorted"), None)
                handler.stop()
                handler.on_created(SimpleNamespace(
                    is_directory=False, src_path=os.path.join(tmp, "note.txt")
                ))
                process_file.assert_not_called()

    def test_organizer_stop_stops_daemon_handler(self):
        organizer = OrganizerTab.__new__(OrganizerTab)
        organizer.observer = Mock()
        organizer.daemon_running = True
        daemon_handler = Mock()
        organizer.daemon_handler = daemon_handler
        organizer.daemon_status_label = Mock()
        organizer._log = Mock()
        organizer.stop_daemon()
        daemon_handler.stop.assert_called_once()
        self.assertFalse(organizer.daemon_running)
        self.assertIsNone(organizer.daemon_handler)

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
        destinations = []

        class RecordingRow:
            def __init__(self, parent, filename, source, destination, on_toggle,
                         *args, **kwargs):
                recorded.append(threading.current_thread().name)
                destinations.append(destination)

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
        self.assertTrue(destinations[0].endswith(os.path.join("Docs", "a.txt")), destinations)

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

    def test_migration_preserves_existing_shared_credential_link(self):
        with tempfile.TemporaryDirectory(prefix="steward_mig_linked_") as tmp:
            db_path = os.path.join(tmp, "test.db")
            key_path = os.path.join(tmp, "test.key")
            db = DatabaseManager(db_path, key_path)

            credential_id = db.set_credential("https://api.shared.com/v1", "shared-key")
            db.add_provider(
                name="SharedProvider",
                base_url="https://api.shared.com/v1",
                api_key="shared-key",
                credential_id=credential_id,
                is_active=True,
            )
            with db._lock:
                db._conn.execute(
                    "UPDATE providers SET api_key_encrypted = NULL WHERE name = ?",
                    ("SharedProvider",),
                )
                db._conn.commit()

            result = migrate_to_shared_credentials(db)
            provider = db.get_provider("SharedProvider")

            self.assertEqual(result["credentials_created"], 0)
            self.assertEqual(provider["credential_id"], credential_id)
            self.assertEqual(provider["api_key"], "shared-key")
            self.assertEqual(len(db.get_all_credentials()), 1)
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

class ConstellationViewTests(unittest.TestCase):
    """The live constellation renders responsively and cleans up animations."""

    def setUp(self):
        import tkinter as tk

        self.root = tk.Tk()
        self.root.withdraw()
        self.widget = ConstellationView(self.root, width=400, height=300)

    def tearDown(self):
        try:
            self.widget.destroy()
        except Exception:
            pass
        try:
            self.root.destroy()
        except Exception:
            pass

    def test_init_and_resize(self):
        self.assertEqual(set(self.widget.nodes), set(AGENT_COLORS))
        self.assertEqual(len(self.widget.edges), 4)
        self.assertTrue(self.widget.bind("<Configure>"))

        before = self.widget.bbox(self.widget.nodes["Cortex"])
        before_center = ((before[0] + before[2]) / 2, (before[1] + before[3]) / 2)

        self.widget._on_resize(SimpleNamespace(width=600, height=400))

        after = self.widget.bbox(self.widget.nodes["Cortex"])
        after_center = ((after[0] + after[2]) / 2, (after[1] + after[3]) / 2)
        self.assertGreater(after_center[0], before_center[0])
        self.assertGreater(after_center[1], before_center[1])
        self.assertAlmostEqual(after_center[0], 300, delta=2)
        self.assertAlmostEqual(after_center[1], 200, delta=2)

    def test_state_transitions(self):
        with patch("gui.constellation_view.SafeTick") as tick_class:
            tick = tick_class.return_value
            tick.start.return_value = tick

            self.widget.update_state("Foldy", "WORKING")

            self.assertEqual(
                self.widget.itemcget(self.widget.nodes["Foldy"], "fill"),
                AGENT_COLORS["Foldy"],
            )
            tick_class.assert_called_once()
            self.assertIs(tick_class.call_args.args[0], self.widget)
            self.assertIn("on_tick", tick_class.call_args.kwargs)

            tick_class.call_args.kwargs["on_tick"]()
            pulsed_color = self.widget.itemcget(
                self.widget.nodes["Foldy"], "fill"
            )
            self.assertNotEqual(pulsed_color, AGENT_COLORS["Foldy"])

    def test_cleanup_on_destroy(self):
        with patch("gui.constellation_view.SafeTick") as tick_class:
            ticks = [Mock(), Mock()]
            tick_class.side_effect = ticks
            for tick in ticks:
                tick.start.return_value = tick

            self.widget.update_state("Foldy", "WORKING")
            self.widget.update_state("Cortex", "WORKING")

            try:
                self.widget.destroy()
            except Exception as exc:
                self.fail(f"destroy raised {exc!r}")

            for tick in ticks:
                tick.cancel.assert_called_once_with()


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
        self.assertEqual(sanitize_category(essay, "C:/x/custom_report.pdf"), "Documents")

    def test_accepts_clean_name_and_strips_illegal_chars(self):
        from utils.helpers import sanitize_category
        self.assertEqual(sanitize_category("Resume_CV", "a.pdf"), "Resume_CV")
        self.assertEqual(sanitize_category("A/B:C*D", "a.pdf"), "ABCD")

    def test_falls_back_by_extension(self):
        from utils.helpers import sanitize_category
        self.assertEqual(sanitize_category("", "photo.PNG"), "Images")
        self.assertEqual(sanitize_category("x" * 200, "a.pdf"), "Documents")

    def test_rejects_windows_reserved_device_names(self):
        from utils.helpers import sanitize_category
        self.assertEqual(sanitize_category("CON", "a.pdf"), "Documents")
        self.assertEqual(sanitize_category("com1.txt", "a.pdf"), "Documents")
        self.assertEqual(sanitize_category("LPT1", "a.pdf"), "Documents")


class SupervisorValidationTests(unittest.TestCase):
    def make_supervisor(self, content):
        manager = Mock()
        manager.route_request.return_value = {
            "choices": [{"message": {"content": content}}]
        }
        return SupervisorAgent(manager)

    def test_rejects_unknown_agent_category(self):
        supervisor = self.make_supervisor(
            '{"agent": "ARBITRARY", "action": "delete files"}'
        )
        result = supervisor.route("delete files")
        self.assertEqual(result, {"agent": AGENT_UNKNOWN, "action": "delete files"})

    def test_rejects_non_text_action(self):
        supervisor = self.make_supervisor(
            '{"agent": "FILE_OP", "action": ["delete", "everything"]}'
        )
        result = supervisor.route("delete everything")
        self.assertEqual(result, {
            "agent": AGENT_UNKNOWN,
            "action": "delete everything",
        })

    def test_accepts_known_category_and_trims_action(self):
        supervisor = self.make_supervisor(
            '{"agent": "FILE_OP", "action": "  organize Incoming  "}'
        )
        result = supervisor.route("organize Incoming")
        self.assertEqual(result, {
            "agent": AGENT_FILE_OP,
            "action": "organize Incoming",
        })


class FileAgentPathSafetyTests(unittest.TestCase):
    def make_agent(self, root):
        log_path = os.path.join(root, "operations.json")
        with patch.object(FileAgent, "OPERATION_LOG_PATH", log_path):
            agent = FileAgent(api_manager=Mock(), root_path=root)
        agent.OPERATION_LOG_PATH = log_path
        return agent

    def test_rename_rejects_path_components(self):
        with tempfile.TemporaryDirectory(prefix="steward_rename_name_") as tmp:
            incoming = os.path.join(tmp, "Incoming")
            os.makedirs(incoming)
            source = os.path.join(incoming, "note.txt")
            with open(source, "w", encoding="utf-8") as handle:
                handle.write("data")
            agent = self.make_agent(tmp)
            result = agent.rename_file(source, os.path.join("..", "Sorted", "note.txt"))
            self.assertIn("without path components", result)
            self.assertTrue(os.path.exists(source))

    def test_delete_refuses_configured_sandbox_root(self):
        with tempfile.TemporaryDirectory(prefix="steward_delete_root_") as tmp:
            incoming = os.path.join(tmp, "Incoming")
            sorted_dir = os.path.join(tmp, "Sorted")
            os.makedirs(incoming)
            os.makedirs(sorted_dir)
            agent = self.make_agent(tmp)
            result = agent.delete_file(incoming)
            self.assertIn("Refusing to delete a configured sandbox root", result)
            self.assertTrue(os.path.isdir(incoming))

    def test_categorise_provider_failure_does_not_move_file(self):
        with tempfile.TemporaryDirectory(prefix="steward_categorise_error_") as tmp:
            incoming = os.path.join(tmp, "Incoming")
            sorted_dir = os.path.join(tmp, "Sorted")
            os.makedirs(incoming)
            os.makedirs(sorted_dir)
            source = os.path.join(incoming, "note.txt")
            with open(source, "w", encoding="utf-8") as handle:
                handle.write("data")
            agent = self.make_agent(tmp)
            agent.api_manager.route_request.side_effect = RuntimeError("provider down")
            agent.move_file = Mock(return_value="Moved")
            result = agent.categorise_file(source, sorted_dir, dry_run=False)
            self.assertIn("Error categorising file: provider down", result)
            agent.move_file.assert_not_called()
            self.assertTrue(os.path.exists(source))


class DatabaseDualReadTests(unittest.TestCase):
    def test_keyless_reference_falls_back_to_valid_legacy_provider_key(self):
        with tempfile.TemporaryDirectory(prefix="steward_dual_read_") as tmp:
            db = DatabaseManager(
                db_path=os.path.join(tmp, "providers.db"),
                key_path=os.path.join(tmp, "providers.key"),
            )
            try:
                credential_id = db.set_credential("https://legacy.example/v1", "")
                db.add_provider(
                    "LegacyProvider",
                    "https://legacy.example/v1",
                    "legacy-key",
                    credential_id=credential_id,
                )
                provider = db.get_provider("LegacyProvider")
                self.assertEqual(provider["api_key"], "legacy-key")
                self.assertIsNone(provider["decryption_error"])
            finally:
                db.close()

    def test_singleton_initialization_is_serialized(self):
        previous_instance = database_module._db_instance
        database_module._db_instance = None
        constructor_entered = threading.Event()
        release_constructor = threading.Event()
        constructor_calls = []
        fake_instance = Mock(db_path="providers.db", key_path="providers.key")

        def fake_constructor(db_path, key_path):
            constructor_calls.append((db_path, key_path))
            constructor_entered.set()
            if not release_constructor.wait(timeout=2):
                raise AssertionError("constructor was not released")
            return fake_instance

        try:
            with patch.object(database_module, "DatabaseManager", side_effect=fake_constructor):
                first = threading.Thread(
                    target=database_module.init_db,
                    args=("providers.db", "providers.key"),
                )
                first.start()
                self.assertTrue(constructor_entered.wait(timeout=2))
                second = threading.Thread(
                    target=database_module.init_db,
                    args=("providers.db", "providers.key"),
                )
                second.start()
                # The global lock must prevent a second constructor from
                # entering while the first one is still in progress.
                self.assertEqual(len(constructor_calls), 1)
                release_constructor.set()
                first.join(timeout=2)
                second.join(timeout=2)
                self.assertFalse(first.is_alive())
                self.assertFalse(second.is_alive())
                self.assertEqual(len(constructor_calls), 1)
                self.assertIs(database_module.get_db(), fake_instance)
        finally:
            release_constructor.set()
            database_module._db_instance = previous_instance


class ChatNoPlanTests(unittest.TestCase):
    def test_clarifying_question_does_not_offer_execution(self):
        chat, callbacks = ChatWorkflowTests().make_chat(
            routing={"agent": AGENT_FILE_OP, "action": "reorganize"},
        )
        chat.file_agent.run.return_value = "Which folder would you like?"
        chat.file_agent.get_pending_plan_id.return_value = None
        with patch("gui.chat_tab.threading.Thread", ChatWorkflowTests.ImmediateThread):
            chat.send_chat()
        for cb in callbacks:
            cb()
        chat.file_agent.execute_pending_plan.assert_not_called()
        ChatWorkflowTests().assert_input_restored(chat)

class SnoopAndFixRegressionTests(unittest.TestCase):
    """Focused contracts for the confirmed Snoop & Fix defects."""

    def test_file_preview_marks_truncated_content(self):
        from agent.tools import read_file_content

        with tempfile.TemporaryDirectory(prefix="steward_truncated_") as tmp:
            source = os.path.join(tmp, "large.txt")
            with open(source, "w", encoding="utf-8") as handle:
                handle.write("A" * 2500)

            result = read_file_content(source)

        self.assertIn("[content truncated", result.lower())
        self.assertTrue(result.startswith("A" * 2000))

    def test_category_sanitizer_handles_non_string_and_invalid_limit(self):
        from utils.helpers import sanitize_category

        self.assertEqual(sanitize_category(None, "photo.png"), "Images")
        self.assertEqual(sanitize_category(123, "report.pdf"), "Documents")
        self.assertEqual(sanitize_category("Reports", "report.pdf", max_len=0), "Documents")
        self.assertEqual(sanitize_category("Reports", "report.pdf", max_len=-1), "Documents")

    def test_supervisor_merges_unambiguous_short_file_follow_up(self):
        manager = Mock()
        manager.route_request.side_effect = [
            {
                "choices": [{"message": {"content": json.dumps({
                    "agent": AGENT_FILE_OP,
                    "action": "organize files by type",
                })}}]
            },
            {
                "choices": [{"message": {"content": json.dumps({
                    "agent": AGENT_FILE_OP,
                    "action": "incoming",
                })}}]
            },
        ]
        supervisor = SupervisorAgent(manager)

        first = supervisor.route("sort my files")
        second = supervisor.route("incoming")

        self.assertEqual(first["action"], "organize files by type")
        self.assertEqual(second["agent"], AGENT_FILE_OP)
        self.assertIn("organize files by type", second["action"].lower())
        self.assertIn("incoming", second["action"].lower())

    def test_supervisor_context_is_instance_local_and_bounded(self):
        manager = Mock()
        manager.route_request.return_value = {
            "choices": [{"message": {"content": json.dumps({
                "agent": AGENT_FILE_OP,
                "action": "organize files",
            })}}]
        }
        first = SupervisorAgent(manager)
        second = SupervisorAgent(manager)

        for _ in range(20):
            first.route("organize files")

        self.assertLessEqual(len(first._conversation), 8)
        self.assertEqual(second._conversation, [])

    def test_chat_hands_resolved_file_action_to_foldy(self):
        chat, callbacks = ChatWorkflowTests().make_chat(
            routing={"agent": AGENT_FILE_OP, "action": "organize Incoming by type"}
        )
        chat.file_agent.run.return_value = "Preview ready"
        chat.file_agent.get_pending_plan_id.return_value = None

        with patch("gui.chat_tab.threading.Thread", ChatWorkflowTests.ImmediateThread):
            chat.send_chat()

        chat.file_agent.run.assert_called_once()
        self.assertEqual(
            chat.file_agent.run.call_args.args[0],
            "organize Incoming by type",
        )
        for callback in callbacks:
            callback()

    def test_organizer_destination_change_invalidates_preview(self):
        organizer = OrganizerTab.__new__(OrganizerTab)
        organizer.watched_var = Mock()
        organizer.dest_var = Mock()
        organizer.dest_var.get.return_value = "Changed"
        row = Mock()
        organizer.preview_rows = [row]
        organizer.pending_operations = [{"selected": True}]
        organizer.btn_execute = Mock()

        organizer._on_preview_paths_changed()

        row.destroy.assert_called_once()
        self.assertEqual(organizer.pending_operations, [])
        organizer.btn_execute.configure.assert_called_with(state="disabled")

    def test_organizer_discards_stale_async_preview(self):
        organizer = OrganizerTab.__new__(OrganizerTab)
        organizer.preview_rows = []
        organizer.pending_operations = []
        organizer.btn_execute = Mock()
        organizer._preview_generation = 2

        organizer._render_preview(
            [("old.txt", "old-source", "old-destination")],
            generation=1,
        )

        self.assertEqual(organizer.pending_operations, [])
        organizer.btn_execute.configure.assert_called_with(state="disabled")

    def test_deleting_credential_invalidates_all_referencing_providers(self):
        with tempfile.TemporaryDirectory(prefix="steward_delete_cred_") as tmp:
            db = DatabaseManager(
                os.path.join(tmp, "test.db"),
                os.path.join(tmp, "test.key"),
            )
            try:
                credential_id = db.set_credential(
                    "https://api.shared.test/v1", "shared-secret"
                )
                db.add_provider(
                    "Primary",
                    "https://api.shared.test/v1",
                    "shared-secret",
                    credential_id=credential_id,
                )
                db.add_provider(
                    "Backup",
                    "https://api.shared.test/v1",
                    "shared-secret",
                    credential_id=credential_id,
                )

                self.assertTrue(db.delete_credential(credential_id))

                for name in ("Primary", "Backup"):
                    provider = db.get_provider(name)
                    self.assertFalse(provider["is_active"])
                    self.assertFalse(provider["api_key"])
                    self.assertIsNone(provider["credential_id"])
                self.assertEqual(db.get_active_providers(), [])
            finally:
                db.close()

    def test_deleting_last_provider_removes_orphan_credential(self):
        with tempfile.TemporaryDirectory(prefix="steward_delete_provider_") as tmp:
            db = DatabaseManager(
                os.path.join(tmp, "test.db"),
                os.path.join(tmp, "test.key"),
            )
            try:
                credential_id = db.set_credential(
                    "https://api.orphan.test/v1", "orphan-secret"
                )
                db.add_provider(
                    "OnlyProvider",
                    "https://api.orphan.test/v1",
                    "orphan-secret",
                    credential_id=credential_id,
                )

                self.assertTrue(db.delete_provider("OnlyProvider"))

                self.assertIsNone(db.get_provider("OnlyProvider"))
                self.assertIsNone(db.get_credential_by_id(credential_id))
            finally:
                db.close()

    def test_deleting_provider_keeps_credential_shared_by_another_provider(self):
        with tempfile.TemporaryDirectory(prefix="steward_shared_credential_") as tmp:
            db = DatabaseManager(
                os.path.join(tmp, "test.db"),
                os.path.join(tmp, "test.key"),
            )
            try:
                credential_id = db.set_credential(
                    "https://api.shared.test/v1", "shared-secret"
                )
                for name in ("Primary", "Backup"):
                    db.add_provider(
                        name,
                        "https://api.shared.test/v1",
                        "shared-secret",
                        credential_id=credential_id,
                    )

                self.assertTrue(db.delete_provider("Primary"))

                self.assertIsNotNone(db.get_credential_by_id(credential_id))
                self.assertIsNotNone(db.get_provider("Backup"))
            finally:
                db.close()

    def test_chat_has_visible_live_feed_clear_control(self):
        source = Path(
            Path(__file__).resolve().parent / "gui" / "chat_tab.py"
        ).read_text(encoding="utf-8-sig")
        self.assertIn("self.btn_clear_feed = ctk.CTkButton(", source)
        self.assertIn('text="Clear"', source)
        self.assertIn("command=self._clear_live_feed", source)

    def test_constellation_uses_both_axes_and_keeps_labels_in_bounds(self):
        import tkinter as tk

        root = tk.Tk()
        root.withdraw()
        try:
            widget = ConstellationView(root, width=400, height=300)
            widget._on_resize(SimpleNamespace(width=800, height=220))

            cortex = widget.bbox(widget.nodes["Cortex"])
            syntax = widget.bbox(widget.nodes["Syntax"])
            scout = widget.bbox(widget.nodes["Scout"])
            scout_label = widget.bbox(widget.labels["Scout"])

            self.assertGreater(cortex[0] - syntax[0], 250)
            self.assertGreater(scout[1] - cortex[1], 40)
            self.assertGreaterEqual(scout[0], 0)
            self.assertLessEqual(scout[2], 800)
            self.assertGreaterEqual(scout_label[1], 0)
            self.assertLessEqual(scout_label[3], 220)
        finally:
            root.destroy()


class SourceIntegrityTests(unittest.TestCase):
    """Guard against accidental duplicate definitions during hand edits."""

    def test_regression_test_classes_are_defined_once(self):
        source = Path(__file__).read_text(encoding="utf-8")
        tree = ast.parse(source)
        class_names = [
            node.name for node in tree.body if isinstance(node, ast.ClassDef)
        ]
        self.assertEqual(class_names.count("CategorySanitizerTests"), 1)
        self.assertEqual(class_names.count("ChatNoPlanTests"), 1)

    def test_categorise_file_method_is_defined_once(self):
        source = (Path(__file__).resolve().parent / "agents" / "file_agent.py").read_text(
            encoding="utf-8"
        )
        self.assertEqual(source.count("def categorise_file("), 1)


class RAGTests(unittest.TestCase):
    """Exercise the isolated ChromaDB ingestion and retrieval pipeline."""

    class LexicalEmbeddingFunction:
        """Small deterministic embedding function for offline regression tests."""

        def __call__(self, input):
            import math
            import re

            vectors = []
            for text in input:
                vector = [0.0] * 64
                tokens = [
                    token for token in re.split(r"[^A-Za-z0-9]+", text.lower())
                    if token
                ]
                for token in tokens:
                    index = int(hashlib.sha256(token.encode()).hexdigest(), 16) % 64
                    vector[index] += 1.0
                norm = math.sqrt(sum(value * value for value in vector)) or 1.0
                vectors.append([value / norm for value in vector])
            return vectors

        def embed_query(self, input):
            return self(input)

        @staticmethod
        def name():
            return "steward_test_lexical"

        @staticmethod
        def build_from_config(config):
            return RAGTests.LexicalEmbeddingFunction()

        def get_config(self):
            return {}

        def default_space(self):
            return "cosine"

    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory(prefix="steward_rag_test_")
        self.index_path = os.path.join(self.temp_dir.name, "rag_index")
        self.agent = RAGAgent(
            persist_directory=self.index_path,
            collection_name="steward_docs",
            embedding_function=self.LexicalEmbeddingFunction(),
        )
        self.addCleanup(self.temp_dir.cleanup)
        self.addCleanup(self.agent.close)

    def test_ingest_and_search(self):
        source = os.path.join(self.temp_dir.name, "known.txt")
        with open(source, "w", encoding="utf-8") as handle:
            handle.write(
                "STEWARD_RAG_TEST_TOKEN_123 is the unique searchable marker. "
                "The remaining text describes a deterministic retrieval test."
            )

        chunk_count = self.agent.ingest_file(source)
        results = self.agent.search("STEWARD RAG TEST")

        self.assertGreaterEqual(chunk_count, 1)
        self.assertTrue(results)
        self.assertIn("STEWARD_RAG_TEST_TOKEN_123", results[0]["content"])
        self.assertEqual(results[0]["source"], os.path.abspath(source))
        self.assertIn("source", results[0])
        self.assertIn("distance", results[0])

    def test_empty_search(self):
        source = os.path.join(self.temp_dir.name, "known.txt")
        with open(source, "w", encoding="utf-8") as handle:
            handle.write("STEWARD_RAG_TEST_TOKEN_123")
        self.agent.ingest_file(source)

        results = self.agent.search("zzzqqxyv unrelated gibberish")

        self.assertTrue(not results or results[0]["distance"] >= 1.0)

    def test_natural_language_search_returns_matching_document(self):
        source = os.path.join(self.temp_dir.name, "custom_report.txt")
        with open(source, "w", encoding="utf-8") as handle:
            handle.write("CUSTOM_REPORT_E2E_TOKEN confirms semantic retrieval works.")
        self.agent.ingest_file(source)

        results = self.agent.search("what is in the custom report", n_results=5)

        self.assertTrue(results)
        self.assertIn("CUSTOM_REPORT_E2E_TOKEN", results[0]["content"])

    def test_emptying_file_removes_stale_chunks(self):
        source = os.path.join(self.temp_dir.name, "emptied.txt")
        with open(source, "w", encoding="utf-8") as handle:
            handle.write("CONTENT_TO_REMOVE")
        self.agent.ingest_file(source)

        with open(source, "w", encoding="utf-8") as handle:
            handle.write("")
        self.agent.ingest_file(source)

        self.assertEqual(self.agent.collection.count(), 0)
        self.assertEqual(self.agent.search("CONTENT REMOVE"), [])

    def test_changed_file_replaces_stale_chunks(self):
        source = os.path.join(self.temp_dir.name, "changing.txt")
        with open(source, "w", encoding="utf-8") as handle:
            handle.write("ORIGINAL_STEWARD_CONTENT")
        self.agent.ingest_file(source)

        with open(source, "w", encoding="utf-8") as handle:
            handle.write("REPLACED_STEWARD_CONTENT")
        self.agent.ingest_file(source)

        results = self.agent.search("REPLACED STEWARD")
        self.assertTrue(results)
        self.assertIn("REPLACED_STEWARD_CONTENT", results[0]["content"])
        self.assertNotIn("ORIGINAL_STEWARD_CONTENT", results[0]["content"])
        self.assertEqual(self.agent.collection.count(), 1)

    def test_chunking_uses_overlap(self):
        chunks = RAGAgent.chunk_text("A" * 600, chunk_size=500, chunk_overlap=50)
        self.assertEqual(len(chunks), 2)
        self.assertEqual(len(chunks[0]), 500)
        self.assertEqual(len(chunks[1]), 150)
        self.assertEqual(chunks[0][-50:], chunks[1][:50])

    def test_ingest_directory_recursively_indexes_supported_files(self):
        nested = os.path.join(self.temp_dir.name, "nested")
        os.makedirs(nested)
        source = os.path.join(nested, "guide.txt")
        with open(source, "w", encoding="utf-8") as handle:
            handle.write("DIRECTORY_RAG_TOKEN")
        with open(os.path.join(nested, "ignored.csv"), "w", encoding="utf-8") as handle:
            handle.write("ignored")

        summary = self.agent.ingest_directory(self.temp_dir.name)

        self.assertEqual(summary["ingested_files"], 1)
        self.assertEqual(summary["ingested_chunks"], 1)
        self.assertEqual(summary["errors"], [])
        results = self.agent.search("DIRECTORY RAG TOKEN")
        self.assertTrue(results)
        self.assertIn("DIRECTORY_RAG_TOKEN", results[0]["content"])

    def test_scout_formats_known_source_and_content(self):
        source = "C:\\docs\\known.txt"
        results = [{
            "source": source,
            "content": "STEWARD_RAG_TEST_TOKEN_123 known snippet",
            "distance": 0.1,
        }]

        message = ChatTab._format_rag_results("known token", results)

        self.assertIn("Search Results for [known token]", message)
        self.assertIn(source, message)
        self.assertIn("STEWARD_RAG_TEST_TOKEN_123", message)

    def test_scout_empty_result_copy(self):
        self.assertEqual(
            ChatTab._format_rag_results("missing", []),
            "No relevant documents found in the knowledge base.",
        )

    def test_chat_scout_searches_and_renders_synthesized_answer(self):
        chat, callbacks = ChatWorkflowTests().make_chat(
            routing={"agent": AGENT_RAG, "action": "semantic search"}
        )
        chat.chat_entry.get.return_value = "STEWARD RAG TEST"
        chat.rag_agent = Mock()
        chat.rag_agent.search.return_value = [{
            "source": "known.txt",
            "content": "STEWARD_RAG_TEST_TOKEN_123",
            "distance": 0.1,
        }]
        chat.supervisor.api_manager.route_request.return_value = {
            "choices": [{
                "message": {
                    "content": "The marker is STEWARD_RAG_TEST_TOKEN_123 (known.txt)."
                }
            }]
        }

        with patch("gui.chat_tab.threading.Thread", ChatWorkflowTests.ImmediateThread):
            chat.send_chat()

        chat.rag_agent.search.assert_called_once_with("semantic search", n_results=5)
        synthesis_request = chat.supervisor.api_manager.route_request.call_args.kwargs
        self.assertEqual(synthesis_request["agent_name"], "Scout")
        self.assertFalse(synthesis_request["require_tools"])
        self.assertIn(
            "STEWARD_RAG_TEST_TOKEN_123",
            synthesis_request["messages"][-1]["content"],
        )
        for callback in callbacks:
            callback()
        rendered = [
            call.args[1] for call in chat._add_bubble.call_args_list
            if call.args and call.args[0] == "STEWARD"
        ]
        self.assertIn("Scout is searching the archives...", rendered)
        scout_bubble = chat._add_bubble.return_value
        scout_bubble.set_message.assert_called_once()
        message = scout_bubble.set_message.call_args.args[0]
        self.assertIn("📚 **Answer:**", message)
        self.assertIn("STEWARD_RAG_TEST_TOKEN_123", message)
        self.assertIn("**Sources:**\n- known.txt", message)

    def test_chat_scout_falls_back_to_formatted_results_when_synthesis_fails(self):
        chat, callbacks = ChatWorkflowTests().make_chat(
            routing={"agent": AGENT_RAG, "action": "semantic search"}
        )
        chat.rag_agent = Mock()
        chat.rag_agent.search.return_value = [{
            "source": "C:\\docs\\known.txt",
            "content": "STEWARD_RAG_TEST_TOKEN_123\nis a searchable marker.",
            "distance": 0.1,
        }]
        chat.supervisor.api_manager.route_request.side_effect = RuntimeError(
            "synthesis unavailable"
        )

        with patch("gui.chat_tab.threading.Thread", ChatWorkflowTests.ImmediateThread):
            with self.assertLogs("gui.chat_tab", level="WARNING"):
                chat.send_chat()

        for callback in callbacks:
            callback()
        message = chat._add_bubble.return_value.set_message.call_args.args[0]
        self.assertIn("🔍 **Search Results:**", message)
        self.assertIn("**known.txt**", message)
        self.assertIn(
            "STEWARD_RAG_TEST_TOKEN_123 is a searchable marker.",
            message,
        )

    def test_chat_scout_ingests_sorted_folder(self):
        with tempfile.TemporaryDirectory(prefix="steward_chat_rag_") as tmp:
            chat, callbacks = ChatWorkflowTests().make_chat(
                routing={"agent": AGENT_RAG, "action": "ingest the Sorted folder"}
            )
            chat.file_agent.root_path = tmp
            chat.rag_agent = Mock()
            chat.rag_agent.ingest_directory.return_value = {
                "files_processed": 2,
                "chunks_created": 7,
            }

            with patch("gui.chat_tab.threading.Thread", ChatWorkflowTests.ImmediateThread):
                chat.send_chat()

            chat.rag_agent.ingest_directory.assert_called_once_with(
                os.path.join(tmp, "Sorted")
            )
            for callback in callbacks:
                callback()
            scout_bubble = chat._add_bubble.return_value
            self.assertIn(
                "Ingested 2 files, created 7 chunks.",
                scout_bubble.set_message.call_args.args[0],
            )

    def test_default_rag_index_is_created_on_first_scout_query(self):
        with tempfile.TemporaryDirectory(prefix="steward_rag_default_") as tmp:
            expected_index = os.path.join(tmp, "rag_index")
            chat = ChatTab.__new__(ChatTab)
            chat.rag_agent = None

            with patch("os.getcwd", return_value=tmp):
                rag_agent = chat._get_rag_agent()

            self.assertIs(rag_agent, chat.rag_agent)
            self.assertTrue(os.path.isdir(expected_index))
            rag_agent.close()

    def test_supervisor_routes_recall_phrases_to_rag(self):
        for phrase in (
            "search my notes",
            "find information about taxes",
            "recall the project decision",
            "what does my file say about launch dates",
            "what is in the custom report",
        ):
            with self.subTest(phrase=phrase):
                manager = Mock()
                manager.route_request.return_value = {
                    "choices": [{"message": {"content": json.dumps({
                        "agent": AGENT_RAG,
                        "action": f"semantic search for {phrase}",
                    })}}]
                }
                supervisor = SupervisorAgent(manager)
                result = supervisor.route(phrase)
                self.assertEqual(result["agent"], AGENT_RAG)

    def test_supervisor_routes_ingestion_phrases_to_rag(self):
        for phrase in (
            "ingest the Sorted folder",
            "index the Sorted folder",
            "learn these documents",
            "remember this document",
            "scan the documents",
            "read all documents",
            "process folder documents",
            "add to knowledge base",
        ):
            with self.subTest(phrase=phrase):
                manager = Mock()
                supervisor = SupervisorAgent(manager)
                result = supervisor.route(phrase)
                self.assertEqual(result["agent"], AGENT_RAG)
                self.assertEqual(result["action"], phrase)
                manager.route_request.assert_not_called()


class MigrationCLITests(unittest.TestCase):
    """Exercise the live CLI only against isolated temporary runtime files."""

    SCRIPT = Path(__file__).resolve().parent / "tools" / "migrate_live.py"
    RUNNER_SCRIPT = Path(__file__).resolve().parent / "tools" / "run_migration.py"

    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory(prefix="steward_migration_cli_")
        self.root = Path(self.temp_dir.name)
        self.db_path = self.root / "steward.db"
        self.key_path = self.root / "secret.key"
        self.backup_dir = self.root / "backups"
        self.appdata = self.root / "appdata"
        db = DatabaseManager(str(self.db_path), str(self.key_path))
        providers = [
            ("SharedOne", "https://shared.example/v1", db._encrypt("key-one")),
            ("SharedTwo", "https://shared.example/v1/", db._encrypt("key-one")),
            ("Other", "https://other.example/v1", db._encrypt("key-two")),
        ]
        with db._lock:
            db._conn.executemany(
                "INSERT INTO providers "
                "(name, base_url, api_key_encrypted, model_name, credential_id) "
                "VALUES (?, ?, ?, 'test-model', NULL)",
                providers,
            )
            db._conn.commit()
        db.close()
        (self.root / "steward_operations.json").write_text("[]\n", encoding="utf-8")

    def tearDown(self):
        self.temp_dir.cleanup()

    def database_hash(self):
        return hashlib.sha256(self.db_path.read_bytes()).hexdigest()

    def run_cli(self, *arguments, confirmation=None):
        environment = os.environ.copy()
        environment["APPDATA"] = str(self.appdata)
        for name in ("CI", "CONTINUOUS_INTEGRATION", "GITHUB_ACTIONS", "TF_BUILD", "BUILD_NUMBER"):
            environment.pop(name, None)
        arguments = [str(argument) for argument in arguments]
        if confirmation is None:
            command = [sys.executable, str(self.SCRIPT), *arguments]
        else:
            wrapper = (
                "import runpy, sys; from unittest.mock import patch; "
                f"sys.argv = {[str(self.SCRIPT), *arguments]!r};\n"
                "with patch.object(sys.stdin, 'isatty', return_value=True), "
                f"patch('builtins.input', return_value={confirmation!r}): "
                f"runpy.run_path({str(self.SCRIPT)!r}, run_name='__main__')"
            )
            command = [sys.executable, "-c", wrapper]
        return subprocess.run(
            command, cwd=self.root, env=environment, capture_output=True,
            text=True, timeout=45,
        )

    def assert_success(self, result):
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_dry_run_does_not_modify_db(self):
        before_hash = self.database_hash()
        result = self.run_cli("--dry-run", "--backup-dir", self.backup_dir)
        self.assert_success(result)
        self.assertIn("DRY RUN complete", result.stdout)
        self.assertEqual(self.database_hash(), before_hash)
        self.assertFalse(self.backup_dir.exists())

    def test_execute_creates_backup_and_migrates(self):
        result = self.run_cli(
            "--execute", "--backup-dir", self.backup_dir, confirmation="MIGRATE"
        )
        self.assert_success(result)
        database_backups = list(self.backup_dir.glob("steward_backup_*.db"))
        manifests = list(self.backup_dir.glob("steward_backup_*_manifest.json"))
        self.assertEqual(len(database_backups), 1)
        self.assertEqual(len(manifests), 1)
        self.assertEqual(len(list(self.backup_dir.glob("steward_backup_*.key"))), 1)
        self.assertEqual(len(list(self.backup_dir.glob("*_operations.json"))), 1)
        manifest = json.loads(manifests[0].read_text(encoding="utf-8"))
        self.assertEqual(set(manifest["files"]), {
            "steward.db", "secret.key", "steward_operations.json",
        })
        for entry in manifest["files"].values():
            backup_path = Path(entry["backup_path"])
            self.assertTrue(backup_path.is_file())
            digest = hashlib.sha256(backup_path.read_bytes()).hexdigest().upper()
            self.assertEqual(digest, entry["sha256"])

        db = DatabaseManager(str(self.db_path), str(self.key_path))
        try:
            providers = db.get_all_providers()
            self.assertEqual(len(providers), 3)
            self.assertTrue(all(p["credential_id"] is not None for p in providers))
            self.assertEqual(len(db.get_all_credentials()), 2)
            self.assertEqual(
                {p["name"]: p["api_key"] for p in providers},
                {"SharedOne": "key-one", "SharedTwo": "key-one", "Other": "key-two"},
            )
        finally:
            db.close()

    def test_rollback_reverses_migration(self):
        migrated = self.run_cli(
            "--execute", "--backup-dir", self.backup_dir, confirmation="MIGRATE"
        )
        self.assert_success(migrated)
        rolled_back = self.run_cli(
            "--rollback", "--backup-dir", self.root / "rollback_backups",
            confirmation="ROLLBACK",
        )
        self.assert_success(rolled_back)
        db = DatabaseManager(str(self.db_path), str(self.key_path))
        try:
            providers = db.get_all_providers()
            self.assertTrue(all(p["credential_id"] is None for p in providers))
            self.assertEqual(
                {p["name"]: p["api_key"] for p in providers},
                {"SharedOne": "key-one", "SharedTwo": "key-one", "Other": "key-two"},
            )
            self.assertEqual(len(db.get_all_credentials()), 2)
        finally:
            db.close()

    def test_legacy_runner_dry_run_delegates_safely(self):
        before_hash = self.database_hash()
        environment = os.environ.copy()
        environment["APPDATA"] = str(self.appdata)
        for name in ("CI", "CONTINUOUS_INTEGRATION", "GITHUB_ACTIONS", "TF_BUILD", "BUILD_NUMBER"):
            environment.pop(name, None)
        result = subprocess.run(
            [sys.executable, str(self.RUNNER_SCRIPT), "--dry-run"],
            cwd=self.root, env=environment, capture_output=True, text=True, timeout=45,
        )
        self.assert_success(result)
        self.assertIn("DRY RUN complete", result.stdout)
        self.assertEqual(self.database_hash(), before_hash)

    def test_dry_run_allows_database_with_only_unlinkable_provider(self):
        db = DatabaseManager(str(self.db_path), str(self.key_path))
        try:
            with db._lock:
                db._conn.execute("DELETE FROM providers")
                db._conn.execute(
                    "INSERT INTO providers "
                    "(name, base_url, api_key_encrypted, model_name, is_local, credential_id) "
                    "VALUES ('Local', 'http://localhost:11434/v1', NULL, 'local', 1, NULL)"
                )
                db._conn.commit()
        finally:
            db.close()
        result = self.run_cli("--dry-run")
        self.assert_success(result)

    def test_missing_key_fails_fast(self):
        self.key_path.unlink()
        result = self.run_cli("--dry-run")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("secret.key is missing", result.stderr)
        self.assertFalse(self.key_path.exists())

    def test_live_confirmation_is_bounded(self):
        logger = Mock()
        with patch.object(migration_cli, "CONFIRMATION_TIMEOUT_SECONDS", 0.05), \
             patch.object(migration_cli.sys.stdin, "isatty", return_value=True), \
             patch("builtins.input", side_effect=lambda prompt: __import__("time").sleep(1)):
            with self.assertRaisesRegex(RuntimeError, "Confirmation timed out"):
                migration_cli.confirm("execute", logger)



class GeneralConversationTests(unittest.TestCase):
    def test_general_chat_routes_to_cortex(self):
        chat, callbacks = ChatWorkflowTests().make_chat(
            routing={"agent": AGENT_GENERAL_CHAT, "action": "hello how are you"},
        )
        chat.supervisor.api_manager = Mock()
        chat.supervisor.api_manager.route_request.return_value = {
            "choices": [{"message": {"content": "I'm doing great! How can I help you organize your files today?"}}],
            "_steward": {"provider": "TestProvider", "model": "test-model"}
        }

        with patch("gui.chat_tab.threading.Thread", ChatWorkflowTests.ImmediateThread):
            chat.send_chat()

        for cb in callbacks:
            cb()

        chat.supervisor.api_manager.route_request.assert_called_once()
        request = chat.supervisor.api_manager.route_request.call_args.kwargs
        self.assertEqual(request["agent_name"], "Cortex")
        self.assertFalse(request["require_tools"])
        self.assertEqual(request["messages"][-1], {"role": "user", "content": "organize this"})
        ChatWorkflowTests().assert_input_restored(chat)

    def test_general_chat_handles_errors_gracefully(self):
        chat, callbacks = ChatWorkflowTests().make_chat(
            routing={"agent": AGENT_GENERAL_CHAT, "action": "test message"},
        )
        chat.supervisor.api_manager = Mock()
        chat.supervisor.api_manager.route_request.side_effect = RuntimeError("API error")

        with patch("gui.chat_tab.threading.Thread", ChatWorkflowTests.ImmediateThread):
            with self.assertLogs("gui.chat_tab", level="ERROR"):
                chat.send_chat()

        for cb in callbacks:
            cb()

        ChatWorkflowTests().assert_input_restored(chat)


class RAGSearchDisplayTests(unittest.TestCase):
    def test_search_returns_formatted_results(self):
        """Verify RAG search returns structured results with source and content."""
        with tempfile.TemporaryDirectory(prefix="steward_rag_display_") as tmp:
            test_file = os.path.join(tmp, "test.txt")
            with open(test_file, "w", encoding="utf-8") as handle:
                handle.write(
                    "STEWARD_RAG_TEST_TOKEN_123 is the unique searchable marker."
                )

            rag = RAGAgent(
                persist_directory=os.path.join(tmp, "rag_index"),
                collection_name="rag_search_display_test",
                embedding_function=RAGTests.LexicalEmbeddingFunction(),
            )
            try:
                rag.ingest_directory(tmp)
                results = rag.search("STEWARD RAG TEST", n_results=1)

                self.assertGreater(len(results), 0)
                self.assertIn("source", results[0])
                self.assertIn("content", results[0])
                self.assertIn("STEWARD_RAG_TEST_TOKEN_123", results[0]["content"])
            finally:
                rag.close()


class RulesEngineTests(unittest.TestCase):
    """Exercise deterministic rules and their LLM-bypass integration."""

    def make_agent(self, root, rules_path):
        log_path = os.path.join(root, "operations.json")
        with patch.object(FileAgent, "OPERATION_LOG_PATH", log_path):
            agent = FileAgent(
                api_manager=Mock(),
                root_path=root,
                rules_path=rules_path,
            )
        agent.OPERATION_LOG_PATH = log_path
        return agent

    def make_workspace(self, tmp, filename):
        incoming = os.path.join(tmp, "Incoming")
        sorted_dir = os.path.join(tmp, "Sorted")
        os.makedirs(incoming)
        os.makedirs(sorted_dir)
        source = os.path.join(incoming, filename)
        with open(source, "w", encoding="utf-8") as handle:
            handle.write("test content")
        return source, sorted_dir

    def test_rule_matches_and_bypasses_llm(self):
        from utils.rules_engine import RulesEngine

        with tempfile.TemporaryDirectory(prefix="steward_rules_bypass_") as tmp:
            rules_path = os.path.join(tmp, "rules.yaml")
            RulesEngine(rules_path).add_rule(
                pattern=".*invoice.*", target="Finance"
            )
            source, sorted_dir = self.make_workspace(tmp, "invoice_123.txt")
            agent = self.make_agent(tmp, rules_path)

            result = agent.categorise_file(source, sorted_dir, dry_run=False)

            agent.api_manager.route_request.assert_not_called()
            self.assertTrue(
                os.path.exists(os.path.join(sorted_dir, "Finance", "invoice_123.txt"))
            )
            self.assertIn("[Rule]", result)
            self.assertTrue(agent.last_categorized_by_rule)
            self.assertEqual(agent.last_rule_pattern, ".*invoice.*")

    def test_no_rule_falls_back_to_llm(self):
        with tempfile.TemporaryDirectory(prefix="steward_rules_fallback_") as tmp:
            rules_path = os.path.join(tmp, "rules.yaml")
            source, sorted_dir = self.make_workspace(tmp, "unknown_file.txt")
            agent = self.make_agent(tmp, rules_path)
            agent.api_manager.route_request.return_value = {
                "choices": [{"message": {"content": "Documents"}}]
            }

            result = agent.categorise_file(source, sorted_dir, dry_run=False)

            agent.api_manager.route_request.assert_called_once()
            self.assertTrue(
                os.path.exists(os.path.join(sorted_dir, "Documents", "unknown_file.txt"))
            )
            self.assertNotIn("[Rule]", result)
            self.assertFalse(agent.last_categorized_by_rule)

    def test_higher_priority_rule_matches_first(self):
        from utils.rules_engine import RulesEngine

        with tempfile.TemporaryDirectory(prefix="steward_rules_priority_") as tmp:
            engine = RulesEngine(os.path.join(tmp, "rules.yaml"))
            engine.add_rule(".*invoice.*", "General", priority=10)
            engine.add_rule("invoice.*", "Finance", priority=200)
            self.assertEqual(engine.match_rule("invoice_123.txt"), "Finance")

    def test_missing_rules_file_is_created_with_empty_structure(self):
        from utils.rules_engine import RulesEngine

        with tempfile.TemporaryDirectory(prefix="steward_rules_missing_") as tmp:
            rules_path = os.path.join(tmp, "rules.yaml")
            engine = RulesEngine(rules_path)
            self.assertTrue(os.path.exists(rules_path))
            self.assertEqual(engine.get_all_rules(), [])
            with open(rules_path, "r", encoding="utf-8") as handle:
                self.assertIn("rules", handle.read())

    def test_learn_override_generates_and_persists_rule(self):
        from utils.rules_engine import RulesEngine

        with tempfile.TemporaryDirectory(prefix="steward_rules_learn_") as tmp:
            rules_path = os.path.join(tmp, "rules.yaml")
            agent = self.make_agent(tmp, rules_path)

            pattern = agent.learn_override(
                "invoice_123.txt", "Documents", "Finance"
            )

            self.assertEqual(pattern, ".*invoice.*")
            self.assertEqual(RulesEngine(rules_path).match_rule("invoice_456.txt"), "Finance")

    def test_rule_target_is_sanitized_before_folder_creation(self):
        from utils.rules_engine import RulesEngine

        with tempfile.TemporaryDirectory(prefix="steward_rules_safe_") as tmp:
            rules_path = os.path.join(tmp, "rules.yaml")
            RulesEngine(rules_path).add_rule(".*unsafe.*", "A/B:C")
            source, sorted_dir = self.make_workspace(tmp, "unsafe.txt")
            agent = self.make_agent(tmp, rules_path)

            agent.categorise_file(source, sorted_dir, dry_run=False)

            self.assertTrue(os.path.exists(os.path.join(sorted_dir, "ABC", "unsafe.txt")))

    def test_delete_rule_removes_and_persists_rule(self):
        from utils.rules_engine import RulesEngine

        with tempfile.TemporaryDirectory(prefix="steward_rules_delete_") as tmp:
            rules_path = os.path.join(tmp, "rules.yaml")
            engine = RulesEngine(rules_path)
            engine.add_rule(".*invoice.*", "Finance")
            engine.add_rule(".*receipt.*", "Finance")

            self.assertTrue(engine.delete_rule(".*invoice.*"))
            self.assertFalse(engine.delete_rule(".*missing.*"))

            persisted = RulesEngine(rules_path).get_all_rules()
            self.assertEqual(len(persisted), 1)
            self.assertEqual(persisted[0]["pattern"], ".*receipt.*")

    def test_organizer_can_add_and_delete_rule(self):
        from utils.rules_engine import RulesEngine

        with tempfile.TemporaryDirectory(prefix="steward_rules_manage_") as tmp:
            rules_path = os.path.join(tmp, "rules.yaml")
            organizer = OrganizerTab.__new__(OrganizerTab)
            organizer.file_agent = Mock()
            organizer.file_agent.rules_path = rules_path
            organizer._refresh_rules_list = Mock()

            self.assertTrue(organizer._submit_add_rule(".*invoice.*", "Finance"))
            self.assertEqual(
                RulesEngine(rules_path).get_all_rules()[0]["target"],
                "Finance",
            )
            organizer._refresh_rules_list.assert_called_once()

            self.assertTrue(organizer._delete_rule(".*invoice.*"))
            self.assertEqual(RulesEngine(rules_path).get_all_rules(), [])
            self.assertEqual(organizer._refresh_rules_list.call_count, 2)

    def test_organizer_rules_button_lists_current_rules(self):
        from utils.rules_engine import RulesEngine

        organizer = OrganizerTab.__new__(OrganizerTab)
        organizer.file_agent = Mock()
        organizer.file_agent.rules_path = os.path.join(
            tempfile.gettempdir(), "steward_rules_ui_test.yaml"
        )
        RulesEngine(organizer.file_agent.rules_path).add_rule(
            ".*invoice.*", "Finance"
        )
        try:
            with patch("gui.organizer_tab.messagebox.showinfo") as showinfo:
                organizer.show_rules()
            showinfo.assert_called_once()
            self.assertIn(".*invoice.*", showinfo.call_args.args[1])
            self.assertIn("Finance", showinfo.call_args.args[1])
        finally:
            if os.path.exists(organizer.file_agent.rules_path):
                os.remove(organizer.file_agent.rules_path)

    def test_clear_chat_destroys_all_chat_children(self):
        chat = ChatTab.__new__(ChatTab)
        chat.chat_display = Mock()
        children = [Mock(), Mock(), Mock()]
        chat.chat_display.winfo_children.return_value = children

        chat.clear_chat()

        for child in children:
            child.destroy.assert_called_once()

    def test_chat_append_marks_rule_categorization(self):
        chat = ChatTab.__new__(ChatTab)
        chat.file_agent = Mock()
        chat.file_agent.last_categorized_by_rule = True
        chat._add_bubble = Mock()

        chat.append_chat("STEWARD", "Moved invoice_123.txt")

        self.assertEqual(
            chat._add_bubble.call_args.args[1],
            "[Rule] Moved invoice_123.txt",
        )


class MarkdownRenderingTests(unittest.TestCase):
    """Markdown syntax is converted to readable plain text for chat bubbles."""

    def test_strip_markdown_removes_headers(self):
        from gui.chat_tab import strip_markdown

        self.assertEqual(strip_markdown("# Header"), "Header")

    def test_strip_markdown_removes_bold(self):
        from gui.chat_tab import strip_markdown

        self.assertEqual(strip_markdown("**bold**"), "bold")

    def test_strip_markdown_removes_code_blocks(self):
        from gui.chat_tab import strip_markdown

        result = strip_markdown("```python\nprint('hi')\n```")
        self.assertEqual(result, "[Code block]")

    def test_strip_markdown_removes_italic_and_inline_code(self):
        from gui.chat_tab import strip_markdown

        self.assertEqual(strip_markdown("*italic* and `code`"), "italic and code")

    def test_strip_markdown_flattens_links_and_images(self):
        from gui.chat_tab import strip_markdown

        self.assertEqual(strip_markdown("[docs](https://example.com)"), "docs")
        self.assertEqual(
            strip_markdown("![diagram](diagram.png)"),
            "[Image: diagram]",
        )

    def test_strip_markdown_removes_blockquotes_and_horizontal_rules(self):
        from gui.chat_tab import strip_markdown

        self.assertEqual(strip_markdown("> quoted"), "quoted")
        self.assertEqual(strip_markdown("---"), "---")

    def test_add_bubble_cleans_message_before_rendering(self):
        chat = ChatTab.__new__(ChatTab)
        chat.chat_display = Mock()
        chat.after_idle = Mock()
        chat._scroll_chat = Mock()

        with patch("gui.chat_tab.ChatBubble") as bubble_class:
            chat._add_bubble("STEWARD", "**Done**", "#FFFFFF")

        bubble_class.assert_called_once_with(
            chat.chat_display, "STEWARD", "Done", "#FFFFFF", "left", "NORMAL"
        )



class HierarchicalSwarmTests(unittest.TestCase):
    """Cortex can break down and delegate work to specialist handlers."""

    @staticmethod
    def provider_response(content):
        return {"choices": [{"message": {"content": content}}]}

    def test_delegate_task_returns_results(self):
        manager = Mock()
        manager.route_request.side_effect = [
            self.provider_response(json.dumps([
                {"agent": "Foldy", "task": "Preview incoming files"},
                {"agent": "Scout", "task": "Search project documents"},
            ])),
            self.provider_response("Combined specialist result"),
        ]
        supervisor = SupervisorAgent(manager)
        foldy = Mock(return_value="Dry-run preview ready")
        scout = Mock(return_value="Three relevant documents found")
        supervisor.register_sub_agent("Foldy", foldy)
        supervisor.register_sub_agent("Scout", scout)

        result = supervisor.delegate_task(
            "Organize the files and search for project documents",
            ["Foldy", "Scout", "Click", "Syntax"],
        )

        self.assertEqual(result["response"], "Combined specialist result")
        self.assertEqual(len(result["tasks"]), 2)
        self.assertEqual(len(result["results"]), 2)
        self.assertFalse(any(item["error"] for item in result["results"]))
        foldy.assert_called_once_with("Preview incoming files")
        scout.assert_called_once_with("Search project documents")
        self.assertEqual(manager.route_request.call_count, 2)
        self.assertEqual(
            manager.route_request.call_args_list[0].kwargs["agent_name"],
            "Cortex",
        )

    def test_delegate_task_isolates_specialist_failure(self):
        manager = Mock()
        manager.route_request.side_effect = [
            self.provider_response(json.dumps([
                {"agent": "Foldy", "task": "Preview files"},
                {"agent": "Scout", "task": "Search documents"},
            ])),
            self.provider_response("Partial result"),
        ]
        supervisor = SupervisorAgent(manager)
        supervisor.register_sub_agent(
            "Foldy", Mock(side_effect=RuntimeError("worker failed"))
        )
        scout = Mock(return_value="Search completed")
        supervisor.register_sub_agent("Scout", scout)

        result = supervisor.delegate_task("Complex request", ["Foldy", "Scout"])

        self.assertTrue(result["results"][0]["error"])
        self.assertFalse(result["results"][1]["error"])
        scout.assert_called_once_with("Search documents")

    def test_multi_specialist_request_routes_to_delegation(self):
        manager = Mock()
        supervisor = SupervisorAgent(manager)

        result = supervisor.route(
            "Organize the files and search for documents about project X"
        )

        self.assertEqual(result["agent"], AGENT_UNKNOWN)
        manager.route_request.assert_not_called()



    def test_delegate_task_bounds_number_of_workers(self):
        manager = Mock()
        breakdown = [
            {"agent": "Syntax", "task": f"Task {index}"}
            for index in range(12)
        ]
        manager.route_request.side_effect = [
            self.provider_response(json.dumps(breakdown)),
            self.provider_response("Bounded result"),
        ]
        supervisor = SupervisorAgent(manager)
        syntax = Mock(return_value="Code task complete")
        supervisor.register_sub_agent("Syntax", syntax)

        result = supervisor.delegate_task("Complex request", ["Syntax"])

        self.assertEqual(len(result["tasks"]), 8)
        self.assertEqual(syntax.call_count, 8)



class ScheduledScannerTests(unittest.TestCase):
    """Scheduled scans process Incoming files in an isolated sandbox."""

    def test_scanner_processes_files(self):
        from agent.daemon import ScheduledScanner

        with tempfile.TemporaryDirectory(prefix="steward_scheduled_scan_") as tmp:
            incoming = os.path.join(tmp, "Incoming")
            sorted_dir = os.path.join(tmp, "Sorted")
            os.makedirs(incoming)
            os.makedirs(sorted_dir)
            source = os.path.join(incoming, "report.txt")
            with open(source, "w", encoding="utf-8") as handle:
                handle.write("scheduled scan test")

            file_agent = Mock()
            file_agent.root_path = tmp

            def categorise(filepath, destination, dry_run=None):
                self.assertFalse(dry_run)
                category_dir = os.path.join(destination, "Documents")
                os.makedirs(category_dir, exist_ok=True)
                target = os.path.join(category_dir, os.path.basename(filepath))
                os.replace(filepath, target)
                return f"Moved '{filepath}' to '{target}'"

            file_agent.categorise_file.side_effect = categorise
            scanner = ScheduledScanner(file_agent, interval_minutes=1)

            self.assertTrue(scanner.start())
            summary = scanner._scan()
            scanner.stop()

            self.assertEqual(summary["processed"], 1)
            self.assertEqual(summary["failed"], 0)
            self.assertFalse(os.path.exists(source))
            self.assertTrue(os.path.exists(
                os.path.join(sorted_dir, "Documents", "report.txt")
            ))
            file_agent.categorise_file.assert_called_once_with(
                source, sorted_dir, dry_run=False
            )
            self.assertFalse(scanner.running)
            self.assertIsNotNone(scanner.last_scan_time)

    def test_scanner_rejects_invalid_interval(self):
        from agent.daemon import ScheduledScanner

        with self.assertRaises(ValueError):
            ScheduledScanner(Mock(), interval_minutes=0)

    def test_schedule_state_survives_restart(self):
        class Value:
            def __init__(self, value):
                self.value = value

            def get(self):
                return self.value

            def set(self, value):
                self.value = value

        with tempfile.TemporaryDirectory(prefix="steward_schedule_state_") as tmp:
            state_path = os.path.join(tmp, "scheduled_scan.json")
            organizer = OrganizerTab.__new__(OrganizerTab)
            organizer._schedule_state_path = state_path
            organizer.schedule_enabled_var = Value(True)
            organizer.schedule_interval_var = Value("30 min")
            organizer._last_scheduled_scan_time = "2026-11-23T12:00:00"

            self.assertTrue(organizer._save_schedule_state())

            restored = OrganizerTab.__new__(OrganizerTab)
            restored._schedule_state_path = state_path
            restored.schedule_enabled_var = Value(False)
            restored.schedule_interval_var = Value("1 hr")
            restored._last_scheduled_scan_time = None
            restored._load_schedule_state()

            self.assertTrue(restored.schedule_enabled_var.get())
            self.assertEqual(restored.schedule_interval_var.get(), "30 min")
            self.assertEqual(
                restored._last_scheduled_scan_time,
                "2026-11-23T12:00:00",
            )

    def test_organizer_exposes_scheduled_scan_controls(self):
        source = (
            Path(__file__).resolve().parent / "gui" / "organizer_tab.py"
        ).read_text(encoding="utf-8")
        self.assertIn("Enable Scheduled Scan", source)
        self.assertIn("schedule_interval_dropdown", source)
        self.assertIn("schedule_status_label", source)

        dropdown_start = source.index("self.schedule_interval_dropdown =")
        dropdown_end = source.index(".pack(", dropdown_start)
        dropdown_source = source[dropdown_start:dropdown_end]
        self.assertNotIn("hover_color", dropdown_source)



class ChatBubbleTextTests(unittest.TestCase):
    """Chat bubbles use a wrapping text widget and support dynamic updates."""

    class FakeTextbox:
        def __init__(self, *args, **kwargs):
            self.state = kwargs.get("state")
            self.content = ""

        def configure(self, **kwargs):
            if "state" in kwargs:
                self.state = kwargs["state"]

        def insert(self, index, text):
            self.content = text

        def delete(self, start, end):
            self.content = ""

        def get(self, start, end):
            return self.content

        def pack(self, *args, **kwargs):
            pass

        def bind(self, *args, **kwargs):
            pass

        def after_idle(self, callback):
            pass

    def make_bubble(self, message):
        bubble = ChatBubble.__new__(ChatBubble)
        bubble.sender = "Test"
        bubble.color = "#FFFFFF"
        bubble.align = "left"
        bubble.pack = Mock()

        textbox = self.FakeTextbox()
        with patch("gui.chat_tab.ctk.CTkFrame"), \
             patch("gui.chat_tab.ctk.CTkLabel"), \
             patch("gui.chat_tab.ctk.CTkTextbox", return_value=textbox) as textbox_class:
            bubble.build(message)

        self.assertEqual(textbox_class.call_args.kwargs["wrap"], "word")
        return bubble, textbox

    def test_bubble_text_widget_created(self):
        """Verify ChatBubble uses a Text widget for proper wrapping."""
        bubble, _ = self.make_bubble("A" * 1000)
        self.assertTrue(hasattr(bubble, "msg_text"))
        self.assertFalse(hasattr(bubble, "msg_label"))

    def test_set_message_updates_text_widget(self):
        """Verify set_message() works with the new Text widget."""
        bubble, textbox = self.make_bubble("Initial message")
        bubble.set_message("Updated message")
        content = textbox.get("1.0", "end").strip()
        self.assertEqual(content, "Updated message")
        self.assertEqual(textbox.state, "disabled")


if __name__ == "__main__":
    unittest.main()
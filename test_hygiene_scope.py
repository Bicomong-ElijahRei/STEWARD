"""Focused HYG-1 regressions for removed desktop-control routing surfaces."""

import json
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from agents import supervisor as supervisor_module
from agents.supervisor import SupervisorAgent


ROOT = Path(__file__).resolve().parent
LEGACY_CATEGORY = "PC_" + "CONTROL"


class RemovedScopeTests(unittest.TestCase):
    """The removed capability has no active persona or executable route."""

    def test_active_registries_exclude_removed_persona(self):
        from agents.agent_config import AGENT_CONFIG, AGENT_ROUTING_KEYS
        from gui.settings_tab import SettingsTab

        self.assertNotIn("Click", AGENT_CONFIG)
        self.assertNotIn(LEGACY_CATEGORY, AGENT_ROUTING_KEYS)
        self.assertNotIn("Click", SettingsTab.AGENT_CHOICES)

    def test_active_source_excludes_legacy_category_token(self):
        source_paths = [
            *(ROOT / "agents").glob("*.py"),
            *(ROOT / "gui").glob("*.py"),
            *(ROOT / "core").glob("*.py"),
        ]
        offenders = [
            str(path.relative_to(ROOT))
            for path in source_paths
            if LEGACY_CATEGORY in path.read_text(encoding="utf-8-sig")
        ]
        self.assertEqual([], offenders)

    def test_removed_agent_skeleton_is_not_tracked(self):
        self.assertFalse((ROOT / "agents" / "pc_agent.py").exists())

    def test_legacy_model_category_becomes_truthful_out_of_scope(self):
        manager = Mock()
        manager.route_request.return_value = {
            "choices": [{
                "message": {
                    "content": json.dumps({
                        "agent": LEGACY_CATEGORY,
                        "action": "open an application",
                    }),
                },
            }],
        }
        supervisor = SupervisorAgent(manager)

        result = supervisor.route("open an application")

        self.assertEqual("OUT_OF_SCOPE", result["agent"])
        self.assertEqual("open an application", result["action"])

    def test_arbitrary_model_category_remains_unknown(self):
        manager = Mock()
        manager.route_request.return_value = {
            "choices": [{
                "message": {
                    "content": json.dumps({
                        "agent": "ARBITRARY",
                        "action": "do something",
                    }),
                },
            }],
        }
        supervisor = SupervisorAgent(manager)

        result = supervisor.route("do something")

        self.assertEqual("UNKNOWN", result["agent"])

    def test_out_of_scope_chat_request_is_truthful_and_not_delegated(self):
        from gui.chat_tab import ChatTab

        chat = ChatTab.__new__(ChatTab)
        chat._processing = False
        chat.winfo_exists = Mock(return_value=True)
        chat.chat_entry = Mock()
        chat.chat_entry.get.return_value = "open an application"
        chat.send_btn = Mock()
        chat._add_bubble = Mock()
        chat.live_feed = Mock()
        chat.provider_callback = None
        chat.supervisor = Mock()
        chat.supervisor.route.return_value = {
            "agent": "OUT_OF_SCOPE",
            "action": "open an application",
        }
        chat.file_agent = Mock()
        chat._report_provider = Mock(return_value="")
        chat.handoff_canvas = Mock()
        callbacks = []
        chat.after = Mock(
            side_effect=lambda delay, callback: callbacks.append(callback)
        )

        class ImmediateThread:
            def __init__(self, target, daemon):
                self.target = target

            def start(self):
                self.target()

        with patch("gui.chat_tab.threading.Thread", ImmediateThread):
            chat.send_chat()
        for callback in callbacks:
            callback()

        chat.supervisor.delegate_task.assert_not_called()
        rendered = [
            call.args[1]
            for call in chat._add_bubble.call_args_list
            if call.args and call.args[0] == "STEWARD"
        ]
        self.assertTrue(any("outside" in message.lower() for message in rendered))
        self.assertTrue(any("no action" in message.lower() for message in rendered))


if __name__ == "__main__":
    unittest.main()

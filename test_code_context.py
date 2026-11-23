"""Regression tests for the bounded, read-only code-context index."""

import hashlib
import math
import os
import re
import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import Mock, patch


class DeterministicEmbeddingFunction:
    """Offline embedding function matching the existing RAG test approach."""

    def __call__(self, input):
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
        return "steward_code_test_lexical"

    @staticmethod
    def build_from_config(config):
        return DeterministicEmbeddingFunction()

    def get_config(self):
        return {}

    def default_space(self):
        return "cosine"


class CodeIndexAgentTests(unittest.TestCase):
    """Exercise the isolated persistent CODE collection."""

    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory(prefix="steward_code_index_")
        self.project_root = Path(self.temp_dir.name) / "project"
        self.project_root.mkdir()
        self.index_path = Path(self.temp_dir.name) / "rag_index"
        from agents.code_index_agent import CodeIndexAgent

        self.agent = CodeIndexAgent(
            persist_directory=str(self.index_path),
            collection_name="steward_code",
            embedding_function=DeterministicEmbeddingFunction(),
            max_files=20,
            max_file_bytes=4096,
            chunk_size=800,
            chunk_overlap=100,
        )
        self.addCleanup(self.temp_dir.cleanup)
        self.addCleanup(self.agent.close)

    def write(self, relative_path, content):
        path = self.project_root / relative_path
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
        return path

    def index(self):
        return self.agent.index_project(str(self.project_root))

    def test_denylisted_paths_are_never_opened_or_indexed(self):
        allowed = self.write("allowed.py", "def allowed_symbol():\n    return 1\n")
        denied_files = [
            self.write(".env", "DENIED_ENV_TOKEN=secret\n"),
            self.write("secret.key", "DENIED_KEY_TOKEN\n"),
            self.write("steward_operations.json", '{"DENIED_JSON_TOKEN": true}\n'),
            self.write("config.db", "DENIED_DB_TOKEN\n"),
            self.write("credentials.key", "DENIED_KEY_EXT_TOKEN\n"),
        ]
        denied_directories = [
            self.write(".git/config", "DENIED_GIT_TOKEN\n"),
            self.write("venv/package.py", "DENIED_VENV_TOKEN\n"),
            self.write("__pycache__/cached.py", "DENIED_CACHE_TOKEN\n"),
            self.write("node_modules/dependency.py", "DENIED_NODE_TOKEN\n"),
            self.write("rag_index/cached.py", "DENIED_RAG_INDEX_TOKEN\n"),
            self.write("media/image.py", "DENIED_MEDIA_TOKEN\n"),
        ]

        with patch("builtins.open", wraps=open) as open_spy:
            summary = self.index()

        opened_names = {
            str(Path(str(call.args[0])).resolve()).lower()
            for call in open_spy.call_args_list
            if call.args
        }
        for path in denied_files + denied_directories:
            self.assertNotIn(str(path.resolve()).lower(), opened_names)
        self.assertEqual(summary["files_processed"], 1)
        self.assertEqual(summary["files_indexed"], 1)
        self.assertEqual(self.agent.search("DENIED", n_results=20), [])
        self.assertTrue(self.agent.search("allowed_symbol", n_results=5))
        self.assertTrue(allowed.exists())

    def test_symlink_or_junction_escape_is_refused_before_read(self):
        outside = Path(self.temp_dir.name) / "outside"
        outside.mkdir()
        outside_file = outside / "escaped.py"
        outside_file.write_text("def escaped_symbol():\n    return 'DENIED_ESCAPE'\n", encoding="utf-8")
        link = self.project_root / "linked"
        created = False
        try:
            try:
                os.symlink(str(outside), str(link), target_is_directory=True)
                created = True
            except (OSError, NotImplementedError):
                link.unlink(missing_ok=True)
                import subprocess

                result = subprocess.run(
                    ["cmd", "/c", "mklink", "/J", str(link), str(outside)],
                    capture_output=True,
                    text=True,
                    timeout=10,
                )
                created = result.returncode == 0

            if not created:
                self.skipTest("This host cannot create a directory symlink or junction")

            with patch("builtins.open", wraps=open) as open_spy:
                summary = self.index()

            opened_names = {
                str(Path(str(call.args[0])).resolve()).lower()
                for call in open_spy.call_args_list
                if call.args
            }
            self.assertNotIn(str(outside_file.resolve()).lower(), opened_names)
            self.assertTrue(summary["refused_paths"])
            self.assertEqual(self.agent.search("escaped_symbol", n_results=5), [])
        finally:
            if link.exists():
                try:
                    os.rmdir(str(link))
                except OSError:
                    try:
                        link.unlink()
                    except OSError:
                        pass

    def test_changed_file_replaces_deleted_file_removes_and_reindex_is_idempotent(self):
        source = self.write("service.py", "def changed_symbol():\n    return 'ORIGINAL_TOKEN'\n")
        first = self.index()
        self.assertEqual(first["files_indexed"], 1)

        second = self.index()
        self.assertEqual(second["files_unchanged"], 1)
        self.assertEqual(second["files_indexed"], 0)
        self.assertEqual(self.agent.collection.count(), first["chunks_created"])

        source.write_text(
            "def changed_symbol():\n    return 'REPLACED_TOKEN'\n",
            encoding="utf-8",
        )
        third = self.index()
        self.assertEqual(third["files_updated"], 1)
        results = self.agent.search("REPLACED_TOKEN", n_results=5)
        self.assertTrue(results)
        self.assertEqual(results[0]["relative_path"], "service.py")
        self.assertEqual(self.agent.search("ORIGINAL_TOKEN", n_results=5), [])

        source.unlink()
        fourth = self.index()
        self.assertEqual(fourth["files_deleted"], 1)
        self.assertEqual(self.agent.collection.count(), 0)

    def test_known_symbol_retrieval_returns_path_lines_symbol_and_bounded_k(self):
        self.write(
            "pkg/service.py",
            "def known_symbol(value):\n"
            "    '''Known test symbol.'''\n"
            "    return value + 1\n"
            "\n"
            "def another_symbol():\n"
            "    return 2\n",
        )
        self.index()

        results = self.agent.search("known_symbol", n_results=1)

        self.assertEqual(len(results), 1)
        self.assertEqual(results[0]["relative_path"], "pkg/service.py")
        self.assertEqual(results[0]["start_line"], 1)
        self.assertEqual(results[0]["end_line"], 3)
        self.assertEqual(results[0]["symbol"], "known_symbol")
        self.assertIn("known_symbol", results[0]["content"])
        self.assertEqual(len(self.agent.search("symbol", n_results=1)), 1)

    def test_multiple_roots_are_isolated_by_root_and_relative_path(self):
        first_root = Path(self.temp_dir.name) / "first"
        second_root = Path(self.temp_dir.name) / "second"
        first_root.mkdir()
        second_root.mkdir()
        (first_root / "service.py").write_text(
            "def first_symbol():\n    return 'FIRST_TOKEN'\n", encoding="utf-8"
        )
        (second_root / "service.py").write_text(
            "def second_symbol():\n    return 'SECOND_TOKEN'\n", encoding="utf-8"
        )

        self.agent.index_project(str(first_root))
        self.agent.index_project(str(second_root))

        second_results = self.agent.search(
            "SECOND_TOKEN", n_results=5, root=str(second_root)
        )
        self.assertTrue(second_results)
        self.assertEqual(second_results[0]["relative_path"], "service.py")
        self.assertEqual(
            self.agent.search(
                "SECOND_TOKEN", n_results=5, root=str(first_root)
            ),
            [],
        )

    def test_non_python_fallback_reports_source_line_range(self):
        self.write("notes.txt", "alpha\nbravo\ncharlie\n")
        self.index()

        results = self.agent.search("bravo", n_results=1)
        self.assertTrue(results)
        self.assertEqual(results[0]["relative_path"], "notes.txt")
        self.assertGreaterEqual(results[0]["start_line"], 1)
        self.assertGreaterEqual(results[0]["end_line"], results[0]["start_line"])

    def test_status_and_clear_report_collection_state(self):
        self.write("one.py", "def one():\n    return 1\n")
        self.index()

        status = self.agent.status()
        self.assertEqual(status["files"], 1)
        self.assertGreaterEqual(status["chunks"], 1)

        self.assertGreaterEqual(self.agent.clear(), 1)
        self.assertEqual(self.agent.status()["files"], 0)
        self.assertEqual(self.agent.status()["chunks"], 0)


    def test_indexing_is_read_only_and_enforces_deterministic_bounds(self):
        source = self.write(
            "large.py",
            "def bounded_symbol():\n" + "    # padding\n" * 1000,
        )
        second = self.write("second.py", "def second_symbol():\n    return 2\n")
        before = {
            path: hashlib.sha256(path.read_bytes()).hexdigest()
            for path in (source, second)
        }

        self.agent.max_files = 1
        summary = self.index()

        after = {
            path: hashlib.sha256(path.read_bytes()).hexdigest()
            for path in (source, second)
        }
        self.assertEqual(before, after)
        self.assertEqual(summary["files_processed"], 1)
        self.assertTrue(summary["file_limit_reached"])
        self.assertEqual(summary["max_files"], 1)
        self.assertEqual(summary["max_file_bytes"], 4096)
        self.assertTrue(summary["truncated_files"])
        truncation = summary["truncated_files"][0]
        self.assertEqual(truncation["relative_path"], "large.py")
        self.assertEqual(truncation["indexed_bytes"], 4096)
        self.assertGreater(truncation["original_bytes"], 4096)

    def test_pre_cancelled_index_does_not_read_files(self):
        source = self.write("cancelled.py", "def cancelled_symbol():\n    return 1\n")
        cancel_event = threading.Event()
        cancel_event.set()

        with patch("builtins.open", wraps=open) as open_spy:
            summary = self.agent.index_project(
                str(self.project_root), cancel_event=cancel_event
            )

        opened_names = {
            str(Path(str(call.args[0])).resolve()).lower()
            for call in open_spy.call_args_list
            if call.args
        }
        self.assertNotIn(str(source.resolve()).lower(), opened_names)
        self.assertTrue(summary["cancelled"])
        self.assertEqual(summary["files_processed"], 0)


class SyntaxCodeContextTests(unittest.TestCase):
    """Verify bounded context does not weaken Syntax's text-only boundary."""

    def setUp(self):
        from agents.coding_agent import CodingAgent

        self.manager = Mock()
        self.manager.route_request.return_value = {
            "choices": [{"message": {"content": "context-aware answer"}}],
            "_steward": {"provider": "CodeProvider", "model": "code-model"},
        }
        self.agent = CodingAgent(api_manager=self.manager)

    def test_context_is_attached_to_bounded_text_only_prompt(self):
        result = self.agent.handle_request(
            "explain known_symbol",
            code_context=[{
                "relative_path": "pkg/service.py",
                "start_line": 10,
                "end_line": 12,
                "symbol": "known_symbol",
                "content": "def known_symbol():\n    return 1\n",
            }],
        )

        self.assertEqual(result, "context-aware answer")
        request = self.manager.route_request.call_args.kwargs
        prompt = request["messages"][-1]["content"]
        self.assertIn("Retrieved code context", prompt)
        self.assertIn("pkg/service.py:10-12", prompt)
        self.assertIn("known_symbol", prompt)
        self.assertEqual(request["agent_name"], "Syntax")
        self.assertFalse(request["require_tools"])
        self.assertNotIn("tools", request)
        self.assertTrue(
            all(message["role"] in ("system", "user") for message in request["messages"])
        )

    def test_no_index_context_leaves_existing_prompt_unchanged(self):
        self.agent.handle_request("write a parser")
        request = self.manager.route_request.call_args.kwargs
        prompt = request["messages"][-1]["content"]

        self.assertNotIn("Retrieved code context", prompt)
        self.assertIn("Task: write a parser", prompt)
        self.assertIn("Original request:", prompt)

    def test_hostile_tool_bearing_response_is_still_rejected(self):
        self.manager.route_request.return_value = {
            "choices": [{
                "message": {
                    "content": None,
                    "tool_calls": [{
                        "type": "function",
                        "function": {"name": "delete_file"},
                    }],
                },
            }],
        }

        with self.assertRaisesRegex(ValueError, "unsupported tool call"):
            self.agent.handle_request("write a parser")


class ChatCodeIndexLifecycleTests(unittest.TestCase):
    """Verify chat clear/cancel prevents stale index UI continuations."""

    def make_chat(self):
        from gui.chat_tab import ChatTab

        chat = ChatTab.__new__(ChatTab)
        chat.chat_display = Mock()
        chat.chat_display.winfo_children.return_value = []
        chat._general_chat_history = []
        chat._conversation_epoch = 0
        chat._code_index_epoch = 0
        chat._code_index_cancel = threading.Event()
        chat._code_index_thread = None
        chat._code_index_agent = Mock()
        chat.file_agent = Mock()
        chat.send_btn = Mock()
        chat.chat_entry = Mock()
        return chat

    def test_clear_chat_cancels_indexing_and_invalidates_stale_continuations(self):
        chat = self.make_chat()
        chat._code_index_cancel.set()

        chat.clear_chat()

        self.assertTrue(chat._code_index_cancel.is_set())
        self.assertEqual(chat._code_index_epoch, 1)
        self.assertEqual(chat._conversation_epoch, 1)
        self.assertFalse(chat._code_index_is_current(0, 0))

    def test_current_index_generation_is_accepted(self):
        chat = self.make_chat()
        self.assertTrue(chat._code_index_is_current(0, 0))


if __name__ == "__main__":
    unittest.main(verbosity=2)

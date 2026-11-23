"""Regression tests for Phase C7 static dependency-graph code context."""

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from test_code_context import DeterministicEmbeddingFunction


class DependencyGraphCodeIndexTests(unittest.TestCase):
    """Exercise static graph derivation, bounds, and graph-aware retrieval."""

    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory(prefix="steward_code_graph_")
        self.project_root = Path(self.temp_dir.name) / "project"
        self.project_root.mkdir()
        self.index_path = Path(self.temp_dir.name) / "rag_index"
        from agents.code_index_agent import CodeIndexAgent

        self.agent = CodeIndexAgent(
            persist_directory=str(self.index_path),
            collection_name="steward_code",
            embedding_function=DeterministicEmbeddingFunction(),
            max_files=100,
            max_file_bytes=8192,
            chunk_size=800,
            chunk_overlap=100,
        )
        self.addCleanup(self.temp_dir.cleanup)
        self.addCleanup(self.agent.close)

    def write(self, relative_path, content, root=None):
        base = self.project_root if root is None else root
        path = base / relative_path
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
        return path

    def index(self, root=None):
        target = self.project_root if root is None else root
        return self.agent.index_project(str(target))

    def test_static_derivation_never_imports_or_executes_indexed_modules(self):
        self.write(
            "dangerous_module.py",
            "raise RuntimeError('indexed source must never execute')\n",
        )

        with patch("builtins.__import__", wraps=__import__) as import_spy:
            summary = self.index()

        imported_names = {
            str(call.args[0])
            for call in import_spy.call_args_list
            if call.args
        }
        self.assertNotIn("dangerous_module", imported_names)
        self.assertEqual(summary["errors"], [])
        self.assertTrue(self.agent.graph_snapshot()["edges"])

    def test_denied_paths_are_never_opened_during_graph_build(self):
        allowed = self.write("allowed.py", "def allowed():\n    return 1\n")
        denied = self.write("venv/dependency.py", "DENIED_GRAPH_TOKEN = True\n")

        with patch("builtins.open", wraps=open) as open_spy:
            self.index()

        opened_names = {
            str(Path(str(call.args[0])).resolve()).lower()
            for call in open_spy.call_args_list
            if call.args
        }
        self.assertIn(str(allowed.resolve()).lower(), opened_names)
        self.assertNotIn(str(denied.resolve()).lower(), opened_names)
        self.assertNotIn(
            "venv/dependency.py",
            {
                edge.get("target_path")
                for edge in self.agent.graph_snapshot()["edges"]
            },
        )

    def test_external_and_unresolved_imports_are_recorded_with_zero_reads(self):
        source = self.write(
            "imports.py",
            "import os\n"
            "import third_party_module\n"
            "from missing_module import missing_name\n",
        )

        with patch("builtins.open", wraps=open) as open_spy:
            self.index()

        edges = self.agent.graph_snapshot()["edges"]
        imports = [edge for edge in edges if edge["kind"] == "import"]
        self.assertTrue(
            any(
                edge["module"] == "os"
                and edge["status"] == "external"
                for edge in imports
            )
        )
        self.assertTrue(
            any(
                edge["module"] == "missing_module"
                and edge["status"] == "unresolved"
                for edge in imports
            )
        )
        opened_source_paths = {
            str(Path(str(call.args[0])).resolve()).lower()
            for call in open_spy.call_args_list
            if call.args and Path(str(call.args[0])).suffix == ".py"
        }
        self.assertEqual(opened_source_paths, {str(source.resolve()).lower()})

    def test_graph_bounds_cycles_and_self_imports_terminate_deterministically(self):
        from agents.code_index_agent import CodeIndexAgent

        module_names = [f"module_{index}" for index in range(40)]
        for index, name in enumerate(module_names):
            following = module_names[index + 1] if index + 1 < len(module_names) else name
            self.write(
                f"{name}.py",
                f"import {following}\n"
                f"def value_{index}():\n"
                f"    return {index}\n",
            )

        with patch.object(CodeIndexAgent, "MAX_GRAPH_TOTAL_EDGES", 7):
            self.index()
            snapshot = self.agent.graph_snapshot()
        self.assertLessEqual(snapshot["edge_count"], 7)

        self.agent.max_graph_depth = 2
        self.agent.max_graph_visited_nodes = 4
        self.agent.max_graph_edges_per_node = 1
        traversal = self.agent.traverse_dependencies(
            ["module_0.py"], root=str(self.project_root)
        )
        self.assertLessEqual(len(traversal), 4)
        self.assertTrue(all(node["depth"] <= 2 for node in traversal))
        self.assertEqual(
            traversal,
            self.agent.traverse_dependencies(
                ["module_0.py"], root=str(self.project_root)
            ),
        )
        self.assertIn(
            "module_0.py",
            {node["relative_path"] for node in traversal},
        )

    def test_cross_file_dependency_retrieval_finds_relevant_dependency(self):
        self.write(
            "dependency.py",
            "def important_function():\n"
            "    return 'DEPENDENCY_RESULT'\n",
        )
        self.write(
            "caller.py",
            "from dependency import important_function\n"
            "def call_it():\n"
            "    return important_function()\n",
        )
        self.index()

        results = self.agent.search("call_it", n_results=5)

        self.assertTrue(results)
        self.assertIn(
            "dependency.py",
            {result["relative_path"] for result in results},
        )

    def test_root_isolation_prevents_cross_root_edges_or_content(self):
        first_root = Path(self.temp_dir.name) / "first"
        second_root = Path(self.temp_dir.name) / "second"
        first_root.mkdir()
        second_root.mkdir()
        self.write(
            "caller.py",
            "from dependency import shared\n"
            "def first_only():\n"
            "    return shared()\n",
            root=first_root,
        )
        self.write(
            "dependency.py",
            "def shared():\n"
            "    return 'FIRST_ROOT_ONLY'\n",
            root=first_root,
        )
        self.write(
            "caller.py",
            "from dependency import shared\n"
            "def second_only():\n"
            "    return shared()\n",
            root=second_root,
        )
        self.write(
            "dependency.py",
            "def shared():\n"
            "    return 'SECOND_ROOT_ONLY'\n",
            root=second_root,
        )

        self.index(first_root)
        self.index(second_root)

        first_snapshot = self.agent.graph_snapshot(root=str(first_root))
        first_edges = [
            edge for edge in first_snapshot["edges"]
            if edge["kind"] == "import"
        ]
        self.assertTrue(first_edges)
        self.assertTrue(
            all(edge["root_id"] == first_snapshot["root_id"] for edge in first_edges)
        )
        first_results = self.agent.search(
            "FIRST_ROOT_ONLY", n_results=5, root=str(first_root)
        )
        self.assertTrue(first_results)
        self.assertNotIn(
            "SECOND_ROOT_ONLY",
            " ".join(result["content"] for result in first_results),
        )

    def test_changed_deleted_files_update_edges_and_rebuild_is_idempotent(self):
        self.write("dependency.py", "def value():\n    return 1\n")
        self.write(
            "caller.py",
            "from dependency import value\n"
            "def caller():\n"
            "    return value()\n",
        )
        self.index()
        first = self.agent.graph_snapshot()
        first_count = self.agent.collection.count()

        self.write(
            "caller.py",
            "from replacement import value\n"
            "def caller():\n"
            "    return value()\n",
        )
        self.write("replacement.py", "def value():\n    return 2\n")
        self.index()
        changed = self.agent.graph_snapshot()
        changed_targets = {
            edge["target_path"]
            for edge in changed["edges"]
            if edge["kind"] == "import"
        }
        self.assertIn("replacement.py", changed_targets)
        self.assertNotIn("dependency.py", changed_targets)

        (self.project_root / "replacement.py").unlink()
        self.index()
        deleted = self.agent.graph_snapshot()
        deleted_targets = {
            edge["target_path"]
            for edge in deleted["edges"]
            if edge["kind"] == "import"
        }
        self.assertNotIn("replacement.py", deleted_targets)

        before_idempotent = json.dumps(deleted, sort_keys=True)
        count_before_idempotent = self.agent.collection.count()
        self.index()
        self.assertEqual(before_idempotent, json.dumps(self.agent.graph_snapshot(), sort_keys=True))
        self.assertEqual(count_before_idempotent, self.agent.collection.count())
        self.assertGreater(first_count, 0)

    def test_hostile_module_and_import_strings_never_read_out_of_root(self):
        outside = Path(self.temp_dir.name) / "outside.py"
        outside.write_text("OUTSIDE_SECRET = True\n", encoding="utf-8")
        source = self.write(
            "hostile.py",
            "import os\n"
            "from ..escape import escaped\n"
            "__import__('../outside')\n"
            "importlib.import_module('C:\\\\outside')\n",
        )

        with patch("builtins.open", wraps=open) as open_spy:
            self.index()

        opened_names = {
            str(Path(str(call.args[0])).resolve()).lower()
            for call in open_spy.call_args_list
            if call.args
        }
        self.assertNotIn(str(outside.resolve()).lower(), opened_names)
        self.assertIn(str(source.resolve()).lower(), opened_names)
        for edge in self.agent.graph_snapshot()["edges"]:
            self.assertNotIn("outside", edge["target_path"].lower())
            self.assertNotIn("escape", edge["target_path"].lower())

    def test_syntax_and_architect_context_bounds_remain_unchanged(self):
        from agents.coding_agent import CodingAgent
        from agents.plan_agent import PlanAgent

        results = [
            {
                "relative_path": f"pkg/file_{index}.py",
                "start_line": 1,
                "end_line": 20,
                "symbol": f"symbol_{index}",
                "content": "X" * 3000,
            }
            for index in range(10)
        ]
        syntax_context = CodingAgent._format_code_context(results)
        architect_context = PlanAgent._format_code_context(results)

        for context in (syntax_context, architect_context):
            self.assertLessEqual(context.count("--- pkg/file_"), 5)
            self.assertLessEqual(len(context), 8000)
            sections = context.split("\n\n--- ")[1:]
            for section in sections:
                content = section.split(" ---\n", 1)[1]
                self.assertLessEqual(len(content), 2000)

        self.assertEqual(CodingAgent._format_code_context(None), "")
        self.assertEqual(PlanAgent._format_code_context(None), "")


if __name__ == "__main__":
    unittest.main()

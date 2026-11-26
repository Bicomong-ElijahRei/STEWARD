"""Regression tests for deterministic ChromaDB client lifecycle ownership."""

import os
import shutil
import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from agents.code_index_agent import CodeIndexAgent
from agents.rag_agent import RAGAgent


class DeterministicEmbeddingFunction:
    """Small offline embedding function for lifecycle tests."""

    def __call__(self, input):
        return [[1.0] + [0.0] * 63 for _ in input]

    def embed_query(self, input):
        return self(input)

    @staticmethod
    def name():
        return "steward_chroma_lifecycle_test"

    @staticmethod
    def build_from_config(config):
        return DeterministicEmbeddingFunction()

    def get_config(self):
        return {}

    def default_space(self):
        return "cosine"


class ChromaLifecycleTests(unittest.TestCase):
    """Exercise client ownership at the production agent boundary."""

    AGENT_TYPES = (RAGAgent, CodeIndexAgent)

    def _make_agent(self, agent_type, index_path):
        return agent_type(
            persist_directory=str(index_path),
            collection_name="lifecycle_test",
            embedding_function=DeterministicEmbeddingFunction(),
        )

    def test_reinitialization_does_not_orphan_the_previous_client(self):
        for agent_type in self.AGENT_TYPES:
            with self.subTest(agent_type=agent_type.__name__):
                root = tempfile.mkdtemp(prefix="steward_chroma_reinit_")
                index_path = Path(root) / "index"
                agent = self._make_agent(agent_type, index_path)
                original_client = agent.client
                try:
                    self.assertTrue(agent.initialize())
                    self.assertIsNot(agent.client, original_client)
                    agent.close()
                    sqlite_file = index_path / "chroma.sqlite3"
                    moved_sqlite = sqlite_file.with_name(sqlite_file.name + ".moved")
                    os.replace(sqlite_file, moved_sqlite)
                    self.assertTrue(moved_sqlite.exists())
                    shutil.rmtree(root)
                    self.assertFalse(os.path.exists(root))
                finally:
                    agent.close()
                    if original_client is not None:
                        original_client.close()
                    if os.path.exists(root):
                        shutil.rmtree(root)

    def test_teardown_releases_the_sqlite_handle_immediately(self):
        for agent_type in self.AGENT_TYPES:
            with self.subTest(agent_type=agent_type.__name__):
                root = tempfile.mkdtemp(prefix="steward_chroma_sqlite_")
                index_path = Path(root) / "index"
                agent = self._make_agent(agent_type, index_path)
                try:
                    agent.collection.add(
                        documents=["sqlite lifecycle marker"],
                        ids=["sqlite-lifecycle-marker"],
                    )
                    agent.close()

                    sqlite_file = index_path / "chroma.sqlite3"
                    moved_sqlite = sqlite_file.with_name(sqlite_file.name + ".moved")
                    os.replace(sqlite_file, moved_sqlite)
                    self.assertTrue(moved_sqlite.exists())
                finally:
                    agent.close()
                    if os.path.exists(root):
                        shutil.rmtree(root)

    def test_concurrent_delete_recreate_live_lock_is_released_by_teardown(self):
        for agent_type in self.AGENT_TYPES:
            with self.subTest(agent_type=agent_type.__name__):
                root = tempfile.mkdtemp(prefix="steward_chroma_lock_")
                index_path = Path(root) / "index"
                agent = self._make_agent(agent_type, index_path)
                try:
                    agent.collection.add(
                        documents=["lifecycle marker"],
                        ids=["lifecycle-marker"],
                    )
                    barrier = threading.Barrier(2)
                    errors = []

                    def delete_collection():
                        try:
                            barrier.wait(timeout=5)
                            agent.client.delete_collection(agent.collection_name)
                        except Exception as exc:
                            errors.append(exc)

                    def recreate_collection():
                        try:
                            barrier.wait(timeout=5)
                            agent.client.get_or_create_collection(
                                name=agent.collection_name,
                                embedding_function=DeterministicEmbeddingFunction(),
                            )
                        except Exception as exc:
                            errors.append(exc)

                    workers = [
                        threading.Thread(target=delete_collection),
                        threading.Thread(target=recreate_collection),
                    ]
                    for worker in workers:
                        worker.start()
                    for worker in workers:
                        worker.join(timeout=10)
                    self.assertFalse(any(worker.is_alive() for worker in workers))
                    self.assertEqual(errors, [])

                    index_files = list(index_path.rglob("data_level0.bin"))
                    self.assertTrue(index_files)
                    for index_file in index_files:
                        moved = index_file.with_name(index_file.name + ".moved")
                        if os.name == "nt":
                            with self.assertRaises(PermissionError):
                                os.replace(index_file, moved)
                        else:
                            os.replace(index_file, moved)
                            os.replace(moved, index_file)

                    self.assertTrue(agent.initialize())
                    agent.close()
                    for index_file in index_files:
                        moved = index_file.with_name(index_file.name + ".moved")
                        os.replace(index_file, moved)
                        self.assertTrue(moved.exists())

                    shutil.rmtree(root)
                    self.assertFalse(os.path.exists(root))
                finally:
                    agent.close()
                    if os.path.exists(root):
                        shutil.rmtree(root)

    def test_initialization_failure_closes_the_created_client(self):
        for agent_type in self.AGENT_TYPES:
            with self.subTest(agent_type=agent_type.__name__):
                client = Mock()
                client.get_or_create_collection.side_effect = RuntimeError(
                    "collection creation failed"
                )
                with self.assertLogs(agent_type.__module__, level="ERROR"):
                    with patch("chromadb.PersistentClient", return_value=client):
                        agent = self._make_agent(
                            agent_type, Path(tempfile.gettempdir())
                        )

                client.close.assert_called_once_with()
                self.assertIsNone(agent.client)
                self.assertIsNone(agent.collection)
                self.assertIn("collection creation failed", agent.initialization_error)

    def test_initialization_cleanup_failure_is_reported(self):
        for agent_type in self.AGENT_TYPES:
            with self.subTest(agent_type=agent_type.__name__):
                client = Mock()
                client.get_or_create_collection.side_effect = RuntimeError(
                    "collection creation failed"
                )
                client.close.side_effect = RuntimeError("cleanup close failed")
                with self.assertLogs(agent_type.__module__, level="ERROR"):
                    with patch("chromadb.PersistentClient", return_value=client):
                        agent = self._make_agent(
                            agent_type, Path(tempfile.gettempdir())
                        )

                self.assertIs(agent.client, client)
                self.assertIsNone(agent.collection)
                self.assertIn("cleanup close failed", agent.initialization_error)

    def test_reinitialization_close_failure_is_observable(self):
        for agent_type in self.AGENT_TYPES:
            with self.subTest(agent_type=agent_type.__name__):
                client = Mock()
                client.close.side_effect = RuntimeError("existing close failed")
                agent = object.__new__(agent_type)
                agent.available = True
                agent.client = client
                agent.collection = Mock()
                agent.initialization_error = ""
                agent._lock = threading.RLock()
                agent.persist_directory = tempfile.gettempdir()
                agent.collection_name = "lifecycle_test"
                agent.embedding_function = None

                with self.assertLogs(agent_type.__module__, level="ERROR"):
                    with self.assertRaisesRegex(
                        RuntimeError, "Failed to close existing"
                    ):
                        agent.initialize()

                self.assertIs(agent.client, client)
                self.assertIsNone(agent.collection)
                self.assertIn("existing close failed", agent.initialization_error)

    def test_close_failure_is_observable_and_keeps_the_client_reference(self):
        for agent_type in self.AGENT_TYPES:
            with self.subTest(agent_type=agent_type.__name__):
                client = Mock()
                client.close.side_effect = RuntimeError("close failed")
                agent = object.__new__(agent_type)
                agent.client = client
                agent.collection = Mock()
                agent._lock = threading.RLock()

                with self.assertLogs(agent_type.__module__, level="ERROR"):
                    with self.assertRaisesRegex(RuntimeError, "Failed to close"):
                        agent.close()

                self.assertIs(agent.client, client)
                self.assertIsNone(agent.collection)


if __name__ == "__main__":
    unittest.main()

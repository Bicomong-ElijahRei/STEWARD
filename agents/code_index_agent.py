"""
CodeIndexAgent - bounded, read-only semantic context for source code.

This agent owns a separate persistent ChromaDB CODE collection. Ingestion is
explicitly rooted at a user-selected project folder and never imports or
executes indexed code.
"""

import ast
import hashlib
import logging
import os
import threading
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


class CodeIndexAgent:
    """Index code symbols and retrieve bounded, path/line-aware snippets."""

    COLLECTION_NAME = "steward_code"
    MAX_SEARCH_DISTANCE = 1.2
    MAX_SEARCH_RESULTS = 20
    MAX_FILES = 2000
    MAX_FILE_BYTES = 256 * 1024
    CHUNK_SIZE = 2400
    CHUNK_OVERLAP = 240
    MAX_ADD_BATCH = 1000
    SUPPORTED_EXTENSIONS = frozenset({
        ".py", ".md", ".txt", ".json", ".yaml", ".yml", ".toml", ".ini", ".cfg",
    })
    DENIED_DIRECTORIES = frozenset({
        ".git", "venv", "__pycache__", "node_modules", "rag_index", "media",
    })

    def __init__(
        self,
        persist_directory: Optional[str] = None,
        collection_name: Optional[str] = None,
        embedding_function: Optional[Any] = None,
        max_search_distance: Optional[float] = None,
        max_files: Optional[int] = None,
        max_file_bytes: Optional[int] = None,
        chunk_size: Optional[int] = None,
        chunk_overlap: Optional[int] = None,
    ):
        self.persist_directory = os.path.abspath(
            persist_directory or os.path.join(os.getcwd(), "rag_index")
        )
        self.collection_name = collection_name or self.COLLECTION_NAME
        self.embedding_function = embedding_function
        self.max_search_distance = (
            self.MAX_SEARCH_DISTANCE
            if max_search_distance is None
            else max_search_distance
        )
        self.max_files = self.MAX_FILES if max_files is None else max_files
        self.max_file_bytes = (
            self.MAX_FILE_BYTES if max_file_bytes is None else max_file_bytes
        )
        self.chunk_size = self.CHUNK_SIZE if chunk_size is None else chunk_size
        self.chunk_overlap = (
            self.CHUNK_OVERLAP if chunk_overlap is None else chunk_overlap
        )
        self.available = self._check_chromadb()
        self.client = None
        self.collection = None
        self.initialization_error = ""
        self._lock = threading.RLock()
        self._generation = 0
        self.initialize()

    def _check_chromadb(self) -> bool:
        try:
            import chromadb  # noqa: F401
            return True
        except ImportError:
            logger.warning("CodeIndexAgent: chromadb not installed")
            return False

    def initialize(self):
        if not self.available:
            return False
        try:
            import chromadb
            os.makedirs(self.persist_directory, exist_ok=True)
            self.client = chromadb.PersistentClient(path=self.persist_directory)
            options = {}
            if self.embedding_function is not None:
                options["embedding_function"] = self.embedding_function
            self.collection = self.client.get_or_create_collection(
                name=self.collection_name,
                **options,
            )
            self.initialization_error = ""
            return True
        except Exception as exc:
            self.client = None
            self.collection = None
            self.initialization_error = str(exc)
            logger.error("CodeIndexAgent: ChromaDB initialization failed: %s", exc)
            return False

    def close(self):
        with self._lock:
            client = self.client
            self.collection = None
            self.client = None
        if client is not None:
            try:
                close = getattr(client, "close", None)
                if callable(close):
                    close()
            except Exception as exc:
                logger.warning("CodeIndexAgent: failed to close ChromaDB: %s", exc)

    @staticmethod
    def _normalize_root(root: str) -> str:
        """Resolve an explicit project root to its canonical absolute path."""
        if not isinstance(root, str) or not root.strip():
            raise ValueError("A project root must be explicitly provided")
        expanded = os.path.abspath(os.path.expanduser(root.strip()))
        return os.path.realpath(expanded)

    @classmethod
    def _is_denied_root(cls, root: str) -> bool:
        """Deny a selected root whose own basename is a denied directory."""
        if not isinstance(root, str) or not root.strip():
            return False
        expanded = os.path.abspath(os.path.expanduser(root.strip()))
        basename = os.path.basename(os.path.normpath(expanded)).casefold()
        return basename in cls.DENIED_DIRECTORIES

    @staticmethod
    def _contained_by(root: str, candidate: str) -> bool:
        """Return containment using realpath, abspath, commonpath, and normcase."""
        root_real = os.path.realpath(os.path.abspath(root))
        candidate_real = os.path.realpath(os.path.abspath(candidate))
        try:
            common = os.path.commonpath([
                os.path.normcase(root_real), os.path.normcase(candidate_real),
            ])
        except ValueError:
            return False
        return common == os.path.normcase(root_real)

    @classmethod
    def _is_denied_relative_path(cls, relative_path: str) -> bool:
        """Apply the denylist to every path component, independent of root."""
        parts = [part.lower() for part in relative_path.replace("\\", "/").split("/")]
        if any(part in cls.DENIED_DIRECTORIES for part in parts[:-1]):
            return True
        filename = parts[-1] if parts else ""
        if filename in {".git", "secret.key", "steward_operations.json"}:
            return True
        if filename.startswith(".env"):
            return True
        if filename.endswith((".db", ".key")):
            return True
        return False

    def _is_escape(self, root: str, path: str) -> bool:
        """Refuse symlink/junction targets outside the selected root."""
        try:
            return not self._contained_by(root, path)
        except (OSError, ValueError):
            return True

    @staticmethod
    def _is_link_or_junction(path: str) -> bool:
        is_junction = getattr(os.path, "isjunction", None)
        return os.path.islink(path) or (callable(is_junction) and is_junction(path))

    @staticmethod
    def _relative_path(root: str, path: str) -> str:
        return os.path.relpath(path, root).replace("\\", "/")

    @staticmethod
    def _symbol_nodes(tree: ast.AST) -> List[ast.AST]:
        """Return top-level Python definitions with source line boundaries."""
        nodes = []
        for node in getattr(tree, "body", []):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                nodes.append(node)
        return nodes

    def _chunk_symbols(self, text: str, relative_path: str) -> List[Dict[str, Any]]:
        """Chunk Python by AST symbol, falling back to overlapping windows."""
        if relative_path.lower().endswith(".py"):
            try:
                tree = ast.parse(text)
            except (SyntaxError, UnicodeDecodeError, ValueError):
                tree = None
            if tree is not None:
                nodes = self._symbol_nodes(tree)
                if nodes:
                    chunks = []
                    lines = text.splitlines(keepends=True)
                    for node in nodes:
                        start = max(1, getattr(node, "lineno", 1))
                        end = min(
                            len(lines), getattr(node, "end_lineno", start) or start
                        )
                        content = "".join(lines[start - 1:end])
                        if not content.strip():
                            continue
                        symbol = getattr(node, "name", "<symbol>")
                        for chunk in self._overlapping_windows(content):
                            chunks.append({
                                "content": chunk,
                                "start_line": start,
                                "end_line": end,
                                "symbol": symbol,
                                "part": len(chunks),
                            })
                    if chunks:
                        return chunks
        return [
            {
                "content": chunk,
                "start_line": 1,
                "end_line": max(1, text.count("\n") + 1),
                "symbol": "<module>",
                "part": part,
            }
            for part, chunk in enumerate(self._overlapping_windows(text))
        ]

    def _overlapping_windows(self, text: str) -> List[str]:
        if not text.strip():
            return []
        chunks = []
        start = 0
        while start < len(text):
            end = min(start + self.chunk_size, len(text))
            chunk = text[start:end].strip()
            if chunk:
                chunks.append(chunk)
            if end >= len(text):
                break
            start = end - self.chunk_overlap
        return chunks

    def _candidate_files(self, root: str, refused_paths: List[str]):
        """Yield deterministic eligible files without following directory links."""
        for current_root, directories, filenames in os.walk(
            root, topdown=True, followlinks=False
        ):
            safe_directories = []
            for directory in sorted(directories):
                path = os.path.join(current_root, directory)
                relative = self._relative_path(root, path)
                if self._is_denied_relative_path(relative + "/placeholder"):
                    continue
                if self._is_link_or_junction(path):
                    if self._is_escape(root, path):
                        refused_paths.append(relative)
                    continue
                safe_directories.append(directory)
            directories[:] = safe_directories

            for filename in sorted(filenames):
                path = os.path.join(current_root, filename)
                relative = self._relative_path(root, path)
                extension = os.path.splitext(filename)[1].lower()
                if extension not in self.SUPPORTED_EXTENSIONS:
                    continue
                if self._is_denied_relative_path(relative):
                    continue
                if self._is_link_or_junction(path) and self._is_escape(root, path):
                    refused_paths.append(relative)
                    continue
                if not os.path.isfile(path):
                    continue
                yield path, relative

    def _read_bounded(self, path: str) -> Dict[str, Any]:
        """Read one file within the byte cap without executing its contents."""
        original_bytes = os.path.getsize(path)
        with open(path, "rb") as handle:
            raw = handle.read(self.max_file_bytes)
        truncated = original_bytes > len(raw)
        try:
            text = raw.decode("utf-8-sig")
        except UnicodeDecodeError:
            text = raw.decode("utf-8", errors="replace")
        return {
            "text": text,
            "content_hash": hashlib.sha256(raw).hexdigest(),
            "original_bytes": original_bytes,
            "indexed_bytes": len(raw),
            "truncated": truncated,
        }

    @staticmethod
    def _chunk_id(root_id: str, relative_path: str, part: int) -> str:
        digest = hashlib.sha256(
            f"{root_id}\n{relative_path}".encode("utf-8")
        ).hexdigest()[:24]
        return f"code-{digest}-{part:06d}"

    def _active_root(self) -> Optional[str]:
        """Return the most recently indexed root persisted with the collection."""
        if not self.available or self.collection is None:
            return None
        try:
            metadata = self.collection.metadata or {}
        except Exception:
            metadata = {}
        value = metadata.get("active_root")
        return str(value) if value else None

    def _set_active_root(self, root_id: str):
        """Persist the selected root without exposing it to provider prompts."""
        if not self.available or self.collection is None:
            return
        try:
            self.collection.modify(metadata={"active_root": root_id})
        except Exception as exc:
            logger.warning("CodeIndexAgent: failed to persist active root: %s", exc)

    def _existing_metadata(self) -> Dict[str, Dict[str, Any]]:
        if not self.available or self.collection is None:
            return {}
        with self._lock:
            raw = self.collection.get(include=["metadatas"])
        existing = {}
        for item_id, metadata in zip(
            raw.get("ids") or [], raw.get("metadatas") or []
        ):
            if isinstance(metadata, dict):
                existing[item_id] = dict(metadata)
        return existing

    def _replace_file_chunks(
        self,
        root_id: str,
        relative_path: str,
        chunks: List[Dict[str, Any]],
        generation: Optional[int] = None,
    ) -> int:
        if not self.available or self.collection is None:
            raise RuntimeError(self.initialization_error or "Code index unavailable")
        with self._lock:
            if generation is not None and generation != self._generation:
                return 0
            existing = self.collection.get(
                where={
                    "$and": [
                        {"root_id": root_id},
                        {"relative_path": relative_path},
                    ]
                },
                include=["metadatas"],
            )
            stale_ids = list(existing.get("ids") or [])
            if stale_ids:
                self.collection.delete(ids=stale_ids)

            if not chunks:
                return 0
            ids = [
                self._chunk_id(root_id, relative_path, chunk["part"])
                for chunk in chunks
            ]
            metadatas = [
                {
                    "root_id": root_id,
                    "relative_path": relative_path,
                    "start_line": int(chunk["start_line"]),
                    "end_line": int(chunk["end_line"]),
                    "symbol": str(chunk["symbol"]),
                    "part": int(chunk["part"]),
                }
                for chunk in chunks
            ]
            for offset in range(0, len(chunks), self.MAX_ADD_BATCH):
                end = min(offset + self.MAX_ADD_BATCH, len(chunks))
                self.collection.add(
                    ids=ids[offset:end],
                    documents=[chunks[index]["content"] for index in range(offset, end)],
                    metadatas=metadatas[offset:end],
                )
            return len(chunks)

    def index_project(
        self, root: str, cancel_event: Optional[threading.Event] = None
    ) -> Dict[str, Any]:
        """Incrementally index one explicitly selected project folder."""
        if self._is_denied_root(root):
            raise ValueError(
                "Code project root cannot be a denied directory: "
                f"{os.path.basename(os.path.normpath(os.path.abspath(os.path.expanduser(root.strip()))))}"
            )
        root_path = self._normalize_root(root)
        if not os.path.isdir(root_path):
            raise NotADirectoryError(f"Code project root not found: {root_path}")
        if self.max_files <= 0 or self.max_file_bytes <= 0:
            raise ValueError("Code index bounds must be positive")

        summary = {
            "root": root_path,
            "files_processed": 0,
            "files_indexed": 0,
            "files_updated": 0,
            "files_unchanged": 0,
            "files_deleted": 0,
            "chunks_created": 0,
            "errors": [],
            "refused_paths": [],
            "truncated_files": [],
            "file_limit_reached": False,
            "max_files": self.max_files,
            "max_file_bytes": self.max_file_bytes,
            "cancelled": False,
        }
        if cancel_event is not None and cancel_event.is_set():
            summary["cancelled"] = True
            return summary

        root_id = os.path.normcase(root_path)
        with self._lock:
            self._generation += 1
            generation = self._generation
        self._set_active_root(root_id)
        existing_by_path: Dict[str, Dict[str, Any]] = {}
        for metadata in self._existing_metadata().values():
            if metadata.get("root_id") == root_id:
                relative = str(metadata.get("relative_path") or "")
                if relative:
                    existing_by_path[relative] = metadata

        seen_paths = set()
        refused_paths = []
        for path, relative in self._candidate_files(root_path, refused_paths):
            if cancel_event is not None and cancel_event.is_set():
                summary["cancelled"] = True
                break
            if generation != self._generation:
                summary["cancelled"] = True
                break
            if summary["files_processed"] >= self.max_files:
                summary["file_limit_reached"] = True
                break

            summary["files_processed"] += 1
            seen_paths.add(relative)
            try:
                source = self._read_bounded(path)
                if source["truncated"]:
                    summary["truncated_files"].append({
                        "relative_path": relative,
                        "original_bytes": source["original_bytes"],
                        "indexed_bytes": source["indexed_bytes"],
                    })
                chunks = self._chunk_symbols(source["text"], relative)
                existing = existing_by_path.get(relative)
                content_hash = source["content_hash"]
                if (
                    existing is not None
                    and existing.get("content_hash") == content_hash
                ):
                    summary["files_unchanged"] += 1
                    continue

                chunk_count = self._replace_file_chunks(
                    root_id, relative, chunks, generation=generation
                )
                if generation != self._generation:
                    summary["cancelled"] = True
                    break
                summary["chunks_created"] += chunk_count
                if existing is None:
                    summary["files_indexed"] += 1
                else:
                    summary["files_updated"] += 1
                self._store_file_hash(root_id, relative, content_hash)
            except Exception as exc:
                summary["errors"].append({
                    "relative_path": relative,
                    "error": str(exc),
                })
                logger.warning("CodeIndexAgent: failed to index %s: %s", path, exc)

        if not summary["cancelled"] and not summary["file_limit_reached"]:
            for relative in sorted(set(existing_by_path) - seen_paths):
                try:
                    self._replace_file_chunks(
                        root_id, relative, [], generation=generation
                    )
                    summary["files_deleted"] += 1
                except Exception as exc:
                    summary["errors"].append({
                        "relative_path": relative,
                        "error": str(exc),
                    })
        summary["refused_paths"] = sorted(set(refused_paths))
        summary["truncated_files"].sort(key=lambda item: item["relative_path"])
        return summary

    def _store_file_hash(self, root_id: str, relative_path: str, content_hash: str):
        """Persist the file hash in each chunk's metadata for idempotence."""
        if not self.available or self.collection is None:
            return
        with self._lock:
            raw = self.collection.get(
                where={
                    "$and": [
                        {"root_id": root_id},
                        {"relative_path": relative_path},
                    ]
                },
                include=["metadatas"],
            )
            ids = list(raw.get("ids") or [])
            metadatas = list(raw.get("metadatas") or [])
            if not ids:
                return
            updated = []
            for metadata in metadatas:
                item = dict(metadata or {})
                item["content_hash"] = content_hash
                updated.append(item)
            self.collection.update(ids=ids, metadatas=updated)

    def search(
        self,
        query: str,
        n_results: int = 5,
        root: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        """Return bounded code snippets with relative path and line metadata."""
        if not isinstance(query, str) or not query.strip():
            return []
        if not isinstance(n_results, int) or isinstance(n_results, bool):
            raise ValueError("n_results must be an integer")
        if n_results <= 0 or not self.available or self.collection is None:
            return []
        n_results = min(n_results, self.MAX_SEARCH_RESULTS)
        try:
            with self._lock:
                count = self.collection.count()
                if count <= 0:
                    return []
                query_kwargs = {
                    "query_texts": [query.strip()],
                    "n_results": min(n_results, count),
                    "include": ["documents", "metadatas", "distances"],
                }
                search_root = root
                if search_root is None:
                    search_root = self._active_root()
                if search_root is not None:
                    query_kwargs["where"] = {
                        "root_id": os.path.normcase(self._normalize_root(search_root))
                    }
                raw = self.collection.query(**query_kwargs)
        except Exception as exc:
            logger.error("CodeIndexAgent: search failed: %s", exc)
            return []

        documents = (raw.get("documents") or [[]])[0]
        metadatas = (raw.get("metadatas") or [[]])[0]
        distances = (raw.get("distances") or [[]])[0]
        results = []
        for index, content in enumerate(documents):
            metadata = metadatas[index] if index < len(metadatas) else {}
            distance = distances[index] if index < len(distances) else None
            if (
                distance is not None
                and self.max_search_distance is not None
                and float(distance) > self.max_search_distance
            ):
                continue
            metadata = metadata or {}
            results.append({
                "relative_path": metadata.get("relative_path", ""),
                "start_line": metadata.get("start_line", 1),
                "end_line": metadata.get("end_line", 1),
                "symbol": metadata.get("symbol", ""),
                "content": content or "",
                "distance": distance,
            })
        return results

    def status(self) -> Dict[str, Any]:
        """Return deterministic collection status without exposing snippets."""
        if not self.available or self.collection is None:
            return {"files": 0, "chunks": 0, "available": False}
        metadata = list(self._existing_metadata().values())
        return {
            "files": len({
                (item.get("root_id"), item.get("relative_path"))
                for item in metadata
            }),
            "chunks": len(metadata),
            "available": True,
        }

    def clear(self) -> int:
        """Remove all CODE collection chunks while preserving the document RAG."""
        if not self.available or self.collection is None:
            return 0
        with self._lock:
            self._generation += 1
            raw = self.collection.get(include=["metadatas"])
            ids = list(raw.get("ids") or [])
            if ids:
                self.collection.delete(ids=ids)
            return len(ids)

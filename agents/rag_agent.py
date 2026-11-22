"""
RAGAgent - Retrieval-Augmented Generation Agent.

Uses a persistent ChromaDB collection for document ingestion, semantic chunk
retrieval, and formatted search results.
"""

import hashlib
import logging
import os
import threading
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


class RAGAgent:
    """Ingest documents into ChromaDB and retrieve relevant text chunks."""

    COLLECTION_NAME = "steward_docs"
    CHUNK_SIZE = 500
    CHUNK_OVERLAP = 50
    MAX_SEARCH_DISTANCE = 1.0
    SUPPORTED_EXTENSIONS = frozenset({".txt", ".pdf", ".docx"})
    MAX_ADD_BATCH = 1000

    def __init__(
        self,
        persist_directory: Optional[str] = None,
        collection_name: Optional[str] = None,
        embedding_function: Optional[Any] = None,
        max_search_distance: Optional[float] = None,
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
        self.available = self._check_chromadb()
        self.client = None
        self.collection = None
        self.initialization_error = ""
        self._lock = threading.RLock()
        self.initialize()

    def _check_chromadb(self) -> bool:
        """Check if ChromaDB is available."""
        try:
            import chromadb  # noqa: F401
            logger.info("RAGAgent: chromadb available")
            return True
        except ImportError:
            logger.warning("RAGAgent: chromadb not installed. RAG unavailable.")
            return False

    def initialize(self):
        """Initialize the persistent client and document collection."""
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
            logger.info("RAGAgent: ChromaDB initialized")
            return True
        except Exception as exc:
            self.client = None
            self.collection = None
            self.initialization_error = str(exc)
            logger.error("RAGAgent: Failed to initialize ChromaDB: %s", exc)
            return False

    def close(self):
        """Release the persistent client, including its Windows file handles."""
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
                logger.warning("RAGAgent: Failed to close ChromaDB cleanly: %s", exc)

    @staticmethod
    def chunk_text(
        text: str,
        chunk_size: int = CHUNK_SIZE,
        chunk_overlap: int = CHUNK_OVERLAP,
    ) -> List[str]:
        """Split text into overlapping chunks, preserving the original text."""
        if not isinstance(text, str) or not text.strip():
            return []
        if not isinstance(chunk_size, int) or chunk_size <= 0:
            raise ValueError("chunk_size must be a positive integer")
        if not isinstance(chunk_overlap, int) or chunk_overlap < 0:
            raise ValueError("chunk_overlap must be a non-negative integer")
        if chunk_overlap >= chunk_size:
            raise ValueError("chunk_overlap must be smaller than chunk_size")

        chunks = []
        start = 0
        text_length = len(text)
        while start < text_length:
            end = min(start + chunk_size, text_length)
            chunk = text[start:end].strip()
            if chunk:
                chunks.append(chunk)
            if end >= text_length:
                break
            start = end - chunk_overlap
        return chunks

    @staticmethod
    def _read_document(file_path: str) -> str:
        """Extract the full text of a supported document for indexing."""
        extension = os.path.splitext(file_path)[1].lower()
        if extension == ".txt":
            with open(file_path, "r", encoding="utf-8", errors="ignore") as handle:
                return handle.read()
        if extension == ".pdf":
            try:
                import PyPDF2
            except ImportError as exc:
                raise RuntimeError("PyPDF2 is required to ingest PDF files") from exc
            with open(file_path, "rb") as handle:
                reader = PyPDF2.PdfReader(handle)
                return "\n".join(page.extract_text() or "" for page in reader.pages)
        if extension == ".docx":
            try:
                import docx
            except ImportError as exc:
                raise RuntimeError("python-docx is required to ingest DOCX files") from exc
            document = docx.Document(file_path)
            return "\n".join(
                paragraph.text for paragraph in document.paragraphs
                if paragraph.text.strip()
            )
        raise ValueError(f"Unsupported RAG document type: {extension or '<none>'}")

    @staticmethod
    def _document_id(source: str, chunk_id: int) -> str:
        digest = hashlib.sha256(source.encode("utf-8")).hexdigest()[:24]
        return f"{digest}-chunk-{chunk_id:06d}"

    def ingest_file(self, file_path: str) -> int:
        """Ingest one supported file and replace any prior chunks for it."""
        if not isinstance(file_path, str) or not file_path.strip():
            raise ValueError("file_path must be a non-empty string")
        source = os.path.abspath(os.path.expanduser(file_path))
        if not os.path.isfile(source):
            raise FileNotFoundError(f"RAG source file not found: {source}")
        extension = os.path.splitext(source)[1].lower()
        if extension not in self.SUPPORTED_EXTENSIONS:
            raise ValueError(f"Unsupported RAG document type: {extension or '<none>'}")

        text = self._read_document(source)
        chunks = self.chunk_text(text)
        if not chunks:
            if self.available and self.collection is not None:
                with self._lock:
                    existing = self.collection.get(
                        where={"source": source},
                        include=["metadatas"],
                    )
                    stale_ids = list(existing.get("ids") or [])
                    if stale_ids:
                        self.collection.delete(ids=stale_ids)
            return 0
        if not self.available or self.collection is None:
            raise RuntimeError(self.initialization_error or "RAGAgent is unavailable")

        ids = [self._document_id(source, index) for index in range(len(chunks))]
        metadatas = [
            {"source": source, "chunk_id": index}
            for index in range(len(chunks))
        ]

        with self._lock:
            existing = self.collection.get(
                where={"source": source},
                include=["metadatas"],
            )
            existing_ids = list(existing.get("ids") or [])
            existing_set = set(existing_ids)
            desired_set = set(ids)

            new_indices = [
                index for index, item_id in enumerate(ids)
                if item_id not in existing_set
            ]
            if new_indices:
                self._add_batches(new_indices, chunks, metadatas)
            changed_indices = [
                index for index, item_id in enumerate(ids)
                if item_id in existing_set
            ]
            if changed_indices:
                self.collection.update(
                    ids=[ids[index] for index in changed_indices],
                    documents=[chunks[index] for index in changed_indices],
                    metadatas=[metadatas[index] for index in changed_indices],
                )
            stale_ids = [
                item_id for item_id in existing_ids
                if item_id not in desired_set
            ]
            if stale_ids:
                self.collection.delete(ids=stale_ids)
        return len(chunks)

    def _add_batches(self, indices, chunks, metadatas):
        """Add chunks in bounded batches to respect ChromaDB limits."""
        for offset in range(0, len(indices), self.MAX_ADD_BATCH):
            batch_indices = indices[offset:offset + self.MAX_ADD_BATCH]
            self.collection.add(
                documents=[chunks[index] for index in batch_indices],
                metadatas=[metadatas[index] for index in batch_indices],
                ids=[
                    self._document_id(
                        metadatas[index]["source"],
                        metadatas[index]["chunk_id"],
                    )
                    for index in batch_indices
                ],
            )

    def ingest_directory(self, dir_path: str) -> Dict[str, Any]:
        """Recursively ingest TXT, PDF, and DOCX files in a directory."""
        if not isinstance(dir_path, str) or not dir_path.strip():
            raise ValueError("dir_path must be a non-empty string")
        root = os.path.abspath(os.path.expanduser(dir_path))
        if not os.path.isdir(root):
            raise NotADirectoryError(f"RAG source directory not found: {root}")

        ingested_files = 0
        ingested_chunks = 0
        errors = []
        for current_root, directories, files in os.walk(root):
            directories.sort()
            for filename in sorted(files):
                if os.path.splitext(filename)[1].lower() not in self.SUPPORTED_EXTENSIONS:
                    continue
                path = os.path.join(current_root, filename)
                try:
                    chunk_count = self.ingest_file(path)
                    ingested_files += 1
                    ingested_chunks += chunk_count
                except Exception as exc:
                    errors.append({"source": path, "error": str(exc)})
                    logger.warning("RAGAgent: Failed to ingest %s: %s", path, exc)
        return {
            "ingested_files": ingested_files,
            "ingested_chunks": ingested_chunks,
            "errors": errors,
        }

    def add_document(self, doc_id: str, text: str, metadata: Optional[Dict] = None) -> str:
        """Add a document directly to the vector store (legacy API)."""
        if not self.available or self.collection is None:
            return "RAGAgent: ChromaDB not available"
        try:
            self.collection.add(
                documents=[text],
                ids=[doc_id],
                metadatas=[metadata or {}],
            )
            return f"RAGAgent: Added document '{doc_id}'"
        except Exception as exc:
            return f"RAGAgent: Failed to add document: {exc}"

    def search(self, query: str, n_results: int = 5) -> List[Dict[str, Any]]:
        """Return relevant chunks as flat source/content/distance records."""
        if not isinstance(query, str) or not query.strip():
            return []
        if not isinstance(n_results, int) or isinstance(n_results, bool):
            raise ValueError("n_results must be an integer")
        if n_results <= 0:
            return []
        if not self.available or self.collection is None:
            return []

        try:
            with self._lock:
                count = self.collection.count()
                if count <= 0:
                    return []
                raw = self.collection.query(
                    query_texts=[query.strip()],
                    n_results=min(n_results, count),
                    include=["documents", "metadatas", "distances"],
                )
        except Exception as exc:
            logger.error("RAGAgent: Search failed: %s", exc)
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
            results.append({
                "source": metadata.get("source", "") if metadata else "",
                "content": content or "",
                "distance": distance,
            })
        return results

    def query(self, question: str) -> str:
        """Ask a question over stored documents."""
        results = self.search(question)
        if not results:
            return "RAGAgent: No relevant documents found."
        return f"RAGAgent: Found {len(results)} relevant results"

"""Shared lifecycle helpers for STEWARD's persistent ChromaDB clients."""

import gc
from typing import Any


def close_chroma_client(client: Any) -> None:
    """Close a ChromaDB client and finalize its Rust binding references.

    ChromaDB 1.5.9 drops the Rust ``Bindings`` object from its shared system
    during ``Client.close()``, but the Rust-owned SQLite pool can remain alive
    until Python finalizes the binding's reference cycle. On Windows that
    keeps ``chroma.sqlite3`` open and prevents deterministic directory cleanup.

    ``gc.collect()`` uses only the Python standard library and does not access
    Chroma internals. It runs only after ``client.close()`` succeeds so close
    failures remain observable and the caller can retain the client for
    diagnosis or retry.
    """
    client.close()
    gc.collect()

"""
STEWARD v2 - Native API Manager Database & Security Layer

Thread-safe SQLite database with AES-128 encryption (Fernet) for API keys.
All provider credentials encrypted at rest; decrypted only at call time.

No LangChain, LiteLLM, or PyTorch dependencies. Uses only:
sqlite3, cryptography, requests, threading.
"""

import sqlite3
import json
import threading
import os
import uuid
from datetime import datetime, timedelta
from cryptography.fernet import Fernet

DB_PATH = os.path.join(os.getcwd(), "steward.db")
KEY_PATH = os.path.join(os.getcwd(), "secret.key")


class DatabaseManager:
    def __init__(self, db_path: str = DB_PATH, key_path: str = KEY_PATH):
        self.db_path = db_path
        self.key_path = key_path
        self._lock = threading.Lock()
        self._key = self._load_or_create_key()
        self._cipher = Fernet(self._key)
        self._conn = sqlite3.connect(self.db_path, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self.init_db()
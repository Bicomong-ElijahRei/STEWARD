"""
STEWARD v2 - Native API Manager Database & Security Layer

Thread-safe SQLite database with AES-128 encryption (Fernet) for API keys.
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
        self._create_tables()

    def _load_or_create_key(self) -> bytes:
        if os.path.exists(self.key_path):
            with open(self.key_path, "rb") as f:
                return f.read()
        else:
            key = Fernet.generate_key()
            with open(self.key_path, "wb") as f:
                f.write(key)
            return key

    def _encrypt(self, text: str) -> bytes:
        return self._cipher.encrypt(text.encode("utf-8"))

    def _decrypt(self, blob: bytes) -> str:
        if not blob:
            return ""
        return self._cipher.decrypt(blob).decode("utf-8")

    def _create_tables(self):
        with self._lock:
            cursor = self._conn.cursor()
            # Providers table
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS providers (
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
            # Usage Ledger table
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS usage_ledger (
                    provider_id INTEGER,
                    window_start TEXT,
                    requests_used INTEGER DEFAULT 0,
                    tokens_used INTEGER DEFAULT 0,
                    PRIMARY KEY (provider_id, window_start)
                )
            """)
            # Traces table
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS traces (
                    id TEXT PRIMARY KEY,
                    timestamp TEXT,
                    agent_name TEXT,
                    latency_ms INTEGER,
                    provider_chain TEXT,
                    status TEXT,
                    error_msg TEXT
                )
            """)
            self._conn.commit()

    def add_provider(self, name, base_url, api_key, model_name="", 
                     is_local=False, is_active=True, speed_score_ms=9999, 
                     intelligence_tier="Unknown", supports_tools=False):
        with self._lock:
            enc_key = self._encrypt(api_key)
            cursor = self._conn.cursor()
            cursor.execute("""
                INSERT INTO providers 
                (name, base_url, api_key_encrypted, model_name, is_local, is_active, speed_score_ms, intelligence_tier, supports_tools)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(name) DO UPDATE SET
                base_url=excluded.base_url,
                api_key_encrypted=excluded.api_key_encrypted,
                model_name=excluded.model_name,
                is_active=excluded.is_active,
                speed_score_ms=excluded.speed_score_ms,
                intelligence_tier=excluded.intelligence_tier,
                supports_tools=excluded.supports_tools
            """, (name, base_url, enc_key, model_name, is_local, is_active, speed_score_ms, intelligence_tier, supports_tools))
            self._conn.commit()

    def get_active_providers(self):
        with self._lock:
            cursor = self._conn.cursor()
            cursor.execute("SELECT * FROM providers WHERE is_active = 1")
            rows = cursor.fetchall()
            providers = []
            for row in rows:
                p = dict(row)
                p['api_key'] = self._decrypt(p['api_key_encrypted']) # Decrypt for use
                for field in ("is_local", "is_active", "supports_tools"):
                    p[field] = bool(p[field])
                providers.append(p)
            return providers

    def get_provider(self, name):
        """Return one provider by name, including its decrypted API key."""
        with self._lock:
            cursor = self._conn.cursor()
            cursor.execute("SELECT * FROM providers WHERE name = ?", (name,))
            row = cursor.fetchone()
            if row is None:
                return None
            provider = dict(row)
            provider["api_key"] = self._decrypt(provider["api_key_encrypted"])
            for field in ("is_local", "is_active", "supports_tools"):
                provider[field] = bool(provider[field])
            return provider

    def update_provider_fields(self, name, **fields):
        """Update whitelisted provider fields and commit the change."""
        allowed_fields = {
            "base_url", "model_name", "is_local", "is_active",
            "speed_score_ms", "intelligence_tier", "supports_tools",
            "cooldown_until", "failure_count",
        }
        invalid_fields = set(fields) - allowed_fields
        if invalid_fields:
            raise ValueError(f"Unsupported provider fields: {sorted(invalid_fields)}")
        if not fields:
            return

        assignments = ", ".join(f"{field} = ?" for field in fields)
        values = list(fields.values()) + [name]
        with self._lock:
            cursor = self._conn.cursor()
            cursor.execute(
                f"UPDATE providers SET {assignments} WHERE name = ?", values
            )
            self._conn.commit()

    def record_usage(self, provider_id, tokens_used=0):
        """Add one request and its token count to the current hourly window."""
        window_start = datetime.now().replace(
            minute=0, second=0, microsecond=0
        ).isoformat()
        with self._lock:
            cursor = self._conn.cursor()
            cursor.execute("""
                INSERT INTO usage_ledger
                    (provider_id, window_start, requests_used, tokens_used)
                VALUES (?, ?, 1, ?)
                ON CONFLICT(provider_id, window_start) DO UPDATE SET
                    requests_used = requests_used + 1,
                    tokens_used = tokens_used + excluded.tokens_used
            """, (provider_id, window_start, int(tokens_used or 0)))
            self._conn.commit()

    def record_trace(self, agent_name, latency_ms, provider_chain, status, error_msg=""):
        with self._lock:
            trace_id = str(uuid.uuid4())
            timestamp = datetime.now().isoformat()
            cursor = self._conn.cursor()
            cursor.execute("""
                INSERT INTO traces (id, timestamp, agent_name, latency_ms, provider_chain, status, error_msg)
                VALUES (?, ?, ?, ?, ?, ?, ?)
            """, (trace_id, timestamp, agent_name, latency_ms, json.dumps(provider_chain), status, error_msg))
            self._conn.commit()

    def close(self):
        with self._lock:
            self._conn.close()

# ── Singleton Helpers ────────────────────────────────────────────────────

_db_instance = None

def init_db(db_path: str = DB_PATH, key_path: str = KEY_PATH):
    """Initialize the global database instance."""
    global _db_instance
    if _db_instance is None:
        _db_instance = DatabaseManager(db_path, key_path)
    return _db_instance

def get_db():
    """Retrieve the global database instance."""
    global _db_instance
    if _db_instance is None:
        raise RuntimeError("Database not initialized. Call init_db() first.")
    return _db_instance
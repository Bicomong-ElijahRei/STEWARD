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
from cryptography.fernet import Fernet, InvalidToken

DB_PATH = os.path.join(os.getcwd(), "steward.db")
KEY_PATH = os.path.join(os.getcwd(), "secret.key")

DECRYPTION_ERROR = (
    "Stored API key cannot be decrypted. Restore the matching secret.key "
    "or re-enter the provider's API key."
)

class DatabaseManager:
    def __init__(self, db_path: str = DB_PATH, key_path: str = KEY_PATH):
        self.db_path = db_path
        self.key_path = key_path
        self._lock = threading.Lock()
        self._key = self._load_or_create_key()
        self._cipher = Fernet(self._key)
        self._conn = sqlite3.connect(self.db_path, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self.decryption_errors = {}
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
                    assigned_agent TEXT DEFAULT 'Any',
                    cooldown_until TEXT,
                    failure_count INTEGER DEFAULT 0
                )
            """)
            cursor.execute("PRAGMA table_info(providers)")
            provider_columns = {row["name"] for row in cursor.fetchall()}
            if "assigned_agent" not in provider_columns:
                cursor.execute(
                    "ALTER TABLE providers "
                    "ADD COLUMN assigned_agent TEXT DEFAULT 'Any'"
                )
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
                     intelligence_tier="Unknown", supports_tools=False,
                     assigned_agent="Any"):
        with self._lock:
            enc_key = self._encrypt(api_key)
            cursor = self._conn.cursor()
            cursor.execute("""
                INSERT INTO providers
                (name, base_url, api_key_encrypted, model_name, is_local, is_active,
                 speed_score_ms, intelligence_tier, supports_tools, assigned_agent)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(name) DO UPDATE SET
                base_url=excluded.base_url,
                api_key_encrypted=excluded.api_key_encrypted,
                model_name=excluded.model_name,
                is_local=excluded.is_local,
                is_active=excluded.is_active,
                speed_score_ms=excluded.speed_score_ms,
                intelligence_tier=excluded.intelligence_tier,
                supports_tools=excluded.supports_tools,
                assigned_agent=excluded.assigned_agent
            """, (
                name, base_url, enc_key, model_name, is_local, is_active,
                speed_score_ms, intelligence_tier, supports_tools,
                assigned_agent or "Any",
            ))
            self._conn.commit()
            cursor.execute("SELECT id FROM providers WHERE name = ?", (name,))
            row = cursor.fetchone()
            return row["id"] if row else cursor.lastrowid

    def _provider_from_row(self, row):
        """Build a provider without disguising credential decryption failures."""
        provider = dict(row)
        name = provider.get("name") or "Unknown"
        try:
            provider["api_key"] = self._decrypt(provider["api_key_encrypted"])
        except InvalidToken:
            provider["api_key"] = None
            provider["decryption_error"] = DECRYPTION_ERROR
            self.decryption_errors[name] = DECRYPTION_ERROR
        else:
            provider["decryption_error"] = None
            self.decryption_errors.pop(name, None)
        provider["assigned_agent"] = provider.get("assigned_agent") or "Any"
        for field in ("is_local", "is_active", "supports_tools"):
            provider[field] = bool(provider[field])
        return provider

    def get_active_providers(self):
        with self._lock:
            cursor = self._conn.cursor()
            cursor.execute("SELECT * FROM providers WHERE is_active = 1")
            rows = cursor.fetchall()
            self.decryption_errors = {}
            providers = []
            for row in rows:
                provider = self._provider_from_row(row)
                if provider["decryption_error"] is None:
                    providers.append(provider)
            return providers

    def get_all_providers(self):
        """Return providers, marking credentials that need recovery as unavailable."""
        with self._lock:
            cursor = self._conn.cursor()
            cursor.execute("SELECT * FROM providers")
            rows = cursor.fetchall()
            self.decryption_errors = {}
            return [self._provider_from_row(row) for row in rows]

    def delete_provider(self, name: str) -> bool:
        """Delete a provider by name."""
        with self._lock:
            cursor = self._conn.cursor()
            cursor.execute("DELETE FROM providers WHERE name = ?", (name,))
            self._conn.commit()
            return cursor.rowcount > 0

    def get_provider(self, name):
        """Return one provider, explicitly marking an undecryptable API key."""
        with self._lock:
            cursor = self._conn.cursor()
            cursor.execute("SELECT * FROM providers WHERE name = ?", (name,))
            row = cursor.fetchone()
            if row is None:
                return None
            return self._provider_from_row(row)

    def update_provider_fields(self, name, **fields):
        """Update whitelisted provider fields and commit the change."""
        allowed_fields = {
            "base_url", "model_name", "is_local", "is_active",
            "speed_score_ms", "intelligence_tier", "supports_tools",
            "assigned_agent", "cooldown_until", "failure_count",
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
        global _db_instance
        if _db_instance is self:
            _db_instance = None

# ── Singleton Helpers ────────────────────────────────────────────────────

_db_instance = None

def init_db(db_path: str = DB_PATH, key_path: str = KEY_PATH, force_new: bool = False):
    """Initialize the global database instance for the exact DB and key paths."""
    global _db_instance
    paths_changed = (
        db_path != getattr(_db_instance, "db_path", None)
        or key_path != getattr(_db_instance, "key_path", None)
    )
    if _db_instance is None or force_new or paths_changed:
        previous = _db_instance
        instance = DatabaseManager(db_path, key_path)
        _db_instance = instance
        if previous is not None:
            previous.close()
    return _db_instance

def get_db():
    """Retrieve the global database instance."""
    global _db_instance
    if _db_instance is None:
        raise RuntimeError("Database not initialized. Call init_db() first.")
    return _db_instance
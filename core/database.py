"""
STEWARD v2 - Native API Manager Database & Security Layer

Thread-safe SQLite database with AES-128 encryption (Fernet) for API keys.
"""

import sqlite3
import json
import threading
import os
import uuid
import urllib.parse
from datetime import datetime, timezone, timedelta
from cryptography.fernet import Fernet, InvalidToken

DB_PATH = os.path.join(os.getcwd(), "steward.db")
KEY_PATH = os.path.join(os.getcwd(), "secret.key")

DECRYPTION_ERROR = (
    "Stored API key cannot be decrypted. Restore the matching secret.key "
    "or re-enter the provider's API key."
)

def normalize_base_url(url: str) -> str:
    """Normalize base URL: strip whitespace, trailing slashes, and lowercase scheme + host."""
    if not url:
        return ""
    url = url.strip().rstrip("/")
    parsed = urllib.parse.urlsplit(url)
    scheme = parsed.scheme.lower()
    netloc = parsed.netloc.lower()
    path = parsed.path.rstrip("/")
    return urllib.parse.urlunsplit((scheme, netloc, path, "", ""))

class DatabaseManager:
    def __init__(self, db_path: str = DB_PATH, key_path: str = KEY_PATH):
        self.db_path = db_path
        self.key_path = key_path
        self._lock = threading.Lock()
        self._key = self._load_or_create_key()
        self._cipher = Fernet(self._key)
        self._conn = sqlite3.connect(self.db_path, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA foreign_keys = ON")
        self.decryption_errors = {}
        self._create_tables()

    def _load_or_create_key(self) -> bytes:
        if os.path.exists(self.key_path):
            with open(self.key_path, "rb") as f:
                return f.read()
        elif os.path.exists(self.db_path):
            raise RuntimeError(
                f"Database exists at '{self.db_path}' but secret.key is missing at '{self.key_path}'. "
                "Refusing to generate a new key to avoid permanent loss of encrypted data."
            )
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
            # Credentials table
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS credentials (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    base_url_normalized TEXT NOT NULL,
                    api_key_encrypted BLOB NOT NULL,
                    label TEXT,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                )
            """)

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
                    failure_count INTEGER DEFAULT 0,
                    credential_id INTEGER REFERENCES credentials(id) ON DELETE SET NULL
                )
            """)
            cursor.execute("PRAGMA table_info(providers)")
            provider_columns = {row["name"] for row in cursor.fetchall()}
            if "assigned_agent" not in provider_columns:
                cursor.execute(
                    "ALTER TABLE providers "
                    "ADD COLUMN assigned_agent TEXT DEFAULT 'Any'"
                )
            if "credential_id" not in provider_columns:
                cursor.execute(
                    "ALTER TABLE providers "
                    "ADD COLUMN credential_id INTEGER REFERENCES credentials(id) ON DELETE SET NULL"
                )
            cursor.execute("""
                CREATE INDEX IF NOT EXISTS idx_providers_credential_id 
                ON providers(credential_id)
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

    def get_credential_by_url(self, base_url: str):
        """Retrieve credential by base URL (normalized). Prefers credentials linked to active providers."""
        norm_url = normalize_base_url(base_url)
        if not norm_url:
            return None
        with self._lock:
            cursor = self._conn.cursor()
            # Prefer credential linked to an active, fast provider
            cursor.execute("""
                SELECT c.* FROM credentials c
                JOIN providers p ON p.credential_id = c.id
                WHERE c.base_url_normalized = ? AND p.is_active = 1
                ORDER BY p.speed_score_ms ASC
                LIMIT 1
            """, (norm_url,))
            row = cursor.fetchone()
            if not row:
                cursor.execute("SELECT * FROM credentials WHERE base_url_normalized = ? LIMIT 1", (norm_url,))
                row = cursor.fetchone()
            if not row:
                return None
            cred = dict(row)
            try:
                cred["api_key"] = self._decrypt(cred["api_key_encrypted"])
            except InvalidToken:
                cred["api_key"] = None
                cred["decryption_error"] = DECRYPTION_ERROR
            else:
                cred["decryption_error"] = None
            return cred

    def get_credential_by_id(self, cred_id: int):
        """Retrieve credential by ID."""
        if cred_id is None:
            return None
        with self._lock:
            cursor = self._conn.cursor()
            cursor.execute("SELECT * FROM credentials WHERE id = ?", (cred_id,))
            row = cursor.fetchone()
            if not row:
                return None
            cred = dict(row)
            try:
                cred["api_key"] = self._decrypt(cred["api_key_encrypted"])
            except InvalidToken:
                cred["api_key"] = None
                cred["decryption_error"] = DECRYPTION_ERROR
            else:
                cred["decryption_error"] = None
            return cred

    def get_all_credentials(self):
        """Retrieve all credentials."""
        with self._lock:
            cursor = self._conn.cursor()
            cursor.execute("SELECT * FROM credentials")
            rows = cursor.fetchall()
            results = []
            for row in rows:
                cred = dict(row)
                try:
                    cred["api_key"] = self._decrypt(cred["api_key_encrypted"])
                except InvalidToken:
                    cred["api_key"] = None
                    cred["decryption_error"] = DECRYPTION_ERROR
                else:
                    cred["decryption_error"] = None
                results.append(cred)
            return results

    def set_credential(self, base_url: str, api_key: str, label: str = "") -> int:
        """Create or update the canonical shared credential for a base URL. Returns credential ID."""
        norm_url = normalize_base_url(base_url)
        if not norm_url:
            raise ValueError("base_url is required for set_credential")
        enc_key = self._encrypt(api_key) if api_key else b""
        now = datetime.now(timezone.utc).isoformat()
        with self._lock:
            cursor = self._conn.cursor()
            # Find existing credential for this URL (take the oldest/canonical one)
            cursor.execute("SELECT id, label FROM credentials WHERE base_url_normalized = ? ORDER BY id ASC LIMIT 1", (norm_url,))
            row = cursor.fetchone()
            if row:
                # Update the existing canonical credential (handles key rotation)
                cursor.execute("""
                    UPDATE credentials SET api_key_encrypted = ?, label = ?, updated_at = ? WHERE id = ?
                """, (enc_key, label or row["label"], now, row["id"]))
                self._conn.commit()
                return row["id"]
            else:
                # No credential exists for this URL; create it
                cursor.execute("""
                    INSERT INTO credentials (base_url_normalized, api_key_encrypted, label, created_at, updated_at)
                    VALUES (?, ?, ?, ?, ?)
                """, (norm_url, enc_key, label, now, now))
                cred_id = cursor.lastrowid
                self._conn.commit()
                return cred_id
        
    def delete_credential(self, cred_id: int) -> bool:
        """Delete a credential by ID. Referencing providers have credential_id set to NULL via ON DELETE SET NULL."""
        with self._lock:
            cursor = self._conn.cursor()
            cursor.execute("DELETE FROM credentials WHERE id = ?", (cred_id,))
            self._conn.commit()
            return cursor.rowcount > 0

    def add_provider(self, name, base_url, api_key, model_name="",
                     is_local=False, is_active=True, speed_score_ms=9999,
                     intelligence_tier="Unknown", supports_tools=False,
                     assigned_agent="Any", credential_id=None):
        with self._lock:
            norm_url = normalize_base_url(base_url)
            enc_key = self._encrypt(api_key) if api_key else b""
            cursor = self._conn.cursor()

            # Resolve or associate credential_id if not given explicitly
            if credential_id is None and not is_local and norm_url:
                if api_key:
                    # Try to find an existing credential with the SAME key (not just same endpoint)
                    cursor.execute(
                        "SELECT id, api_key_encrypted FROM credentials WHERE base_url_normalized = ?",
                        (norm_url,)
                    )
                    for cred_row in cursor.fetchall():
                        try:
                            existing_key = self._decrypt(cred_row["api_key_encrypted"])
                            if existing_key == api_key:
                                credential_id = cred_row["id"]
                                enc_key = cred_row["api_key_encrypted"]
                                break
                        except InvalidToken:
                            continue
                    
                    if credential_id is None:
                        # No matching credential found; create a new one
                        now = datetime.now(timezone.utc).isoformat()
                        cursor.execute("""
                            INSERT INTO credentials (base_url_normalized, api_key_encrypted, label, created_at, updated_at)
                            VALUES (?, ?, ?, ?, ?)
                        """, (norm_url, enc_key, name, now, now))
                        credential_id = cursor.lastrowid
                else:
                    cursor.execute("SELECT id, api_key_encrypted FROM credentials WHERE base_url_normalized = ?", (norm_url,))
                    existing_cred = cursor.fetchone()
                    if existing_cred:
                        credential_id = existing_cred["id"]
                        enc_key = existing_cred["api_key_encrypted"]

            cursor.execute("""
                INSERT INTO providers
                (name, base_url, api_key_encrypted, model_name, is_local, is_active,
                 speed_score_ms, intelligence_tier, supports_tools, assigned_agent, credential_id)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(name) DO UPDATE SET
                base_url=excluded.base_url,
                api_key_encrypted=excluded.api_key_encrypted,
                model_name=excluded.model_name,
                is_local=excluded.is_local,
                is_active=excluded.is_active,
                speed_score_ms=excluded.speed_score_ms,
                intelligence_tier=excluded.intelligence_tier,
                supports_tools=excluded.supports_tools,
                assigned_agent=excluded.assigned_agent,
                credential_id=excluded.credential_id
            """, (
                name, base_url, enc_key, model_name, is_local, is_active,
                speed_score_ms, intelligence_tier, supports_tools,
                assigned_agent or "Any", credential_id
            ))
            self._conn.commit()
            cursor.execute("SELECT id FROM providers WHERE name = ?", (name,))
            row = cursor.fetchone()
            return row["id"] if row else cursor.lastrowid

    def _provider_from_row(self, row):
        """Build a provider without disguising credential decryption failures.
        Dual-read: prefer joined/referenced credential; fall back to legacy column.
        """
        provider = dict(row)
        name = provider.get("name") or "Unknown"
        cred_id = provider.get("credential_id")
        encrypted_blob = None
        dangling_cred = False

        if cred_id is not None:
            cursor = self._conn.cursor()
            cursor.execute("SELECT * FROM credentials WHERE id = ?", (cred_id,))
            cred_row = cursor.fetchone()
            if cred_row is not None:
                encrypted_blob = cred_row["api_key_encrypted"]
                provider["credential_label"] = cred_row["label"]
                provider["credential_base_url"] = cred_row["base_url_normalized"]
                # A referenced keyless credential must not hide a valid legacy
                # provider key. Invalid encrypted data is intentionally *not*
                # bypassed: it indicates a key mismatch and must be recoverable.
                if not encrypted_blob:
                    encrypted_blob = provider.get("api_key_encrypted")
            else:
                dangling_cred = True
        else:
            encrypted_blob = provider.get("api_key_encrypted")

        if dangling_cred:
            provider["api_key"] = None
            provider["decryption_error"] = "Credential reference missing or unassigned"
            self.decryption_errors[name] = provider["decryption_error"]
        elif not encrypted_blob:
            provider["api_key"] = ""
            provider["decryption_error"] = None
            self.decryption_errors.pop(name, None)
        else:
            try:
                provider["api_key"] = self._decrypt(encrypted_blob)
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
        global _db_instance
        with _db_lock:
            with self._lock:
                self._conn.close()
            if _db_instance is self:
                _db_instance = None

    def migrate_to_shared_credentials(self):
        return migrate_to_shared_credentials(self)

    def rollback_from_shared_credentials(self):
        return rollback_from_shared_credentials(self)

# ── Migration & Rollback Logic ──────────────────────────────────────────

def _precedence_key(p):
    """Sort key for conflict resolution:
    1. Active (0) wins over inactive (1)
    2. Lower valid speed_score_ms wins (speed <= 0 or None treated as 9999)
    3. Alphabetical name as deterministic tie-breaker
    """
    active_rank = 0 if p.get("is_active") else 1
    speed = p.get("speed_score_ms")
    if speed is None or speed <= 0:
        speed = 9999
    name = p.get("name") or ""
    return (active_rank, speed, name)


def migrate_to_shared_credentials(db: DatabaseManager | None = None) -> dict:
    """Migrate legacy providers to the shared credentials table inside a single BEGIN IMMEDIATE transaction.
    
    Idempotent: running multiple times yields the same database state.
    """
    if db is None:
        db = get_db()

    with db._lock:
        conn = db._conn
        prev_isolation = conn.isolation_level
        conn.isolation_level = None  # Autocommit mode to allow explicit BEGIN IMMEDIATE
        cursor = conn.cursor()
        cursor.execute("BEGIN IMMEDIATE")
        try:
            # 1. Ensure schema is ready
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS credentials (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    base_url_normalized TEXT NOT NULL,
                    api_key_encrypted BLOB NOT NULL,
                    label TEXT,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                )
            """)
            cursor.execute("PRAGMA table_info(providers)")
            columns = {row["name"] for row in cursor.fetchall()}
            if "credential_id" not in columns:
                cursor.execute(
                    "ALTER TABLE providers ADD COLUMN credential_id INTEGER REFERENCES credentials(id) ON DELETE SET NULL"
                )
            cursor.execute(
                "CREATE INDEX IF NOT EXISTS idx_providers_credential_id ON providers(credential_id)"
            )

            # 2. Fetch all providers
            cursor.execute("SELECT * FROM providers")
            raw_providers = [dict(r) for r in cursor.fetchall()]

            # 3. Group by normalized base_url
            endpoints: dict[str, list[dict]] = {}
            for p in raw_providers:
                if p.get("is_local"):
                    cursor.execute("UPDATE providers SET credential_id = NULL WHERE id = ?", (p["id"],))
                    continue
                url = normalize_base_url(p.get("base_url") or "")
                if not url:
                    cursor.execute("UPDATE providers SET credential_id = NULL WHERE id = ?", (p["id"],))
                    continue
                endpoints.setdefault(url, []).append(p)

            now = datetime.now(timezone.utc).isoformat()
            endpoints_migrated = 0
            credentials_created = 0
            providers_linked = 0

            # 4. Process each endpoint
            for norm_url, prov_list in endpoints.items():
                endpoints_migrated += 1
                key_groups: dict[bytes, list[dict]] = {}
                keyless_or_undecryptable: list[dict] = []

                for p in prov_list:
                    raw_blob = p.get("api_key_encrypted")
                    if not raw_blob:
                        keyless_or_undecryptable.append(p)
                        continue
                    try:
                        dec_key = db._decrypt(raw_blob)
                    except InvalidToken:
                        keyless_or_undecryptable.append(p)
                        continue
                    key_groups.setdefault(dec_key, []).append((p, raw_blob))

                # Create one credential per distinct DECRYPTED key
                for dec_key, providers_with_this_key in key_groups.items():
                    winner = min([item[0] for item in providers_with_this_key], key=_precedence_key)
                    label = winner["name"]
                    # Use the winner's encrypted blob for the canonical credential
                    winner_blob = next(item[1] for item in providers_with_this_key if item[0] == winner)
                    
                    # Idempotency: check if a credential with this exact decrypted key already exists
                    existing_cred_id = None
                    cursor.execute("SELECT id, api_key_encrypted FROM credentials WHERE base_url_normalized = ?", (norm_url,))
                    for c_row in cursor.fetchall():
                        try:
                            if db._decrypt(c_row["api_key_encrypted"]) == dec_key:
                                existing_cred_id = c_row["id"]
                                break
                        except InvalidToken:
                            continue
                    
                    if existing_cred_id is not None:
                        cred_id = existing_cred_id
                    else:
                        cursor.execute("""
                            INSERT INTO credentials (base_url_normalized, api_key_encrypted, label, created_at, updated_at)
                            VALUES (?, ?, ?, ?, ?)
                        """, (norm_url, winner_blob, label, now, now))
                        cred_id = cursor.lastrowid
                        credentials_created += 1
                    
                    for p, _ in providers_with_this_key:
                        cursor.execute("UPDATE providers SET credential_id = ? WHERE id = ?", (cred_id, p["id"]))
                        providers_linked += 1

                for p in keyless_or_undecryptable:
                    cursor.execute("UPDATE providers SET credential_id = NULL WHERE id = ?", (p["id"],))

            cursor.execute("COMMIT")
            return {
                "endpoints_migrated": endpoints_migrated,
                "credentials_created": credentials_created,
                "providers_linked": providers_linked,
            }
        except Exception:
            cursor.execute("ROLLBACK")
            raise
        finally:
            conn.isolation_level = prev_isolation


def rollback_from_shared_credentials(db: DatabaseManager | None = None) -> dict:
    """Reverse migration to shared credentials.
    
    Populates legacy api_key_encrypted from joined credentials and sets
    credential_id = NULL on all providers. Does NOT drop credentials table.
    """
    if db is None:
        db = get_db()

    with db._lock:
        conn = db._conn
        prev_isolation = conn.isolation_level
        conn.isolation_level = None
        cursor = conn.cursor()
        cursor.execute("BEGIN IMMEDIATE")
        try:
            cursor.execute("""
                SELECT p.id, c.api_key_encrypted 
                FROM providers p 
                JOIN credentials c ON p.credential_id = c.id
                WHERE p.credential_id IS NOT NULL
            """)
            joined_rows = cursor.fetchall()
            restored_count = 0
            for row in joined_rows:
                cursor.execute("""
                    UPDATE providers SET
                        api_key_encrypted = ?,
                        credential_id = NULL
                    WHERE id = ?
                """, (row["api_key_encrypted"], row["id"]))
                restored_count += 1

            cursor.execute("""
                UPDATE providers SET credential_id = NULL WHERE credential_id IS NOT NULL
            """)
            cursor.execute("COMMIT")
            return {"providers_restored": restored_count}
        except Exception:
            cursor.execute("ROLLBACK")
            raise
        finally:
            conn.isolation_level = prev_isolation

# ── Singleton Helpers ────────────────────────────────────────────────────

_db_instance = None
_db_lock = threading.RLock()

def init_db(db_path: str = DB_PATH, key_path: str = KEY_PATH, force_new: bool = False):
    """Initialize the global database instance for the exact DB and key paths."""
    global _db_instance
    with _db_lock:
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
    with _db_lock:
        if _db_instance is None:
            raise RuntimeError("Database not initialized. Call init_db() first.")
        return _db_instance
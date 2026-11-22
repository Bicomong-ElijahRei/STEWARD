# STEWARD — Batch 4b: Credential Store Safety Review & Architecture Design

**Document Status:** Pending Owner Review (Awaiting approval before Batch 4c implementation)  
**Target Subsystem:** `core/database.py`, `core/router.py`, `gui/settings_tab.py`, `core/discovery.py`  
**Current HEAD:** `3f0ed7d1`  
**Applicable Rules:** `.clinerules`, `PLAN.md` (Cross-cutting v2.1 backlog: Shared Credential Store)

---

## Executive Summary

Currently in STEWARD, API keys are encrypted individually per row in the `providers` table (`providers.api_key_encrypted`). When a user adds multiple models from the same endpoint provider (e.g. OpenRouter, Groq, Anthropic, or an OpenAI-compatible gateway), the identical API key is duplicated across $N$ rows. Rotating or fixing an expired key requires manual updates across all $N$ rows, and catalog discovery (`core/discovery.py`) currently relies on an interim GUI workaround (`_find_reusable_key` in `gui/settings_tab.py`) to copy keys from sibling rows.

The proposed feature introduces a dedicated `credentials` table keyed by normalized base URL (`base_url_normalized`), transforming the relationship between endpoints and providers into a normalized 1-to-$N$ foreign-key relationship (`providers.credential_id -> credentials.id`).

Per STEWARD architectural safety mandates, this document delivers a comprehensive security, cryptographic, operational, and schema review prior to executing any schema migration or code modifications in Batch 4c.

---

## 1. SCHEMA DESIGN

### 1.1 Existing Schema (Baseline)

In the current schema (`core/database.py`), the `providers` table maintains an encrypted API key column directly:

```sql
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
);
```

### 1.2 Proposed Schema Additions & Changes

#### New Table: `credentials`
A dedicated credential store holding distinct endpoint secrets:

```sql
CREATE TABLE IF NOT EXISTS credentials (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    base_url_normalized TEXT UNIQUE NOT NULL,
    api_key_encrypted BLOB NOT NULL,
    label TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE UNIQUE INDEX IF NOT EXISTS idx_credentials_base_url_normalized 
    ON credentials(base_url_normalized);
```

#### Alterations to `providers`
The `providers` table is updated to reference `credentials.id`:

```sql
-- Transitional dual-schema column addition
ALTER TABLE providers ADD COLUMN credential_id INTEGER 
    REFERENCES credentials(id) ON DELETE SET NULL;

CREATE INDEX IF NOT EXISTS idx_providers_credential_id 
    ON providers(credential_id);
```

### 1.3 Key Architectural Design Decisions

1. **`credentials.id` Autoincrement:**
   - **Decision:** `credentials.id` MUST be defined as `INTEGER PRIMARY KEY AUTOINCREMENT`.
   - **Rationale:** Standard `INTEGER PRIMARY KEY` in SQLite reuses vacant IDs if rows are deleted. By enforcing `AUTOINCREMENT`, SQLite guarantees strictly monotonic ID allocation (tracking the highest allocated ID in `sqlite_sequence`). This eliminates "dangling reference re-capture" bugs where a deleted credential ID might otherwise be reassigned to a newly added credential for an unrelated endpoint.

2. **Foreign Key Enforcement (SQLite vs. Application Code):**
   - **Decision:** Dual-layer enforcement (SQLite engine enforcement + defensive application validation).
   - **SQLite Engine Enforcement:** By default, SQLite turns foreign key constraints OFF on every connection (`PRAGMA foreign_keys` defaults to `0`). In `DatabaseManager.__init__` and any auxiliary connections, `PRAGMA foreign_keys = ON;` must be executed immediately after `sqlite3.connect()`.
   - **Constraint Behavior:** The foreign key constraint specifies `ON DELETE SET NULL`. If a credential record is explicitly deleted, all referencing provider rows have their `credential_id` reset to `NULL` rather than causing an unhandled cascading error or leaving invalid pointer references.
   - **Application Code Enforcement:** Even if SQLite foreign key pragmas fail to run (e.g. in external debug shells or third-party SQLite viewers), `DatabaseManager._provider_from_row()` and `add_provider()` defensively validate `credential_id` references. If a provider's `credential_id` cannot be resolved in `credentials`, the application treats the provider as entering a recoverable state (`api_key = None`, `decryption_error = "Credential missing or unassigned"`), preventing crashes.

3. **URL Normalization Specification:**
   - Base URLs must be deterministically normalized using standard semantics:
     ```python
     def normalize_base_url(url: str) -> str:
         if not url:
             return ""
         url = url.strip().rstrip("/")
         # Ensure scheme and netloc are case-insensitive lowercase
         parsed = urllib.parse.urlsplit(url)
         scheme = parsed.scheme.lower()
         netloc = parsed.netloc.lower()
         path = parsed.path.rstrip("/")
         return urllib.parse.urlunsplit((scheme, netloc, path, "", ""))
     ```
   - Examples:
     - `https://OpenRouter.AI/api/v1/` $\to$ `https://openrouter.ai/api/v1`
     - `http://localhost:11434/v1/` $\to$ `http://localhost:11434/v1`

---

## 2. MIGRATION PLAN

### 2.1 Atomic Step-by-Step Execution

SQLite supports transactional DDL. The schema migration must execute inside a single atomic `BEGIN IMMEDIATE` transaction to eliminate concurrency race conditions.

```
+-------------------------------------------------------------+
| Step 1: Pre-flight Verification                             |
|  - Verify secret.key exists and decrypts a canary/sample    |
|  - Check database lock status                               |
+-------------------------------------------------------------+
                              |
+-------------------------------------------------------------+
| Step 2: Out-of-Tree Physical Backup                         |
|  - Copy steward.db and secret.key to %APPDATA%\STEWARD\...  |
|  - Compute and record SHA256 checksums                      |
+-------------------------------------------------------------+
                              |
+-------------------------------------------------------------+
| Step 3: Transactional Migration (BEGIN IMMEDIATE)           |
|  - CREATE TABLE IF NOT EXISTS credentials                   |
|  - CREATE UNIQUE INDEX idx_credentials_base_url_normalized  |
|  - ALTER TABLE providers ADD COLUMN credential_id           |
|  - Extract, normalize, and populate distinct credentials    |
|  - Backfill providers.credential_id                         |
|  - Verify row count and mapping integrity                   |
|  - COMMIT                                                   |
+-------------------------------------------------------------+
                              |
+-------------------------------------------------------------+
| Step 4: Post-Migration Validation                           |
|  - Verify all active providers decrypt correctly            |
|  - Run test suite against migrated database                 |
+-------------------------------------------------------------+
```

### 2.2 Migration SQL & Logic

```sql
BEGIN IMMEDIATE;

-- 1. Create the new credentials table
CREATE TABLE IF NOT EXISTS credentials (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    base_url_normalized TEXT UNIQUE NOT NULL,
    api_key_encrypted BLOB NOT NULL,
    label TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE UNIQUE INDEX IF NOT EXISTS idx_credentials_base_url_normalized 
    ON credentials(base_url_normalized);

-- 2. Add foreign key column to providers (if not already present)
-- Handled via Python PRAGMA table_info inspection before ALTER TABLE
-- ALTER TABLE providers ADD COLUMN credential_id INTEGER REFERENCES credentials(id) ON DELETE SET NULL;

COMMIT;
```

Data migration occurs within the same or subsequent atomic transaction:
1. Scan `providers`:
   - Group rows by `normalize_base_url(base_url)`.
   - Filter out empty keys (`b""` or `NULL`) and local endpoints (`is_local = 1`).
2. Insert distinct endpoint credentials into `credentials`.
3. Update `providers.credential_id` with the generated `credentials.id`.

### 2.3 Roll Forward vs. Roll Back Strategy

- **Roll Forward:**
  - If a migration step encounters an unexpected state (e.g. unexpected column type or schema variant), the migration transaction executes `ROLLBACK`, leaving the original database untouched.
  - Fixes are addressed in code, and the migration re-attempts forward execution.
- **Roll Back:**
  - In the event of an operational regression in production post-migration:
    1. Close all active database connections.
    2. Execute reverse migration script: copies `credentials.api_key_encrypted` back to `providers.api_key_encrypted` (if modified during runtime), drops `credentials` table, or restores directly from the pre-migration atomic backup.
    3. The backup restoration guarantees 100% byte-for-byte fidelity.

### 2.4 Halfway Crash Analysis

- If the application process crashes, the OS terminates, or power fails halfway through the migration:
  - Because migration occurs under `BEGIN IMMEDIATE` in SQLite with rollback journal / WAL, SQLite's atomic write-ahead log automatically rolls back the uncommitted transaction upon next connection.
  - No partial schema or orphaned `credential_id` columns can exist without a completed commit.

### 2.5 Dual-Schema Transitional State ("Both Schemas Readable")

To prevent any breaking changes during the transition:
- **Dual-Read Policy in `DatabaseManager._provider_from_row`:**
  ```python
  if row.get("credential_id") is not None:
      # Primary path: look up via credentials table
      cred = self._get_credential_by_id(row["credential_id"])
      encrypted_blob = cred["api_key_encrypted"] if cred else None
  else:
      # Fallback path: legacy per-row encrypted key
      encrypted_blob = row.get("api_key_encrypted")
  ```
- **Dual-Write Policy during transition:**
  When `add_provider` or `update_provider` is called:
  1. Upsert into `credentials` table.
  2. Set `credential_id` on `providers`.
  3. Mirror ciphertext into legacy `api_key_encrypted` column for zero-downtime rollback capability during Phase 4c.

---

## 3. BACKUP STRATEGY

### 3.1 Backup Location (Outside Working Directory)

Per STEWARD architectural safety rules (`.clinerules` and `PLAN.md`), live runtime files (`steward.db`, `secret.key`) must never be endangered by repository cleanups, git resets, or agent file tool wipes.

- **Primary Backup Root:**  
  `%APPDATA%\STEWARD\backups\`  
  Full Windows path: `C:\Users\<USER>\AppData\Roaming\STEWARD\backups\`
- **Fallback Directory (if APPDATA is unset):**  
  `os.path.expanduser("~/.steward/backups/")`

Backups must **NEVER** be saved within `C:\Users\WELCOME\Desktop\STEWARD\` or any repo subfolder.

### 3.2 Backup Naming Convention

Backup files are stamped with UTC timestamps and the current git HEAD commit SHA:
- Database snapshot: `steward_backup_YYYYMMDD_HHMMSS_<commit_sha>.db`
- Encryption key snapshot: `steward_backup_YYYYMMDD_HHMMSS_<commit_sha>.key`
- Verification Manifest: `steward_backup_YYYYMMDD_HHMMSS_<commit_sha>.json`

**Manifest Structure:**
```json
{
  "timestamp": "2026-11-22T14:45:00Z",
  "commit_sha": "3f0ed7d1",
  "db_sha256": "E67C3B4452CAF0015DCD573955F16B7791A905652002D665648A94683DDF2B5A",
  "key_sha256": "B7FD62B31B442CCEA167BF73B6607BB05CC3D093ECBF5D1111961BC8DFF09ADE",
  "provider_count": 16,
  "tables": ["providers", "usage_ledger", "traces"],
  "format_version": 1
}
```

### 3.3 Restoration Procedure

1. **Terminate Application:** Ensure the STEWARD GUI and any background agent threads are completely halted.
2. **Verify Backup Integrity:** Validate that `db_sha256` and `key_sha256` in the manifest match the backup files:
   ```powershell
   Get-FileHash steward_backup_*.db, steward_backup_*.key
   ```
3. **Quarantine Existing Files:** Rename existing `steward.db` to `steward.db.corrupt.<timestamp>`.
4. **Copy Backup Files:** Copy the verified backup files back to the application runtime root (`steward.db` and `secret.key`).
5. **Database Integrity Check:** Run SQLite internal verification:
   ```sql
   PRAGMA integrity_check;
   PRAGMA foreign_key_check;
   ```

---

## 4. CRYPTOGRAPHIC IMPACT

### 4.1 Encryption Algorithm & Payload Structure

- **Cryptographic Primitive:** AES-128-CBC with PKCS7 padding and HMAC-SHA256 authentication (via `cryptography.fernet.Fernet`).
- **Encrypted Content:** The raw UTF-8 string representation of the API key (e.g. `sk-or-v1-...`).
- **Impact of Proposed Schema:** **None on the cipher layer.** Fernet still encrypts and decrypts identical plaintext strings. The ciphertext token format (`Version (1B) || Timestamp (8B) || IV (16B) || Ciphertext (variable) || HMAC (32B)`) remains completely identical.

### 4.2 Key Binding & Authentication Context

- Fernet does not support Associated Authenticated Data (AAD). Ciphertexts are not cryptographically bound to table names, column names, row IDs, or URLs.
- Moving the ciphertext blob from `providers.api_key_encrypted` to `credentials.api_key_encrypted` introduces **no cryptographic format change**. The ciphertext generated in `providers` can be moved directly to `credentials` without re-encrypting, provided the identical `secret.key` is used.
- However, for defense-in-depth and verification during migration, decrypting and re-encrypting under fresh Fernet IVs confirms that `secret.key` is currently valid and active.

### 4.3 Key Confusion & Wrong-Key Decryption Scenarios

- **Key Rotation / Mismatch:** If `secret.key` is rotated or replaced, Fernet's HMAC authentication detects the mismatch and raises `cryptography.fernet.InvalidToken`.
- **Batch 2A M4 Compatibility:** Batch 2A M4 established that invalid tokens must never raise uncaught exceptions or cause application crashes; instead, the provider must transition to a recoverable degraded state:
  ```python
  try:
      provider["api_key"] = self._decrypt(cred["api_key_encrypted"])
  except InvalidToken:
      provider["api_key"] = None
      provider["decryption_error"] = DECRYPTION_ERROR
  ```
- Under the new design, if a shared credential fails decryption, all providers referencing that `credential_id` inherit the recoverable state cleanly and uniformly.

---

## 5. BLAST RADIUS

### 5.1 Code Path Enumeration

The following code paths interact with credentials and must be audited/updated in Batch 4c:

1. **`core/database.py`:**
   - `DatabaseManager._create_tables()`: Create `credentials` table, add `credential_id` column to `providers`.
   - `DatabaseManager.add_provider()`: Must resolve/insert normalized endpoint in `credentials` and assign `credential_id`.
   - `DatabaseManager._provider_from_row()`: Must join or look up `credentials` and populate `provider["api_key"]`.
   - `DatabaseManager.get_active_providers()`: Selects active providers, filters out decryption errors.
   - `DatabaseManager.get_all_providers()`: Retrieves all providers with decrypted keys or recovery states.
   - `DatabaseManager.get_provider(name)`: Retrieves single provider with decrypted key.
   - `DatabaseManager.delete_provider(name)`: Deletes provider row; must handle foreign key references cleanly.
   - New database helper methods: `get_credential_by_url()`, `set_credential()`, `get_all_credentials()`, `delete_credential()`.

2. **`core/router.py`:**
   - `APIManager.route_request()`: Calls `get_active_providers()`, injects `Authorization: Bearer {provider['api_key']}`. No direct database query modifications needed if `provider["api_key"]` dictionary contract is preserved.

3. **`core/validator.py`:**
   - `validate_provider()`, `health_check()`, `intelligence_probe()`, `tool_calling_check()`: Receive `api_key` as function argument. Signatures remain unchanged.

4. **`core/discovery.py`:**
   - `upsert_discovered_models()`: Currently inserts discovered models with `api_key=""` and `is_active=False`. Updated to link discovered models to existing `credential_id` for `https://openrouter.ai/api/v1` if a credential already exists.

5. **`gui/settings_tab.py`:**
   - `_find_reusable_key()`: Legacy helper searching sibling provider rows. Will be replaced by direct query to `credentials` table.
   - `_on_validation_complete()`: Saves provider and its endpoint credential.
   - `_toggle_provider()`: Validates whether provider has an assigned credential before activation.
   - `_on_provider_activation_complete()`: Links validated key to shared credential.

### 5.2 Blast Radius Quantification

| Attribute | Legacy Architecture (Per-Row Key) | Proposed Architecture (Shared Credential Store) |
| :--- | :--- | :--- |
| **Storage Multiplicity** | $N$ identical ciphertexts stored for $N$ models on 1 endpoint | 1 canonical ciphertext stored per endpoint |
| **Key Rotation Effort** | Update $N$ separate rows manually | Update 1 credential row; instantly inherited by $N$ models |
| **Credential Invalidation** | If 1 row is corrupted, only that 1 model fails | If 1 credential is corrupted or revoked, all $N$ models on that endpoint fail |
| **Mitigation for Blast Radius** | User had to diagnose multiple failing models independently | Single health status indicator for the endpoint; router automatically cascades to alternative providers (e.g. Gemini, Groq, Ollama) |

**Quantified Risk:** If a user configures 20 OpenRouter models, the failure blast radius of a bad key grows from 1 model to 20 models. However, this is identical to real-world semantics (if the OpenRouter API key is revoked, all 20 models are unusable regardless). Centralization ensures the user rotates the key **once** to fix all 20 models simultaneously, rather than experiencing 19 lingering failures.

---

## 6. MIGRATION OF EXISTING DATA

### 6.1 Extraction and Re-encryption of 16 Existing Rows

The live database currently holds 16 provider rows. The migration procedure executes as follows:

1. **Extraction:**
   - Query all rows from `providers` with `api_key_encrypted IS NOT NULL` and `length(api_key_encrypted) > 0`.
   - Decrypt each key in memory using `DatabaseManager._decrypt()`.
   - Track providers where decryption raises `InvalidToken`.

2. **Categorization & Handling:**

   - **Scenario A: Single Key Shared by $N$ Providers (Normal Case)**
     - Providers with identical normalized `base_url` and identical decrypted `api_key`.
     - *Action:* Insert a single record into `credentials` for that `base_url_normalized`. Point all $N$ providers' `credential_id` to this single record.
   
   - **Scenario B: Conflicting Keys for the Same Base URL (Duplicate / Conflict Case)**
     - Multiple providers share the same `base_url_normalized` but have differing decrypted `api_key` values.
     - *Resolution Precedence Rule:*
       1. Active provider (`is_active = 1`) takes precedence over inactive provider (`is_active = 0`).
       2. If both are active, the provider with the lower valid `speed_score_ms` (most recently/successfully validated) wins.
       3. The winning key becomes the canonical `credentials` entry for that `base_url_normalized`.
       4. Secondary/conflicting keys are assigned a distinct disambiguated credential row with a label (e.g. `label = "Legacy key from <provider_name>"`) or flagged for user review in the UI, ensuring no secret is silently discarded without recourse.

   - **Scenario C: Orphaned / Local / Keyless Providers**
     - Local providers (`is_local = 1`, e.g. Ollama `http://localhost:11434/v1`) or inactive catalog models with empty keys (`""` or `None`).
     - *Action:* These rows are assigned `credential_id = NULL`. Local providers require no credentials. Discovered models remain inactive until assigned a credential.

   - **Scenario D: Decryption Failures during Migration**
     - A provider row whose `api_key_encrypted` cannot be decrypted by current `secret.key`.
     - *Action:* Do not drop the row. Retain `credential_id = NULL` and keep legacy `api_key_encrypted` intact. The provider continues to display as recoverable in the UI, prompting the user to re-enter the API key or restore the original `secret.key`.

### 6.2 Key Rotation Post-Migration

When a user rotates an API key:
- Application calls `db.set_credential(base_url, new_api_key)`.
- The database executes `UPDATE credentials SET api_key_encrypted = ?, updated_at = ? WHERE base_url_normalized = ?`.
- No updates to the `providers` table are necessary. Every provider pointing to that `credential_id` immediately decrypts the new key on its next access.

---

## 7. FAILURE MODES

### 7.1 Interrupted Migration
- **Trigger:** Process killed (`SIGKILL`, power failure, crash) midway through migration.
- **Consequence:** SQLite rollbacks the transaction automatically on the next connection attempt.
- **System State:** Database remains in original un-migrated state. No corruption, no loss of data.

### 7.2 Corrupt `credentials` Table (Intact `providers` Table)
- **Trigger:** Physical disk sector corruption affecting `credentials` B-tree, or manual tampering with `credentials.api_key_encrypted`.
- **Consequence:** `Fernet.decrypt()` raises `InvalidToken`, or query raises `sqlite3.DatabaseError`.
- **System State & Recovery:**
  - `DatabaseManager._provider_from_row()` catches `InvalidToken` and handles database errors gracefully.
  - Providers using the corrupted credential have `provider["api_key"] = None` and `provider["decryption_error"] = DECRYPTION_ERROR`.
  - `APIManager.route_request()` filters them out; router skips them and routes to healthy providers.
  - Settings tab GUI renders provider cards in the orange/red recoverable state with an "Update Key" button.

### 7.3 Dangling Foreign Key (`credential_id` references non-existent ID)
- **Trigger:** Credential row deleted while foreign key enforcement was bypassed, or database edited externally.
- **Consequence:** Foreign key join returns `NULL` for credential fields.
- **System State & Recovery:**
  - `_provider_from_row()` checks `if cred is None:`.
  - Sets `api_key = None` and `decryption_error = "Credential reference missing"`.
  - Application does not crash. Provider is flagged as requiring key assignment.

### 7.4 Missing or Recreated `secret.key`
- **Trigger:** `secret.key` deleted from disk.
- **Hazard:** Existing `_load_or_create_key()` in `DatabaseManager` creates a fresh key if missing! This would permanently lock out existing encrypted credentials.
- **Enforced Safety Check:** Migration and database initialization must explicitly distinguish between first-time setup (no database exists) and disaster recovery (database exists but `secret.key` is missing). If `steward.db` exists but `secret.key` is absent, the application must **FAIL FAST** with a critical error rather than generating a new key.

---

## 8. UI IMPACT

### 8.1 Changes to `gui/settings_tab.py`

1. **Provider Cards:**
   - Display a clean status tag indicating the shared credential source: e.g. `Shared: OpenRouter` or `Direct Key` or `Local (No Auth)`.
   - Providers with decryption errors or missing credentials display a clear `Recover Key` button.

2. **"Add Provider" Form:**
   - When entering or pasting a `base_url`, the form checks asynchronously if a credential already exists for that normalized URL.
   - If a matching credential exists:
     - The API key field displays a placeholder: `[Using saved key for this endpoint]`.
     - An informational badge appears: `ℹ️ Reusing credential saved for openrouter.ai`.
     - An optional toggle allows: `[ ] Overwrite saved key for all models on this endpoint`.

3. **Shared Credential Edit Confirmation:**
   - If the user modifies an API key for a base URL that is currently shared by multiple providers:
     - The UI presents a confirmation dialog:  
       *"This API key is shared by 12 active providers on https://openrouter.ai/api/v1. Updating it will rotate credentials for all 12 providers. Do you want to proceed?"*
     - This eliminates unintentional credential disruptions.

4. **"Discover Free Models" Workflow:**
   - Discovery continues to query OpenRouter catalog and insert models as `is_active = 0`.
   - Discovered models automatically associate with the existing OpenRouter `credential_id`.
   - When a user clicks "Enable" on any discovered model:
     - If the OpenRouter credential is already present in `credentials`, the provider enables immediately without prompting the user for an API key.
     - If no credential exists, the user is prompted once. That key is saved to `credentials`, and all subsequent activations reuse it seamlessly.

5. **Provider Deletion Behavior:**
   - When a user deletes a provider from the GUI (`_delete_provider`):
     - The provider row is deleted from `providers`.
     - The referenced `credentials` row is **retained** if other providers still reference it.
     - If no other providers reference that credential, the user is prompted:  
       *"No other providers use this API key. Would you like to remove the saved credential from the secure store as well?"*

---

## 9. SECURITY REVIEW

### 9.1 Capabilities Enabled
- **Single-Point Rotation:** Revoked or leaked keys can be rotated across the entire cluster of models in one atomic operation.
- **Attack Surface Minimization:** Elimination of duplicate ciphertexts in storage. Previously, 16 duplicate ciphertexts existed; moving to normalized credentials minimizes cryptographic exposure.
- **Auditability:** Clear visibility into which external endpoints STEWARD connects to, and which models share credentials.

### 9.2 Broken Assumptions & Mitigations
- **Assumption:** Legacy code or external scripts querying `SELECT api_key_encrypted FROM providers`.
  - *Mitigation:* Transitional dual-write ensures `api_key_encrypted` on `providers` remains populated during Batch 4c until fully deprecated.
- **Assumption:** Unintended side effects from editing a key.
  - *Mitigation:* Explicit modal warning when modifying a shared credential.

### 9.3 Data Exfiltration Analysis
- No new network egress points are introduced.
- Credential management is purely internal to SQLite and `DatabaseManager`.
- The settings tab continues to mask API keys in UI display (`show="*"`).
- Plaintext API keys exist only in short-lived memory during outbound requests (`core/router.py`) and validator health checks (`core/validator.py`).

### 9.4 Review of `.clineignore` and `.clinerules`
- `.clineignore` currently contains:
  ```
  secret.key
  steward.db
  *.db
  ```
- **Evaluation:** `.clineignore` already correctly protects `secret.key` and all `.db` files from agent context reading tools.
- **Recommendation:** Add `*.backup`, `*.bak`, `*.sql` to `.clineignore` to ensure that temporary migration artifacts or local dumps can never be accidentally read or committed by automated tools.
- `.clinerules` protection rule remains binding:
  *"The agent must never write to, delete, or recreate steward.db or secret.key."*

---

## 10. TEST PLAN

The following comprehensive test suite must be implemented and passing in Batch 4c before enabling the new credential store in production:

### 10.1 Unit & Normalization Tests
- `test_normalize_base_url()`: Test URL normalization with trailing slashes, varying case, default ports, query params, and malformed inputs.
- `test_credential_crud()`: Test `create_credential`, `get_credential`, `update_credential`, `delete_credential` in `DatabaseManager`.

### 10.2 Migration Verification Tests
- `test_migration_from_v1_to_v2()`:
  - Create synthetic v1 database with 16 rows containing identical and distinct endpoints and keys.
  - Run migration.
  - Assert `credentials` table created and populated with exact expected unique count.
  - Assert all `providers.credential_id` correctly link to matching endpoint.
  - Assert decrypted keys match original inputs 100%.
- `test_migration_idempotence()`:
  - Run migration twice on the same database.
  - Assert second run completes cleanly with zero changes or errors.

### 10.3 Rollback & Dual-Schema Tests
- `test_dual_schema_reading()`:
  - Ensure provider rows with legacy `api_key_encrypted` and rows with `credential_id` both resolve correctly.
- `test_migration_rollback()`:
  - Simulate migration failure mid-transaction; verify transaction rolls back and v1 schema remains pristine.

### 10.4 Hostile & Disaster Recovery Tests
- `test_corrupt_credentials_blob()`:
  - Deliberately corrupt `credentials.api_key_encrypted` with random bytes.
  - Verify `_provider_from_row()` sets `api_key = None` and populates `decryption_error`.
  - Verify `APIManager.route_request()` cleanly skips the corrupted provider and routes to healthy providers without crashing.
- `test_missing_secret_key_fails_fast()`:
  - Instantiate database with existing `steward.db` but missing `secret.key`.
  - Verify migration/initialization fails fast with a explicit exception instead of generating a new key.
- `test_dangling_credential_id()`:
  - Insert provider with non-existent `credential_id` (simulating foreign key constraint violation).
  - Verify application handles missing credential as recoverable state rather than raising an unhandled SQLite exception.
- `test_conflicting_keys_migration()`:
  - Seed v1 database with 2 providers pointing to `https://openrouter.ai/api/v1` with different API keys.
  - Verify migration resolves conflict deterministically according to precedence rules without discarding secrets.
- `test_concurrent_rotation_and_routing()`:
  - Run multi-threaded stress test rotating credentials in thread A while router makes requests in thread B.
  - Verify thread safety with `threading.Lock()` and no deadlocks or stale reads.

---

## Conclusion & Handoff

This safety review establishes the exact blueprint for Batch 4c. By implementing a dual-schema transitional migration, out-of-tree backup protocols, strict URL normalization, and robust error recovery, STEWARD can safely adopt a normalized credential store without risk to live data or application stability.

**Batch 4b complete — awaiting owner approval before 4c begins.**

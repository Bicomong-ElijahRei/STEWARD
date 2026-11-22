# Shared Credential Live Migration Guide

## What changes

STEWARD originally stored an encrypted API key on every provider row. The shared
credential migration groups non-local providers by normalized endpoint and by
their decrypted key, creates canonical rows in `credentials`, and links each
provider through `credential_id`. Providers sharing an endpoint and key share a
credential; different keys remain separate. Local, keyless, and undecryptable
providers are not linked. Providers already linked to a valid shared credential keep
that link, including when their legacy encrypted column is empty.

Legacy encrypted provider keys remain in place. Logical rollback copies the
linked credential ciphertext back to each legacy provider column and clears all
`credential_id` values. It deliberately does **not** drop the credentials table.
The encryption key itself is never rotated or regenerated.

## Before you start

1. Close the STEWARD GUI and stop its background agent. This prevents database
   changes while the snapshot and migration are running.
2. Open PowerShell in the repository/runtime directory containing `steward.db`,
   `secret.key`, and `steward_operations.json`. The tool uses the paths configured
   by `core.database.DB_PATH` and `core.database.KEY_PATH` (currently based on the
   working directory).
3. Do not delete, rename, or replace `secret.key`. If it is absent, the tool exits
   without creating one. Restore the matching key before continuing.
4. Review `%APPDATA%\STEWARD\migration.log` after every attempt. If `APPDATA` is
   unset, the fallback location is `~/.steward/migration.log`.

## Operator procedure

### 1. Preview safely

```powershell
python tools/migrate_live.py --dry-run
```

Dry-run is the default, so `python tools/migrate_live.py` is equivalent. The tool
performs read-only pre-flight checks, makes a consistent temporary SQLite backup,
and runs migration and validation only against that copy. The temporary backup is
removed when the process exits. No persistent backup is created and the live
database is not opened for writes.

Check the reported pre/post provider and credential counts. A successful preview
ends with `DRY RUN complete; live steward.db was not modified.`

### 2. Execute the migration

```powershell
python tools/migrate_live.py --execute
```

At an interactive terminal, type `MIGRATE` exactly when prompted. Confirmation is
bounded to 300 seconds; a timeout aborts before backup or mutation. In a recognized
CI environment (`CI` or another common CI variable), the prompt is skipped;
non-interactive non-CI execution is refused.

Before migration, the tool copies the database, key, and operations log into
`%APPDATA%\STEWARD\backups\`. It verifies the SQLite backup with
`PRAGMA integrity_check`, verifies copied key/log hashes, and writes a SHA-256
manifest. Existing backup names are never overwritten: a timestamp collision or
any backup failure aborts before migration. Retry after a collision, or select an
empty alternate directory:

```powershell
python tools/migrate_live.py --execute --backup-dir "D:\STEWARD-backups"
```

After migration the tool checks SQLite integrity, unchanged provider count, and
successful decryption for every linked provider. The migration itself preserves
existing valid shared links. Validation failure triggers automatic logical rollback,
returns a non-zero exit code, and preserves the backup set.

### 3. Roll back logically (optional)

```powershell
python tools/migrate_live.py --rollback
```

Type `ROLLBACK` when prompted. Rollback confirmation is also bounded to 300
seconds. Rollback is a live mutation, so it creates a new backup set first and
applies the same CI/interactive rules. Use a different
`--backup-dir` if a same-second backup name would collide. Successful rollback
checks integrity, provider count, NULL `credential_id` values, and legacy-key
decryption.

## CLI flags

| Flag | Behavior |
| --- | --- |
| `--dry-run` | Default. Migrate and validate only a temporary database copy. |
| `--execute` | Back up and migrate the configured live database. |
| `--rollback` | Back up and reverse shared-credential links on the live database. |
| `--backup-dir PATH` | Persistent backup destination; defaults to `%APPDATA%\STEWARD\backups\` (or `~/.steward/backups/`). Ignored by dry-run. |
| `-h`, `--help` | Show command help. |

The three mode flags are mutually exclusive. Success returns exit code 0;
pre-flight, confirmation, backup, migration, or validation failures return 1.
`tools/run_migration.py` is retained as a compatibility wrapper: its `--dry-run`
mode delegates to the same guarded dry-run, while `--live` delegates to the same
confirmed, backed-up execute workflow.

## Restore a physical backup after a failure

Use this procedure if files are damaged or logical rollback is insufficient.
Restoring replaces runtime state and must not be done while STEWARD is running.

1. Stop STEWARD completely and locate the desired `<prefix>_manifest.json` and its
   three sibling files in the backup directory.
2. Verify every backup file's SHA-256 against the manifest. In PowerShell:

   ```powershell
   Get-FileHash -Algorithm SHA256 "C:\path\to\backups\<prefix>.db"
   Get-FileHash -Algorithm SHA256 "C:\path\to\backups\<prefix>.key"
   Get-FileHash -Algorithm SHA256 "C:\path\to\backups\<prefix>_operations.json"
   ```

3. Preserve the current runtime files by moving them to a new quarantine
   directory outside the repository. Do not overwrite the only good backup.
4. Copy `<prefix>.db` to `steward.db`, `<prefix>.key` to `secret.key`, and
   `<prefix>_operations.json` to `steward_operations.json` in the runtime
   directory. Keep the original backup set unchanged.
5. Start STEWARD and verify provider loading and decryption. For manual SQLite
   inspection, `PRAGMA integrity_check;` must return `ok`.

Never restore a database without its matching key. Never generate a replacement
key to make an encrypted backup readable; the original ciphertext cannot be
recovered with a new key.

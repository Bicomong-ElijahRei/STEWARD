"""Regression tests for copy-based migration into the STEWARD AppData directory."""

import json
import os
import tempfile
import unittest
from unittest.mock import patch

from agents.file_agent import migrate_legacy_operation_log
from core.database import migrate_legacy_database_files
from utils.helpers import get_app_data_dir


class AppDataMigrationTests(unittest.TestCase):
    """Verify persistent-state migration is safe, isolated, and copy-based."""

    def test_app_data_directory_uses_appdata_environment(self):
        with tempfile.TemporaryDirectory(prefix="steward_appdata_") as tmp:
            with patch.dict(os.environ, {"APPDATA": tmp}):
                app_data_dir = get_app_data_dir()

            self.assertEqual(app_data_dir, os.path.join(tmp, "STEWARD"))
            self.assertTrue(os.path.isdir(app_data_dir))

    def test_database_migration_copies_files_and_keeps_legacy_sources(self):
        with tempfile.TemporaryDirectory(prefix="steward_db_migration_") as tmp:
            legacy_root = os.path.join(tmp, "legacy")
            app_data_root = os.path.join(tmp, "appdata")
            os.makedirs(legacy_root)
            os.makedirs(app_data_root)
            legacy_db = os.path.join(legacy_root, "steward.db")
            legacy_key = os.path.join(legacy_root, "secret.key")
            target_db = os.path.join(app_data_root, "steward.db")
            target_key = os.path.join(app_data_root, "secret.key")
            with open(legacy_db, "wb") as handle:
                handle.write(b"database-content")
            with open(legacy_key, "wb") as handle:
                handle.write(b"key-content")

            result = migrate_legacy_database_files(
                target_db, target_key, legacy_root=legacy_root
            )

            self.assertEqual(result, {"database": True, "key": True})
            with open(target_db, "rb") as handle:
                self.assertEqual(handle.read(), b"database-content")
            with open(target_key, "rb") as handle:
                self.assertEqual(handle.read(), b"key-content")
            self.assertTrue(os.path.exists(legacy_db))
            self.assertTrue(os.path.exists(legacy_key))

    def test_database_migration_does_not_overwrite_existing_destination(self):
        with tempfile.TemporaryDirectory(prefix="steward_db_no_overwrite_") as tmp:
            legacy_root = os.path.join(tmp, "legacy")
            app_data_root = os.path.join(tmp, "appdata")
            os.makedirs(legacy_root)
            os.makedirs(app_data_root)
            legacy_db = os.path.join(legacy_root, "steward.db")
            target_db = os.path.join(app_data_root, "steward.db")
            with open(legacy_db, "wb") as handle:
                handle.write(b"legacy")
            with open(target_db, "wb") as handle:
                handle.write(b"current")

            result = migrate_legacy_database_files(
                target_db,
                os.path.join(app_data_root, "secret.key"),
                legacy_root=legacy_root,
            )

            self.assertFalse(result["database"])
            with open(target_db, "rb") as handle:
                self.assertEqual(handle.read(), b"current")

    def test_operation_log_migration_copies_without_removing_source(self):
        with tempfile.TemporaryDirectory(prefix="steward_ops_migration_") as tmp:
            legacy_root = os.path.join(tmp, "legacy")
            app_data_root = os.path.join(tmp, "appdata")
            os.makedirs(legacy_root)
            os.makedirs(app_data_root)
            legacy_log = os.path.join(legacy_root, "steward_operations.json")
            target_log = os.path.join(app_data_root, "steward_operations.json")
            with open(legacy_log, "w", encoding="utf-8") as handle:
                json.dump([{"operation": "move"}], handle)

            migrated = migrate_legacy_operation_log(
                target_log, legacy_root=legacy_root
            )

            self.assertTrue(migrated)
            with open(target_log, "r", encoding="utf-8") as handle:
                self.assertEqual(json.load(handle), [{"operation": "move"}])
            self.assertTrue(os.path.exists(legacy_log))


if __name__ == "__main__":
    unittest.main()

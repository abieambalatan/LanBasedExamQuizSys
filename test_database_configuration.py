"""Check database selection without connecting to or creating any database."""

import os
from pathlib import Path
import subprocess
import sys
import unittest


ROOT = Path(__file__).resolve().parent


class DatabaseConfigurationTests(unittest.TestCase):
    def run_config(self, code, **variables):
        environment = {key: value for key, value in os.environ.items()
                       if not key.startswith("EXAM_PORTAL_DB_") and key != "DJANGO_SETTINGS_MODULE"}
        environment.update({
            "EXAM_PORTAL_SECRET_KEY": "database-selection-test-only",
            "EXAM_PORTAL_ADMIN_PASSWORD": "database-selection-test-only",
            "DJANGO_SETTINGS_MODULE": "exam_portal.settings",
            **variables,
        })
        return subprocess.run([sys.executable, "-c", code], cwd=ROOT, env=environment,
                              capture_output=True, text=True, timeout=15)

    def test_missing_configuration_stops_without_sqlite_fallback(self):
        result = self.run_config("from django.conf import settings; print(settings.DATABASES)")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("PostgreSQL configuration is required", result.stderr)

    def test_explicit_sqlite_engine_is_rejected(self):
        result = self.run_config("import exam_portal.settings", EXAM_PORTAL_DB_ENGINE="sqlite")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("SQLite is disabled", result.stderr)

    def test_legacy_database_path_is_rejected(self):
        result = self.run_config("import exam_portal.settings", EXAM_PORTAL_DB_PATH="exam.db")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("EXAM_PORTAL_DB_PATH is no longer supported", result.stderr)

    def test_postgresql_is_default_with_configured_credentials(self):
        result = self.run_config(
            "from django.conf import settings; print(settings.DATABASES['default']['ENGINE'])",
            EXAM_PORTAL_DB_NAME="configuration_only", EXAM_PORTAL_DB_USER="configuration_only",
            EXAM_PORTAL_DB_PASSWORD="configuration_only",
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.strip(), "django.db.backends.postgresql")

    def test_database_helper_rejects_sqlite_outside_isolated_tests(self):
        result = self.run_config(
            "from django.conf import settings; "
            "settings.configure(DATABASES={'default': {'ENGINE': 'django.db.backends.sqlite3', 'NAME': 'exam.db'}}); "
            "from portal.db import get_db; get_db()"
        )
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("portal requires PostgreSQL", result.stderr)

    def test_test_fixtures_cannot_create_a_workspace_database(self):
        result = self.run_config("import exam_portal.test_settings", EXAM_PORTAL_DB_PATH=str(ROOT / "exam.db"))
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("outside the workspace", result.stderr)

    def test_production_server_refuses_test_database_configuration(self):
        result = self.run_config("import app; app.main()", DJANGO_SETTINGS_MODULE="exam_portal.test_settings")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("classroom server requires PostgreSQL", result.stderr)


if __name__ == "__main__":
    unittest.main()

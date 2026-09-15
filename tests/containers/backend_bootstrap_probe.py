"""Execute bootstrap entry points inside the built production image.

Run this file as a read-only mount under the image's default user, with
--network none --read-only --tmpfs /tmp. No source checkout or database is mounted.
This independent unittest probe uses only the Python standard library.
"""

import json
import os
import re
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


class BackendBootstrapImageTests(unittest.TestCase):
    def command(self, *args, **overrides):
        # Deliberately unusable database targets. Validation must finish before SQL.
        env = dict(os.environ, ENVIRONMENT="development",
            JWT_SECRET_KEY="isolated-image-probe-not-a-real-secret-2026",
            POSTGRES_URL="postgresql+asyncpg://probe:probe@127.0.0.1:1/probe",
            REDIS_URL="redis://127.0.0.1:1/0", PYTHONDONTWRITEBYTECODE="1")
        env.update(overrides)
        return subprocess.run([sys.executable, *args], cwd="/app", env=env,
            capture_output=True, text=True, timeout=20)

    def test_administrator_entry_point_reaches_input_validation(self):
        result = self.command("scripts/create_admin.py", "--create-only", ADMIN_EMAIL="invalid@sphere.local",
            ADMIN_PASSWORD="synthetic-image-password")
        self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
        self.assertIn("Invalid admin credentials:", result.stderr)
        self.assertNotIn("synthetic-image-password", result.stdout + result.stderr)

    def test_enrollment_entry_point_reaches_config_validation(self):
        with tempfile.TemporaryDirectory() as temporary:
            config = Path(temporary) / "environments" / "development.json"
            config.parent.mkdir()
            config.write_text(json.dumps({}), encoding="utf-8")
            result = self.command("-m", "scripts.seed_enrollment_key",
                AGENT_CONFIG_DIR=temporary, AGENT_CONFIG_ENV="development")
        self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
        self.assertIn("Configured enrollment_api_key must be a non-empty string", result.stderr)

    def test_migration_cli_can_read_the_packaged_single_head(self):
        result = self.command("-m", "alembic", "-c", "alembic/alembic.ini", "heads")
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        heads = re.findall(r"^([a-zA-Z0-9_]+) (?:\([^)]+\) )*\(head\)$", result.stdout, flags=re.M)
        self.assertEqual(len(heads), 1, result.stdout)

    def test_runtime_user_cannot_write_the_application_directory(self):
        self.assertNotEqual(os.geteuid(), 0)
        with self.assertRaises(OSError):
            Path("/app/image-probe-write-must-fail").write_text("probe", encoding="utf-8")


if __name__ == "__main__":
    unittest.main(verbosity=2)

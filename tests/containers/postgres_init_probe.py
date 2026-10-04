"""Run the shipped PostgreSQL init.sql on fresh, network-isolated containers.

No host ports or existing database/volume is used. First initialization must pass
before the same disposable-volume cluster is restarted and checked again.
"""

import argparse
import json
import subprocess
import time
import unittest
import uuid
from pathlib import Path

REPOSITORY = Path(__file__).resolve().parents[2]
EVIDENCE = None
RECORDS = []


def docker(*args, timeout=60):
    return subprocess.run(["docker", *args], check=True, capture_output=True,
        text=True, encoding="utf-8", timeout=timeout).stdout.strip()


class PostgresInitializationTests(unittest.TestCase):
    def wait_ready(self, container, user):
        deadline = time.monotonic() + 45
        while time.monotonic() < deadline:
            state = json.loads(docker("inspect", container))[0]["State"]
            self.assertTrue(state["Running"], f"PostgreSQL exited during initialization: {state['ExitCode']}")
            # The entrypoint's temporary initialization server has no TCP listener.
            result = subprocess.run(["docker", "exec", container, "pg_isready", "-h", "127.0.0.1",
                "-U", user, "-d", "sphereplatform"], capture_output=True, timeout=10)
            if result.returncode == 0:
                return
            time.sleep(0.5)
        self.fail("PostgreSQL did not reach its final server within 45 seconds")

    def assert_cluster(self, container, user):
        query = """SELECT json_build_object(
            'user', current_user,
            'database', current_database(),
            'n8n_owner', (SELECT pg_get_userbyid(datdba) FROM pg_database WHERE datname = 'n8n'),
            'extensions', (SELECT array_agg(extname ORDER BY extname) FROM pg_extension
                WHERE extname IN ('uuid-ossp', 'pg_trgm', 'btree_gin')));"""
        output = docker("exec", container, "psql", "-X", "-A", "-t", "-v", "ON_ERROR_STOP=1",
            "-U", user, "-d", "sphereplatform", "-c", query)
        state = json.loads(output)
        self.assertEqual(state, {"user": user, "database": "sphereplatform", "n8n_owner": user,
            "extensions": ["btree_gin", "pg_trgm", "uuid-ossp"]})
        self.assertEqual(docker("exec", container, "psql", "-X", "-A", "-t", "-v", "ON_ERROR_STOP=1",
            "-U", user, "-d", "n8n", "-c", "SELECT current_database()"), "n8n")
        return state

    def exercise(self, user):
        run_id = "sphere-init-audit-" + uuid.uuid4().hex[:12]
        record = {"user": user, "network": "none", "host_ports": [],
            "init_sql": "infrastructure/postgres/init.sql", "first_passed": False,
            "restart_passed": False, "removed": False}
        RECORDS.append(record)
        volume = docker("volume", "create", "--label", "sphere.audit.init=" + run_id, run_id + "-data")
        container = None
        try:
            container = docker("run", "-d", "--name", run_id, "--label", "sphere.audit.init=" + run_id,
                "--network", "none", "--mount", f"type=volume,source={volume},target=/var/lib/postgresql/data",
                "--mount", f"type=bind,source={REPOSITORY / 'infrastructure/postgres/init.sql'},target=/docker-entrypoint-initdb.d/init.sql,readonly",
                "-e", "POSTGRES_DB=sphereplatform", "-e", "POSTGRES_USER=" + user,
                "-e", "POSTGRES_PASSWORD=isolated-postgres-init-password", "postgres:15-alpine")
            record["image_id"] = json.loads(docker("inspect", container))[0]["Image"]
            self.wait_ready(container, user)
            record["first"] = self.assert_cluster(container, user)
            record["first_passed"] = True
            # An explicit marker proves the same cluster survives the restart.
            docker("exec", container, "psql", "-X", "-v", "ON_ERROR_STOP=1", "-U", user,
                "-d", "sphereplatform", "-c", "CREATE TABLE init_audit_marker (value integer); INSERT INTO init_audit_marker VALUES (17)")
            docker("restart", "-t", "10", container)
            self.wait_ready(container, user)
            record["repeat"] = self.assert_cluster(container, user)
            self.assertEqual(docker("exec", container, "psql", "-X", "-A", "-t", "-U", user,
                "-d", "sphereplatform", "-c", "SELECT value FROM init_audit_marker"), "17")
            record["restart_passed"] = True
        finally:
            if container:
                logs = subprocess.run(["docker", "logs", container], capture_output=True,
                    text=True, encoding="utf-8", timeout=15)
                if EVIDENCE:
                    (EVIDENCE / f"postgres-init-{user}.txt").write_text(logs.stdout + logs.stderr, encoding="utf-8")
                info = json.loads(docker("inspect", container))[0]
                self.assertEqual(info["Id"], container)
                self.assertEqual(info["Config"]["Labels"].get("sphere.audit.init"), run_id)
                docker("rm", "-f", "-v", container)
            info = json.loads(docker("volume", "inspect", volume))[0]
            self.assertEqual(info["Name"], volume)
            self.assertEqual(info["Labels"].get("sphere.audit.init"), run_id)
            docker("volume", "rm", volume)
            record["removed"] = True

    def test_default_user_initializes_and_restarts_with_owned_n8n_and_extensions(self):
        self.exercise("sphere")

    def test_configured_user_initializes_and_restarts_with_owned_n8n_and_extensions(self):
        self.exercise("sphere_audit_operator")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--evidence-dir", type=Path, required=True)
    args = parser.parse_args()
    EVIDENCE = args.evidence_dir.resolve()
    EVIDENCE.mkdir(parents=True, exist_ok=True)
    suite = unittest.defaultTestLoader.loadTestsFromTestCase(PostgresInitializationTests)
    result = unittest.TextTestRunner(verbosity=2).run(suite)
    (EVIDENCE / "postgres-init-summary.json").write_text(json.dumps({
        "tests": result.testsRun, "failures": len(result.failures), "errors": len(result.errors),
        "records": RECORDS}, indent=2) + "\n", encoding="utf-8")
    raise SystemExit(0 if result.wasSuccessful() else 1)

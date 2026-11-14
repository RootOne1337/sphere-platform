import base64
import contextlib
import hashlib
import io
import json
import tempfile
import unittest
import urllib.error
import zipfile
from pathlib import Path
from unittest.mock import patch

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa

from scripts.pilot import android_cloud_package as delivery


class AndroidCloudPackageTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.key = rsa.generate_private_key(public_exponent=65537, key_size=3072)
        cls.der = base64.b64encode(
            cls.key.public_key().public_bytes(
                serialization.Encoding.DER, serialization.PublicFormat.SubjectPublicKeyInfo
            )
        ).decode()
        cls.pem = cls.key.private_bytes(
            serialization.Encoding.PEM,
            serialization.PrivateFormat.PKCS8,
            serialization.NoEncryption(),
        )

    def config(self):
        return {
            "environment": {
                "SPHERE_SERVER_URL": "",
                "SPHERE_FALLBACK_SERVER_URL": "",
                "SPHERE_CONFIG_URL": "https://config.example/agent.json",
                "SPHERE_CONFIG_MIRROR_URLS": "",
                "SPHERE_DISCOVERY_INSTALLATION_ID": "ce123d0a-c903-4397-8ab0-202ec028b9ac",
                "SPHERE_DISCOVERY_PUBLIC_KEY": self.der,
                "SPHERE_DISCOVERY_KEY_ID": "fixture-v1",
                "SPHERE_ENROLLMENT_KEY": "test-only-enrollment-fixture",
            },
            "recipientPublicKeyDer": self.der,
        }

    def test_config_cannot_inject_environment_or_commands(self):
        for update in [
            {"SPHERE_ENROLLMENT_KEY": "secret\nINJECTED=true"},
            {"SPHERE_CONFIG_URL": "http://config.example/a"},
            {"SPHERE_CONFIG_URL": "https://user:password@config.example/a"},
            {"SPHERE_CONFIG_URL": "https://config.example/a?token=secret"},
            {"SPHERE_SERVER_URL": "https://unexpected.example"},
            {"JAVA_TOOL_OPTIONS": "-javaagent:untrusted.jar"},
        ]:
            with self.subTest(update=list(update)):
                value = self.config()
                value["environment"].update(update)
                with self.assertRaises(ValueError):
                    delivery.validate_configuration(json.dumps(value))

    def test_duplicate_fields_and_weak_or_private_recipient_fail(self):
        raw = json.dumps(self.config())
        with self.assertRaises(ValueError):
            delivery.validate_configuration(
                raw.replace('"environment":', '"environment":{},"environment":')
            )
        value = self.config()
        value["recipientPublicKeyDer"] = base64.b64encode(self.pem).decode()
        with self.assertRaises(ValueError):
            delivery.validate_configuration(json.dumps(value))
        weak = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        with self.assertRaises(ValueError):
            delivery.recipient(
                base64.b64encode(
                    weak.public_key().public_bytes(
                        serialization.Encoding.DER, serialization.PublicFormat.SubjectPublicKeyInfo
                    )
                ).decode()
            )

    def test_prepare_is_validated_before_writing_and_uses_allowlisted_variables(self):
        with tempfile.TemporaryDirectory() as temporary:
            env = Path(temporary) / "env"
            env.touch()
            key = Path(temporary) / "recipient"
            bad = self.config()
            bad["environment"]["UNEXPECTED"] = "value"
            with self.assertRaises(ValueError):
                delivery.prepare_configuration(json.dumps(bad), env, key)
            self.assertEqual("", env.read_text())
            self.assertFalse(key.exists())
            with contextlib.redirect_stdout(io.StringIO()) as output:
                delivery.prepare_configuration(json.dumps(self.config()), env, key)
            self.assertEqual(self.der, key.read_text())
            self.assertEqual(8, env.read_text().count("<<SPHERE_"))
            self.assertIn("::add-mask::test-only-enrollment-fixture", output.getvalue())
            before = env.read_bytes()
            with self.assertRaises(ValueError):
                delivery.prepare_configuration(json.dumps(self.config()), env, key)
            self.assertEqual(before, env.read_bytes())

    def test_source_admission_requires_success_and_identical_components(self):
        tested, head = "a" * 40, "b" * 40
        run = {
            "id": 123,
            "repository": {"full_name": "owner/repo"},
            "status": "completed",
            "conclusion": "success",
            "path": ".github/workflows/ci-android.yml",
            "head_sha": tested,
        }

        def git(_root, *args):
            if args[0] == "show":
                return "jobs:\n  build:\n    steps:\n      - run: ./gradlew test\n"
            return head if args[-1] == "HEAD" else "same-component"

        with patch.object(delivery, "git", side_effect=git):
            self.assertEqual(
                (tested, head), delivery.validate_run(Path("."), 123, "owner/repo", run)
            )
            for updates in [
                {"conclusion": "failure"},
                {"path": ".github/workflows/other.yml"},
                {"status": "in_progress"},
                {"repository": {"full_name": "foreign/repo"}},
            ]:
                with self.subTest(updates=updates), self.assertRaises(ValueError):
                    delivery.validate_run(Path("."), 123, "owner/repo", dict(run, **updates))
        with patch.object(delivery, "git", side_effect=[head, "old-tree", "new-tree"]):
            with self.assertRaises(ValueError):
                delivery.validate_run(Path("."), 123, "owner/repo", run)

    def test_validation_job_lookup_is_pinned_to_the_exact_run_attempt(self):
        self.assertEqual(delivery.validation_jobs_path(123, {"run_attempt": 2}),
                         "/actions/runs/123/attempts/2/jobs?per_page=100")
        for attempt in (None, True, 0, -1, "2", 1.0, 10001):
            with self.subTest(attempt=attempt), self.assertRaises(ValueError):
                delivery.validation_jobs_path(123, {"run_attempt": attempt})

    def test_packaging_only_success_cannot_substitute_for_full_ci(self):
        job = {
            "name": "Android tests and signed release smoke build",
            "status": "completed",
            "conclusion": "success",
        }
        delivery.validate_full_job({"total_count": 1, "jobs": [job]})
        for updates in [
            {"conclusion": "skipped"},
            {"status": "in_progress"},
            {"name": "Configured pilot"},
        ]:
            with self.subTest(updates=updates), self.assertRaises(ValueError):
                delivery.validate_full_job({"total_count": 1, "jobs": [dict(job, **updates)]})
        recipe = "jobs:\n  build:\n    steps:\n      - run: ./gradlew test\n"
        wrapped = (
            recipe.replace("  build:\n", "  build:\n" + delivery.BUILD_CONDITION)
            + "  configured-pilot:\n    uses: package.yml\n"
        )
        self.assertEqual(delivery.build_recipe(recipe), delivery.build_recipe(wrapped))
        self.assertNotEqual(
            delivery.build_recipe(recipe),
            delivery.build_recipe(recipe.replace("gradlew test", "gradlew assembleDebug")),
        )

    def test_sealed_package_is_bound_to_receipt_and_never_overwrites(self):
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            apk = directory / "candidate.apk"
            apk.write_bytes(b"private-fixture-apk")
            sealed = directory / "candidate.sealed"
            output = directory / "unsealed.apk"
            receipt = delivery.seal(
                apk, self.der, {"sourceRevision": "a" * 40, "packageRunId": 42}, sealed
            )
            self.assertNotIn(apk.read_bytes(), sealed.read_bytes())
            self.assertFalse(receipt["runtimeInstalled"])
            self.assertFalse(receipt["apkSignedByMaintainer"])
            self.assertEqual(receipt, delivery.unseal(sealed, self.pem, "a" * 40, 42, output))
            self.assertEqual(apk.read_bytes(), output.read_bytes())
            with self.assertRaises(ValueError):
                delivery.unseal(sealed, self.pem, "a" * 40, 42, output)
            output.unlink()
            with self.assertRaises(ValueError):
                delivery.unseal(sealed, self.pem, "a" * 40, 43, output)
            self.assertFalse(output.exists())
            original = sealed.read_bytes()
            line, encrypted = original.split(b"\n", 1)
            changed = json.loads(line)
            changed["receipt"]["nativeArtifactDigest"] = "tampered"
            sealed.write_bytes(delivery.canonical(changed) + b"\n" + encrypted)
            with self.assertRaises(InvalidTag):
                delivery.unseal(sealed, self.pem, "a" * 40, 42, output)
            self.assertFalse(output.exists())
            sealed.write_bytes(original)
            data = bytearray(sealed.read_bytes())
            data[-1] ^= 1
            sealed.write_bytes(data)
            with self.assertRaises(InvalidTag):
                delivery.unseal(sealed, self.pem, "a" * 40, 42, output)
            self.assertFalse(output.exists())

    def test_only_encrypted_artifacts_are_uploaded_and_compiler_cache_is_not_shared(self):
        workflow = (
            Path(__file__).resolve().parents[1] / ".github/workflows/package-android-pilot.yml"
        ).read_text()
        upload = workflow.split("uses: actions/upload-artifact@v6\n", 1)[1]
        paths = upload.split("          path: |\n", 1)[1].split("          if-no-files-found:", 1)[
            0
        ]
        self.assertEqual(
            [
                "${{ runner.temp }}/pilot-package.sealed",
                "${{ runner.temp }}/pilot-package.receipt.json",
            ],
            [line.strip() for line in paths.splitlines() if line.strip()],
        )
        self.assertIn("cache-disabled: true", workflow)
        self.assertIn("--no-build-cache --no-configuration-cache", workflow)
        self.assertIn("  workflow_call:", workflow)
        self.assertNotIn("pull_request:", workflow)

    def test_configured_output_gate_rejects_a_generic_smoke_apk(self):
        from unittest.mock import patch

        env = self.config()["environment"]
        fields = {
            "APPLICATION_ID": "com.sphereplatform.agent.pilot.debug",
            "GIT_SHA": "a" * 40,
            "DEFAULT_SERVER_URL": "",
            "DEFAULT_FALLBACK_SERVER_URL": "",
            "DEFAULT_API_KEY": env["SPHERE_ENROLLMENT_KEY"],
            "CONFIG_URL": env["SPHERE_CONFIG_URL"],
            "CONFIG_MIRROR_URLS": "",
            "DISCOVERY_INSTALLATION_ID": env["SPHERE_DISCOVERY_INSTALLATION_ID"],
            "DISCOVERY_PUBLIC_KEY": env["SPHERE_DISCOVERY_PUBLIC_KEY"],
            "DISCOVERY_KEY_ID": env["SPHERE_DISCOVERY_KEY_ID"],
        }
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            generated = (
                root
                / "android/app/build/generated/source/buildConfig/dev/debug/com/sphereplatform/agent/BuildConfig.java"
            )
            generated.parent.mkdir(parents=True)
            text = "\n".join(
                name + " = " + json.dumps(value) + ";" for name, value in fields.items()
            )
            text += "\nAPP_SCOPED_VPN_CANARY = true;\nSTREAM_PLANAR_INPUT = true;\nCONTINUOUS_INPUT_CANARY = true;\nSTREAM_GPU_BRIDGE = false;"
            generated.write_text(text)
            native = root / "native"
            native.mkdir()
            rows = [
                {"abi": abi, "sha256": hashlib.sha256(abi.encode()).hexdigest()}
                for abi in ["x86_64", "arm64-v8a", "armeabi-v7a"]
            ]
            (native / "manifest.json").write_text(json.dumps({"artifacts": rows}))
            apk = root / "android/app/build/outputs/apk/dev/debug/app-dev-debug.apk"
            apk.parent.mkdir(parents=True)
            with zipfile.ZipFile(apk, "w") as archive:
                for row in rows:
                    archive.writestr("lib/" + row["abi"] + "/libwg-go.so", row["abi"].encode())
            with patch.dict("os.environ", env), patch.object(delivery, "clean_components"):
                delivery.verify_configured_output(root, native, "a" * 40)
                generated.write_text(text.replace(env["SPHERE_ENROLLMENT_KEY"], ""))
                with self.assertRaises(ValueError):
                    delivery.verify_configured_output(root, native, "a" * 40)

    def test_native_artifact_requires_hardened_manifest_exact_hashes_and_safe_paths(self):
        abis = ["arm64-v8a", "armeabi-v7a", "x86_64"]
        rows = [{"abi": abi, "sha256": hashlib.sha256(abi.encode()).hexdigest()} for abi in abis]
        apk = io.BytesIO()
        with zipfile.ZipFile(apk, "w") as archive:
            for abi in abis:
                archive.writestr(f"lib/{abi}/libwg-go.so", abi.encode())

        def bundle(tampered=False, traversal=False, bad_hash=False):
            native_rows = [dict(row) for row in rows]
            if bad_hash:
                native_rows[0]["sha256"] = "0" * 64
            manifest = {
                "runtime_sleep_clock_patch_applied": True,
                "jni_lifecycle_hardened": not tampered,
                "artifacts": native_rows,
            }
            result = io.BytesIO()
            with zipfile.ZipFile(result, "w") as archive:
                archive.writestr("root/sphere-awg-native/manifest.json", json.dumps(manifest))
                archive.writestr(
                    "root/android/app/build/outputs/apk/dev/debug/app-dev-debug.apk", apk.getvalue()
                )
                if traversal:
                    archive.writestr("../escape", b"no")
            return result.getvalue()

        with tempfile.TemporaryDirectory() as temporary:
            output = Path(temporary) / "native"
            for data in [bundle(tampered=True), bundle(traversal=True), bundle(bad_hash=True)]:
                with self.assertRaises(ValueError):
                    delivery.extract_native(data, output)
                self.assertFalse(output.exists())
            receipt = delivery.extract_native(bundle(), output)
            self.assertEqual(abis, receipt["nativeAbis"])
            self.assertEqual(b"x86_64", (output / "jniLibs/x86_64/libwg-go.so").read_bytes())

    def test_download_strips_authorization_on_redirect_and_checks_github_digest(self):
        data = b"bounded artifact bytes"
        artifact = {
            "id": 42,
            "expired": False,
            "size_in_bytes": len(data),
            "digest": "sha256:" + hashlib.sha256(data).hexdigest(),
        }

        class Opener:
            def __init__(self, location):
                self.location = location
                self.requests = []

            def open(self, request, timeout):
                self.requests.append(request)
                if len(self.requests) == 1:
                    raise urllib.error.HTTPError(
                        request.full_url, 302, "redirect", {"Location": self.location}, None
                    )
                return io.BytesIO(data)

        opener = Opener("https://fixture.blob.core.windows.net/archive?signature=private")
        with patch.object(delivery.urllib.request, "build_opener", return_value=opener):
            self.assertEqual(
                data, delivery.download_archive("owner/repo", artifact, "private-test-token")
            )
        self.assertEqual(
            "Bearer private-test-token", opener.requests[0].get_header("Authorization")
        )
        self.assertIsNone(opener.requests[1].get_header("Authorization"))
        opener = Opener("https://untrusted.example/archive")
        with (
            patch.object(delivery.urllib.request, "build_opener", return_value=opener),
            self.assertRaises(ValueError),
        ):
            delivery.download_archive("owner/repo", artifact, "private-test-token")
        self.assertEqual(1, len(opener.requests))
        opener = Opener("https://fixture.blob.core.windows.net/archive")
        with (
            patch.object(delivery.urllib.request, "build_opener", return_value=opener),
            self.assertRaises(ValueError),
        ):
            delivery.download_archive(
                "owner/repo", dict(artifact, digest="sha256:" + "0" * 64), "private-test-token"
            )


if __name__ == "__main__":
    unittest.main()

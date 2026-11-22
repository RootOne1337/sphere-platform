"""Manual configured Android packaging with encrypted-only GitHub artifacts.

No signing private key leaves the maintainer host. This is build delivery only;
neither the CI artifact nor local decryption authorizes OTA or proves a tunnel.
"""

from __future__ import annotations

import argparse
import base64
import hashlib
import io
import json
import os
import re
import subprocess
import urllib.error
import urllib.request
import uuid
import zipfile
from pathlib import Path, PurePosixPath
from urllib.parse import urlsplit

CONFIG_KEYS = frozenset(
    {
        "SPHERE_SERVER_URL",
        "SPHERE_FALLBACK_SERVER_URL",
        "SPHERE_CONFIG_URL",
        "SPHERE_CONFIG_MIRROR_URLS",
        "SPHERE_DISCOVERY_INSTALLATION_ID",
        "SPHERE_DISCOVERY_PUBLIC_KEY",
        "SPHERE_DISCOVERY_KEY_ID",
        "SPHERE_ENROLLMENT_KEY",
    }
)
COMPONENTS = ("android", "scripts/build_awg_native.py")
CI_WORKFLOW = ".github/workflows/ci-android.yml"
BUILD_CONDITION = (
    "    if: ${{ github.event_name != 'workflow_dispatch' || !inputs.package_only }}\n"
)
ARCHIVE_LIMIT = 300 * 1024 * 1024
APK_LIMIT = 128 * 1024 * 1024
CONTEXT = b"sphere-configured-android-package-v1"


def require(condition: object) -> None:
    if not condition:
        raise ValueError("android_cloud_package_not_admitted")


def canonical(value: dict) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":")).encode()


def git(root: Path, *args: str) -> str:
    return subprocess.check_output(["git", *args], cwd=root, text=True, timeout=20).strip()


def clean_components(root: Path) -> None:
    require(not git(root, "diff", "--name-only", "HEAD", "--", *COMPONENTS, CI_WORKFLOW))
    require(not git(root, "ls-files", "--others", "--exclude-standard", "--", "android/app/src"))


def recipient(encoded: str):
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric import rsa

    key = serialization.load_der_public_key(base64.b64decode(encoded, validate=True))
    require(
        isinstance(key, rsa.RSAPublicKey)
        and key.key_size in (3072, 4096)
        and key.public_numbers().e == 65537
    )
    return key


def validate_configuration(raw: str) -> tuple[dict[str, str], str]:
    require(isinstance(raw, str) and 0 < len(raw.encode()) <= 16384)

    def pairs(items):
        require(len({key for key, _ in items}) == len(items))
        return dict(items)

    body = json.loads(raw, object_pairs_hook=pairs)
    require(isinstance(body, dict) and body.keys() == {"environment", "recipientPublicKeyDer"})
    env = body["environment"]
    require(isinstance(env, dict) and env.keys() == CONFIG_KEYS)
    require(
        all(
            isinstance(value, str)
            and value == value.strip()
            and len(value) <= 4096
            and not any(ord(c) < 32 for c in value)
            for value in env.values()
        )
    )
    require(env["SPHERE_SERVER_URL"] == env["SPHERE_FALLBACK_SERVER_URL"] == "")
    require(16 <= len(env["SPHERE_ENROLLMENT_KEY"]) <= 1024)
    require(
        str(uuid.UUID(env["SPHERE_DISCOVERY_INSTALLATION_ID"]))
        == env["SPHERE_DISCOVERY_INSTALLATION_ID"]
    )
    require(bool(re.fullmatch(r"[A-Za-z0-9_.-]{1,128}", env["SPHERE_DISCOVERY_KEY_ID"])))
    discovery = base64.b64decode(env["SPHERE_DISCOVERY_PUBLIC_KEY"], validate=True)
    require(256 <= len(discovery) <= 1024)
    urls = [env["SPHERE_CONFIG_URL"], *env["SPHERE_CONFIG_MIRROR_URLS"].split(",")]
    urls = [value for value in urls if value]
    require(1 <= len(urls) <= 3 and len(set(urls)) == len(urls))
    for value in urls:
        require(value == value.strip())
        url = urlsplit(value)
        require(
            url.scheme == "https"
            and url.hostname
            and url.port in (None, 443)
            and not url.username
            and not url.password
            and not url.fragment
            and not url.query
        )
    require(env["SPHERE_CONFIG_URL"])
    key = body["recipientPublicKeyDer"]
    require(isinstance(key, str) and len(key) <= 1400)
    recipient(key)
    return env, key


def prepare_configuration(raw: str, env_file: Path, key_file: Path) -> None:
    env, key = validate_configuration(raw)
    require(env_file.is_file() and not key_file.exists())
    # Escape workflow command metacharacters; values never become shell source.
    for value in env.values():
        if value:
            print("::add-mask::" + value.replace("%", "%25"))
    with env_file.open("a", encoding="utf-8") as stream:
        for name, value in env.items():
            delimiter = "SPHERE_" + uuid.uuid4().hex
            stream.write(f"{name}<<{delimiter}\n{value}\n{delimiter}\n")
    key_file.write_text(key, encoding="ascii")


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        return None


def api_json(repo: str, path: str, token: str) -> dict:
    require(bool(re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", repo)))
    request = urllib.request.Request(
        "https://api.github.com/repos/" + repo + path,
        headers={"Authorization": "Bearer " + token, "Accept": "application/vnd.github+json"},
    )
    with urllib.request.urlopen(request, timeout=30) as response:
        data = response.read(8 * 1024 * 1024 + 1)
    require(len(data) <= 8 * 1024 * 1024)
    return json.loads(data)


def validate_run(root: Path, run_id: int, repo: str, run: dict) -> tuple[str, str]:
    require(type(run_id) is int and run_id > 0 and run.get("id") == run_id)
    require(
        run.get("repository", {}).get("full_name") == repo
        and run.get("status") == "completed"
        and run.get("conclusion") == "success"
        and run.get("path") == ".github/workflows/ci-android.yml"
    )
    tested = run.get("head_sha")
    require(isinstance(tested, str) and bool(re.fullmatch(r"[a-f0-9]{40}", tested)))
    head = git(root, "rev-parse", "HEAD")
    require(
        all(
            git(root, "rev-parse", f"{tested}:{path}") == git(root, "rev-parse", f"{head}:{path}")
            for path in COMPONENTS
        )
    )
    require(
        build_recipe(git(root, "show", f"{tested}:{CI_WORKFLOW}"))
        == build_recipe(git(root, "show", f"{head}:{CI_WORKFLOW}"))
    )
    return tested, head


def build_recipe(workflow: str) -> str:
    """Only the full build job may match; a packaging-only success is insufficient."""
    match = re.search(r"^  build:\n.*?(?=^  [A-Za-z0-9_-]+:\n|\Z)", workflow, re.M | re.S)
    require(match is not None)
    recipe = match.group(0)
    require(recipe.count(BUILD_CONDITION) <= 1)
    return recipe.replace(BUILD_CONDITION, "").strip()


def validate_full_job(jobs: dict) -> None:
    require(type(jobs.get("total_count")) is int and 0 < jobs["total_count"] <= 100)
    matches = [
        job
        for job in jobs["jobs"]
        if job.get("name") == "Android tests and signed release smoke build"
    ]
    require(
        len(matches) == 1
        and matches[0].get("status") == "completed"
        and matches[0].get("conclusion") == "success"
    )


def validation_jobs_path(run_id: int, run: dict) -> str:
    """Bind admission to the successful run attempt, not an aggregate job list."""
    attempt = run.get("run_attempt")
    require(type(run_id) is int and run_id > 0 and type(attempt) is int and 1 <= attempt <= 10000)
    return f"/actions/runs/{run_id}/attempts/{attempt}/jobs?per_page=100"


def download_archive(repo: str, artifact: dict, token: str) -> bytes:
    require(bool(re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", repo)))
    require(
        artifact.get("expired") is False
        and type(artifact.get("id")) is int
        and type(artifact.get("size_in_bytes")) is int
        and 0 < artifact["size_in_bytes"] <= ARCHIVE_LIMIT
    )
    digest = artifact.get("digest")
    require(isinstance(digest, str) and bool(re.fullmatch(r"sha256:[a-f0-9]{64}", digest)))
    request = urllib.request.Request(
        f"https://api.github.com/repos/{repo}/actions/artifacts/{artifact['id']}/zip",
        headers={"Authorization": "Bearer " + token},
    )
    opener = urllib.request.build_opener(NoRedirect)
    try:
        opener.open(request, timeout=30).close()
        raise ValueError("artifact_redirect_required")
    except urllib.error.HTTPError as error:
        require(error.code == 302)
        location = error.headers["Location"]
        error.close()
    url = urlsplit(location)
    require(
        url.scheme == "https"
        and url.port in (None, 443)
        and not url.username
        and not url.password
        and url.hostname
        and (
            url.hostname.endswith(".blob.core.windows.net")
            or url.hostname.endswith(".actions.githubusercontent.com")
        )
    )
    # Deliberately no Authorization header on the signed storage URL, nor onward redirects.
    with opener.open(urllib.request.Request(location), timeout=45) as response:
        data = response.read(ARCHIVE_LIMIT + 1)
    require(len(data) == artifact["size_in_bytes"] and len(data) <= ARCHIVE_LIMIT)
    require("sha256:" + hashlib.sha256(data).hexdigest() == digest)
    return data


def extract_native(data: bytes, output: Path) -> dict:
    require(not output.exists())
    with zipfile.ZipFile(io.BytesIO(data)) as archive:
        entries = archive.infolist()
        require(
            1 <= len(entries) <= 4096 and sum(row.file_size for row in entries) <= 512 * 1024 * 1024
        )
        require(len({row.filename for row in entries}) == len(entries))
        require(
            all(
                not row.filename.startswith("/")
                and "\\" not in row.filename
                and ".." not in PurePosixPath(row.filename).parts
                and (row.external_attr >> 16) & 0o170000 in (0, 0o100000, 0o040000)
                for row in entries
            )
        )
        manifests = [
            row for row in entries if row.filename.endswith("sphere-awg-native/manifest.json")
        ]
        apks = [
            row
            for row in entries
            if row.filename.endswith("app/build/outputs/apk/dev/debug/app-dev-debug.apk")
        ]
        require(
            len(manifests) == len(apks) == 1
            and 0 < manifests[0].file_size <= 65536
            and 0 < apks[0].file_size <= APK_LIMIT
        )
        raw = archive.read(manifests[0])
        manifest = json.loads(raw)
        require(
            manifest.get("runtime_sleep_clock_patch_applied") is True
            and manifest.get("jni_lifecycle_hardened") is True
        )
        rows = manifest["artifacts"]
        require(
            len(rows) == 3
            and {row["abi"] for row in rows} == {"arm64-v8a", "armeabi-v7a", "x86_64"}
        )
        with zipfile.ZipFile(io.BytesIO(archive.read(apks[0]))) as apk:
            require(len(apk.namelist()) == len(set(apk.namelist())))
            require(
                {name for name in apk.namelist() if name.endswith("/libwg-go.so")}
                == {f"lib/{row['abi']}/libwg-go.so" for row in rows}
            )
            verified = []
            for row in rows:
                info = apk.getinfo(f"lib/{row['abi']}/libwg-go.so")
                require(0 < info.file_size <= 64 * 1024 * 1024)
                content = apk.read(info)
                require(hashlib.sha256(content).hexdigest() == row["sha256"])
                verified.append((row["abi"], content))
        output.mkdir(parents=True)
        for abi, content in verified:
            directory = output / "jniLibs" / abi
            directory.mkdir(parents=True)
            (directory / "libwg-go.so").write_bytes(content)
        (output / "manifest.json").write_bytes(raw)
        return {
            "nativeManifestSha256": hashlib.sha256(raw).hexdigest(),
            "nativeAbis": sorted(row["abi"] for row in rows),
        }


def seal(apk: Path, recipient_der: str, metadata: dict, output: Path) -> dict:
    from cryptography.hazmat.primitives import hashes
    from cryptography.hazmat.primitives.asymmetric import padding
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM

    require(not output.exists() and 0 < apk.stat().st_size <= APK_LIMIT)
    data = apk.read_bytes()
    key = AESGCM.generate_key(bit_length=256)
    nonce = os.urandom(12)
    receipt = dict(
        metadata,
        apkSha256=hashlib.sha256(data).hexdigest(),
        apkBytes=len(data),
        kind="sphere-encrypted-android-pilot",
        schemaVersion=1,
        apkSignedByMaintainer=False,
        runtimeInstalled=False,
        productionAccepted=False,
    )
    aad = CONTEXT + b"\0" + canonical(receipt)
    ciphertext = AESGCM(key).encrypt(nonce, data, aad)
    wrapped = recipient(recipient_der).encrypt(
        key,
        padding.OAEP(mgf=padding.MGF1(hashes.SHA256()), algorithm=hashes.SHA256(), label=CONTEXT),
    )
    header = {
        "receipt": receipt,
        "nonce": base64.b64encode(nonce).decode(),
        "wrappedKey": base64.b64encode(wrapped).decode(),
    }
    with output.open("xb") as stream:
        stream.write(canonical(header) + b"\n" + ciphertext)
    return receipt


def verify_configured_output(root: Path, native: Path, source: str) -> None:
    clean_components(root)
    build_config = (
        root
        / "android/app/build/generated/source/buildConfig/dev/debug/com/sphereplatform/agent/BuildConfig.java"
    )
    generated = build_config.read_text(encoding="utf-8")
    values = {
        "APPLICATION_ID": "com.sphereplatform.agent.pilot.debug",
        "GIT_SHA": source,
        "DEFAULT_SERVER_URL": "",
        "DEFAULT_FALLBACK_SERVER_URL": "",
        "DEFAULT_API_KEY": os.environ["SPHERE_ENROLLMENT_KEY"],
        "CONFIG_URL": os.environ["SPHERE_CONFIG_URL"],
        "CONFIG_MIRROR_URLS": os.environ["SPHERE_CONFIG_MIRROR_URLS"],
        "DISCOVERY_INSTALLATION_ID": os.environ["SPHERE_DISCOVERY_INSTALLATION_ID"],
        "DISCOVERY_PUBLIC_KEY": os.environ["SPHERE_DISCOVERY_PUBLIC_KEY"],
        "DISCOVERY_KEY_ID": os.environ["SPHERE_DISCOVERY_KEY_ID"],
    }
    require(
        all(name + " = " + json.dumps(value) + ";" in generated for name, value in values.items())
    )
    require(
        all(
            name + " = true;" in generated
            for name in ("APP_SCOPED_VPN_CANARY", "STREAM_PLANAR_INPUT", "CONTINUOUS_INPUT_CANARY")
        )
    )
    require("STREAM_GPU_BRIDGE = false;" in generated)
    apk = root / "android/app/build/outputs/apk/dev/debug/app-dev-debug.apk"
    manifest = json.loads((native / "manifest.json").read_text())
    with zipfile.ZipFile(apk) as archive:
        require(len(archive.namelist()) == len(set(archive.namelist())))
        require(
            {p for p in archive.namelist() if p.endswith("/libwg-go.so")}
            == {f"lib/{row['abi']}/libwg-go.so" for row in manifest["artifacts"]}
        )
        for row in manifest["artifacts"]:
            require(
                hashlib.sha256(archive.read(f"lib/{row['abi']}/libwg-go.so")).hexdigest()
                == row["sha256"]
            )


def unseal(
    source: Path, private_pem: bytes, expected_source: str, expected_run: int, output: Path
) -> dict:
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import padding
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM

    require(
        isinstance(expected_source, str)
        and bool(re.fullmatch(r"[a-f0-9]{40}", expected_source))
        and type(expected_run) is int
        and expected_run > 0
    )
    require(not output.exists() and 16 < source.stat().st_size <= APK_LIMIT + 16384)
    with source.open("rb") as stream:
        line = stream.readline(16385)
        require(line.endswith(b"\n") and len(line) <= 16384)
        header = json.loads(line)
        ciphertext = stream.read(APK_LIMIT + 17)
        require(not stream.read(1))
    require(header.keys() == {"receipt", "nonce", "wrappedKey"})
    receipt = header["receipt"]
    require(
        receipt.get("sourceRevision") == expected_source
        and receipt.get("packageRunId") == expected_run
        and receipt.get("kind") == "sphere-encrypted-android-pilot"
        and receipt.get("schemaVersion") == 1
        and receipt.get("runtimeInstalled") is False
        and receipt.get("apkSignedByMaintainer") is False
    )
    key = serialization.load_pem_private_key(private_pem, password=None)
    secret = key.decrypt(
        base64.b64decode(header["wrappedKey"], validate=True),
        padding.OAEP(mgf=padding.MGF1(hashes.SHA256()), algorithm=hashes.SHA256(), label=CONTEXT),
    )
    data = AESGCM(secret).decrypt(
        base64.b64decode(header["nonce"], validate=True),
        ciphertext,
        CONTEXT + b"\0" + canonical(receipt),
    )
    require(
        len(data) == receipt["apkBytes"]
        and hashlib.sha256(data).hexdigest() == receipt["apkSha256"]
    )
    with output.open("xb") as stream:
        stream.write(data)
    return receipt


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=["admit", "prepare", "seal", "unseal"])
    parser.add_argument("--run-id", type=int)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--input", type=Path)
    parser.add_argument("--key", type=Path)
    parser.add_argument("--source")
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[2]
    if args.action == "admit":
        token = os.environ["GH_TOKEN"]
        repo = os.environ["GITHUB_REPOSITORY"]
        run = api_json(repo, f"/actions/runs/{args.run_id}", token)
        tested, head = validate_run(root, args.run_id, repo, run)
        clean_components(root)
        validate_full_job(api_json(repo, validation_jobs_path(args.run_id, run), token))
        artifacts = api_json(repo, f"/actions/runs/{args.run_id}/artifacts?per_page=100", token)
        require(artifacts.get("total_count", 101) <= 100)
        matches = [
            row
            for row in artifacts["artifacts"]
            if row["name"] == "android-app-vpn-candidate-" + tested
        ]
        require(
            len(matches) == 1
            and matches[0]["workflow_run"]["id"] == args.run_id
            and matches[0]["workflow_run"]["head_sha"] == tested
        )
        artifact = matches[0]
        native = extract_native(download_archive(repo, artifact, token), args.output)
        value = dict(
            native,
            sourceRevision=head,
            androidTree=git(root, "rev-parse", "HEAD:android"),
            validationSource=tested,
            validationRunId=args.run_id,
            nativeArtifactId=artifact["id"],
            nativeArtifactDigest=artifact["digest"],
        )
        (args.output / "validation.json").write_bytes(canonical(value))
    elif args.action == "prepare":
        prepare_configuration(
            os.environ["SPHERE_PILOT_PACKAGE_CONFIG"], Path(os.environ["GITHUB_ENV"]), args.output
        )
    elif args.action == "seal":
        native = args.key.parent / "native"
        value = json.loads((native / "validation.json").read_bytes())
        require(value["sourceRevision"] == git(root, "rev-parse", "HEAD"))
        verify_configured_output(root, native, value["sourceRevision"])
        value.update(
            packageRunId=int(os.environ["GITHUB_RUN_ID"]),
            repository=os.environ["GITHUB_REPOSITORY"],
        )
        receipt = seal(args.input, args.key.read_text(), value, args.output)
        args.output.with_suffix(".receipt.json").write_bytes(canonical(receipt))
    else:
        unseal(args.input, args.key.read_bytes(), args.source, args.run_id, args.output)
    print(json.dumps({"action": args.action, "completed": True, "runtimeInstalled": False}))


if __name__ == "__main__":
    try:
        main()
    except Exception:
        # URLs, provider/config text and arbitrary API exceptions are private.
        print(json.dumps({"completed": False, "code": "android_cloud_package_not_admitted"}))
        raise SystemExit(2)

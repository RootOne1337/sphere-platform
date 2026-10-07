"""Build a small standalone touch helper/optional disposable receiver; no device changes."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import tempfile
import zipfile
from pathlib import Path


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--sdk", type=Path, required=True)
    parser.add_argument("--java-home", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--receiver", action="store_true")
    parser.add_argument("--platform", default="android-35")
    parser.add_argument("--build-tools", default="35.0.0")
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[2]
    native = root / "android/app/src/main/java/com/sphereplatform/agent/commands"
    sources = [native / f"{name}.java" for name in ("RootTouchSession", "RootTouchWire", "RootTouchBridge")]
    if args.receiver:
        # The receiver must be independent of the injector being verified.
        sources = [Path(__file__).resolve().parent / "android/TouchCanaryActivity.java"]
    platform = args.sdk / "platforms" / args.platform / "android.jar"
    build = args.sdk / "build-tools" / args.build_tools
    suffix = ".exe" if os.name == "nt" else ""
    java, javac = (args.java_home / "bin" / (name + suffix) for name in ("java", "javac"))
    aapt = build / ("aapt" + suffix)
    for path in [*sources, java, javac, platform, build / "lib/d8.jar", *([aapt] if args.receiver else [])]:
        if not path.is_file():
            parser.error(f"Required file does not exist: {path}")
    destination = args.output.resolve()
    if destination.exists() or destination.suffix != (".apk" if args.receiver else ".jar"):
        parser.error("Choose a fresh .jar helper or .apk receiver output.")
    destination.parent.mkdir(parents=True, exist_ok=True)
    flags = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0

    def run(command: list[str]) -> None:
        subprocess.run(command, check=True, timeout=120, creationflags=flags)
    with tempfile.TemporaryDirectory(prefix="sphere-touch-build-", dir=destination.parent) as temporary:
        work = Path(temporary)
        classes, dex = work / "classes", work / "dex"
        classes.mkdir()
        dex.mkdir()
        run([str(javac), "--release", "8", "-cp", str(platform), "-d", str(classes), *map(str, sources)])
        run([str(java), "-cp", str(build / "lib/d8.jar"), "com.android.tools.r8.D8",
                        "--min-api", "26", "--lib", str(platform), "--output", str(dex),
                        *map(str, sorted(classes.rglob("*.class")))])
        if args.receiver:
            manifest = work / "AndroidManifest.xml"
            manifest.write_text('''<manifest xmlns:android="http://schemas.android.com/apk/res/android"
package="com.sphereplatform.audit.touchinput" android:versionCode="1" android:versionName="1">
<uses-sdk android:minSdkVersion="26" android:targetSdkVersion="28"/>
<application android:debuggable="true" android:label="Sphere touch canary">
<activity android:name=".TouchCanaryActivity" android:exported="true" android:screenOrientation="landscape"/>
</application></manifest>''', encoding="utf-8")
            run([str(aapt), "package", "-f", "-M", str(manifest), "-I", str(platform), "-F", str(destination)])
        with zipfile.ZipFile(destination, "a" if args.receiver else "w", zipfile.ZIP_DEFLATED) as archive:
            archive.write(dex / "classes.dex", "classes.dex")
    print(json.dumps({"artifact": str(destination), "bytes": destination.stat().st_size,
                      "sha256": hashlib.sha256(destination.read_bytes()).hexdigest(),
                      "source_sha256": {str(path.relative_to(root)): hashlib.sha256(path.read_bytes()).hexdigest() for path in sources},
                      "receiver": args.receiver, "deviceChangesPerformed": False}))


if __name__ == "__main__":
    main()

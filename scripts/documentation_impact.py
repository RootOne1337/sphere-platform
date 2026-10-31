"""Suggest documentation reviews from changed paths; never modifies files or services.

This is a curated, deliberately incomplete path map, not a semantic diff or a
requirement that every suggested document change. Unknown paths remain visible.
"""

from __future__ import annotations

import argparse
import fnmatch
import json
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


@dataclass(frozen=True)
class Rule:
    name: str
    patterns: tuple[str, ...]
    documents: tuple[str, ...]
    checks: tuple[str, ...] = ()


# Patterns use fnmatch: * can span directory separators. All matching rules apply.
RULES = (
    Rule("Web interface", ("frontend/app/*", "frontend/components/*", "frontend/lib/*", "frontend/src/*", "frontend/middleware.ts"),
         ("docs/web-ui-guide.md",)),
    Rule("Script and route studio", ("frontend/app/*/scripts/*", "frontend/components/*script*", "frontend/components/*Script*", "frontend/components/*route*", "frontend/components/*Route*", "backend/api/v1/scripts/*", "backend/services/*script*", "scripts/pilot/*route*", "motor_worker/*"),
         ("docs/operations/SCRIPT-STUDIO.md", "docs/operations/ROUTE-STUDIO.md", "docs/operations/MOTOR-WORKER.md")),
    Rule("HTTP API and schemas", ("backend/api/*", "backend/schemas/*", "backend/main.py", "scripts/export_api_docs.py"),
         ("docs/api-reference.md", "docs/api-endpoints.md", "docs/openapi.json"),
         ("python -m scripts.export_api_docs --check",)),
    Rule("Device and fleet", ("backend/*device*", "frontend/*device*", "frontend/*Device*", "*fleet*", "*Fleet*"),
         ("docs/operations/DEVICE-CATALOG.md", "docs/operations/DEVICE-STREAM-GUIDE.md", "docs/operations/PILOT-ACCEPTANCE.md")),
    Rule("Groups and locations", ("frontend/app/*/groups/*", "frontend/app/*/locations/*", "frontend/src/features/groups/*", "frontend/src/features/locations/*", "backend/api/v1/groups/*", "backend/api/v1/locations/*", "backend/services/group*", "backend/services/location*", "backend/schemas/group*", "backend/schemas/location*"),
         ("docs/operations/GROUP-HIERARCHY.md", "docs/operations/LOCATION-HIERARCHY.md")),
    Rule("Device logs and observability", ("frontend/app/*/logs/*", "frontend/app/*/monitoring/*", "backend/api/v1/logs/*", "backend/api/v1/monitoring/*", "backend/monitoring/*", "infrastructure/monitoring/*"),
         ("docs/operations/DEVICE-LOG-STORAGE.md", "docs/operations/OBSERVABILITY.md")),
    Rule("Session and user access", ("frontend/lib/store.ts", "frontend/src/features/access/*", "frontend/app/*/users/*", "frontend/app/*/settings/*", "backend/api/v1/auth/*", "backend/api/v1/users/*", "backend/core/security.py"),
         ("docs/security/frontend-sessions.md", "docs/operations/USER-ACCESS.md")),
    Rule("Tasks and orchestration", ("frontend/app/*/tasks/*", "frontend/app/*/orchestration/*", "frontend/app/*/pipeline-settings/*", "backend/api/v1/tasks/*", "backend/api/v1/pipelines/*", "backend/tasks/*"),
         ("docs/operations/TASKS-AND-ORCHESTRATION.md", "docs/operations/PIPELINE-DEFINITIONS.md", "docs/security/task-control-protocol.md")),
    Rule("VPN", ("*vpn*", "*VPN*", "*Vpn*", "*wireguard*", "*WireGuard*"),
         ("docs/operations/VPN-PROFILES.md", "docs/operations/VPN-CONTROL-OUTCOMES.md")),
    Rule("Android agent", ("android/*", "agent-config/*"),
         ("docs/android-agent.md", "docs/operations/ANDROID-CLOUD-PILOT.md")),
    Rule("PC agent", ("pc-agent/*",), ("docs/pc-agent.md",)),
    Rule("Configuration and deployment", ("docker-compose*.yml", ".env.example", "backend/core/config.py", "infrastructure/*", "alembic/*", "backend/Dockerfile*", "frontend/Dockerfile*"),
         ("docs/configuration.md", "docs/deployment.md", "docs/operations/STARTUP.md")),
    Rule("Protocol and architecture", ("backend/websocket/*", "backend/services/*", "backend/models/*", "specs/*"),
         ("docs/architecture.md",)),
    Rule("Documentation system", ("docs/*", "README.md", "CONTRIBUTING.md", "scripts/check_documentation_status.py", "scripts/documentation_impact.py"),
         ("docs/DOCUMENTATION.md", "docs/README.md"),
         ("python -m scripts.check_documentation_status",)),
    Rule("CI and contribution", (".github/*", ".pre-commit-config.yaml", "pyproject.toml", "Makefile"),
         ("CONTRIBUTING.md", ".github/REPOSITORY-GUIDE.md")),
    Rule("n8n integration", ("n8n-nodes/*",), ("docs/architecture.md", "docs/api-reference.md")),
)


def paths_from_name_status(data: bytes) -> list[str]:
    """Parse Git -z name-status, keeping both endpoints of renames/copies."""
    parts = data.split(b"\0")
    if parts and parts[-1] == b"":
        parts.pop()
    result: list[str] = []
    i = 0
    while i < len(parts):
        status = parts[i].decode("ascii")
        i += 1
        count = 2 if status.startswith(("R", "C")) else 1
        if i + count > len(parts):
            raise ValueError("Incomplete git name-status output")
        result.extend(p.decode("utf-8", errors="surrogateescape") for p in parts[i:i + count])
        i += count
    return result


def git(*args: str) -> bytes:
    return subprocess.run(["git", *args], cwd=ROOT, check=True, stdout=subprocess.PIPE,
                          stderr=subprocess.PIPE).stdout


def changed_paths(mode: str, base: str | None = None) -> list[str]:
    if mode == "base":
        if not base or base.startswith("-"):
            raise ValueError("The base must be a revision, not an option")
        # Merge-base diff measures changes introduced by this branch, not base changes.
        data = git("diff", "--name-status", "-z", "--find-renames", f"{base}...HEAD", "--")
    elif mode == "staged":
        data = git("diff", "--cached", "--name-status", "-z", "--find-renames", "--")
    elif mode == "worktree":
        # HEAD vs working tree includes staged and unstaged tracked changes.
        data = git("diff", "HEAD", "--name-status", "-z", "--find-renames", "--")
    else:
        raise ValueError(f"Unknown mode: {mode}")
    paths = paths_from_name_status(data)
    if mode == "worktree":
        paths.extend(p.decode("utf-8", errors="surrogateescape") for p in
                     git("ls-files", "--others", "--exclude-standard", "-z").split(b"\0") if p)
    return sorted(set(paths))


def analyze(paths: list[str]) -> dict:
    normalized = sorted(set(p.replace("\\", "/").removeprefix("./") for p in paths))
    matched: set[str] = set()
    groups = []
    for rule in RULES:
        files = [p for p in normalized if any(fnmatch.fnmatchcase(p, pattern) for pattern in rule.patterns)]
        if files:
            matched.update(files)
            groups.append({"area": rule.name, "matchedPaths": files,
                           "reviewCandidates": list(rule.documents), "suggestedChecks": list(rule.checks)})
    return {"version": 1, "changedPaths": normalized, "areas": groups,
            "unmappedPaths": [p for p in normalized if p not in matched],
            "limitations": "Path-based suggestions only: matches do not prove impact, completeness, freshness, runtime or acceptance. Review dependencies and actual behaviour."}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    modes = parser.add_mutually_exclusive_group(required=True)
    modes.add_argument("--base", metavar="REV", help="branch diff from merge base REV to HEAD (committed changes only)")
    modes.add_argument("--staged", action="store_true", help="staged changes only")
    modes.add_argument("--worktree", action="store_true", help="tracked changes from HEAD plus untracked non-ignored files")
    modes.add_argument("--path", action="append", help="repository-relative path to assess; repeat for multiple paths")
    parser.add_argument("--json", action="store_true", help="emit JSON for tools")
    args = parser.parse_args()
    try:
        paths = args.path if args.path is not None else changed_paths(
            "base" if args.base else "staged" if args.staged else "worktree", args.base)
        result = analyze(paths)
    except (subprocess.CalledProcessError, ValueError) as exc:
        details = exc.stderr.decode("utf-8", errors="replace").strip() if isinstance(exc, subprocess.CalledProcessError) else str(exc)
        print(f"Не удалось получить изменения: {details}", file=sys.stderr)
        return 2
    if args.json:
        print(json.dumps(result, ensure_ascii=True, indent=2))
        return 0
    print(f"Изменённых путей: {len(result['changedPaths'])}. Рекомендации требуют ручной проверки.\n")
    for area in result["areas"]:
        print(f"{area['area']} ({len(area['matchedPaths'])}):")
        for path in area["matchedPaths"]:
            print(f"  источник: {path}")
        for document in area["reviewCandidates"]:
            print(f"  проверить: {document}")
        for check in area["suggestedChecks"]:
            print(f"  команда:  {check}")
    if result["unmappedPaths"]:
        print("\nБез правила — оценить вручную:")
        for path in result["unmappedPaths"]:
            print(f"  {path}")
    print("\nСовпадения не гарантируют полноты, актуальности и приёмки; учитывайте зависимости и реальное поведение.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

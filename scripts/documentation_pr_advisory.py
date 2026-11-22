"""Read-only, bounded PR changed-file advisory for GitHub Actions.

The caller must execute this file and documentation_impact from a trusted base
checkout and supply a separate checkout of the event's PR head. No GitHub data
is executed, and the API response is never used as a shell input.
"""

from __future__ import annotations

import html
import json
import os
import re
import subprocess
import sys
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

from scripts.documentation_impact import analyze

PER_PAGE = 100
MAX_FILES = 3000
MAX_RESPONSE_BYTES = 32 * 1024 * 1024
MAX_RENDERED_PATHS = 100
SHA = re.compile(r"^[a-f0-9]{40}$")
REPOSITORY = re.compile(r"^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$")


class AdvisoryIncomplete(Exception):
    """The result cannot be safely presented as a complete PR file list."""


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def checked_metadata(value: object) -> tuple[str, str, int]:
    if not isinstance(value, dict):
        raise AdvisoryIncomplete("Invalid pull request metadata")
    head, base, count = value.get("head"), value.get("base"), value.get("changed_files")
    if not isinstance(head, dict) or not isinstance(base, dict):
        raise AdvisoryIncomplete("Missing pull request head or base")
    head_sha, base_sha = head.get("sha"), base.get("sha")
    if not isinstance(head_sha, str) or not SHA.fullmatch(head_sha):
        raise AdvisoryIncomplete("Invalid pull request head SHA")
    if not isinstance(base_sha, str) or not SHA.fullmatch(base_sha):
        raise AdvisoryIncomplete("Invalid pull request base SHA")
    if type(count) is not int or count < 0:
        raise AdvisoryIncomplete("Invalid changed-file count")
    return head_sha, base_sha, count


def parse_files(items: object) -> list[str]:
    if not isinstance(items, list) or len(items) > PER_PAGE:
        raise AdvisoryIncomplete("Invalid changed-file page")
    paths = []
    for item in items:
        if not isinstance(item, dict):
            raise AdvisoryIncomplete("Invalid changed-file entry")
        status, name = item.get("status"), item.get("filename")
        if status not in {"added", "removed", "modified", "renamed", "copied", "changed", "unchanged"}:
            raise AdvisoryIncomplete("Unknown changed-file status")
        if not isinstance(name, str) or not name or len(name) > 4096 or "\0" in name:
            raise AdvisoryIncomplete("Invalid changed-file path")
        paths.append(name)
        if status in {"renamed", "copied"}:
            previous = item.get("previous_filename")
            if not isinstance(previous, str) or not previous or len(previous) > 4096 or "\0" in previous:
                raise AdvisoryIncomplete("Missing previous path for rename or copy")
            paths.append(previous)
    return paths


def collect(fetch, expected_head: str, expected_base: str, checkout_head: str) -> dict:
    """Only analyze a complete, stable API listing for the checked-out revision."""
    before = checked_metadata(fetch(""))
    if before[0] != expected_head or checkout_head != expected_head or before[1] != expected_base:
        raise AdvisoryIncomplete("PR head, base or checkout does not match the event")
    if before[2] >= MAX_FILES:
        raise AdvisoryIncomplete("PR reaches or exceeds GitHub's 3000-file API limit")
    paths: list[str] = []
    filenames: set[str] = set()
    count = 0
    for page in range(1, MAX_FILES // PER_PAGE + 1):
        items = fetch(f"/files?per_page={PER_PAGE}&page={page}")
        paths.extend(parse_files(items))
        for item in items:
            if item["filename"] in filenames:
                raise AdvisoryIncomplete("File listing contains duplicate entries")
            filenames.add(item["filename"])
        count += len(items)
        if count > before[2] or count >= MAX_FILES:
            raise AdvisoryIncomplete("File listing exceeds the expected count or API limit")
        if len(items) < PER_PAGE:
            break
    else:
        raise AdvisoryIncomplete("File listing may be truncated by the API")
    after = checked_metadata(fetch(""))
    if before != after:
        raise AdvisoryIncomplete("PR head, base or file count changed during the request")
    if count != before[2]:
        raise AdvisoryIncomplete("File listing is incomplete")
    return analyze(paths)


def safe_code(value: str) -> str:
    # JSON escaping makes newlines/control characters visible, and HTML escaping
    # prevents untrusted filenames from becoming Markdown, links or raw HTML.
    displayed = value if len(value) <= 96 else value[:96] + "… [обрезано]"
    encoded = json.dumps(displayed, ensure_ascii=True)
    escaped = "".join(c if c.isascii() and (c.isalnum() or c in " /.-") else f"&#{ord(c)};" for c in encoded)
    return "<code>" + escaped + "</code>"


def render(result: dict) -> str:
    lines = ["## Подсказки по документации", "",
             "Это эвристика по путям из проверенного списка PR, не проверка смысла изменений.",
             f"Уникальных путей (включая прежние имена): {len(result['changedPaths'])}.", ""]
    remaining = MAX_RENDERED_PATHS
    for area in result["areas"]:
        lines.extend([f"### {html.escape(area['area'])}", ""])
        for path in area["matchedPaths"][:remaining]:
            lines.append(f"- Изменение: {safe_code(path)}")
        remaining -= min(remaining, len(area["matchedPaths"]))
        for path in area["reviewCandidates"]:
            lines.append(f"- Кандидат для проверки: {safe_code(path)}")
        for check in area["suggestedChecks"]:
            lines.append(f"- Возможная проверка: {safe_code(check)}")
        lines.append("")
    if result["unmappedPaths"]:
        lines.extend(["### Без правила — проверить вручную", ""])
        for path in result["unmappedPaths"][:remaining]:
            lines.append(f"- {safe_code(path)}")
        remaining -= min(remaining, len(result["unmappedPaths"]))
    if remaining == 0:
        lines.extend(["", "Список путей в выводе ограничен; оценка выполнена по полному полученному списку."])
    lines.extend(["", "Карта не является полной: совпадение или его отсутствие не подтверждает актуальность документации.", ""])
    return "\n".join(lines)


def fetcher(api_url: str, repository: str, number: int, token: str):
    parsed = urllib.parse.urlsplit(api_url)
    if parsed.scheme != "https" or not parsed.netloc or parsed.username or parsed.password or parsed.query or parsed.fragment:
        raise AdvisoryIncomplete("Invalid GitHub API URL")
    if not REPOSITORY.fullmatch(repository) or type(number) is not int or number <= 0 or not token:
        raise AdvisoryIncomplete("Missing or invalid repository, PR number or token")
    base = api_url.rstrip("/") + "/repos/" + repository + "/pulls/" + str(number)
    opener = urllib.request.build_opener(NoRedirect())

    def fetch(suffix: str):
        request = urllib.request.Request(base + suffix, headers={
            "Accept": "application/vnd.github+json", "Authorization": "Bearer " + token,
            "X-GitHub-Api-Version": "2022-11-28", "User-Agent": "sphere-documentation-advisory",
        })
        try:
            with opener.open(request, timeout=15) as response:
                data = response.read(MAX_RESPONSE_BYTES + 1)
            if len(data) > MAX_RESPONSE_BYTES:
                raise AdvisoryIncomplete("GitHub API response exceeds the size limit")
            return json.loads(data)
        except (OSError, ValueError, urllib.error.URLError) as exc:
            raise AdvisoryIncomplete("GitHub API unavailable or returned invalid data") from exc

    return fetch


def main() -> int:
    try:
        event = json.loads(Path(os.environ["GITHUB_EVENT_PATH"]).read_text(encoding="utf-8"))
        pull = event["pull_request"]
        head, base = pull["head"]["sha"], pull["base"]["sha"]
        number = event["number"]
        if not isinstance(head, str) or not SHA.fullmatch(head) or not isinstance(base, str) or not SHA.fullmatch(base):
            raise AdvisoryIncomplete("Invalid event SHA")
        trusted = subprocess.run(["git", "-C", os.environ["TRUSTED_BASE_PATH"], "rev-parse", "HEAD"],
                                 check=True, capture_output=True, text=True, timeout=10).stdout.strip()
        if trusted != base:
            raise AdvisoryIncomplete("Trusted base checkout does not match the event")
        checkout = subprocess.run(["git", "-C", os.environ["PR_CHECKOUT_PATH"], "rev-parse", "HEAD"],
                                  check=True, capture_output=True, text=True, timeout=10).stdout.strip()
        fetch = fetcher(os.environ["GITHUB_API_URL"], os.environ["GITHUB_REPOSITORY"], number, os.environ["GITHUB_TOKEN"])
        summary = render(collect(fetch, head, base, checkout))
    except (AdvisoryIncomplete, KeyError, OSError, ValueError, TypeError, subprocess.SubprocessError) as exc:
        # Do not publish arbitrary network, subprocess or exception details.
        reason = str(exc) if isinstance(exc, AdvisoryIncomplete) else "event, checkout or API unavailable"
        summary = ("## Подсказки по документации: неполный результат\n\n"
                   + html.escape(reason) + ". Проверьте изменения и документацию вручную; "
                   "вывод об отсутствии влияния невозможен. GitHub API ограничивает список 3000 файлами.\n\n"
                   "Локальная альтернатива при доступных base, head и общем предке: "
                   "`python -m scripts.documentation_impact --base <база>`; "
                   "используйте revision базовой ветки и checkout проверяемого head.\n")
    try:
        with Path(os.environ["GITHUB_STEP_SUMMARY"]).open("a", encoding="utf-8") as stream:
            stream.write(summary)
    except (OSError, KeyError):
        print("Documentation advisory could not write the step summary.", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

"""Exercise the export orchestration without capturing real user data."""
import json
import os
import shutil
import subprocess
from pathlib import Path

import pytest


@pytest.mark.skipif(os.name != 'nt' or not shutil.which('powershell'), reason='Windows PowerShell required')
@pytest.mark.parametrize(('full', 'skip_browser'), [(False, False), (True, False), (False, True)])
def test_export_dispatches_matching_profiles_and_flags(tmp_path, full, skip_browser):
    root = Path(__file__).resolve().parents[1]
    original = (root / 'scripts/migration/export-to-ssd.ps1').read_text(encoding='utf-8')
    start = original.index('function Invoke-Python(')
    end = original.index('Push-Location $root', start)
    mock = '''function Invoke-Python([string]$Script, [string[]]$Arguments) {
    @{Script=$Script; Arguments=@($Arguments)} | ConvertTo-Json -Compress | Add-Content -LiteralPath $env:MIGRATION_DISPATCH_LOG
    if ($Script -in @('capture_workspace.py','backup_data.py','backup_routes_essential.py','backup_routes_sqlite.py','backup_selected_files.py','backup_development_records.py','backup_codex.py')) {
        New-Item -ItemType Directory -Path $Arguments[0] -Force | Out-Null
    }
    if ($Script -eq 'backup_routes_sqlite.py') { '{"entries":[]}' | Set-Content -LiteralPath (Join-Path $Arguments[0] 'manifest.json') }
    if ($Script -eq 'backup_codex.py') { '{"allSqliteHealthy":true}' | Set-Content -LiteralPath (Join-Path $Arguments[0] 'verification.json') }
}
'''
    scripts = tmp_path / 'repo' / 'scripts' / 'migration'
    scripts.mkdir(parents=True)
    exporter = scripts / 'export-to-ssd.ps1'
    exporter.write_text(original[:start] + mock + original[end:], encoding='utf-8')
    (scripts / 'capture-host.ps1').write_text(
        'param([string]$Destination)\nNew-Item -ItemType Directory -Path $Destination | Out-Null\n'
        "'[]' | Set-Content -LiteralPath (Join-Path $Destination 'issues.json')\n", encoding='utf-8')
    (scripts / 'save-running-images.ps1').write_text('param([string]$OutputDirectory)\n', encoding='utf-8')
    log = tmp_path / 'dispatch.jsonl'
    env = os.environ.copy()
    env['MIGRATION_DISPATCH_LOG'] = str(log)
    destination = tmp_path / 'export'
    browser_profile = tmp_path / 'browser'
    (browser_profile / 'File System').mkdir(parents=True)
    args = ['powershell', '-NoProfile', '-File', str(exporter), '-Destination', str(destination),
            '-AllowSameVolume', '-BrowserProfile', str(browser_profile), '-BrowserBucket', '123']
    if full:
        args.extend(['-IncludeModelsAndOldApks', '-IncludeImages'])
    if skip_browser:
        args.append('-SkipBrowserData')
    subprocess.run(args, check=True, capture_output=True, text=True, env=env)
    dispatched = [json.loads(line) for line in log.read_text(encoding='utf-8-sig').splitlines()]
    commands = {entry['Script']: entry['Arguments'] for entry in dispatched}
    assert {'capture_workspace.py', 'backup_data.py', 'backup_verify.py', 'backup_routes_essential.py',
            'backup_routes_sqlite.py', 'backup_selected_files.py', 'backup_development_records.py',
            'backup_codex.py'} <= commands.keys()
    assert commands['backup_selected_files.py'][-2:] == ['--profile', 'all' if full else 'essential']
    if skip_browser:
        assert 'backup_browser_origin.py' not in commands
    else:
        assert commands['backup_browser_origin.py'] == ['--profile', str(browser_profile), '--bucket', '123',
                                                         str(destination / 'browser-origin')]
    assert (destination / 'CAPTURE-RECEIPT.json').is_file()

"""Exercise Windows parser/native WPR validation and reject unsafe launches."""
from pathlib import Path
import platform
import subprocess

import pytest

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts/pilot/collect_disk_writer.ps1"
PROFILE = ROOT / "scripts/pilot/disk-writer.wprp"
pytestmark = pytest.mark.skipif(platform.system() != "Windows", reason="Native Windows WPR checks")


@pytest.mark.parametrize("arguments", [
    ["-DurationSeconds", "29"],
    ["-DurationSeconds", "1801"],
    ["-DurationSeconds", "30", "-IntervalSeconds", "60"],
    ["-StopAfterDropMiB", "1"],
])
def test_invalid_window_is_rejected_without_creating_reports(arguments):
    before = set((ROOT / ".local-pilot").glob("disk-writer-*"))
    result = subprocess.run(["powershell.exe", "-NoProfile", "-NonInteractive", "-File", str(SCRIPT), *arguments],
                            capture_output=True, timeout=15)
    assert result.returncode != 0
    assert set((ROOT / ".local-pilot").glob("disk-writer-*")) == before


def test_windows_recorder_accepts_fixed_memory_profile():
    result = subprocess.run(["wpr.exe", "-profiledetails", str(PROFILE) + "!SphereDiskWriter"],
                            capture_output=True, text=True, timeout=15)
    assert result.returncode == 0, result.stderr
    assert "SphereDiskWriter.Verbose.Memory" in result.stdout
    assert "Number of Buffers\t: 128" in result.stdout
    assert "Buffer Size (KB)\t: 1024" in result.stdout
    assert "FileWrite" in result.stdout and "DiskWriteInit" in result.stdout


def test_nonelevated_launch_does_not_start_recording_or_create_output():
    probe = subprocess.run(["powershell.exe", "-NoProfile", "-NonInteractive", "-Command",
        "([Security.Principal.WindowsPrincipal]::new([Security.Principal.WindowsIdentity]::GetCurrent())).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)"],
        capture_output=True, text=True, timeout=10)
    if probe.stdout.strip() == "True":
        pytest.skip("Negative elevation check requires standard token")
    before = set((ROOT / ".local-pilot").glob("disk-writer-*"))
    result = subprocess.run(["powershell.exe", "-NoProfile", "-NonInteractive", "-File", str(SCRIPT),
                             "-DurationSeconds", "30"], capture_output=True, text=True, timeout=10)
    assert result.returncode == 2
    assert "Nothing started" in result.stderr
    assert set((ROOT / ".local-pilot").glob("disk-writer-*")) == before


def test_status_replacements_work_in_windows_powershell_51(tmp_path):
    # Invoke the production function's AST without starting ETW or requiring
    # elevation; covers the real File.Replace overload, not a mocked filesystem.
    command = r"""
$parseTokens = $null; $parseErrors = $null
$ast = [Management.Automation.Language.Parser]::ParseFile($args[0], [ref]$parseTokens, [ref]$parseErrors)
if ($parseErrors.Count) { throw 'Parse failure' }
$function = $ast.Find({param($node) $node -is [Management.Automation.Language.FunctionDefinitionAst] -and $node.Name -eq 'Save-Status'}, $true)
$output = $args[1]; $encoding = [Text.UTF8Encoding]::new($false)
$status = @{state='first'}; & $function.Body.GetScriptBlock()
$status.state='second'; & $function.Body.GetScriptBlock()
$status.state='third'; & $function.Body.GetScriptBlock()
if ((Get-Content -LiteralPath (Join-Path $output 'status.json') | ConvertFrom-Json).state -ne 'third') { throw 'Latest status lost' }
if ((Get-Content -LiteralPath (Join-Path $output 'status.previous.json') | ConvertFrom-Json).state -ne 'second') { throw 'Previous status lost' }
"""
    # -File preserves native argument passing on PS 5.1.
    helper = tmp_path / "invoke-status.ps1"
    helper.write_text(command, encoding="utf-8")
    result = subprocess.run(["powershell.exe", "-NoProfile", "-NonInteractive", "-File", str(helper),
                             str(SCRIPT), str(tmp_path)], capture_output=True, text=True, timeout=15)
    assert result.returncode == 0, result.stderr

[CmdletBinding()]
param(
    [Parameter(Mandatory)][string]$ConfigPath,
    [Parameter(Mandatory)][string]$PythonExecutable
)
$ErrorActionPreference = 'Stop'
$watchdogRoot = Split-Path -Parent $PSScriptRoot
$watchdogConfig = (Resolve-Path -LiteralPath $ConfigPath).Path
$watchdogPython = (Resolve-Path -LiteralPath $PythonExecutable).Path
Push-Location -LiteralPath $watchdogRoot
try {
    & $watchdogPython -m scripts.ldplayer_watchdog --config $watchdogConfig
    exit $LASTEXITCODE
} finally {
    Pop-Location
}

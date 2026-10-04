[CmdletBinding()]
param(
    [Parameter(Mandatory)][string]$ConfigPath,
    [Parameter(Mandatory)][string]$PythonExecutable
)
$ErrorActionPreference = 'Stop'
$publisherRoot = Split-Path -Parent $PSScriptRoot
$publisherConfig = (Resolve-Path -LiteralPath $ConfigPath).Path
$publisherPython = (Resolve-Path -LiteralPath $PythonExecutable).Path
Push-Location -LiteralPath $publisherRoot
try {
    & $publisherPython -m scripts.discovery_publisher --config $publisherConfig --once
    exit $LASTEXITCODE
} finally {
    Pop-Location
}

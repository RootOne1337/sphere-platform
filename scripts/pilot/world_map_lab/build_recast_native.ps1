param(
    [Parameter(Mandatory)][string]$RecastSource,
    [Parameter(Mandatory)][string]$Zig,
    [Parameter(Mandatory)][string]$Output
)
$ErrorActionPreference = 'Stop'
$revision = git -C $RecastSource rev-parse HEAD
if ($LASTEXITCODE -or $revision -ne '6dc1667f580357e8a2154c28b7867bea7e8ad3a7') {
    throw 'Expected upstream Recast Navigation v1.6.0'
}
New-Item -ItemType Directory -Force $Output | Out-Null
$includes = @("-I$RecastSource/Recast/Include", "-I$RecastSource/Detour/Include")
$sources = @((Get-ChildItem "$RecastSource/Recast/Source/*.cpp").FullName) +
           @((Get-ChildItem "$RecastSource/Detour/Source/*.cpp").FullName)
& $Zig build-lib -O ReleaseFast -lc++ -DDT_POLYREF64 @includes "-femit-bin=$Output/recast.lib" @sources
if ($LASTEXITCODE) { throw 'Recast compilation failed' }
& $Zig c++ -O2 -shared -DDT_POLYREF64 @includes "$PSScriptRoot/ariane_navmesh.cpp" "$Output/recast.lib" -o "$Output/ariane-nav.dll"
if ($LASTEXITCODE) { throw 'Native navigation adapter compilation failed' }
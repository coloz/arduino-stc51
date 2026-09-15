[CmdletBinding()]
param(
    [string]$Fqbn = 'arduino-stc51:mcs251:stc32g12k128:cppcore=enabled,clock=12m',
    [string]$WorkDirectory
)
$ErrorActionPreference = 'Stop'
$RepoRoot = Split-Path -Parent $PSScriptRoot
if (-not $WorkDirectory) { $WorkDirectory = Join-Path $RepoRoot '.build/file-lifecycle' }
$WorkDirectory = [IO.Path]::GetFullPath($WorkDirectory)
$ProbeRoot = Join-Path $WorkDirectory ('probe-' + [guid]::NewGuid().ToString('N'))
$Sketch = Join-Path $ProbeRoot 'FileLifecycle'
New-Item -ItemType Directory -Force $Sketch | Out-Null
$Inputs = @(
    'tests/target/FileLifecycle/FileLifecycle.ino',
    'tests/target/FileLifecycle/backend.c',
    'libraries/SD/src/SDClass.cpp',
    'libraries/SD/src/SDClass.h'
)
$Hashes = @{}
foreach ($InputPath in $Inputs) {
    $Source = Join-Path $RepoRoot $InputPath
    $Target = Join-Path $Sketch (Split-Path -Leaf $Source)
    Copy-Item -LiteralPath $Source -Destination $Target
    $Hash = (Get-FileHash -Algorithm SHA256 -LiteralPath $Source).Hash
    if ((Get-FileHash -Algorithm SHA256 -LiteralPath $Target).Hash -ne $Hash) {
        throw "Probe differs from source: $InputPath"
    }
    $Hashes[$InputPath] = $Hash.ToLowerInvariant()
}
$Result = & (Join-Path $PSScriptRoot 'build-example.ps1') -Fqbn $Fqbn `
    -SketchPath $Sketch -WorkDirectory $WorkDirectory
foreach ($InputPath in $Inputs) {
    if ((Get-FileHash -Algorithm SHA256 -LiteralPath (Join-Path $RepoRoot $InputPath)).Hash.ToLowerInvariant() -ne $Hashes[$InputPath]) {
        throw "Source changed during probe build: $InputPath"
    }
}
$Result | Add-Member -NotePropertyName source_sha256 -NotePropertyValue $Hashes
$Result | ConvertTo-Json -Depth 5 | Set-Content -Encoding UTF8 (Join-Path $ProbeRoot 'build.json')
$Result

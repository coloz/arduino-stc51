[CmdletBinding()]
param(
    [string]$ArduinoCli = 'arduino-cli',
    [string]$Fqbn = 'arduino-stc51:mcs51:stc8g1k08a:clock=12m',
    [string]$SketchPath,
    [string]$WorkDirectory,
    [string]$ToolCacheDirectory
)

$ErrorActionPreference = 'Stop'
$RepoRoot = Split-Path -Parent $PSScriptRoot
$CliCommand = Get-Command $ArduinoCli -CommandType Application -ErrorAction Stop
$ArduinoCli = $CliCommand.Source
if (-not $SketchPath) { $SketchPath = Join-Path $RepoRoot 'examples/Blink' }
$SketchPath = (Resolve-Path -LiteralPath $SketchPath).Path
if (-not (Test-Path -LiteralPath $SketchPath -PathType Container)) {
    throw 'SketchPath must be a sketch directory containing a matching .ino file.'
}
if (-not $WorkDirectory) { $WorkDirectory = Join-Path $RepoRoot '.build/example' }
if (-not $ToolCacheDirectory) { $ToolCacheDirectory = Join-Path $RepoRoot 'sdk/downloads/toolchain' }
$WorkDirectory = [IO.Path]::GetFullPath($WorkDirectory)
$ToolCacheDirectory = [IO.Path]::GetFullPath($ToolCacheDirectory)
if ($WorkDirectory -match '\s' -or $SketchPath -match '\s') {
    throw 'SDCC currently requires sketch and build paths without whitespace.'
}
$Devices = (Get-Content -Raw -Encoding UTF8 (Join-Path $RepoRoot 'tools/variants/devices.json') | ConvertFrom-Json).devices
$FqbnParts = $Fqbn.Split(':')
if ($FqbnParts.Count -lt 3 -or $FqbnParts[0] -ne 'arduino-stc51' -or
    $FqbnParts[1] -ne 'mcs51' -or $FqbnParts[2] -notin @($Devices.id)) {
    throw "Unknown arduino-stc51 board: $Fqbn"
}

function Assert-ExitCode {
    param([string]$Operation)
    if ($LASTEXITCODE -ne 0) { throw "$Operation failed with exit code $LASTEXITCODE." }
}

function Assert-Archive {
    param($System, [string]$Archive)
    if ((Get-Item -LiteralPath $Archive).Length -ne [long]$System.size -or
        (Get-FileHash -LiteralPath $Archive -Algorithm SHA256).Hash.ToLowerInvariant() -ne $System.sha256) {
        throw "Tool archive size or SHA-256 mismatch: $Archive"
    }
}

# Use a fresh installation so removed source files cannot survive a rebuild.
$RunRoot = Join-Path $WorkDirectory ('run-' + [guid]::NewGuid().ToString('N'))
$Data = Join-Path $RunRoot 'data'
$Extract = Join-Path $RunRoot 'extract'
$Build = Join-Path $RunRoot 'build'
New-Item -ItemType Directory -Force -Path $RunRoot,$Data,$Extract,$Build,$ToolCacheDirectory | Out-Null
$VersionLine = Select-String -LiteralPath (Join-Path $RepoRoot 'platform.txt') -Pattern '^version=(.+)$'
$Version = $VersionLine.Matches[0].Groups[1].Value
$Package = & (Join-Path $PSScriptRoot 'package-platform.ps1') -Version $Version -OutputDirectory (Join-Path $RunRoot 'package')
$Platform = Join-Path $Data "packages/arduino-stc51/hardware/mcs51/$Version"
New-Item -ItemType Directory -Force -Path $Platform | Out-Null
& tar -xjf $Package.path -C $Extract
Assert-ExitCode 'Platform extraction'
Copy-Item -Recurse -Force (Join-Path $Extract "arduino-stc51-$Version/*") -Destination $Platform

$Manifest = Get-Content -Raw -Encoding UTF8 (Join-Path $RepoRoot 'tools/toolchain-manifest.json') | ConvertFrom-Json
foreach ($Tool in $Manifest.tools) {
    $System = @($Tool.systems | Where-Object { $_.host -match 'mingw32$' } | Select-Object -First 1)[0]
    if ($null -eq $System) { throw "No Windows tool archive is defined for $($Tool.id)." }
    $Archive = Join-Path $RepoRoot "dist/$($System.archiveFileName)"
    if (-not (Test-Path -LiteralPath $Archive -PathType Leaf)) {
        $Archive = Join-Path $ToolCacheDirectory $System.archiveFileName
        if (-not (Test-Path -LiteralPath $Archive -PathType Leaf)) {
            $Partial = "$Archive.$([guid]::NewGuid().ToString('N')).part"
            & curl.exe --fail --location --retry 3 --silent --show-error --output $Partial $System.url
            Assert-ExitCode "Download $($Tool.id)"
            Assert-Archive -System $System -Archive $Partial
            Move-Item -LiteralPath $Partial -Destination $Archive
        }
    }
    Assert-Archive -System $System -Archive $Archive
    $ToolExtract = Join-Path $Extract $Tool.id
    $ToolTarget = Join-Path $Data "packages/arduino-stc51/tools/$($Tool.packageName)/$($Tool.version)"
    New-Item -ItemType Directory -Force -Path $ToolExtract,$ToolTarget | Out-Null
    if ($Archive.EndsWith('.zip', [StringComparison]::OrdinalIgnoreCase)) {
        Expand-Archive -LiteralPath $Archive -DestinationPath $ToolExtract
    } else {
        & tar -xjf $Archive -C $ToolExtract
        Assert-ExitCode "$($Tool.id) extraction"
    }
    Copy-Item -Recurse -Force (Join-Path $ToolExtract "$($System.archiveRoot)/*") -Destination $ToolTarget
}

# Reuse Arduino CLI's discovery and ctags tools when already installed.
$ArduinoData = if ($env:LOCALAPPDATA) { Join-Path $env:LOCALAPPDATA 'Arduino15' } else { $null }
if ($ArduinoData) {
    $Builtin = Join-Path $ArduinoData 'packages/builtin'
    if (Test-Path -LiteralPath $Builtin) {
        Copy-Item -Recurse -Force -LiteralPath $Builtin -Destination (Join-Path $Data 'packages')
    }
    foreach ($Index in @('package_index.json', 'library_index.json')) {
        $IndexPath = Join-Path $ArduinoData $Index
        if (Test-Path -LiteralPath $IndexPath) { Copy-Item -LiteralPath $IndexPath -Destination $Data }
    }
}
$Config = Join-Path $RunRoot 'arduino-cli.yaml'
# JSON is valid YAML and quotes Windows paths without hand-built escaping.
@{
    directories = @{
        data = $Data
        downloads = (Join-Path $RunRoot 'downloads')
        user = (Join-Path $RunRoot 'user')
    }
} | ConvertTo-Json -Depth 3 | Set-Content -LiteralPath $Config -Encoding UTF8
if (-not (Test-Path -LiteralPath (Join-Path $Data 'package_index.json')) -or
    -not (Test-Path -LiteralPath (Join-Path $Data 'packages/builtin'))) {
    & $ArduinoCli core update-index --config-file $Config | Out-Host
    Assert-ExitCode 'Initialize Arduino CLI indexes and built-in tools'
}
& $ArduinoCli compile --clean --fqbn $Fqbn --build-path $Build --config-file $Config $SketchPath | Out-Host
Assert-ExitCode 'Compile sketch'
$Hex = @(Get-ChildItem -LiteralPath $Build -Filter '*.hex')
if ($Hex.Count -ne 1) { throw "Expected one Intel HEX output in $Build; found $($Hex.Count)." }
Write-Host "Firmware: $($Hex[0].FullName)"
Write-Host "Arduino CLI configuration: $Config"
[pscustomobject]@{
    fqbn = $Fqbn
    firmware = $Hex[0].FullName
    config = $Config
    build = $Build
    platform = $Platform
}

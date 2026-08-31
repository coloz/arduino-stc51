[CmdletBinding()]
param(
    [ValidatePattern('^\d+\.\d+\.\d+$')]
    [string]$Version = '0.0.1',
    [string]$OutputDirectory
)

$ErrorActionPreference = 'Stop'
$RepoRoot = Split-Path -Parent $PSScriptRoot
if (-not $OutputDirectory) { $OutputDirectory = Join-Path $RepoRoot 'dist' }

$TempBase = [IO.Path]::GetTempPath()
$Stage = Join-Path $TempBase ("arduino-stc51-package-" + [guid]::NewGuid().ToString('N'))
$RootName = "arduino-stc51-$Version"
$PackageRoot = Join-Path $Stage $RootName
$ArchiveName = "$RootName.tar.bz2"
$Archive = Join-Path $OutputDirectory $ArchiveName

try {
    New-Item -ItemType Directory -Force -Path $PackageRoot,$OutputDirectory | Out-Null
    Copy-Item -Force (Join-Path $RepoRoot 'boards.txt'),(Join-Path $RepoRoot 'platform.txt'),(Join-Path $RepoRoot 'README.md'),(Join-Path $RepoRoot 'LICENSE') -Destination $PackageRoot
    Copy-Item -Recurse -Force (Join-Path $RepoRoot 'cores/STC') -Destination (New-Item -ItemType Directory -Force -Path (Join-Path $PackageRoot 'cores'))
    $ToolsTarget = New-Item -ItemType Directory -Force -Path (Join-Path $PackageRoot 'tools')
    Copy-Item -Recurse -Force (Join-Path $RepoRoot 'tools/wrapper') -Destination $ToolsTarget
    Copy-Item -Recurse -Force (Join-Path $RepoRoot 'tools/variants') -Destination $ToolsTarget
    Copy-Item -Force (Join-Path $RepoRoot 'tools/toolchain-manifest.json') -Destination $ToolsTarget
    foreach ($PlatformDirectory in @('docs', 'examples', 'libraries', 'LICENSES', 'scripts')) {
        $SourceDirectory = Join-Path $RepoRoot $PlatformDirectory
        if (Test-Path -LiteralPath $SourceDirectory) {
            Copy-Item -Recurse -Force $SourceDirectory -Destination $PackageRoot
        }
    }

    # Keep only auditable SDK metadata in the platform package.  Downloaded
    # vendor archives and extracted sources stay in the ignored local cache.
    $SdkTarget = New-Item -ItemType Directory -Force -Path (Join-Path $PackageRoot 'sdk')
    Copy-Item -Force (Join-Path $RepoRoot 'sdk/README.md'),(Join-Path $RepoRoot 'sdk/manifest.json') -Destination $SdkTarget

    $VariantsTarget = New-Item -ItemType Directory -Force -Path (Join-Path $PackageRoot 'variants')
    Copy-Item -Recurse -Force (Join-Path $RepoRoot 'variants/_common') -Destination $VariantsTarget
    $Devices = (Get-Content -Raw -Encoding UTF8 (Join-Path $RepoRoot 'tools/variants/devices.json') | ConvertFrom-Json).devices
    foreach ($Device in $Devices) {
        $Variant = $Device.model -replace '-', '_'
        Copy-Item -Recurse -Force (Join-Path $RepoRoot "variants/$Variant") -Destination $VariantsTarget
    }

    # Stable timestamps make repeated packaging byte-for-byte reproducible.
    $Timestamp = [datetime]::SpecifyKind([datetime]'2026-08-31T00:00:00', [DateTimeKind]::Utc)
    Get-ChildItem -LiteralPath $PackageRoot -Recurse -Force | ForEach-Object { $_.LastWriteTimeUtc = $Timestamp }
    (Get-Item -LiteralPath $PackageRoot).LastWriteTimeUtc = $Timestamp

    if (Test-Path -LiteralPath $Archive) { Remove-Item -LiteralPath $Archive -Force }
    tar -cjf $Archive -C $Stage $RootName
    if ($LASTEXITCODE -ne 0) { throw 'tar failed to create the platform archive.' }

    $Item = Get-Item -LiteralPath $Archive
    $Hash = (Get-FileHash -LiteralPath $Archive -Algorithm SHA256).Hash.ToLowerInvariant()
    [pscustomobject]@{
        version = $Version
        archiveFileName = $ArchiveName
        size = $Item.Length
        checksum = "SHA-256:$Hash"
        path = $Item.FullName
    }
}
finally {
    if (Test-Path -LiteralPath $Stage) {
        $Resolved = (Resolve-Path -LiteralPath $Stage).Path
        $ExpectedPrefix = [IO.Path]::GetFullPath($TempBase)
        if (-not $Resolved.StartsWith($ExpectedPrefix, [StringComparison]::OrdinalIgnoreCase) -or
            (Split-Path -Leaf $Resolved) -notlike 'arduino-stc51-package-*') {
            throw "Refusing to clean unexpected staging path: $Resolved"
        }
        Remove-Item -LiteralPath $Resolved -Recurse -Force
    }
}

[CmdletBinding()]
param(
    [ValidatePattern('^\d+\.\d+\.\d+$')]
    [string]$Version = '0.0.1',
    [string]$OutputDirectory
)

$ErrorActionPreference = 'Stop'
$RepoRoot = Split-Path -Parent $PSScriptRoot
$PlatformVersion = (Select-String -LiteralPath (Join-Path $RepoRoot 'platform.txt') -Pattern '^version=(.+)$').Matches[0].Groups[1].Value
if ($Version -ne $PlatformVersion) {
    throw "Package version $Version does not match platform.txt version $PlatformVersion."
}
if (-not $OutputDirectory) { $OutputDirectory = Join-Path $RepoRoot 'dist' }

$TempBase = [IO.Path]::GetTempPath()
$Stage = Join-Path $TempBase ("arduino-stc51-package-" + [guid]::NewGuid().ToString('N'))
$RootName = "arduino-stc51-$Version"
$PackageRoot = Join-Path $Stage $RootName
$ArchiveName = "$RootName.tar.bz2"
$Archive = Join-Path $OutputDirectory $ArchiveName
$RootMetadataFiles = @(
    'boards.txt',
    'platform.txt',
    'README.md',
    'RELEASE_NOTES.md',
    'LICENSE'
)
$ReleaseNotesLinkTarget = 'RELEASE_NOTES.md'
$ReadmeReleaseNotesLink = "]($ReleaseNotesLinkTarget)"

try {
    foreach ($MetadataFile in $RootMetadataFiles) {
        if (-not (Test-Path -LiteralPath (Join-Path $RepoRoot $MetadataFile) -PathType Leaf)) {
            throw "Required platform root metadata is missing: $MetadataFile"
        }
    }
    $SourceReadme = Get-Content -Raw -Encoding UTF8 (Join-Path $RepoRoot 'README.md')
    if (-not $SourceReadme.Contains($ReadmeReleaseNotesLink)) {
        throw "README.md does not link to the packaged $ReleaseNotesLinkTarget file."
    }

    New-Item -ItemType Directory -Force -Path $PackageRoot,$OutputDirectory | Out-Null
    foreach ($MetadataFile in $RootMetadataFiles) {
        Copy-Item -Force -LiteralPath (Join-Path $RepoRoot $MetadataFile) -Destination $PackageRoot
    }
    $PackagedReadmePath = Join-Path $PackageRoot 'README.md'
    $PackagedReleaseNotesPath = Join-Path $PackageRoot $ReleaseNotesLinkTarget
    if (-not (Test-Path -LiteralPath $PackagedReleaseNotesPath -PathType Leaf)) {
        throw "Packaged release notes are missing: $ReleaseNotesLinkTarget"
    }
    $PackagedReadme = Get-Content -Raw -Encoding UTF8 $PackagedReadmePath
    if (-not $PackagedReadme.Contains($ReadmeReleaseNotesLink)) {
        throw "Packaged README.md does not link to $ReleaseNotesLinkTarget."
    }
    Copy-Item -Recurse -Force (Join-Path $RepoRoot 'cores/STC') -Destination (New-Item -ItemType Directory -Force -Path (Join-Path $PackageRoot 'cores'))
    $ToolsTarget = New-Item -ItemType Directory -Force -Path (Join-Path $PackageRoot 'tools')
    Copy-Item -Recurse -Force (Join-Path $RepoRoot 'tools/wrapper') -Destination $ToolsTarget
    $VariantToolsTarget = New-Item -ItemType Directory -Force -Path (Join-Path $ToolsTarget 'variants')
    Copy-Item -LiteralPath (Join-Path $RepoRoot 'tools/variants/devices.json') -Destination $VariantToolsTarget
    # The Arduino CLI bridge uses locked fail-closed adapters and alignment
    # helpers. Copy an explicit runtime allow-list so maintenance scripts,
    # regression reports and Python caches stay outside the installed platform.
    $CppCliTarget = New-Item -ItemType Directory -Force -Path (Join-Path $ToolsTarget 'cpp-cli')
    $CppCliRuntimeFiles = @(
        'adapt.py',
        'align-member-functions.py',
        'collect-c-abi-roots.py',
        'select-cpp-archive-sidecars.py',
        'slice-readonly-const-rel.py',
        'split-c-function-tu.py',
        'build-function-split-archive.py',
        'audit-function-split-link-map.py',
        'aslink_map_symbols.py',
        'native-storage.py',
        'stcxx-cli.sh',
        'toolchain-paths.sh',
        'toolchain-lock.json',
        'toolchain-lock.windows-x86_64.json',
        'stcxx-cli.py',
        'archive_members.py',
        'cpp-metadata.py',
        'c-metadata.py',
        'check-heap.py',
        'check-sidecars.py',
        'audit-bridge-warnings.py',
        'audit-heap-link.py',
        'write-link-manifest.py',
        'toolchain-lock.macos-arm64.json',
        'verify-macos-frontend.py',
        'README.md'
    )
    foreach ($RuntimeFile in $CppCliRuntimeFiles) {
        Copy-Item -Force (Join-Path $RepoRoot "tools/cpp-cli/$RuntimeFile") -Destination $CppCliTarget
    }
    $PackagedCppCliFiles = @(
        Get-ChildItem -LiteralPath $CppCliTarget -File |
            ForEach-Object Name |
            Sort-Object
    )
    $ExpectedCppCliFiles = @($CppCliRuntimeFiles | Sort-Object)
    if (($PackagedCppCliFiles -join "`n") -cne ($ExpectedCppCliFiles -join "`n")) {
        throw "Packaged cpp-cli file set differs from the explicit runtime allow-list."
    }
    foreach ($RuntimeFile in $CppCliRuntimeFiles) {
        $SourceHash = (Get-FileHash -Algorithm SHA256 -LiteralPath `
            (Join-Path $RepoRoot "tools/cpp-cli/$RuntimeFile")).Hash
        $PackagedHash = (Get-FileHash -Algorithm SHA256 -LiteralPath `
            (Join-Path $CppCliTarget $RuntimeFile)).Hash
        if ($SourceHash -cne $PackagedHash) {
            throw "Packaged cpp-cli runtime differs from source: $RuntimeFile"
        }
    }
    $CppPipelineTarget = New-Item -ItemType Directory -Force -Path (Join-Path $ToolsTarget 'cpp-core-pipeline')
    foreach ($RuntimeFile in @('audit_and_adapt.py', 'README.md')) {
        Copy-Item -Force (Join-Path $RepoRoot "tools/cpp-core-pipeline/$RuntimeFile") -Destination $CppPipelineTarget
    }
    foreach ($PlatformDirectory in @('libraries', 'LICENSES')) {
        $SourceDirectory = Join-Path $RepoRoot $PlatformDirectory
        if (Test-Path -LiteralPath $SourceDirectory) {
            Copy-Item -Recurse -Force $SourceDirectory -Destination $PackageRoot
        }
    }

    $ExamplesTarget = New-Item -ItemType Directory -Force -Path (Join-Path $PackageRoot 'examples')
    Get-ChildItem -LiteralPath (Join-Path $RepoRoot 'examples') -Directory |
        ForEach-Object { Copy-Item -LiteralPath $_.FullName -Recurse -Force -Destination $ExamplesTarget }

    # Source builds, packaging, index generation and CI checks run from the
    # repository. Arduino recipes only execute tools/wrapper and tools/cpp-cli.
    $ToolchainLicensesTarget = New-Item -ItemType Directory -Force -Path (Join-Path $ToolsTarget 'toolchain-licenses')
    Copy-Item -LiteralPath (Join-Path $RepoRoot 'tools/toolchain-licenses/boost-LICENSE_1_0.txt') -Destination $ToolchainLicensesTarget

    # Keep only auditable SDK metadata in the platform package.  Downloaded
    # vendor archives and extracted sources stay in the ignored local cache.
    $SdkTarget = New-Item -ItemType Directory -Force -Path (Join-Path $PackageRoot 'sdk')
    Copy-Item -Force (Join-Path $RepoRoot 'sdk/README.md'),(Join-Path $RepoRoot 'sdk/manifest.json') -Destination $SdkTarget

    $VariantsTarget = New-Item -ItemType Directory -Force -Path (Join-Path $PackageRoot 'variants')
    Copy-Item -Recurse -Force (Join-Path $RepoRoot 'variants/_common') -Destination $VariantsTarget
    $Devices = (Get-Content -Raw -Encoding UTF8 (Join-Path $RepoRoot 'tools/variants/devices.json') | ConvertFrom-Json).devices
    if (@($Devices | Where-Object { $_.target -ne 'mcs251' }).Count -ne 0) {
        throw 'Only MCS251 devices may enter the platform package.'
    }
    foreach ($Device in $Devices) {
        $Variant = $Device.model -replace '-', '_'
        Copy-Item -Recurse -Force (Join-Path $RepoRoot "variants/$Variant") -Destination $VariantsTarget
    }

    $RequiredCppRuntime = @(
        'tools/cpp-cli/adapt.py',
        'tools/cpp-cli/align-member-functions.py',
        'tools/cpp-cli/collect-c-abi-roots.py',
        'tools/cpp-cli/select-cpp-archive-sidecars.py',
        'tools/cpp-cli/slice-readonly-const-rel.py',
        'tools/cpp-cli/split-c-function-tu.py',
        'tools/cpp-cli/build-function-split-archive.py',
        'tools/cpp-cli/audit-function-split-link-map.py',
        'tools/cpp-cli/aslink_map_symbols.py',
        'tools/cpp-cli/native-storage.py',
        'tools/cpp-cli/stcxx-cli.sh',
        'tools/cpp-cli/toolchain-lock.json',
        'tools/wrapper/stc-native-launch.sh',
        'tools/cpp-core-pipeline/audit_and_adapt.py'
    )
    foreach ($RelativePath in $RequiredCppRuntime) {
        if (-not (Test-Path -LiteralPath (Join-Path $PackageRoot $RelativePath))) {
            throw "Required C++ Arduino CLI runtime file is missing: $RelativePath"
        }
    }
    foreach ($RelativePath in @(
        'cores/STC/WCharacter.h',
        'cores/STC/binary.h',
        'cores/STC/WProgram.h'
    )) {
        if (-not (Test-Path -LiteralPath (Join-Path $PackageRoot $RelativePath))) {
            throw "Required Arduino compatibility header is missing: $RelativePath"
        }
    }
    $RemovedCoreFiles = @(
        'cores/STC/String.h',
        'cores/STC/stcxx_string_backend.c'
    )
    foreach ($RelativePath in $RemovedCoreFiles) {
        if (Test-Path -LiteralPath (Join-Path $PackageRoot $RelativePath)) {
            throw "Removed core file entered package staging: $RelativePath"
        }
    }
    # Keep repository maintenance resources out of the installed platform.
    foreach ($SourceOnlyPath in @(
        'scripts', 'tests', '.github', 'tools/toolchain-patches',
        'tools/clang-stc-target', 'tools/llvm-cbe-stc',
        'tools/variants/generate.mjs', 'tools/toolchain-manifest.json'
    )) {
        if (Test-Path -LiteralPath (Join-Path $PackageRoot $SourceOnlyPath)) {
            throw "Source-only resource entered package staging: $SourceOnlyPath"
        }
    }
    $ForbiddenCppRuntime = @(
        Get-ChildItem -LiteralPath $PackageRoot -Recurse -Force |
            Where-Object {
                $_.Name -eq '__pycache__' -or
                $_.Name -like '*.pyc' -or
                $_.Name -like '.build-*' -or
                $_.Name -eq '.adapter-regression.json'
            }
    )
    if ($ForbiddenCppRuntime.Count -ne 0) {
        $Names = ($ForbiddenCppRuntime | ForEach-Object FullName) -join ', '
        throw "Forbidden local C++ pipeline artifact entered package staging: $Names"
    }

    # Stable timestamps make repeated packaging byte-for-byte reproducible.
    $Timestamp = [datetime]::SpecifyKind([datetime]'2026-08-31T00:00:00', [DateTimeKind]::Utc)
    Get-ChildItem -LiteralPath $PackageRoot -Recurse -Force | ForEach-Object { $_.LastWriteTimeUtc = $Timestamp }
    (Get-Item -LiteralPath $PackageRoot).LastWriteTimeUtc = $Timestamp

    # Feed bsdtar a stable, explicit entry order and normalize every header.
    # This avoids checkout-user and filesystem enumeration differences between
    # local Windows and GitHub's Windows runners.
    $ArchiveList = Join-Path $Stage 'archive-files.txt'
    [string[]]$ArchiveEntries = @($RootName) + @(
        Get-ChildItem -LiteralPath $PackageRoot -Recurse -Force |
            ForEach-Object { $_.FullName.Substring($Stage.Length + 1).Replace('\', '/') }
    )
    [Array]::Sort($ArchiveEntries, [StringComparer]::Ordinal)
    [IO.File]::WriteAllLines($ArchiveList, $ArchiveEntries, [Text.UTF8Encoding]::new($false))

    if (Test-Path -LiteralPath $Archive) { Remove-Item -LiteralPath $Archive -Force }
    tar --format ustar --uid 0 --gid 0 --uname root --gname root `
        --mtime '2026-08-31 00:00:00Z' --no-recursion `
        -cjf $Archive -C $Stage -T $ArchiveList
    if ($LASTEXITCODE -ne 0) { throw 'tar failed to create the platform archive.' }

    $ArchiveContents = @(tar -tjf $Archive)
    if ($LASTEXITCODE -ne 0) { throw 'tar failed to inspect the platform archive.' }
    foreach ($RequiredArchiveEntry in @(
        "$RootName/README.md",
        "$RootName/RELEASE_NOTES.md"
    )) {
        if ($ArchiveContents -cnotcontains $RequiredArchiveEntry) {
            throw "Required platform root metadata is missing from archive: $RequiredArchiveEntry"
        }
    }
    $ForbiddenArchiveEntries = @($ArchiveContents | Where-Object {
        $_ -match '(^|/)(__pycache__|\.build-[^/]*)(/|$)' -or
        $_ -match '(^|/)(scripts|tests|\.github)(/|$)' -or
        $_ -match '/tools/(toolchain-patches|clang-stc-target|llvm-cbe-stc)(/|$)' -or
        $_ -match '/tools/(variants/generate\.mjs|toolchain-manifest\.json)$' -or
        $_ -match '(^|/)\.adapter-regression\.json$' -or
        $_ -match '\.pyc$' -or
        $_ -match '/cores/STC/(String\.h|stcxx_string_backend\.c)$'
    })
    if ($ForbiddenArchiveEntries.Count -ne 0) {
        throw "Forbidden local artifact entered package archive: $($ForbiddenArchiveEntries -join ', ')"
    }

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

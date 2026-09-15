[CmdletBinding()]
param(
    [Parameter(Mandatory=$true)][string]$CompilerLockSha256,
    [Parameter(Mandatory=$true)][string]$BackupDirectory,
    # Use only after publishing and verifying a complete, freshly built out tree.
    [switch]$PublishedOutAlreadyPrepared
)
$ErrorActionPreference = 'Stop'
$sdkRoot = Split-Path -Parent $PSScriptRoot
$compilerRoot = Join-Path (Split-Path -Parent $sdkRoot) 'stcxx'
function Hash([string]$Path) { (Get-FileHash -LiteralPath $Path -Algorithm SHA256).Hash.ToLowerInvariant() }
function Test-PublishedManifest([string]$Root, [string]$Text, [string]$LockHash) {
    $resolvedRoot = [IO.Path]::GetFullPath($Root).TrimEnd('\') + '\'
    $entries = @{}
    foreach ($line in ($Text -split "`n")) {
        if ($line -eq '') { continue }
        if ($line.TrimEnd("`r") -cnotmatch '^([0-9a-f]{64})  (.+)$') { throw 'Malformed published manifest line' }
        $expected = $Matches[1]
        $relative = $Matches[2]
        if ($relative -cnotmatch '^(bin/|libexec/|share/|toolchain-lock\.json$)' -or
            $relative -match '(^|/)\.\.?(/|$)|[\\:]' -or $relative.Contains('//')) { throw "Unsafe manifest path: $relative" }
        $absolute = [IO.Path]::GetFullPath((Join-Path $Root $relative))
        if (-not $absolute.StartsWith($resolvedRoot, [StringComparison]::OrdinalIgnoreCase)) { throw "Manifest path escapes publication: $relative" }
        if ($entries.ContainsKey($relative)) { throw "Duplicate manifest path: $relative" }
        if ((Hash $absolute) -ne $expected) { throw "Published manifest digest mismatch: $relative" }
        $entries[$relative] = $expected
    }
    if ($entries['toolchain-lock.json'] -ne $LockHash) { throw 'Published manifest lock binding mismatch' }
    # Auxiliary self-test output outside the publication inventory is not an
    # executable input. Within bin/libexec/share, every file must be bound.
    foreach ($directory in @('bin', 'libexec', 'share')) {
        foreach ($file in Get-ChildItem -LiteralPath (Join-Path $Root $directory) -Recurse -File) {
            $relative = $file.FullName.Substring($resolvedRoot.Length).Replace('\', '/')
            if (-not $entries.ContainsKey($relative)) { throw "Unbound published input: $relative" }
        }
    }
}
function Add-HashReplacement([hashtable]$Table, [string]$Old, [string]$New) {
    if ($Old -cnotmatch '^[0-9a-f]{64}$' -or $New -cnotmatch '^[0-9a-f]{64}$') { throw 'Invalid hash replacement' }
    if ($Table.ContainsKey($Old) -and $Table[$Old] -ne $New) { throw "Ambiguous hash replacement: $Old" }
    $Table[$Old] = $New
}
function Update-CliDriverBindings([string]$Content, [string]$DriverHash, [int]$ExpectedCount) {
    if ($DriverHash -cnotmatch '^[0-9a-f]{64}$') { throw 'Invalid CLI driver hash' }
    $pattern = '(?<prefix>"(?:path"\s*:\s*"tools/cpp-cli/stcxx-cli\.sh"\s*,\s*"sha256|driver_path"\s*:\s*"tools/cpp-cli/stcxx-cli\.sh"\s*,\s*"driver_sha256)"\s*:\s*")[0-9a-f]{64}(?<suffix>")'
    if ([regex]::Matches($Content, $pattern).Count -ne $ExpectedCount) {
        throw "Expected $ExpectedCount active CLI driver bindings"
    }
    return [regex]::Replace($Content, $pattern, [Text.RegularExpressions.MatchEvaluator]{
        param($match)
        return $match.Groups['prefix'].Value + $DriverHash + $match.Groups['suffix'].Value
    })
}
$sourceLock = Join-Path $compilerRoot 'arduino/toolchain-lock.json'
if ((Hash $sourceLock) -ne $CompilerLockSha256) { throw 'Compiler lock changed' }
$compilerLock = Get-Content -LiteralPath $sourceLock -Raw -Encoding UTF8 | ConvertFrom-Json
$sdkLock = Get-Content -LiteralPath (Join-Path $sdkRoot 'tools/cpp-cli/toolchain-lock.json') -Raw -Encoding UTF8 | ConvertFrom-Json
if ((Hash (Join-Path $sdkRoot 'tools/llvm-cbe-stc/llvm-cbe-83f1bea-stc-sdcc.patch')) -ne $compilerLock.llvm_cbe.patch_sha256) { throw 'CBE patch mirrors disagree' }
if ((Hash (Join-Path $sdkRoot 'tools/toolchain-patches/sdcc-mcs251-arduino-cpp.patch')) -ne $compilerLock.sdcc.patch_sha256) { throw 'SDCC patch mirrors disagree' }
$outRoot = Join-Path $compilerRoot 'out'
$expectedElf = if ($PublishedOutAlreadyPrepared) { $compilerLock.sdcc.reference_elf_sha256 } else { $sdkLock.tools.sdcc.elf_sha256 }
if ((Hash (Join-Path $outRoot 'libexec/sdcc')) -ne $expectedElf) { throw 'SDCC ELF does not match the selected publication mode' }
if ($expectedElf -ne $compilerLock.sdcc.reference_elf_sha256) { throw 'New SDCC ELF requires a complete prepared publication' }
if ((Hash (Join-Path $outRoot 'bin/sdcc')) -ne $compilerLock.sdcc.reference_wrapper_sha256) { throw 'Published wrapper does not match compiler lock' }
$manifestPath = Join-Path $outRoot 'MANIFEST.sha256'
$manifest = [IO.File]::ReadAllText($manifestPath)
$oldPublishedLock = $sdkLock.tools.sdcc.published_out_lock_sha256
$expectedPublishedLock = if ($PublishedOutAlreadyPrepared) { $CompilerLockSha256 } else { $oldPublishedLock }
Test-PublishedManifest $outRoot $manifest $expectedPublishedLock
foreach ($name in @('sdld', 'sdldmcs251')) {
    if ((Hash (Join-Path $outRoot "bin/$name")) -ne $compilerLock.sdcc."reference_${name}_sha256") { throw "Published $name does not match compiler lock" }
}
$paths = @('tools/cpp-cli/toolchain-lock.json', 'cores/STC/cpp/core-manifest.json',
           'cores/STC/cpp/runtime-manifest.json', 'tools/toolchain-patches/README.md')
$driverBindingCounts = @{
    'tools/cpp-cli/toolchain-lock.json' = 1
    'cores/STC/cpp/core-manifest.json' = 2
}
$driverHash = Hash (Join-Path $sdkRoot 'tools/cpp-cli/stcxx-cli.sh')
$nextManifest = if ($PublishedOutAlreadyPrepared) { $manifest } else { $manifest.Replace("$oldPublishedLock  toolchain-lock.json", "$CompilerLockSha256  toolchain-lock.json") }
$hasher = [Security.Cryptography.SHA256]::Create()
try { $nextManifestHash = [BitConverter]::ToString($hasher.ComputeHash([Text.Encoding]::UTF8.GetBytes($nextManifest))).Replace('-', '').ToLowerInvariant() }
finally { $hasher.Dispose() }
$replacements = @{}
$mallocSource = Join-Path $compilerRoot 'device/lib/malloc.c'
$mallocBlob = & git -C $compilerRoot -c core.safecrlf=false hash-object device/lib/malloc.c
if ($LASTEXITCODE -ne 0 -or $mallocBlob -cnotmatch '^[0-9a-f]{40}$') { throw 'Cannot identify malloc ABI source' }
if ($compilerLock.sdcc.patched_source_blobs -and
    $compilerLock.sdcc.patched_source_blobs.'device/lib/malloc.c' -ne $mallocBlob) {
    throw 'Malloc source disagrees with the compiler source lock'
}
Add-HashReplacement $replacements $sdkLock.tools.sdcc.malloc_abi_source_sha256 (Hash $mallocSource)
# The MCS251 allocator ABI also lives in its private header and initializer.
# Verify each source against the compiler lock before refreshing its metadata.
$mallocAbiBlobReplacements = @{}
foreach ($entry in $sdkLock.tools.sdcc.malloc_abi_sources.PSObject.Properties) {
    $abiSource = Join-Path $compilerRoot $entry.Name
    $abiBlob = & git -C $compilerRoot -c core.safecrlf=false hash-object -- $entry.Name
    if ($LASTEXITCODE -ne 0 -or $abiBlob -cnotmatch '^[0-9a-f]{40}$' -or
        $compilerLock.sdcc.patched_source_blobs.($entry.Name) -ne $abiBlob) {
        throw "Allocator ABI source disagrees with compiler lock: $($entry.Name)"
    }
    Add-HashReplacement $replacements $entry.Value.raw_sha256 (Hash $abiSource)
    if ($entry.Value.git_blob -cnotmatch '^[0-9a-f]{40}$') { throw 'Invalid allocator source Git blob' }
    $mallocAbiBlobReplacements[$entry.Value.git_blob] = $abiBlob
}
Add-HashReplacement $replacements $sdkLock.tools.llvm_cbe.patch_sha256 $compilerLock.llvm_cbe.patch_sha256
Add-HashReplacement $replacements $sdkLock.tools.llvm_cbe.sha256 $compilerLock.llvm_cbe.reference_binary_sha256
if ($compilerLock.bridge.regression_sha256) {
    Add-HashReplacement $replacements $sdkLock.tools.sdcc.standalone_bridge_regression_sha256 $compilerLock.bridge.regression_sha256
}
Add-HashReplacement $replacements $sdkLock.tools.sdcc.standalone_bridge_adapter_sha256 $compilerLock.bridge.shared_adapter_sha256
Add-HashReplacement $replacements $sdkLock.tools.sdcc.patch_sha256 $compilerLock.sdcc.patch_sha256
Add-HashReplacement $replacements $sdkLock.tools.sdcc.sha256 $compilerLock.sdcc.reference_wrapper_sha256
Add-HashReplacement $replacements $sdkLock.tools.sdcc.elf_sha256 $compilerLock.sdcc.reference_elf_sha256
Add-HashReplacement $replacements $oldPublishedLock $CompilerLockSha256
Add-HashReplacement $replacements $sdkLock.tools.sdcc.published_out_manifest_sha256 $nextManifestHash
foreach ($name in @('sdar', 'sdas251', 'sdld', 'sdldmcs251', 'sdcpp')) {
    Add-HashReplacement $replacements $sdkLock.tools.$name.sha256 (Hash (Join-Path $outRoot "bin/$name"))
}
foreach ($target in @('mcs251')) {
    $model = 'mcs251-large-stack-auto'
    $runtimeName = 'mcs251.lib'
    $inputs = $sdkLock.targets.$target.sdcc_inputs
    Add-HashReplacement $replacements $inputs.libsdcc_sha256 (Hash (Join-Path $outRoot "share/sdcc/lib/$model/libsdcc.lib"))
    Add-HashReplacement $replacements $inputs.target_runtime_sha256 (Hash (Join-Path $outRoot "share/sdcc/lib/$model/$runtimeName"))
}
foreach ($header in @('stddef', 'stdint')) {
    Add-HashReplacement $replacements $sdkLock.tools.sdcc_inputs."${header}_sha256" (Hash (Join-Path $outRoot "share/sdcc/include/$header.h"))
}
foreach ($helper in $sdkLock.pipeline_helpers.PSObject.Properties) {
    # Historical regression sources are not executable pipeline inputs and
    # may have been removed from a source-only worktree. Preserve their old
    # evidence; never invent new qualification hashes for missing tests.
    if ($helper.Name.EndsWith('_regression') -and
        -not (Test-Path -LiteralPath (Join-Path $sdkRoot $helper.Value.path))) {
        continue
    }
    Add-HashReplacement $replacements $helper.Value.sha256 (Hash (Join-Path $sdkRoot $helper.Value.path))
}
$pending = @{}
foreach ($relative in $paths) {
    $path = Join-Path $sdkRoot $relative
    $content = [IO.File]::ReadAllText($path)
    # Historical qualification belongs to its original binaries. Rebinding
    # those hashes to the new candidate would misrepresent old test evidence.
    $historicalQualification = $null
    if ($relative -eq 'tools/toolchain-patches/README.md') {
        $historicalPattern = '(?ms)^## Historical Linux qualification.*?(?=^## Remaining release gates)'
        $historicalMatches = [regex]::Matches($content, $historicalPattern)
        if ($historicalMatches.Count -ne 1) {
            throw 'Cannot identify exactly one historical qualification block; refusing to rebind its evidence'
        }
        $historicalMatch = $historicalMatches[0]
        $historicalQualification = $historicalMatch.Value
        $content = $content.Remove($historicalMatch.Index, $historicalMatch.Length).Insert(
            $historicalMatch.Index, '<!-- PRESERVED-HISTORICAL-QUALIFICATION -->')
    }
    # One pass prevents A->B and B->C mappings from accidentally turning A into C.
    $content = [regex]::Replace($content, '(?<![0-9a-f])[0-9a-f]{64}(?![0-9a-f])', [Text.RegularExpressions.MatchEvaluator]{
        param($match)
        if ($replacements.ContainsKey($match.Value)) { return $replacements[$match.Value] }
        return $match.Value
    })
    # Each active manifest may still contain an older driver digest than the
    # CLI lock. Update only these path-bound fields, never historical evidence.
    if ($driverBindingCounts.ContainsKey($relative)) {
        $content = Update-CliDriverBindings $content $driverHash $driverBindingCounts[$relative]
    }
    if ($relative -in @('tools/cpp-cli/toolchain-lock.json', 'cores/STC/cpp/core-manifest.json')) {
        # These are active manifests. Earlier entries may predate even the
        # old CLI lock, so replacing only that old digest misses their binding.
        $content = [regex]::Replace($content, '("published_out_lock_sha256"\s*:\s*")[0-9a-f]{64}(")', ('${1}' + $CompilerLockSha256 + '${2}'))
        $content = [regex]::Replace($content, '("published_out_manifest_sha256"\s*:\s*")[0-9a-f]{64}(")', ('${1}' + $nextManifestHash + '${2}'))
    }
    $content = $content.Replace($sdkLock.tools.sdcc.malloc_abi_source_git_blob, $mallocBlob)
    $content = [regex]::Replace($content, '(?<![0-9a-f])[0-9a-f]{40}(?![0-9a-f])', [Text.RegularExpressions.MatchEvaluator]{
        param($match)
        if ($mallocAbiBlobReplacements.ContainsKey($match.Value)) { return $mallocAbiBlobReplacements[$match.Value] }
        return $match.Value
    })
    $content = $content.Replace('D:\\Git\\sdcc-c251-arduino', $compilerRoot.Replace('\','\\'))
    $content = $content.Replace('D:\Git\sdcc-c251-arduino', $compilerRoot)
    $content = $content.Replace('D:\\Git\\stc51\\sdcc-c251-arduino', $compilerRoot.Replace('\','\\'))
    $content = $content.Replace('D:\Git\stc51\sdcc-c251-arduino', $compilerRoot)
    $content = $content.Replace('/mnt/d/Git/sdcc-c251-arduino', '/mnt/d/Git/stc51/stcxx')
    $content = $content.Replace('/mnt/d/Git/stc51/sdcc-c251-arduino', '/mnt/d/Git/stc51/stcxx')
    if ($null -ne $historicalQualification) {
        $content = $content.Replace('<!-- PRESERVED-HISTORICAL-QUALIFICATION -->', $historicalQualification)
    }
    $pending[$relative] = $content
}
if ((Hash $sourceLock) -ne $CompilerLockSha256) { throw 'Compiler inputs changed during synchronization' }
New-Item -ItemType Directory -Path $BackupDirectory -ErrorAction Stop | Out-Null
foreach ($relative in $paths) {
    $target = Join-Path $BackupDirectory $relative
    New-Item -ItemType Directory -Path (Split-Path -Parent $target) -Force | Out-Null
    Copy-Item -LiteralPath (Join-Path $sdkRoot $relative) -Destination $target
}
Copy-Item -LiteralPath (Join-Path $outRoot 'toolchain-lock.json') -Destination (Join-Path $BackupDirectory 'published-toolchain-lock.json')
Copy-Item -LiteralPath $manifestPath -Destination (Join-Path $BackupDirectory 'MANIFEST.sha256')
if (-not $PublishedOutAlreadyPrepared) {
    Copy-Item -LiteralPath $sourceLock -Destination (Join-Path $outRoot 'toolchain-lock.json')
    [IO.File]::WriteAllText($manifestPath, $nextManifest, [Text.UTF8Encoding]::new($false))
}
foreach ($relative in $paths) {
    [IO.File]::WriteAllText((Join-Path $sdkRoot $relative), $pending[$relative], [Text.UTF8Encoding]::new($false))
}
Test-PublishedManifest $outRoot ([IO.File]::ReadAllText($manifestPath)) $CompilerLockSha256
Write-Output "Candidate metadata synchronized; published lock $CompilerLockSha256. This does not confer release qualification or commit source."

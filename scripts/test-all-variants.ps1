[CmdletBinding()]
param(
    [string]$ArduinoCli = 'C:\Program Files\Arduino CLI\arduino-cli.exe',
    [string]$WorkDirectory,
    [string]$ToolCacheDirectory,
    [string[]]$DeviceId,
    [switch]$KeepWorkDirectory
)

$ErrorActionPreference = 'Stop'
$RepoRoot = Split-Path -Parent $PSScriptRoot
$OwnWorkDirectory = -not $WorkDirectory
if ($OwnWorkDirectory) {
    $WorkDirectory = Join-Path ([IO.Path]::GetTempPath()) (
        'arduino-stc51-variant-test-' + [guid]::NewGuid().ToString('N'))
}
$WorkDirectory = [IO.Path]::GetFullPath($WorkDirectory)
if (-not $ToolCacheDirectory) {
    # sdk/downloads is intentionally ignored except for its .gitignore marker.
    $ToolCacheDirectory = Join-Path $RepoRoot 'sdk/downloads/toolchain'
}
$ToolCacheDirectory = [IO.Path]::GetFullPath($ToolCacheDirectory)

function Assert-LastExitCode {
    param([string]$Operation)
    if ($LASTEXITCODE -ne 0) { throw "$Operation failed with exit code $LASTEXITCODE." }
}

function Assert-VerifiedArchive {
    param($System, [string]$Archive)

    if ((Get-Item -LiteralPath $Archive).Length -ne [long]$System.size) {
        throw "Size mismatch for $($System.archiveFileName)."
    }
    $Hash = (Get-FileHash -LiteralPath $Archive -Algorithm SHA256).Hash.ToLowerInvariant()
    if ($Hash -ne $System.sha256) {
        throw "SHA-256 mismatch for $($System.archiveFileName)."
    }
}

function Get-VerifiedArchive {
    param($System, [string]$DestinationDirectory, [string]$CacheDirectory)

    $Archive = Join-Path $DestinationDirectory $System.archiveFileName
    $LocalArchive = Join-Path $RepoRoot "dist/$($System.archiveFileName)"
    if (Test-Path -LiteralPath $LocalArchive) {
        Copy-Item -Force -LiteralPath $LocalArchive -Destination $Archive
    } else {
        $CachedArchive = Join-Path $CacheDirectory $System.archiveFileName
        if (Test-Path -LiteralPath $CachedArchive) {
            try {
                Assert-VerifiedArchive -System $System -Archive $CachedArchive
            } catch {
                Remove-Item -LiteralPath $CachedArchive -Force
            }
        }
        if (-not (Test-Path -LiteralPath $CachedArchive)) {
            $PartialArchive = "$CachedArchive.part"
            if (Test-Path -LiteralPath $PartialArchive) {
                Remove-Item -LiteralPath $PartialArchive -Force
            }
            & curl.exe --fail --location --retry 4 --retry-delay 2 --retry-all-errors `
                --silent --show-error --output $PartialArchive $System.url
            Assert-LastExitCode "Download $($System.archiveFileName)"
            Assert-VerifiedArchive -System $System -Archive $PartialArchive
            Move-Item -Force -LiteralPath $PartialArchive -Destination $CachedArchive
        }
        Copy-Item -Force -LiteralPath $CachedArchive -Destination $Archive
    }
    Assert-VerifiedArchive -System $System -Archive $Archive
    return $Archive
}

Push-Location $RepoRoot
try {
    if (-not (Test-Path -LiteralPath $ArduinoCli -PathType Leaf)) {
        throw "Arduino CLI was not found: $ArduinoCli"
    }
    Write-Host "Variant test work directory: $WorkDirectory"
    Write-Host "Verified tool cache: $ToolCacheDirectory"

    $Package = & (Join-Path $PSScriptRoot 'package-platform.ps1')
    $PlatformArchive = $Package.path
    $Data = Join-Path $WorkDirectory 'data'
    $Platform = Join-Path $Data 'packages/arduino-stc51/hardware/mcs51/0.0.1'
    $Downloads = Join-Path $WorkDirectory 'downloads'
    $Extract = Join-Path $WorkDirectory 'extract'
    New-Item -ItemType Directory -Force `
        -Path $Platform,$Downloads,$Extract,$Data,$ToolCacheDirectory | Out-Null

    $PlatformExtract = Join-Path $Extract 'platform'
    New-Item -ItemType Directory -Force -Path $PlatformExtract | Out-Null
    tar -xjf $PlatformArchive -C $PlatformExtract
    Assert-LastExitCode 'Platform extraction'
    Copy-Item -Recurse -Force (Join-Path $PlatformExtract 'arduino-stc51-0.0.1/*') -Destination $Platform

    $Manifest = Get-Content -Raw -Encoding UTF8 tools/toolchain-manifest.json | ConvertFrom-Json
    foreach ($Tool in $Manifest.tools) {
        $System = @($Tool.systems | Where-Object { $_.host -match 'mingw32$' } | Select-Object -First 1)[0]
        if ($null -eq $System) { throw "No Windows archive is defined for $($Tool.id)." }
        $Target = Join-Path $Data "packages/arduino-stc51/tools/$($Tool.packageName)/$($Tool.version)"
        $ToolSentinel = switch ($Tool.id) {
            'sdcc-mcs251'        { Join-Path $Target 'bin/sdcc.exe' }
            'mcs51-tools'        { Join-Path $Target 'win/busybox.exe' }
            'mcs51-archive-tools' { Join-Path $Target 'bin/sdar.exe' }
            default              { $null }
        }
        if ($ToolSentinel -and (Test-Path -LiteralPath $ToolSentinel -PathType Leaf)) {
            continue
        }
        $Archive = Get-VerifiedArchive -System $System -DestinationDirectory $Downloads `
            -CacheDirectory $ToolCacheDirectory
        $Destination = Join-Path $Extract $Tool.id
        New-Item -ItemType Directory -Force -Path $Destination | Out-Null
        if ($Archive.EndsWith('.zip', [StringComparison]::OrdinalIgnoreCase)) {
            Expand-Archive -Force -LiteralPath $Archive -DestinationPath $Destination
        } else {
            tar -xjf $Archive -C $Destination
            Assert-LastExitCode "$($Tool.id) extraction"
        }

        $Source = Join-Path $Destination $System.archiveRoot
        New-Item -ItemType Directory -Force -Path $Target | Out-Null
        Copy-Item -Recurse -Force (Join-Path $Source '*') -Destination $Target
    }

    $Sketch = Join-Path $WorkDirectory 'user/Smoke'
    New-Item -ItemType Directory -Force -Path $Sketch | Out-Null
    Copy-Item -Force (Join-Path $Platform 'examples/Smoke/Smoke.ino') -Destination $Sketch

    $ConfigPath = Join-Path $WorkDirectory 'arduino-cli.yaml'
    $DataConfig = $Data.Replace('\', '/')
    $DownloadConfig = (Join-Path $WorkDirectory 'arduino-downloads').Replace('\', '/')
    $UserConfig = (Join-Path $WorkDirectory 'user').Replace('\', '/')
    @"
directories:
  data: $DataConfig
  downloads: $DownloadConfig
  user: $UserConfig
"@ | Set-Content -Encoding UTF8 $ConfigPath

    $Results = [Collections.Generic.List[object]]::new()
    $Devices = (Get-Content -Raw -Encoding UTF8 tools/variants/devices.json | ConvertFrom-Json).devices
    if ($DeviceId) {
        $KnownIds = @($Devices | ForEach-Object id)
        foreach ($RequestedId in $DeviceId) {
            if ($RequestedId -notin $KnownIds) {
                throw "Unknown device id: $RequestedId"
            }
        }
        $Devices = @($Devices | Where-Object id -In $DeviceId)
    }
    foreach ($Device in $Devices) {
        $Build = Join-Path $WorkDirectory "build/$($Device.id)"
        $Started = Get-Date
        & $ArduinoCli compile --clean --fqbn "arduino-stc51:mcs51:$($Device.id)" `
            --build-path $Build --config-file $ConfigPath $Sketch
        Assert-LastExitCode "Compile $($Device.model)"
        if (-not (Get-ChildItem -LiteralPath $Build -Filter '*.hex')) {
            throw "Compile $($Device.model) produced no HEX file."
        }
        $Results.Add([pscustomobject]@{
            model = $Device.model
            execution = if ($Device.target -eq 'mcs251') { 'mcs251' } else { 'mcs51' }
            adc = $Device.adc -ne $false
            status = 'PASS'
            seconds = [math]::Round(((Get-Date) - $Started).TotalSeconds, 2)
        })
    }

    if (-not $DeviceId -or ('ai8051u_34k64' -in $DeviceId)) {
        $AiBuild = Join-Path $WorkDirectory 'build/ai8051u-mcs251'
        $Started = Get-Date
        & $ArduinoCli compile --clean `
            --fqbn 'arduino-stc51:mcs51:ai8051u_34k64:execution=mcs251' `
            --build-path $AiBuild --config-file $ConfigPath $Sketch
        Assert-LastExitCode 'Compile AI8051U-34K64 MCS251 mode'
        if (-not (Get-ChildItem -LiteralPath $AiBuild -Filter '*.hex')) {
            throw 'AI8051U-34K64 MCS251 compile produced no HEX file.'
        }
        $Results.Add([pscustomobject]@{
            model = 'AI8051U-34K64'
            execution = 'mcs251'
            adc = $true
            status = 'PASS'
            seconds = [math]::Round(((Get-Date) - $Started).TotalSeconds, 2)
        })
    }

    # The 2 KiB STC12C2052AD cannot carry unrelated ADC and UART smoke paths in
    # one image. Compile a second image so both subsystems remain independently
    # link-verified against the real capacity limit.
    if (-not $DeviceId -or ('stc12c2052ad' -in $DeviceId)) {
        $CompactSerialSketch = Join-Path $Platform 'examples/CompactSerialSmoke'
        $CompactSerialBuild = Join-Path $WorkDirectory 'build/stc12c2052ad-compact-serial'
        $Started = Get-Date
        & $ArduinoCli compile --clean --fqbn 'arduino-stc51:mcs51:stc12c2052ad' `
            --build-path $CompactSerialBuild --config-file $ConfigPath $CompactSerialSketch
        Assert-LastExitCode 'Compile STC12C2052AD compact serial profile'
        if (-not (Get-ChildItem -LiteralPath $CompactSerialBuild -Filter '*.hex')) {
            throw 'STC12C2052AD compact serial compile produced no HEX file.'
        }
        $Results.Add([pscustomobject]@{
            model = 'STC12C2052AD'
            execution = 'mcs51/compact-uart'
            adc = $false
            status = 'PASS'
            seconds = [math]::Round(((Get-Date) - $Started).TotalSeconds, 2)
        })
    }

    $LibraryProbes = @(
        @{ name = 'Wire'; id = 'stc89c52rc'; fqbn = 'arduino-stc51:mcs51:stc89c52rc'; example = 'MasterRegisterRead'; execution = 'mcs51/library' },
        @{ name = 'SPI'; id = 'stc8g1k08a'; fqbn = 'arduino-stc51:mcs51:stc8g1k08a'; example = 'SoftwareLoopback'; execution = 'mcs51/library' },
        @{ name = 'SoftwareSerial'; id = 'stc8h1k08'; fqbn = 'arduino-stc51:mcs51:stc8h1k08'; example = 'PollingEcho'; execution = 'mcs51/library' },
        @{ name = 'LiquidCrystal'; id = 'stc8h8k64u'; fqbn = 'arduino-stc51:mcs51:stc8h8k64u'; example = 'HelloWorld'; execution = 'mcs51/library' },
        @{ name = 'Stepper'; id = 'stc8h8k64u'; fqbn = 'arduino-stc51:mcs51:stc8h8k64u'; example = 'OneRevolution'; execution = 'mcs51/library' },
        @{ name = 'SoftwareSerial'; id = 'stc32g12k128'; fqbn = 'arduino-stc51:mcs51:stc32g12k128'; example = 'PollingEcho'; execution = 'mcs251/library' },
        @{ name = 'SD'; id = 'stc8h8k64u'; fqbn = 'arduino-stc51:mcs51:stc8h8k64u'; example = 'ReadFile'; execution = 'mcs51/library' },
        @{ name = 'SD'; id = 'stc32g12k128'; fqbn = 'arduino-stc51:mcs51:stc32g12k128'; example = 'ReadFile'; execution = 'mcs251/library' }
    )
    foreach ($Probe in $LibraryProbes) {
        if ($DeviceId -and ($Probe.id -notin $DeviceId)) {
            continue
        }
        $LibrarySketch = Join-Path $Platform "libraries/$($Probe.name)/examples/$($Probe.example)"
        $LibraryBuild = Join-Path $WorkDirectory "build/library-$($Probe.name.ToLowerInvariant())-$($Probe.id)"
        $Started = Get-Date
        & $ArduinoCli compile --clean --fqbn $Probe.fqbn `
            --build-path $LibraryBuild --config-file $ConfigPath $LibrarySketch
        Assert-LastExitCode "Compile $($Probe.name) example for $($Probe.id)"
        if (-not (Get-ChildItem -LiteralPath $LibraryBuild -Filter '*.hex')) {
            throw "$($Probe.name) example for $($Probe.id) produced no HEX file."
        }
        $Results.Add([pscustomobject]@{
            model = $Probe.name
            execution = $Probe.execution
            adc = '-'
            status = 'PASS'
            seconds = [math]::Round(((Get-Date) - $Started).TotalSeconds, 2)
        })
    }

    $Results | Format-Table -AutoSize
    Write-Host "Variant compile/link tests: PASS ($($Results.Count) configurations)"
}
finally {
    Pop-Location
    if ($OwnWorkDirectory -and -not $KeepWorkDirectory -and
        (Test-Path -LiteralPath $WorkDirectory)) {
        $Resolved = (Resolve-Path -LiteralPath $WorkDirectory).Path
        $TempPrefix = [IO.Path]::GetFullPath([IO.Path]::GetTempPath())
        if (-not $Resolved.StartsWith($TempPrefix, [StringComparison]::OrdinalIgnoreCase) -or
            (Split-Path -Leaf $Resolved) -notlike 'arduino-stc51-variant-test-*') {
            throw "Refusing to clean unexpected test directory: $Resolved"
        }
        Remove-Item -LiteralPath $Resolved -Recurse -Force
    }
}

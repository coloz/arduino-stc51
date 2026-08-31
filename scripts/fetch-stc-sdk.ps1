[CmdletBinding(DefaultParameterSetName = 'List')]
param(
    [Parameter(Mandatory = $true, ParameterSetName = 'List')]
    [switch] $List,

    [Parameter(Mandatory = $true, ParameterSetName = 'One')]
    [ValidateNotNullOrEmpty()]
    [string] $Asset,

    [Parameter(Mandatory = $true, ParameterSetName = 'All')]
    [switch] $All,

    [Parameter(Mandatory = $true, ParameterSetName = 'One')]
    [Parameter(Mandatory = $true, ParameterSetName = 'All')]
    [ValidateNotNullOrEmpty()]
    [string] $Destination,

    [Parameter(ParameterSetName = 'One')]
    [Parameter(ParameterSetName = 'All')]
    [switch] $Force
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

$repositoryRoot = Split-Path -Parent $PSScriptRoot
$manifestPath = Join-Path $repositoryRoot 'sdk\manifest.json'
$manifest = Get-Content -LiteralPath $manifestPath -Raw -Encoding UTF8 | ConvertFrom-Json
$vendorAssets = @($manifest.vendorAssets)

if ($PSCmdlet.ParameterSetName -eq 'List') {
    $vendorAssets |
        Select-Object id, kind, version, releaseDate, fileName, size, sha256, url |
        Format-Table -AutoSize
    return
}

if ([IO.Path]::IsPathRooted($Destination)) {
    $destinationPath = [IO.Path]::GetFullPath($Destination)
}
else {
    $destinationPath = [IO.Path]::GetFullPath((Join-Path (Get-Location) $Destination))
}

if (-not (Test-Path -LiteralPath $destinationPath)) {
    $null = New-Item -ItemType Directory -Path $destinationPath
}

$destinationItem = Get-Item -LiteralPath $destinationPath
if (-not $destinationItem.PSIsContainer) {
    throw "Destination is not a directory: $destinationPath"
}

if ($PSCmdlet.ParameterSetName -eq 'All') {
    $selectedAssets = $vendorAssets
}
else {
    $selectedAssets = @($vendorAssets | Where-Object { $_.id -eq $Asset })
    if ($selectedAssets.Count -ne 1) {
        $validIds = ($vendorAssets.id | Sort-Object) -join ', '
        throw "Unknown asset '$Asset'. Valid IDs: $validIds"
    }
}

function Test-PinnedFile {
    param(
        [Parameter(Mandatory = $true)]
        [string] $Path,

        [Parameter(Mandatory = $true)]
        [long] $ExpectedSize,

        [Parameter(Mandatory = $true)]
        [string] $ExpectedSha256
    )

    $item = Get-Item -LiteralPath $Path
    if ($item.Length -ne $ExpectedSize) {
        throw "Size mismatch for '$Path': expected $ExpectedSize bytes, got $($item.Length)."
    }

    $actualSha256 = (Get-FileHash -LiteralPath $Path -Algorithm SHA256).Hash.ToLowerInvariant()
    if ($actualSha256 -ne $ExpectedSha256.ToLowerInvariant()) {
        throw "SHA-256 mismatch for '$Path': expected $ExpectedSha256, got $actualSha256."
    }
}

foreach ($entry in $selectedAssets) {
    $targetPath = Join-Path $destinationPath ([string] $entry.fileName)

    if ((Test-Path -LiteralPath $targetPath) -and -not $Force) {
        Test-PinnedFile -Path $targetPath -ExpectedSize ([long] $entry.size) -ExpectedSha256 ([string] $entry.sha256)
        Write-Host "Verified existing file: $targetPath"
        continue
    }

    $partialName = '.{0}.{1}.partial' -f ([string] $entry.fileName), ([Guid]::NewGuid().ToString('N'))
    $partialPath = Join-Path $destinationPath $partialName

    try {
        Write-Host "Downloading $($entry.id) from $($entry.url)"
        Invoke-WebRequest -Uri ([string] $entry.url) -OutFile $partialPath -UseBasicParsing
        Test-PinnedFile -Path $partialPath -ExpectedSize ([long] $entry.size) -ExpectedSha256 ([string] $entry.sha256)
        Move-Item -LiteralPath $partialPath -Destination $targetPath -Force
        Write-Host "Downloaded and verified: $targetPath"
    }
    finally {
        if (Test-Path -LiteralPath $partialPath) {
            Remove-Item -LiteralPath $partialPath -Force
        }
    }
}

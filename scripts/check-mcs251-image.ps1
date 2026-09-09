[CmdletBinding()]
param()

$ErrorActionPreference = 'Stop'
$Verifier = Join-Path $PSScriptRoot 'verify-mcs251-image.ps1'
$FixtureDirectory = Join-Path (Split-Path -Parent $PSScriptRoot) ".tmp/mcs251-image-check-$([Guid]::NewGuid().ToString('N'))"
[void](New-Item -ItemType Directory -Path $FixtureDirectory)

function New-HexRecord {
    param([byte]$Kind, [uint16]$Address, [byte[]]$Data)
    $Bytes = @([int]$Data.Length, ($Address -shr 8), ($Address -band 255), [int]$Kind) + @($Data)
    $Sum = 0
    foreach ($Byte in $Bytes) { $Sum += $Byte }
    $Bytes += ((-$Sum) -band 255)
    return ':' + (($Bytes | ForEach-Object { '{0:X2}' -f [int]$_ }) -join '')
}

function Write-Fixture {
    param([string]$Name, [uint32]$Floor, [string[]]$MapLines)
    $Hex = Join-Path $FixtureDirectory "$Name.hex"
    $Map = Join-Path $FixtureDirectory "$Name.map"
    $Records = @(
        (New-HexRecord 4 0 ([byte[]]@(0, ($Floor -shr 16))))
        (New-HexRecord 0 ($Floor -band 65535) ([byte[]]@(0)))
        (New-HexRecord 4 0 ([byte[]]@(0, 255)))
        (New-HexRecord 0 0 ([byte[]]@(2, 0, 3, 138, ($Floor -shr 16), (($Floor -shr 8) -band 255), ($Floor -band 255), 0, 0)))
        (New-HexRecord 1 0 ([byte[]]@()))
    )
    [IO.File]::WriteAllLines($Hex, [string[]]$Records)
    [IO.File]::WriteAllLines($Map, $MapLines)
    return @{ HexPath = $Hex; MapPath = $Map }
}

function Assert-Image {
    param([string]$Name, [uint32]$Floor, [string[]]$MapLines, [string]$ExpectedError = '')
    $Paths = Write-Fixture $Name $Floor $MapLines
    $ActualError = ''
    try {
        & $Verifier @Paths -Layout segmented_home -FlashFloor $Floor `
            -HomeAddress 0xff0000 -CodeFloor $Floor `
            -MaximumCodeBytes (0x1000000 - $Floor) -Model $Name
    } catch {
        $ActualError = $_.Exception.Message
    }
    if ($ExpectedError) {
        if (-not $ActualError.Contains($ExpectedError)) {
            throw "$Name expected '$ExpectedError'; found '$ActualError'."
        }
    } elseif ($ActualError) {
        throw "$Name unexpectedly failed: $ActualError"
    }
}

foreach ($Floor in @(0xfe0000, 0xfc2800)) {
    $Name = 'valid-' + $Floor.ToString('X6')
    $MapLines = @(
        ('Code Window: 0x{0:X6}:0x1000000' -f $Floor)
        ('Code Window Area: GSINIT0 0x{0:X6} 0x1' -f $Floor)
        'Code Window Area: HOME 0xFF0000 0x7'
        'Code Window Area: CSEG_F_lowercase_function_name_beyond_32_characters 0xFF0007 0x2'
    )
    Assert-Image $Name $Floor $MapLines
    Assert-Image 'overlap' $Floor ($MapLines + 'Code Window Area: duplicate 0xFF0007 0x1') 'overlap'
    Assert-Image 'overflow' $Floor ($MapLines + 'Code Window Area: outside 0xFFFFFF 0x2') 'outside'
    Assert-Image 'missing-ledger' $Floor @('HOME 00FF0000 00000007 = 7. bytes (REL,CON,CODE)') 'ledger header'
    Assert-Image 'wrong-window' $Floor (@('Code Window: 0xFF0000:0x1000000') + $MapLines[1..3]) 'does not match'
    Assert-Image 'missing-area' $Floor $MapLines[0..2] 'absent from'
    Assert-Image 'malformed-area' $Floor ($MapLines + 'Code Window Area: invalid') 'malformed'
    Assert-Image 'trampoline-outside-home' $Floor @(
        $MapLines[0], $MapLines[1], 'Code Window Area: HOME 0xFF0000 0x3',
        'Code Window Area: CSEG_F_trampoline 0xFF0003 0x6'
    ) 'not contained'
}
Write-Host "MCS251 segmented image verifier: PASS (16 checks; fixtures: $FixtureDirectory)"

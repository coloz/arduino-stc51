[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)]
    [string]$HexPath,
    [Parameter(Mandatory = $true)]
    [string]$MapPath,
    [Parameter(Mandatory = $true)]
    [ValidateSet('post_home_contiguous', 'pre_home_contiguous')]
    [string]$Layout,
    [Parameter(Mandatory = $true)]
    [uint32]$FlashFloor,
    [Parameter(Mandatory = $true)]
    [uint32]$HomeAddress,
    [Parameter(Mandatory = $true)]
    [uint32]$CodeFloor,
    [Parameter(Mandatory = $true)]
    [uint32]$MaximumCodeBytes,
    [uint32]$FlashCeiling = 0xffffff,
    [string]$Model = 'MCS251 target'
)

$ErrorActionPreference = 'Stop'

if (-not (Test-Path -LiteralPath $HexPath -PathType Leaf)) {
    throw "Intel HEX file was not found: $HexPath"
}
if (-not (Test-Path -LiteralPath $MapPath -PathType Leaf)) {
    throw "Linker map was not found: $MapPath"
}
if ($FlashCeiling -gt 0xffffff -or $FlashFloor -gt $HomeAddress -or
    $HomeAddress -gt $FlashCeiling -or $MaximumCodeBytes -eq 0) {
    throw 'FlashFloor, HomeAddress and the 24-bit address ceiling are inconsistent.'
}
if ($Layout -eq 'post_home_contiguous') {
    if ($CodeFloor -ne $HomeAddress -or $FlashFloor -ne $HomeAddress) {
        throw 'A post-HOME layout must begin both Flash and code at HOME.'
    }
    if ([uint64]$MaximumCodeBytes -ne
        ([uint64]$FlashCeiling - [uint64]$HomeAddress + [uint64]1)) {
        throw 'The post-HOME code limit must equal the complete HOME-to-FlashCeiling window.'
    }
} else {
    if ($CodeFloor -lt $FlashFloor -or $CodeFloor -ge $HomeAddress) {
        throw 'A pre-HOME layout must start code inside Flash and below HOME.'
    }
    if ([uint64]$MaximumCodeBytes -ne
        ([uint64]$HomeAddress - [uint64]$CodeFloor)) {
        throw 'The pre-HOME code limit must equal the continuous interval below HOME.'
    }
}

function Read-IntelHexImage {
    param([string]$Path)

    $Image = @{}
    [uint32]$BaseAddress = 0
    $EofSeen = $false
    $LineNumber = 0
    foreach ($Line in Get-Content -LiteralPath $Path) {
        ++$LineNumber
        if ([string]::IsNullOrWhiteSpace($Line)) { continue }
        if ($EofSeen) { throw "A record follows EOF at line $LineNumber." }
        if (($Line[0] -ne ':') -or ((($Line.Length - 1) % 2) -ne 0)) {
            throw "Malformed Intel HEX record at line $LineNumber."
        }

        $Record = [Collections.Generic.List[byte]]::new()
        for ($Offset = 1; $Offset -lt $Line.Length; $Offset += 2) {
            try {
                $Record.Add([byte][Convert]::ToInt32($Line.Substring($Offset, 2), 16))
            } catch {
                throw "Malformed Intel HEX byte at line $LineNumber."
            }
        }
        if ($Record.Count -lt 5) {
            throw "Truncated Intel HEX record at line $LineNumber."
        }

        $ByteCount = [int]$Record[0]
        if ($Record.Count -ne ($ByteCount + 5)) {
            throw "Intel HEX byte count mismatch at line $LineNumber."
        }
        $Checksum = 0
        foreach ($Byte in $Record) { $Checksum = ($Checksum + $Byte) -band 0xff }
        if ($Checksum -ne 0) {
            throw "Intel HEX checksum mismatch at line $LineNumber."
        }

        $RecordAddress = ([int]$Record[1] -shl 8) -bor [int]$Record[2]
        $RecordType = [int]$Record[3]
        switch ($RecordType) {
            0 {
                for ($Index = 0; $Index -lt $ByteCount; ++$Index) {
                    [uint32]$AbsoluteAddress = $BaseAddress + $RecordAddress + $Index
                    $Value = [byte]$Record[4 + $Index]
                    if ($Image.ContainsKey($AbsoluteAddress) -and
                        ([byte]$Image[$AbsoluteAddress] -ne $Value)) {
                        throw "Conflicting Intel HEX data at 0x$($AbsoluteAddress.ToString('X6'))."
                    }
                    $Image[$AbsoluteAddress] = $Value
                }
            }
            1 {
                if ($ByteCount -ne 0 -or $RecordAddress -ne 0) {
                    throw "Invalid EOF record at line $LineNumber."
                }
                $EofSeen = $true
            }
            2 {
                if ($ByteCount -ne 2 -or $RecordAddress -ne 0) {
                    throw "Invalid segment-address record at line $LineNumber."
                }
                $BaseAddress = [uint32]((([int]$Record[4] -shl 8) -bor
                    [int]$Record[5]) -shl 4)
            }
            4 {
                if ($ByteCount -ne 2 -or $RecordAddress -ne 0) {
                    throw "Invalid linear-address record at line $LineNumber."
                }
                $BaseAddress = [uint32]((([int]$Record[4] -shl 8) -bor
                    [int]$Record[5]) -shl 16)
            }
            default {
                throw "Unsupported Intel HEX record type $RecordType at line $LineNumber."
            }
        }
    }
    if (-not $EofSeen) { throw 'Intel HEX file has no EOF record.' }
    if ($Image.Count -eq 0) { throw 'Intel HEX image contains no data.' }
    return $Image
}

function Get-ImageByte {
    param($Image, [uint32]$Address, [string]$Description)

    if (-not $Image.ContainsKey($Address)) {
        throw "Missing $Description byte at 0x$($Address.ToString('X6'))."
    }
    return [byte]$Image[$Address]
}

function Get-EjmpTarget {
    param($Image, [uint32]$Address, [string]$Description)

    $Opcode = Get-ImageByte $Image $Address $Description
    if ($Opcode -ne 0x8a) {
        throw "$Description at 0x$($Address.ToString('X6')) must start with MCS251 EJMP opcode 0x8A; found 0x$($Opcode.ToString('X2'))."
    }
    return [uint32]((([uint32](Get-ImageByte $Image ($Address + 1) "$Description target") -shl 16) -bor
        ([uint32](Get-ImageByte $Image ($Address + 2) "$Description target") -shl 8) -bor
        [uint32](Get-ImageByte $Image ($Address + 3) "$Description target")))
}

$Image = Read-IntelHexImage -Path $HexPath
foreach ($Address in $Image.Keys) {
    [uint32]$AbsoluteAddress = $Address
    if ($AbsoluteAddress -lt $FlashFloor -or $AbsoluteAddress -gt $FlashCeiling) {
        throw "Image byte 0x$($AbsoluteAddress.ToString('X6')) is outside $Model program Flash."
    }
}

$CodeAreas = [Collections.Generic.List[object]]::new()
foreach ($Line in Get-Content -LiteralPath $MapPath) {
    if ($Line -match '^([A-Z][A-Z0-9_]*)\s+([0-9A-F]{8})\s+([0-9A-F]{8})\s+=\s+\d+\. bytes \([^)]*CODE\)\s*$') {
        [uint32]$AreaAddress = [Convert]::ToUInt32($Matches[2], 16)
        [uint32]$AreaSize = [Convert]::ToUInt32($Matches[3], 16)
        if ($AreaSize -ne 0) {
            $CodeAreas.Add([pscustomobject]@{
                name = $Matches[1]
                address = $AreaAddress
                size = $AreaSize
            })
        }
    }
}
if ($CodeAreas.Count -eq 0) { throw 'The linker map contains no non-empty CODE areas.' }

$HomeAreas = @($CodeAreas | Where-Object name -eq 'HOME')
$Gsinit0Areas = @($CodeAreas | Where-Object name -eq 'GSINIT0')
if ($HomeAreas.Count -ne 1 -or [uint32]$HomeAreas[0].address -ne $HomeAddress) {
    throw 'The linker map does not place exactly one HOME area at the reset address.'
}
if ($Gsinit0Areas.Count -ne 1) {
    throw 'The linker map does not contain exactly one non-empty GSINIT0 area.'
}

foreach ($Area in $CodeAreas) {
    [uint64]$AreaEnd = [uint64]$Area.address + [uint64]$Area.size
    if ([uint32]$Area.address -lt $FlashFloor -or
        $AreaEnd -gt ([uint64]$FlashCeiling + [uint64]1)) {
        throw "CODE area $($Area.name) is outside $Model program Flash."
    }
    if ($Layout -eq 'pre_home_contiguous' -and $Area.name -ne 'HOME' -and
        ([uint32]$Area.address -lt $CodeFloor -or $AreaEnd -gt $HomeAddress)) {
        throw "CODE area $($Area.name) escapes the continuous pre-HOME link interval."
    }
    if ($Layout -eq 'post_home_contiguous' -and
        [uint32]$Area.address -lt $HomeAddress) {
        throw "CODE area $($Area.name) falls below the post-HOME link interval."
    }
}

if ((Get-ImageByte $Image $HomeAddress 'reset vector') -ne 0x02) {
    throw "$Model reset vector must start with the MCS251 HOME LJMP opcode 0x02."
}
[uint32]$ResetTrampoline = ($HomeAddress -band 0xff0000) -bor
    ([uint32](Get-ImageByte $Image ($HomeAddress + 1) 'reset vector target') -shl 8) -bor
    [uint32](Get-ImageByte $Image ($HomeAddress + 2) 'reset vector target')
if ($ResetTrampoline -lt $HomeAddress -or $ResetTrampoline -gt ($FlashCeiling - [uint32]3)) {
    throw "Reset LJMP target 0x$($ResetTrampoline.ToString('X6')) is outside the HOME window."
}
[uint32]$StartupTarget = Get-EjmpTarget $Image $ResetTrampoline 'reset trampoline'
[uint32]$MappedGsinit0 = $Gsinit0Areas[0].address
if ($StartupTarget -ne $MappedGsinit0) {
    throw "Reset trampoline targets 0x$($StartupTarget.ToString('X6')); map GSINIT0 is 0x$($MappedGsinit0.ToString('X6'))."
}
if ($Layout -eq 'pre_home_contiguous' -and $StartupTarget -ne $CodeFloor) {
    throw "Pre-HOME reset trampoline does not target CodeFloor/GSINIT0."
}
if ($Layout -eq 'post_home_contiguous' -and $StartupTarget -lt $HomeAddress) {
    throw 'Post-HOME reset trampoline targets below HOME.'
}
[void](Get-ImageByte $Image $StartupTarget 'GSINIT0')

Write-Host "$Model MCS251 image: PASS ($Layout, Flash 0x$($FlashFloor.ToString('X6'))-0x$($FlashCeiling.ToString('X6')), HOME 0x$($HomeAddress.ToString('X6')), GSINIT0 0x$($StartupTarget.ToString('X6')))"

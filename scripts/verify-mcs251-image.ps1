[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)]
    [string]$HexPath,
    [Parameter(Mandatory = $true)]
    [string]$MapPath,
    [Parameter(Mandatory = $true)]
    [ValidateSet('post_home_contiguous', 'pre_home_contiguous', 'segmented_home')]
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
} elseif ($Layout -eq 'pre_home_contiguous') {
    if ($CodeFloor -lt $FlashFloor -or $CodeFloor -ge $HomeAddress) {
        throw 'A pre-HOME layout must start code inside Flash and below HOME.'
    }
    if ([uint64]$MaximumCodeBytes -ne
        ([uint64]$HomeAddress - [uint64]$CodeFloor)) {
        throw 'The pre-HOME code limit must equal the continuous interval below HOME.'
    }
} else {
    if ($CodeFloor -ne $FlashFloor -or $CodeFloor -ge $HomeAddress) {
        throw 'A segmented-HOME layout must start code at the Flash floor below HOME.'
    }
    if ([uint64]$MaximumCodeBytes -ne
        ([uint64]$FlashCeiling - [uint64]$FlashFloor + [uint64]1)) {
        throw 'The segmented-HOME code limit must equal the complete physical Flash window.'
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
$AreaDefinitions = @{}
$MapLines = @(Get-Content -LiteralPath $MapPath)
if ($Layout -eq 'segmented_home') {
    $WindowHeaders = @($MapLines | Where-Object { $_ -match '^Code Window:' })
    if ($WindowHeaders.Count -ne 1 -or
        $WindowHeaders[0] -notmatch '^Code Window: 0x([0-9A-Fa-f]+):0x([0-9A-Fa-f]+)$') {
        throw 'The segmented-HOME map must contain exactly one valid Code Window ledger header.'
    }
    if ([Convert]::ToUInt64($Matches[1], 16) -ne [uint64]$FlashFloor -or
        [Convert]::ToUInt64($Matches[2], 16) -ne [uint64]$FlashCeiling + [uint64]1) {
        throw 'The linked Code Window does not match the configured physical Flash interval.'
    }
}
foreach ($Line in $MapLines) {
    $AreaRecord = if ($Layout -eq 'segmented_home') {
        # This ledger preserves full area names and real ABS fragment addresses,
        # unlike the paginated, fixed-width historical area summary.
        $Line -match '^Code Window Area: (\S+) 0x([0-9A-Fa-f]+) 0x([0-9A-Fa-f]+)$'
    } else {
        $Line -match '^([A-Za-z_][A-Za-z0-9_]*)\s+([0-9A-Fa-f]{8})\s+([0-9A-Fa-f]{8})\s+=\s+\d+\. bytes \([^)]*CODE\)\s*$'
    }
    if ($AreaRecord) {
        $AreaName = $Matches[1]
        [uint32]$AreaAddress = [Convert]::ToUInt32($Matches[2], 16)
        [uint32]$AreaSize = [Convert]::ToUInt32($Matches[3], 16)
        if ($AreaSize -ne 0) {
            # ASlink can repeat an area's heading on a new map page. The
            # segmented ledger has one record per allocation; repeated names
            # may describe separate absolute fragments and are checked below.
            if ($Layout -ne 'segmented_home' -and $AreaDefinitions.ContainsKey($AreaName)) {
                $PreviousArea = $AreaDefinitions[$AreaName]
                if ($PreviousArea.address -ne $AreaAddress -or $PreviousArea.size -ne $AreaSize) {
                    throw "The map contains inconsistent definitions for CODE area $AreaName."
                }
                continue
            }
            $MappedArea = [pscustomobject]@{
                name = $AreaName
                address = $AreaAddress
                size = $AreaSize
            }
            $AreaDefinitions[$AreaName] = $MappedArea
            $CodeAreas.Add($MappedArea)
        }
    } elseif ($Layout -eq 'segmented_home' -and $Line.StartsWith('Code Window Area:')) {
        throw 'The map contains a malformed Code Window Area ledger record.'
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

[uint64]$MappedCodeBytes = 0
[uint64]$PreviousAreaEnd = $FlashFloor
$PreviousAreaName = ''
$SortedCodeAreas = @($CodeAreas | Sort-Object address, name)
foreach ($Area in $SortedCodeAreas) {
    [uint64]$AreaEnd = [uint64]$Area.address + [uint64]$Area.size
    if ([uint32]$Area.address -lt $FlashFloor -or
        $AreaEnd -gt ([uint64]$FlashCeiling + [uint64]1)) {
        throw "CODE area $($Area.name) is outside $Model program Flash."
    }
    if ([uint64]$Area.address -lt $PreviousAreaEnd) {
        throw "CODE areas $PreviousAreaName and $($Area.name) overlap."
    }
    $PreviousAreaEnd = $AreaEnd
    $PreviousAreaName = $Area.name
    $MappedCodeBytes += [uint64]$Area.size
    if ($Layout -eq 'pre_home_contiguous' -and $Area.name -ne 'HOME' -and
        ([uint32]$Area.address -lt $CodeFloor -or $AreaEnd -gt $HomeAddress)) {
        throw "CODE area $($Area.name) escapes the continuous pre-HOME link interval."
    }
    if ($Layout -eq 'post_home_contiguous' -and
        [uint32]$Area.address -lt $HomeAddress) {
        throw "CODE area $($Area.name) falls below the post-HOME link interval."
    }
}
if ($MappedCodeBytes -gt [uint64]$MaximumCodeBytes -or
    [uint64]$Image.Count -gt [uint64]$MaximumCodeBytes) {
    throw 'The mapped CODE or Intel HEX byte total exceeds the configured program capacity.'
}
if ($Layout -eq 'segmented_home') {
    # Reserved .ds bytes need not be emitted, but every emitted byte must
    # belong to the allocator ledger. Missing records must not pass silently.
    $AreaIndex = 0
    foreach ($Address in ($Image.Keys | Sort-Object)) {
        while ($AreaIndex -lt $SortedCodeAreas.Count -and
            [uint64]$Address -ge ([uint64]$SortedCodeAreas[$AreaIndex].address +
                                [uint64]$SortedCodeAreas[$AreaIndex].size)) {
            $AreaIndex++
        }
        if ($AreaIndex -ge $SortedCodeAreas.Count -or
            [uint64]$Address -lt [uint64]$SortedCodeAreas[$AreaIndex].address) {
            throw "Image byte 0x$(([uint32]$Address).ToString('X6')) is absent from the Code Window ledger."
        }
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
if ([uint64]$ResetTrampoline + [uint64]4 -gt
    [uint64]$HomeAreas[0].address + [uint64]$HomeAreas[0].size) {
    throw 'The reset trampoline is not contained in the mapped HOME area.'
}
[uint32]$StartupTarget = Get-EjmpTarget $Image $ResetTrampoline 'reset trampoline'
[uint32]$MappedGsinit0 = $Gsinit0Areas[0].address
if ($StartupTarget -ne $MappedGsinit0) {
    throw "Reset trampoline targets 0x$($StartupTarget.ToString('X6')); map GSINIT0 is 0x$($MappedGsinit0.ToString('X6'))."
}
if ($Layout -in @('pre_home_contiguous', 'segmented_home') -and $StartupTarget -ne $CodeFloor) {
    throw "Pre-HOME startup does not target CodeFloor/GSINIT0."
}
if ($Layout -eq 'post_home_contiguous' -and $StartupTarget -lt $HomeAddress) {
    throw 'Post-HOME reset trampoline targets below HOME.'
}
[void](Get-ImageByte $Image $StartupTarget 'GSINIT0')

Write-Host "$Model MCS251 image: PASS ($Layout, Flash 0x$($FlashFloor.ToString('X6'))-0x$($FlashCeiling.ToString('X6')), HOME 0x$($HomeAddress.ToString('X6')), GSINIT0 0x$($StartupTarget.ToString('X6')))"

[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)]
    [string]$HexPath,
    [uint32]$HomeAddress = 0xff0000,
    [uint32]$CodeFloor = 0xfc2800
)

$ErrorActionPreference = 'Stop'

if ($CodeFloor -ge $HomeAddress) {
    throw 'CodeFloor must be below the K246 HOME/vector address.'
}
if (-not (Test-Path -LiteralPath $HexPath -PathType Leaf)) {
    throw "Intel HEX file was not found: $HexPath"
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
                if ($EofSeen) { throw "Data follows EOF at line $LineNumber." }
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
                if ($ByteCount -ne 0) { throw "Invalid EOF record at line $LineNumber." }
                $EofSeen = $true
            }
            2 {
                if ($ByteCount -ne 2) { throw "Invalid segment-address record at line $LineNumber." }
                $BaseAddress = [uint32]((([int]$Record[4] -shl 8) -bor
                    [int]$Record[5]) -shl 4)
            }
            4 {
                if ($ByteCount -ne 2) { throw "Invalid linear-address record at line $LineNumber." }
                $BaseAddress = [uint32]((([int]$Record[4] -shl 8) -bor
                    [int]$Record[5]) -shl 16)
            }
        }
    }
    if (-not $EofSeen) { throw 'Intel HEX file has no EOF record.' }
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
    if (($Address -lt $CodeFloor) -or ($Address -gt 0xffffff)) {
        throw "Image byte 0x$($Address.ToString('X6')) is outside physical K246 user Flash."
    }
}

if ((Get-ImageByte $Image $CodeFloor 'GSINIT0') -eq $null) {
    throw 'GSINIT0 is absent.'
}
if ((Get-ImageByte $Image $HomeAddress 'reset vector') -ne 0x02) {
    throw 'K246 reset vector must start with the MCS251 HOME LJMP trampoline.'
}
[uint32]$ResetTrampoline = $HomeAddress + 0x27
if (((Get-ImageByte $Image ($HomeAddress + 1) 'reset vector target') -ne 0x00) -or
    ((Get-ImageByte $Image ($HomeAddress + 2) 'reset vector target') -ne 0x27)) {
    throw "K246 reset LJMP must target the trampoline at 0x$($ResetTrampoline.ToString('X6'))."
}

foreach ($Vector in @(
    @{ name = 'INT0'; offset = 0x03 },
    @{ name = 'Timer0'; offset = 0x0b },
    @{ name = 'INT1'; offset = 0x13 },
    @{ name = 'UART1'; offset = 0x23 }
)) {
    [uint32]$VectorAddress = $HomeAddress + $Vector.offset
    [uint32]$Target = Get-EjmpTarget $Image $VectorAddress "$($Vector.name) vector"
    if (($Target -lt $CodeFloor) -or ($Target -gt 0xffffff)) {
        throw "$($Vector.name) EJMP target 0x$($Target.ToString('X6')) is outside physical K246 user Flash."
    }
    [void](Get-ImageByte $Image $Target "$($Vector.name) handler")
}

[uint32]$Timer1Address = $HomeAddress + 0x1b
if ((Get-ImageByte $Image $Timer1Address 'unclaimed Timer1 vector') -ne 0x32) {
    throw 'The unclaimed K246 Timer1 vector must remain RETI opcode 0x32.'
}

[uint32]$ResetTarget = Get-EjmpTarget $Image $ResetTrampoline 'reset trampoline'
if ($ResetTarget -ne $CodeFloor) {
    throw "K246 reset trampoline targets 0x$($ResetTarget.ToString('X6')); expected GSINIT0 at 0x$($CodeFloor.ToString('X6'))."
}

Write-Host 'STC32G144K246 image: PASS (reset/GSINIT0, INT0, Timer0, INT1, UART1; Timer1 RETI)'

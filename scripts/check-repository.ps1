[CmdletBinding()]
param()

$ErrorActionPreference = 'Stop'
$RepoRoot = Split-Path -Parent $PSScriptRoot

function Assert-True {
    param([bool]$Condition, [string]$Message)
    if (-not $Condition) { throw $Message }
}

Push-Location $RepoRoot
try {
    & node tools/variants/generate.mjs --check
    Assert-True ($LASTEXITCODE -eq 0) 'Generated board/variant files are stale.'

    $Database = Get-Content -Raw -Encoding UTF8 tools/variants/devices.json | ConvertFrom-Json
    $Boards = Get-Content -Raw -Encoding UTF8 boards.txt
    $Platform = Get-Content -Raw -Encoding UTF8 platform.txt
    $SdkManifest = Get-Content -Raw -Encoding UTF8 sdk/manifest.json | ConvertFrom-Json
    $ToolManifest = Get-Content -Raw -Encoding UTF8 tools/toolchain-manifest.json | ConvertFrom-Json

    $DeviceCount = @($Database.devices).Count
    Assert-True ($Database.schema_version -eq 2) 'Expected device database schema 2 with ADC routes.'
    Assert-True ($DeviceCount -ge 25) 'Expected at least the researched 25 target devices.'
    Assert-True (($Database.devices | Where-Object selection -eq 'popular').Count -eq 10) 'Expected 10 popular devices.'
    Assert-True (($Database.devices | Where-Object selection -eq 'rising').Count -eq 3) 'Expected 3 rising devices.'
    Assert-True (($Database.devices | Where-Object selection -eq 'additional_common').Count -ge 12) 'Expected at least 12 additional common devices.'
    Assert-True (($Database.devices | Where-Object adc -ne $false).Count -eq 20) 'Expected 20 ADC-capable devices.'
    Assert-True ($SdkManifest.vendorAssets.Count -eq 7) 'Expected seven pinned STC vendor assets.'
    Assert-True ($ToolManifest.tools.Count -eq 3) 'Expected three pinned build tools.'
    Assert-True ($Platform -match '(?m)^name=arduino-stc51$') 'platform.txt name must be arduino-stc51.'
    Assert-True ($Platform -match '(?m)^version=0\.0\.1$') 'platform.txt version must be 0.0.1.'
    Assert-True ($Platform -notmatch 'cnpmjs|asfaf|msc51') 'A removed proxy or legacy platform typo returned.'
    Assert-True ($Platform -notmatch '(?m)^runtime\.tools\.[^=]+\.path=') 'platform.txt must not override Board Manager runtime tool paths.'
    Assert-True ($Platform -match '(?m)^compiler\.dep\.flags=-MMD$') 'Compiler dependency flags must be isolated from preprocessor recipes.'
    Assert-True ($Platform -match '(?m)^compiler\.ar\.path=\{runtime\.tools\.sdcc-mcs251\.path\}/bin$') 'macOS/default archiver must come from the primary toolchain.'
    Assert-True ($Platform -match '(?m)^compiler\.ar\.path\.windows=\{runtime\.tools\.MCS51ArchiveTools\.path\}/bin$') 'Windows archive helper override is missing.'
    Assert-True ($Platform -match '(?m)^compiler\.shell\.cmd\.macosx=/bin/sh$') 'Explicit macOS shell override is missing.'
    Assert-True ($Platform -match '\{build\.timer_flags\}') 'Compiler recipes do not propagate per-board timer-cycle flags.'
    Assert-True ($Boards -match '(?m)^menu\.machine=STC89 machine cycle') 'STC89 6T/12T board menu is missing.'
    foreach ($CoreFile in @(
        'Arduino.h', 'HardwareSerial.c', 'HardwareSerial_print.c',
        'HardwareSerial_object.c', 'WInterrupts.c', 'WMath.c',
        'wiring.c', 'wiring_microseconds.c', 'wiring_digital.c',
        'wiring_analog.c', 'wiring_analog_write.c', 'wiring_shift.c',
        'wiring_pulse.c'
    )) {
        Assert-True (Test-Path -LiteralPath (Join-Path $RepoRoot "cores/STC/$CoreFile")) "Missing unified-core API file: $CoreFile."
    }
    $CoreSfr = Get-Content -Raw -Encoding UTF8 (Join-Path $RepoRoot 'cores/STC/stc_sfr.h')
    Assert-True ($CoreSfr -match 'STC_CORE_FAMILY_89[\s\S]*STC_SFR\(P4, 0xe8\)') 'Unified STC89 P4 must use the official 0xE8 address.'
    Assert-True ($CoreSfr -match 'STC_CORE_ADC_LAYOUT == STC_ADC_LAYOUT_STC12C2052AD_C5_8BIT[\s\S]*STC_SFR\(ADC_CONTR, 0xc5\)[\s\S]*STC_SFR\(ADC_DATA,\s+0xc6\)') 'STC12C2052AD ADC SFR layout is missing or unguarded.'
    Assert-True ($CoreSfr -match '# else[\s\S]*STC_SFR\(ADC_CONTR, 0xbc\)[\s\S]*STC_SFR\(ADC_RES,\s+0xbd\)[\s\S]*STC_SFR\(ADC_RESL,\s+0xbe\)') 'BC/BD/BE ADC SFR layout is missing.'
    Assert-True ($CoreSfr -match 'STC_CORE_ADC_USES_P1ASF[\s\S]*STC_SFR\(P1ASF, 0x9d\)') 'Legacy ADC P1ASF declaration must be capability-gated.'
    Assert-True ($CoreSfr -match 'STC_ADC_LAYOUT_MODERN_BC_ADCCFG[\s\S]*STC_SFR\(ADCCFG, 0xde\)') 'Modern ADCCFG declaration is missing.'
    Assert-True ($CoreSfr -match 'STC_CORE_PINMUX_PSWX1_BIT0_CLEAR[\s\S]*0xfd69u') 'AI8 P_SWX1 extended-SFR declaration is missing.'
    $WiringCore = Get-Content -Raw -Encoding UTF8 (Join-Path $RepoRoot 'cores/STC/wiring.c')
    Assert-True ($WiringCore -match 'saved_p_sw2 = P_SW2[\s\S]*P_SW2 = saved_p_sw2 \| 0x80u[\s\S]*STC_P_SWX1 &= \(uint8_t\)~0x01u[\s\S]*P_SW2 = saved_p_sw2') 'AI8 startup must clear P_SWX1.0 through EAXFR and restore P_SW2.'
    $AnalogCore = Get-Content -Raw -Encoding UTF8 (Join-Path $RepoRoot 'cores/STC/wiring_analog.c')
    Assert-True ($AnalogCore -match 'STC_ADC_TIMEOUT_LOOPS' -and $AnalogCore -match 'timeout != 0u') 'analogRead must use a bounded timeout.'
    Assert-True ($AnalogCore -match 'STC_ADC_LAYOUT_MODERN_BC_ADCCFG[\s\S]*STC_ADC_START_MASK\s+0x40u' -and $AnalogCore -match 'STC_ADC_FLAG_MASK\s+0x20u') 'Modern ADC control bits are wrong.'
    Assert-True ($AnalogCore -match '#else[\s\S]*STC_ADC_START_MASK\s+0x08u[\s\S]*STC_ADC_FLAG_MASK\s+0x10u') 'Legacy ADC control bits are wrong.'
    $DigitalCore = Get-Content -Raw -Encoding UTF8 (Join-Path $RepoRoot 'cores/STC/wiring_digital.c')
    Assert-True ($DigitalCore -match 'STC_CORE_ADC_USES_P1ASF[\s\S]*P1ASF &= \(uint8_t\)~mask') 'pinMode must restore a legacy analog pin to digital operation.'
    Assert-True ($DigitalCore -match 'STC_VARIANT_PHYSICAL_ALIAS[\s\S]*Never leave both port cells driving one package pad') 'pinMode must release the other logical port cell on aliased package pads.'
    $Legacy89Sfr = Get-Content -Raw -Encoding UTF8 (Join-Path $RepoRoot 'cores/STC89/bsp/STC89C5xRC.h')
    Assert-True ($Legacy89Sfr -match '#define SFR_P4 0xe8' -and $Legacy89Sfr -match '#define SFR_XICON 0xc0') 'Legacy STC89 P4/XICON addresses do not match the official SDK.'
    $SerialCore = Get-Content -Raw -Encoding UTF8 (Join-Path $RepoRoot 'cores/STC/HardwareSerial.c')
    Assert-True ($SerialCore -match 'AUXR &= \(uint8_t\)~STC_AUXR_S1_BRT_T2') 'UART1 must explicitly select Timer1 instead of reset-default Timer2.'
    Assert-True ($SerialCore -match 'STC_CORE_HAS_MODERN_UART1_BRT[\s\S]*TMOD &= 0x0fu') 'Modern UART1 must select Timer1 16-bit auto-reload mode.'
    $LibraryChecks = @(
        @{ name = 'Wire'; example = 'MasterRegisterRead' },
        @{ name = 'SPI'; example = 'SoftwareLoopback' },
        @{ name = 'SoftwareSerial'; example = 'PollingEcho' },
        @{ name = 'LiquidCrystal'; example = 'HelloWorld' },
        @{ name = 'Stepper'; example = 'OneRevolution' },
        @{ name = 'SD'; example = 'ReadFile' }
    )
    foreach ($Library in $LibraryChecks) {
        $LibraryRoot = Join-Path $RepoRoot "libraries/$($Library.name)"
        $PropertiesPath = Join-Path $LibraryRoot 'library.properties'
        $HeaderPath = Join-Path $LibraryRoot "src/$($Library.name).h"
        $SourcePath = Join-Path $LibraryRoot "src/$($Library.name).c"
        $ExamplePath = Join-Path $LibraryRoot "examples/$($Library.example)/$($Library.example).ino"

        Assert-True (Test-Path -LiteralPath $PropertiesPath) "Missing $($Library.name) metadata."
        Assert-True (Test-Path -LiteralPath $HeaderPath) "Missing $($Library.name) public header."
        Assert-True (Test-Path -LiteralPath $SourcePath) "Missing $($Library.name) implementation."
        Assert-True (Test-Path -LiteralPath $ExamplePath) "Missing $($Library.name) compile example."

        $LibraryProperties = Get-Content -Raw -Encoding UTF8 $PropertiesPath
        $LibraryHeader = Get-Content -Raw -Encoding UTF8 $HeaderPath
        $LibrarySource = Get-Content -Raw -Encoding UTF8 $SourcePath
        Assert-True ($LibraryProperties -match "(?m)^name=$([regex]::Escape($Library.name))$") "Wrong library name for $($Library.name)."
        Assert-True ($LibraryProperties -match '(?m)^architectures=mcs51$') "$($Library.name) must target the packaged mcs51 architecture."
        Assert-True ($LibraryProperties -match "(?m)^includes=$([regex]::Escape($Library.name)).h$") "Wrong public include for $($Library.name)."
        Assert-True ($LibraryProperties -match '(?m)^license=MIT$') "$($Library.name) must state its clean-room MIT license."
        Assert-True ($LibraryHeader -match '#include <Arduino.h>') "$($Library.name) must use the unified Arduino header."
        Assert-True ($LibrarySource -match 'SPDX-License-Identifier: MIT') "$($Library.name) implementation lacks an SPDX license marker."
    }
    $SdHeader = Get-Content -Raw -Encoding UTF8 (Join-Path $RepoRoot 'libraries/SD/src/SD.h')
    $SdSource = Get-Content -Raw -Encoding UTF8 (Join-Path $RepoRoot 'libraries/SD/src/SD.c')
    Assert-True ($SdHeader -match 'STC_XDATA_BYTES\) \|\| \(STC_XDATA_BYTES < 1024UL\)') 'SD must reject targets with less than 1 KiB XDATA.'
    Assert-True ($SdHeader -match '# define FILE_WRITE 0x17u') 'SD FILE_WRITE must retain the official flag value even though filesystem writes are rejected.'
    Assert-True ($SdHeader -match 'STC_SD_CODE const STCSDClass SD') 'SD dispatch table must be kept in code space.'
    Assert-True ($SdSource -match 'static STC_SD_XDATA uint8_t sd_sector\[SD_SECTOR_SIZE\]') 'SD sector cache must be static XDATA, not stack data.'
    Assert-True ($SdSource -match 'sd_load_le16' -and $SdSource -match 'sd_load_le32') 'SD must decode FAT fields explicitly for the big-endian MCS251 backend.'
    Assert-True ($SdSource -match 'SD_CMD0_GO_IDLE_STATE' -and
                 $SdSource -match 'SD_CMD8_SEND_IF_COND' -and
                 $SdSource -match 'SD_CMD41_SD_SEND_OP_COND' -and
                 $SdSource -match 'SD_CMD58_READ_OCR' -and
                 $SdSource -match 'SD_CMD17_READ_SINGLE_BLOCK' -and
                 $SdSource -match 'SD_CMD24_WRITE_BLOCK') 'SD command coverage regressed.'
    Assert-True ($SdSource -match 'SD_ROOT_SCAN_SECTOR_LIMIT') 'SD must bound corrupt FAT32 root-directory walks.'
    Assert-True ($SdSource -notmatch '\b(malloc|calloc|realloc|free)\s*\(') 'SD must not allocate dynamically on small-memory targets.'
    Assert-True ($SdSource -notmatch '\b(packed|__packed)\b') 'SD must not depend on packed host-endian FAT structures.'
    $LeakedDependencies = @(Get-ChildItem -LiteralPath $RepoRoot -Force -File -Filter '*.d')
    Assert-True ($LeakedDependencies.Count -eq 0) "Compiler leaked dependency files into the repository root: $($LeakedDependencies.Name -join ', ')."
    Assert-True (Test-Path -LiteralPath (Join-Path $RepoRoot '.gitattributes')) 'Missing line-ending policy for POSIX wrappers.'
    $ShellScripts = @(
        Get-ChildItem -LiteralPath (Join-Path $RepoRoot 'tools/wrapper') -Filter '*.sh'
        Get-ChildItem -LiteralPath (Join-Path $RepoRoot 'scripts') -Filter '*.sh'
    )
    foreach ($ShellScript in $ShellScripts) {
        Assert-True (-not ([IO.File]::ReadAllBytes($ShellScript.FullName) -contains 13)) "$($ShellScript.Name) contains CR bytes; POSIX shells require LF."
    }
    $CompileWrapper = Get-Content -Raw -Encoding UTF8 tools/wrapper/stc-compile.sh
    Assert-True ($CompileWrapper -match [regex]::Escape('/dev/null')) 'The compile wrapper must recognize the Unix null device.'
    Assert-True ($CompileWrapper -match [regex]::Escape('$SDCC.exe')) 'The compile wrapper must normalize the Windows sdcc.exe path for xargs.'
    Assert-True ($CompileWrapper -match [regex]::Escape('*.c) DEPENDENCY_NAME=${SOURCE_NAME%.c}.d')) 'C-library discovery must redirect SDCC dependency output instead of leaking nul.d.'
    $SizeWrapperPath = Join-Path $RepoRoot 'tools/wrapper/stc-size.sh'
    Assert-True (Test-Path -LiteralPath $SizeWrapperPath) 'Missing SDCC memory-report wrapper.'
    $SizeWrapper = Get-Content -Raw -Encoding UTF8 $SizeWrapperPath
    Assert-True ($SizeWrapper -match 'tack starts at:' -and $SizeWrapper -match 'STC_PROGRAM_BYTES' -and $SizeWrapper -match 'STC_RAM_BYTES') 'The size wrapper must report flash and aggregate internal/external RAM.'
    Assert-True ($Platform -match '(?m)^recipe\.size\.pattern=.*stc-size\.sh') 'platform.txt does not invoke the size wrapper.'
    Assert-True ($Platform -match '(?m)^recipe\.size\.regex=\^STC_PROGRAM_BYTES') 'Program-size regex does not match the size wrapper.'
    Assert-True ($Platform -match '(?m)^recipe\.size\.regex\.data=\^STC_RAM_BYTES') 'RAM-size regex does not match the size wrapper.'
    $PackageScript = Get-Content -Raw -Encoding UTF8 scripts/package-platform.ps1
    foreach ($PlatformDirectory in @('docs', 'examples', 'libraries', 'LICENSES', 'scripts')) {
        Assert-True ($PackageScript -match "'$( [regex]::Escape($PlatformDirectory) )'" -and $PackageScript -match 'Copy-Item -Recurse') "Packaging does not include the complete $PlatformDirectory directory."
    }
    foreach ($PackagedMetadata in @('tools/variants', 'tools/toolchain-manifest.json', 'sdk/README.md', 'sdk/manifest.json')) {
        Assert-True ($PackageScript -match [regex]::Escape($PackagedMetadata)) "Packaging omits referenced metadata: $PackagedMetadata."
    }
    foreach ($LegacyVariant in @('STC8', 'STC15', 'STC89')) {
        Assert-True (-not (Test-Path -LiteralPath (Join-Path $RepoRoot "variants/$LegacyVariant"))) "Legacy generic variant remains: variants/$LegacyVariant."
    }

    $UsbAsset = $SdkManifest.vendorAssets | Where-Object id -eq 'stc-usb-library'
    Assert-True ($null -ne $UsbAsset) 'The current STC USB reference package is missing.'
    Assert-True ($UsbAsset.version -eq '2026-07-29') 'Unexpected STC USB package version.'
    foreach ($ExpectedAiAsset in @(
        @{ id = 'ai8051u-innovative-32'; version = '2025-05-28' },
        @{ id = 'ai8051u-innovative-8'; version = '2025-05-12' }
    )) {
        $AiAsset = $SdkManifest.vendorAssets | Where-Object id -eq $ExpectedAiAsset.id
        Assert-True ($null -ne $AiAsset) "Missing $($ExpectedAiAsset.id)."
        Assert-True ($AiAsset.version -eq $ExpectedAiAsset.version) "Unexpected version for $($ExpectedAiAsset.id)."
    }
    $AiDevice = $Database.devices | Where-Object id -eq 'ai8051u_34k64'
    Assert-True (@($AiDevice.experimental_targets) -contains 'mcs251') 'AI8051U must identify its optional MCS251 path as experimental.'

    $AdcLayoutIds = @{
        stc12c2052ad_c5_8bit = 1
        legacy_bc_10bit_auxr1 = 2
        legacy_bc_10bit_clkdiv = 3
        modern_bc_adccfg = 4
    }

    foreach ($Device in $Database.devices) {
        $Variant = $Device.model -replace '-', '_'
        Assert-True ($Boards -match "(?m)^$([regex]::Escape($Device.id))\.name=") "Missing board $($Device.id)."
        Assert-True ($Boards -match "(?m)^$([regex]::Escape($Device.id))\.build\.core=STC$") "Board $($Device.id) does not use unified core."
        Assert-True ($Boards -match "(?m)^$([regex]::Escape($Device.id))\.build\.variant=$([regex]::Escape($Variant))$") "Wrong variant for $($Device.id)."

        $VariantDir = Join-Path $RepoRoot "variants/$Variant"
        foreach ($File in @('pins_arduino.h', 'variant.c', 'variant.json')) {
            Assert-True (Test-Path -LiteralPath (Join-Path $VariantDir $File)) "Missing variants/$Variant/$File."
        }
        $Metadata = Get-Content -Raw -Encoding UTF8 (Join-Path $VariantDir 'variant.json') | ConvertFrom-Json
        $VariantHeader = Get-Content -Raw -Encoding UTF8 (Join-Path $VariantDir 'pins_arduino.h')
        Assert-True ($Metadata.model -eq $Device.model) "Variant metadata mismatch for $($Device.model)."
        Assert-True ($Metadata.schema_version -eq 2) "Variant metadata schema mismatch for $($Device.model)."
        Assert-True ($Metadata.memory.maximum_code_bytes -eq $Device.maximum_code_bytes) "Code limit mismatch for $($Device.model)."
        $ExpectedUart = $Device.capabilities.uart1 -ne $false
        $ExpectedBufferedRx = $ExpectedUart -and $Device.maximum_code_bytes -gt 2048
        Assert-True ($Metadata.peripherals.uart1 -eq $ExpectedUart) "UART1 metadata mismatch for $($Device.model)."
        Assert-True ($Metadata.peripherals.uart1_buffered_rx -eq $ExpectedBufferedRx) "UART RX profile mismatch for $($Device.model)."

        $HasAdc = $Device.adc -ne $false
        $ExpectedLayout = if ($HasAdc) { [int]$AdcLayoutIds[$Device.adc.layout] } else { 0 }
        $ExpectedBits = if ($HasAdc) { [int]$Device.adc.resolution_bits } else { 0 }
        $ChannelProperties = if ($HasAdc) {
            @($Device.adc.channels.PSObject.Properties | Sort-Object { [int]$_.Value })
        } else {
            @()
        }
        $ExpectedAnalogCount = $ChannelProperties.Count
        $ExpectedPinmux = [int]($Device.pin_selector -eq 'pswx1_bit0_clear_for_p5_4')
        $ExpectedPhysicalIo = if ($null -ne $Device.physical_io) { [int]$Device.physical_io } else { [int]$Device.max_io }
        $ExpectedAliasGroupCount = if ($null -ne $Device.pin_alias_groups) { @($Device.pin_alias_groups).Count } else { 0 }

        $BoardFlagPrefix = "(?m)^$([regex]::Escape($Device.id))\.build\.core_flags="
        Assert-True (($Boards -match "$BoardFlagPrefix.*-DSTC_CORE_HAS_ADC=$([int]$HasAdc)(?: |$)") -and
                     ($Boards -match "$BoardFlagPrefix.*-DSTC_CORE_ADC_LAYOUT=$ExpectedLayout(?: |$)") -and
                     ($Boards -match "$BoardFlagPrefix.*-DSTC_CORE_PINMUX_PSWX1_BIT0_CLEAR=$ExpectedPinmux(?: |$)") -and
                     ($Boards -match "$BoardFlagPrefix.*-DSTC_CORE_ADC_NATIVE_BITS=$ExpectedBits$") ) "ADC board flags mismatch for $($Device.model)."
        Assert-True ($VariantHeader -match "(?m)^#define STC_NUM_LOGICAL_DIGITAL_PINS $($Device.max_io)U$") "Logical GPIO count mismatch for $($Device.model)."
        Assert-True ($VariantHeader -match "(?m)^#define STC_NUM_BONDED_DIGITAL_PINS $($ExpectedPhysicalIo)U$") "Physical GPIO count mismatch for $($Device.model)."
        Assert-True ($VariantHeader -match "(?m)^#define STC_VARIANT_PIN_ALIAS_GROUP_COUNT $($ExpectedAliasGroupCount)U$") "Physical alias count mismatch for $($Device.model)."
        Assert-True ($VariantHeader -match "(?m)^#define STC_VARIANT_PINMUX_PSWX1_BIT0_CLEAR $($ExpectedPinmux)$") "Variant startup pin selector flag mismatch for $($Device.model)."
        Assert-True ($Metadata.pinout.maximum_logical_io -eq $Device.max_io) "Logical GPIO metadata mismatch for $($Device.model)."
        Assert-True ($Metadata.pinout.maximum_physical_io -eq $ExpectedPhysicalIo) "Physical GPIO metadata mismatch for $($Device.model)."
        Assert-True (@($Metadata.pinout.physical_alias_groups).Count -eq $ExpectedAliasGroupCount) "Physical alias metadata mismatch for $($Device.model)."
        if ($ExpectedPinmux -eq 1) {
            Assert-True ($Metadata.pinout.startup_selector -eq $Device.pin_selector) "Startup pin selector mismatch for $($Device.model)."
        } else {
            Assert-True ($null -eq $Metadata.pinout.startup_selector) "Unexpected startup pin selector for $($Device.model)."
        }
        Assert-True ($VariantHeader -match "(?m)^#define STC_VARIANT_HAS_ADC $([int]$HasAdc)$") "Variant ADC capability mismatch for $($Device.model)."
        Assert-True ($VariantHeader -match "(?m)^#define STC_VARIANT_ADC_LAYOUT $($ExpectedLayout)U$") "Variant ADC layout mismatch for $($Device.model)."
        Assert-True ($VariantHeader -match "(?m)^#define STC_VARIANT_ADC_NATIVE_BITS $($ExpectedBits)U$") "Variant ADC resolution mismatch for $($Device.model)."
        Assert-True ($VariantHeader -match "(?m)^#define NUM_ANALOG_INPUTS $ExpectedAnalogCount$") "Analog input count mismatch for $($Device.model)."
        Assert-True ($Metadata.peripherals.adc.supported -eq $HasAdc) "ADC metadata capability mismatch for $($Device.model)."
        Assert-True (@($Metadata.peripherals.adc.channels).Count -eq $ExpectedAnalogCount) "ADC metadata channel count mismatch for $($Device.model)."

        if ($HasAdc) {
            Assert-True ($Metadata.peripherals.adc.layout -eq $Device.adc.layout) "ADC metadata layout mismatch for $($Device.model)."
            Assert-True ($Metadata.peripherals.adc.native_resolution_bits -eq $ExpectedBits) "ADC metadata resolution mismatch for $($Device.model)."
            Assert-True ($VariantHeader -match '(?m)^#define A0 P[0-7]_[0-7]$') "ADC target lacks A0 for $($Device.model)."
            for ($AnalogIndex = 0; $AnalogIndex -lt $ExpectedAnalogCount; $AnalogIndex++) {
                $Route = $ChannelProperties[$AnalogIndex]
                $Pin = [string]$Route.Name
                $PinMacro = $Pin.Replace('.', '_')
                $Channel = [int]$Route.Value
                $MetadataRoute = @($Metadata.peripherals.adc.channels)[$AnalogIndex]
                Assert-True ($VariantHeader -match "(?m)^#define A$AnalogIndex $([regex]::Escape($PinMacro))$") "A$AnalogIndex pin mismatch for $($Device.model)."
                Assert-True ($VariantHeader -match "\(\(pin\) == \($([regex]::Escape($PinMacro))\)\) \? \($($Channel)U\)") "ADC hardware channel mismatch for $($Device.model) $Pin."
                Assert-True ($MetadataRoute.alias -eq "A$AnalogIndex" -and $MetadataRoute.pin -eq $Pin -and $MetadataRoute.channel -eq $Channel) "ADC route metadata mismatch for $($Device.model) A$AnalogIndex."
            }
        } else {
            Assert-True ($VariantHeader -notmatch '(?m)^#define A0 ') "Non-ADC target exposes A0: $($Device.model)."
            Assert-True ($VariantHeader -match '(?m)^#define analogInputToDigitalPin\(index\) \(NOT_A_PIN\)$') "Non-ADC analog mapping must fail for $($Device.model)."
        }
    }

    $Stc8h8Header = Get-Content -Raw -Encoding UTF8 (Join-Path $RepoRoot 'variants/STC8H8K64U/pins_arduino.h')
    Assert-True ($Stc8h8Header -match '(?m)^#define PIN_VALID_MASK_P1 0xFBU$' -and $Stc8h8Header -match '(?m)^#define PIN_VALID_MASK_P5 0x1FU$' -and $Stc8h8Header -match '(?m)^#define PIN_VALID_MASK_P7 0xFFU$') 'STC8H8K64U P1/P5/P7 masks regressed.'

    $Stc32ClHeader = Get-Content -Raw -Encoding UTF8 (Join-Path $RepoRoot 'variants/STC32CL8K64/pins_arduino.h')
    Assert-True ($Stc32ClHeader -match '(?m)^#define STC_NUM_LOGICAL_DIGITAL_PINS 19U$' -and
                 $Stc32ClHeader -match '(?m)^#define STC_NUM_BONDED_DIGITAL_PINS 17U$' -and
                 $Stc32ClHeader -match 'P1_4[\s\S]*P0_2[\s\S]*P1_5[\s\S]*P0_3') 'STC32CL physical GPIO aliases regressed.'
    $AiHeader = Get-Content -Raw -Encoding UTF8 (Join-Path $RepoRoot 'variants/AI8051U_34K64/pins_arduino.h')
    Assert-True ($AiHeader -match '(?m)^#define PIN_VALID_MASK_P5 0xCFU$' -and
                 $AiHeader -match '(?m)^#define STC_NUM_LOGICAL_DIGITAL_PINS 46U$' -and
                 $AiHeader -match '(?m)^#define STC_NUM_BONDED_DIGITAL_PINS 45U$' -and
                 $AiHeader -match 'P4_4[\s\S]*P4_5') 'AI8051U maximum pin mask or physical alias regressed.'
    Assert-True ($Boards -match '(?m)^ai8h2k12u\.build\.core_flags=.*-DSTC_CORE_PINMUX_PSWX1_BIT0_CLEAR=1' -and
                 $Boards -match '(?m)^ai8h2k32u\.build\.core_flags=.*-DSTC_CORE_PINMUX_PSWX1_BIT0_CLEAR=1') 'Ai8H2K variants must select the P5.4 side of the shared pad.'

    Assert-True ($Boards -match '(?m)^stc15f104w\.build\.core_flags=.*-DSTC_CORE_HAS_UART1=0') 'STC15F104W must not advertise UART1.'
    Assert-True ($Boards -match '(?m)^stc12c2052ad\.build\.core_flags=.*-DSTC_CORE_SERIAL_BUFFERED_RX=0') 'The 2 KiB STC12 target must use compact serial RX.'
    Assert-True ($Boards -match '(?m)^stc89c52rc\.menu\.machine\.6t\.build\.timer_flags=.*STC_TIMER0_CLOCK_DIVIDER=6UL.*STC_SERIAL_TIMER1_CLOCK_DIVIDER=6UL') 'STC89 6T menu does not configure both core timers.'

    if (Test-Path -LiteralPath 'package_arduino-stc51_index.json') {
        $PackageText = Get-Content -Raw -Encoding UTF8 package_arduino-stc51_index.json
        $Package = $PackageText | ConvertFrom-Json
        Assert-True ($Package.packages[0].name -eq 'arduino-stc51') 'Package name must be arduino-stc51.'
        $Latest = $Package.packages[0].platforms | Where-Object version -eq '0.0.1'
        Assert-True ($null -ne $Latest) 'Package index does not contain platform 0.0.1.'
        Assert-True (@($Latest.boards).Count -eq $DeviceCount) "Package index must advertise all $DeviceCount boards."
        $Dependencies = @($Latest.toolsDependencies | ForEach-Object name)
        foreach ($Required in @('sdcc-mcs251', 'MCS51Tools', 'MCS51ArchiveTools')) {
            Assert-True ($Dependencies -contains $Required) "Package index is missing $Required."
        }
        Assert-True ($PackageText -notmatch 'github\.com\.cnpmjs\.org') 'Dead proxy URL remains in package index.'

        foreach ($Tool in $ToolManifest.tools) {
            $IndexedTool = $Package.packages[0].tools | Where-Object { $_.name -eq $Tool.packageName -and $_.version -eq $Tool.version }
            Assert-True ($null -ne $IndexedTool) "Package index is missing $($Tool.packageName) $($Tool.version)."
            foreach ($ManifestSystem in @($Tool.systems)) {
                $IndexedSystem = @($IndexedTool.systems) | Where-Object host -eq $ManifestSystem.host
                Assert-True ($null -ne $IndexedSystem) "Package index is missing $($Tool.packageName) for $($ManifestSystem.host)."
                Assert-True ($IndexedSystem.url -eq $ManifestSystem.url) "URL mismatch for $($Tool.packageName) $($ManifestSystem.host)."
                Assert-True ($IndexedSystem.archiveFileName -eq $ManifestSystem.archiveFileName) "Archive name mismatch for $($Tool.packageName) $($ManifestSystem.host)."
                Assert-True ([long]$IndexedSystem.size -eq [long]$ManifestSystem.size) "Size mismatch for $($Tool.packageName) $($ManifestSystem.host)."
                Assert-True ($IndexedSystem.checksum -eq "SHA-256:$($ManifestSystem.sha256)") "Checksum mismatch for $($Tool.packageName) $($ManifestSystem.host)."

                if ($ManifestSystem.url -match '/arduino-stc51/main/dist/') {
                    $LocalToolArchive = Join-Path $RepoRoot "dist/$($ManifestSystem.archiveFileName)"
                    Assert-True (Test-Path -LiteralPath $LocalToolArchive) "Missing local tool archive dist/$($ManifestSystem.archiveFileName)."
                    Assert-True ((Get-Item -LiteralPath $LocalToolArchive).Length -eq [long]$ManifestSystem.size) "Local tool size mismatch: $($ManifestSystem.archiveFileName)."
                    $LocalToolHash = (Get-FileHash -LiteralPath $LocalToolArchive -Algorithm SHA256).Hash.ToLowerInvariant()
                    Assert-True ($LocalToolHash -eq $ManifestSystem.sha256) "Local tool checksum mismatch: $($ManifestSystem.archiveFileName)."
                }
            }
        }

        $PrimaryCompiler = $Package.packages[0].tools | Where-Object name -eq 'sdcc-mcs251'
        foreach ($MacHost in @('arm64-apple-darwin', 'x86_64-apple-darwin')) {
            Assert-True ($null -ne (@($PrimaryCompiler.systems) | Where-Object host -eq $MacHost)) "Primary compiler lacks $MacHost support."
        }
        foreach ($HelperName in @('MCS51Tools', 'MCS51ArchiveTools')) {
            $Helper = $Package.packages[0].tools | Where-Object name -eq $HelperName
            Assert-True ($null -ne (@($Helper.systems) | Where-Object host -eq 'x86_64-apple-darwin')) "$HelperName lacks Arduino's macOS fallback flavour."
        }

        $PlatformArchive = Join-Path $RepoRoot "dist/$($Latest.archiveFileName)"
        Assert-True (Test-Path -LiteralPath $PlatformArchive) 'Package index platform archive is missing from dist/.'
        $ArchiveItem = Get-Item -LiteralPath $PlatformArchive
        $ArchiveChecksum = 'SHA-256:' + (Get-FileHash -LiteralPath $PlatformArchive -Algorithm SHA256).Hash.ToLowerInvariant()
        Assert-True ([long]$Latest.size -eq $ArchiveItem.Length) 'Package index platform archive size is stale.'
        Assert-True ($Latest.checksum -eq $ArchiveChecksum) 'Package index platform archive checksum is stale.'
    }

    Write-Host "Repository checks: PASS ($DeviceCount devices, multi-host tools, manifests, generated files and platform metadata)"
}
finally {
    Pop-Location
}

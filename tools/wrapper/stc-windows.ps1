# Windows Arduino recipe adapter. Uses only Windows PowerShell and .NET.
# No param block: compiler options are positional recipe arguments.
$ErrorActionPreference = 'Stop'
$RecipeArguments = @($args)
# PowerShell's -File binder splits options such as -ID:\path at the colon.
# Read the original process argv after this script to retain compiler syntax.
$HostArguments = [Environment]::GetCommandLineArgs()
for ($HostIndex = 1; $HostIndex + 1 -lt $HostArguments.Count; ++$HostIndex) {
    if ($HostArguments[$HostIndex] -ieq '-File' -and
        [IO.Path]::GetFullPath($HostArguments[$HostIndex + 1]) -eq $PSCommandPath) {
        $RecipeArguments = @($HostArguments | Select-Object -Skip ($HostIndex + 2))
        break
    }
}

function Invoke-StcProcess {
    param([string]$Executable, [string[]]$Arguments, [string]$Directory = '', [switch]$Capture)
    if (-not [IO.File]::Exists($Executable) -and [IO.File]::Exists($Executable + '.exe')) {
        $Executable += '.exe'
    }
    # ProcessStartInfo on Windows PowerShell requires a command-line string.
    # Quote each argv element using the Windows CRT rules; never evaluate it.
    $Quoted = foreach ($Value in $Arguments) {
        # Leave simple options bare, and quote only values that need quoting.
        if ($Value -eq '' -or $Value -match '[\s"]') {
            '"' + [regex]::Replace([regex]::Replace($Value, '(\\*)"', '$1$1\"'), '(\\+)$', '$1$1') + '"'
        } else { $Value }
    }
    $Info = New-Object Diagnostics.ProcessStartInfo
    $Info.FileName = $Executable
    $Info.Arguments = $Quoted -join ' '
    $Info.UseShellExecute = $false
    $Info.CreateNoWindow = $true
    $Info.RedirectStandardOutput = $true
    $Info.RedirectStandardError = $true
    if ($Directory) { $Info.WorkingDirectory = $Directory }
    if ($Capture) {
        $Info.StandardOutputEncoding = New-Object Text.UTF8Encoding($false)
        $Info.StandardErrorEncoding = New-Object Text.UTF8Encoding($false)
    }
    $Process = New-Object Diagnostics.Process
    $Process.StartInfo = $Info
    try {
        [void]$Process.Start()
        if ($Capture) {
            $OutputTask = $Process.StandardOutput.ReadToEndAsync()
            $ErrorTask = $Process.StandardError.ReadToEndAsync()
        } else {
            # Arduino captures this PowerShell process. Explicitly relay both
            # child pipes; a detached Windows process cannot inherit its console.
            $OutputTask = $Process.StandardOutput.BaseStream.CopyToAsync([Console]::OpenStandardOutput())
            $ErrorTask = $Process.StandardError.BaseStream.CopyToAsync([Console]::OpenStandardError())
        }
        $Process.WaitForExit()
        if ($Capture) {
            return [pscustomobject]@{
                Status = $Process.ExitCode
                Output = $OutputTask.GetAwaiter().GetResult()
                Error = $ErrorTask.GetAwaiter().GetResult()
            }
        }
        [void]$OutputTask.GetAwaiter().GetResult()
        [void]$ErrorTask.GetAwaiter().GetResult()
        return $Process.ExitCode
    } finally { $Process.Dispose() }
}

function Assert-StcTarget {
    param([string[]]$Arguments)
    foreach ($Value in $Arguments) {
        if ($Value -cmatch '^(-mmcs51|-DSTCXX_TARGET_MCS51=1|-DSTC_EXECUTION_MODE_MCS51(?:=.*)?|-DSTC16F40K128)$') {
            throw 'Target support has been removed; select a current MCS251 board.'
        }
    }
}

function Invoke-StcCpp {
    param([string]$Sdcc, [string]$Mode, [string]$Source, [string]$Object, [string[]]$Arguments)
    $Platform = [IO.Path]::GetFullPath((Join-Path $PSScriptRoot '../..'))
    $LockPath = Join-Path $Platform 'tools/cpp-cli/toolchain-lock.windows-x86_64.json'
    $Lock = Get-Content -Raw -Encoding UTF8 -LiteralPath $LockPath | ConvertFrom-Json
    if ($Lock.host -cne 'windows-x86_64') { throw 'Expected a native Windows toolchain lock.' }
    $Frontend = $env:STCXX_CPP_TOOLS_ROOT
    if (-not $Frontend) {
        $Parent = [IO.Directory]::GetParent($Platform)
        if ($Parent.Name -cne 'mcs251' -or $Parent.Parent.Name -cne 'hardware' -or
            $Parent.Parent.Parent.Parent.Name -cne 'packages') {
            throw 'Set STCXX_CPP_TOOLS_ROOT when compiling from a source checkout.'
        }
        $Binding = $Lock.arduino_frontend
        foreach ($Value in @($Binding.packager, $Binding.name, $Binding.version)) {
            if ($Value -cnotmatch '^[A-Za-z0-9][A-Za-z0-9._+-]*$') { throw 'Invalid native frontend binding.' }
        }
        $Frontend = Join-Path $Parent.Parent.Parent.Parent.FullName "$($Binding.packager)/tools/$($Binding.name)/$($Binding.version)"
    }
    $Frontend = [IO.Path]::GetFullPath($Frontend)
    # Verify the complete embedded Python bootstrap before loading its DLLs.
    if (-not $Lock.windows_frontend.bootstrap_files) { throw 'Missing Python bootstrap inventory.' }
    foreach ($Entry in $Lock.windows_frontend.bootstrap_files.PSObject.Properties) {
        $Path = [IO.Path]::GetFullPath((Join-Path $Frontend $Entry.Name))
        if (-not $Path.StartsWith($Frontend.TrimEnd('\') + '\', [StringComparison]::OrdinalIgnoreCase)) {
            throw 'Python bootstrap path escapes the frontend package.'
        }
        if (-not [IO.File]::Exists($Path) -or
            (Get-FileHash -Algorithm SHA256 -LiteralPath $Path).Hash.ToLowerInvariant() -cne $Entry.Value) {
            throw "Native Python bootstrap SHA-256 mismatch: $Path"
        }
    }
    $Python = Join-Path $Frontend 'python/python.exe'
    $Driver = Join-Path $Platform 'tools/cpp-cli/stcxx-cli.py'
    if ((Get-FileHash -Algorithm SHA256 -LiteralPath $Driver).Hash.ToLowerInvariant() -cne
        $Lock.pipeline_helpers.windows_cli_driver.sha256) { throw 'Native C++ driver SHA-256 mismatch.' }
    $Suffix = '.stcxx-arguments-' + [guid]::NewGuid().ToString('N')
    $ArgumentFile = if ($Object -match '^(nul:?|/dev/null)$') {
        Join-Path ([IO.Path]::GetTempPath()) $Suffix
    } else { $Object + $Suffix }
    $OldSdcc = $env:STCXX_ARDUINO_SDCC
    $OldFrontend = $env:STCXX_CPP_TOOLS_ROOT
    try {
        $Payload = if ($Arguments.Count) { ($Arguments -join "`0") + "`0" } else { '' }
        [IO.File]::WriteAllBytes($ArgumentFile, [Text.Encoding]::UTF8.GetBytes($Payload))
        $env:STCXX_ARDUINO_SDCC = $Sdcc
        $env:STCXX_CPP_TOOLS_ROOT = $Frontend
        return Invoke-StcProcess $Python @('-I', '-B', $Driver, $Mode, $Source, $Object, $ArgumentFile)
    } finally {
        [IO.File]::Delete($ArgumentFile)
        $env:STCXX_ARDUINO_SDCC = $OldSdcc
        $env:STCXX_CPP_TOOLS_ROOT = $OldFrontend
    }
}

function Invoke-StcCompile {
    param([string]$Sdcc, [string]$Source, [string]$Object, [string]$Mark, [string[]]$Arguments)
    Assert-StcTarget $Arguments
    if ($Arguments -ccontains '-DSTCXX_CPP_CORE=1') {
        $Mode = switch -Regex ($Mark + ':' + $Source) {
            '^re11:.*\.cpp(?:\.merged)?$' { 'preprocess-deps'; break }
            '^re12:.*\.cpp(?:\.merged)?$' { 'preprocess-macros'; break }
            '^re2:.*\.cpp(?:\.merged)?$' { 'compile-cpp'; break }
            '^re1:.*\.c$' { 'compile-c'; break }
        }
        if ($Mode) { return Invoke-StcCpp $Sdcc $Mode $Source $Object $Arguments }
    }
    if ($Arguments -ccontains '--function-sections' -or $Arguments -ccontains '--data-sections') {
        $Help = Invoke-StcProcess $Sdcc @('-mmcs251', '--help') -Capture
        if ($Help.Status -ne 0) { return $Help.Status }
        if (($Help.Output + $Help.Error) -notmatch '(?s)--function-sections.*--data-sections') {
            throw 'Full-Flash layout requires rebuilt sdcc-c251 with --function-sections and --data-sections support.'
        }
    }
    if ($Mark -ceq 're11') { return Invoke-StcProcess $Sdcc ($Arguments + @('-x', 'c', $Source)) }
    if ($Mark -ceq 're12' -and $Object -match '^(nul:?|/dev/null)$') {
        # Arduino appends an unquoted -MF path. Rejoin its fragments and keep
        # SDCC away from the Windows null device, which otherwise leaks nul.d.
        $MfIndex = [Array]::IndexOf($Arguments, '-MF')
        $MfPath = ''
        $Flags = $Arguments
        if ($MfIndex -ge 0) {
            if ($MfIndex + 1 -ge $Arguments.Count) { throw 'Missing -MF destination' }
            $MfPath = $Arguments[($MfIndex + 1)..($Arguments.Count - 1)] -join ' '
            $Flags = @($Arguments | Select-Object -First $MfIndex)
        }
        $Name = [IO.Path]::GetFileName($Source)
        if ($Name.EndsWith('.cpp.merged')) { $Dependency = $Name.Substring(0, $Name.Length - 7) + '.d' }
        elseif ($Name.EndsWith('.cpp') -or $Name.EndsWith('.c')) { $Dependency = [IO.Path]::ChangeExtension($Name, '.d') }
        else { throw "Unsupported discovery source: $Source" }
        $Directory = if ($MfPath) { [IO.Path]::GetDirectoryName($MfPath) } else { [IO.Path]::GetDirectoryName($Source) }
        $Status = Invoke-StcProcess $Sdcc ($Flags + @('-x', 'c', $Source)) $Directory
        if ($Status -eq 0 -and $MfPath) {
            $Generated = Join-Path $Directory $Dependency
            if ([IO.File]::Exists($Generated)) {
                if ([IO.Path]::GetFullPath($Generated) -ne [IO.Path]::GetFullPath($MfPath)) {
                    [IO.File]::Copy($Generated, $MfPath, $true)
                    [IO.File]::Delete($Generated)
                }
            } elseif (-not [IO.File]::Exists($MfPath)) { throw 'SDCC did not produce the Arduino dependency file' }
        }
        return $Status
    }
    if ($Source -cmatch '\.cpp(?:\.merged)?$') {
        $Arguments += @('-x', 'c')
        if ($Mark -cne 're12') { $Arguments += @('--include', 'dummy_variable_main.h') }
    } elseif (-not $Source.EndsWith('.c')) { throw "Unsupported source extension: $Source" }
    $Status = Invoke-StcProcess $Sdcc ($Arguments + @($Source, '-o', $Object))
    if ($Status -ne 0 -or $Mark -ceq 're12') { return $Status }
    if ($Object.EndsWith('.o')) {
        $Rel = [IO.Path]::ChangeExtension($Object, '.rel')
        if ([IO.File]::Exists($Object)) { [IO.File]::Copy($Object, $Rel, $true) }
        elseif ([IO.File]::Exists($Rel)) { [IO.File]::Copy($Rel, $Object, $true) }
        else { throw "SDCC produced neither $Object nor $Rel" }
    }
    return 0
}

function Invoke-StcArchive {
    param([string]$Sdar, [string]$Archive, [string]$Object, [string[]]$Arguments)
    $Rel = if ($Object.EndsWith('.o')) { [IO.Path]::ChangeExtension($Object, '.rel') } else { $Object }
    if (-not [IO.File]::Exists($Rel)) { throw "Core object not found: $Rel" }
    $Library = if ($Archive.EndsWith('.a')) { [IO.Path]::ChangeExtension($Archive, '.lib') } else { $Archive + '.lib' }
    # The C++ linker selects the board-sized heap explicitly before core.lib.
    if ([IO.Path]::GetFileName($Rel) -ceq 'stcxx_heap.c.rel') {
        if ([IO.Path]::GetFileName($Archive) -cne 'core.a') { throw 'Refusing to exclude STCXX heap from a non-core archive' }
        if ([IO.File]::Exists($Archive)) { [IO.File]::Copy($Archive, $Library, $true) }
        return 0
    }
    $Status = Invoke-StcProcess $Sdar ($Arguments + @($Archive, $Rel))
    if ($Status -eq 0) { [IO.File]::Copy($Archive, $Library, $true) }
    return $Status
}

function Invoke-StcLink {
    param([string]$Sdcc, [string[]]$Arguments)
    Assert-StcTarget $Arguments
    if ($Arguments -ccontains '-DSTCXX_CPP_CORE=1') {
        $OutputIndex = [Array]::LastIndexOf($Arguments, '-o')
        if ($OutputIndex -lt 0 -or $OutputIndex + 1 -ge $Arguments.Count) { throw 'C++ link recipe did not provide an output path' }
        return Invoke-StcCpp $Sdcc 'link' '-' $Arguments[$OutputIndex + 1] $Arguments
    }
    $Converted = foreach ($Value in $Arguments) {
        if ($Value.EndsWith('.o')) { [IO.Path]::ChangeExtension($Value, '.rel') }
        elseif ($Value.EndsWith('.a')) {
            $Library = [IO.Path]::ChangeExtension($Value, '.lib')
            [IO.File]::Copy($Value, $Library, $true)
            $Library
        } else { $Value }
    }
    return Invoke-StcProcess $Sdcc $Converted
}

function Write-StcSize {
    param([string]$Report)
    if (-not [IO.File]::Exists($Report)) { throw "SDCC memory report not found: $Report" }
    $StackSeen = $false; $ProgramSeen = $false; $Dynamic = $false; $GridSeen = $false
    $Internal = 0; $GridHigh = 0; $Paged = 0; $External = 0; $Program = 0
    foreach ($Line in [IO.File]::ReadAllLines($Report)) {
        if ($Line -match '^0x([0-9A-Fa-f]+):\|(.*)') {
            $Base = [Convert]::ToInt32($Matches[1], 16)
            $Cells = $Matches[2].Split('|')
            for ($I = 0; $I -lt [Math]::Min(16, $Cells.Count); ++$I) {
                if ($Cells[$I].Trim()) { $GridHigh = [Math]::Max($GridHigh, $Base + $I + 1) }
            }
            $GridSeen = $true
        }
        if ($Line.Contains('No clue at where the stack begins and ends!')) { $Dynamic = $true }
        if ($Line -match '[Ss]tack starts at:\s*0[xX]([0-9A-Fa-f]+)') {
            $Internal = [Convert]::ToInt32($Matches[1], 16); $StackSeen = $true
        }
        foreach ($Kind in @('PAGED EXT. RAM', 'EXTERNAL RAM', 'ROM/EPROM/FLASH')) {
            if ($Line -match ('^\s*' + [regex]::Escape($Kind) + '\s')) {
                $Number = 0
                foreach ($Field in ($Line.Trim() -split '\s+')) {
                    if ($Field -match '^\d+$') { $Number = [int]$Field; break }
                }
                switch ($Kind) {
                    'PAGED EXT. RAM' { $Paged = $Number }
                    'EXTERNAL RAM' { $External = $Number }
                    'ROM/EPROM/FLASH' { $Program = $Number; $ProgramSeen = $true }
                }
            }
        }
    }
    if (-not $StackSeen -and $Dynamic -and $GridSeen) { $Internal = $GridHigh; $StackSeen = $true }
    if (-not $StackSeen -or -not $ProgramSeen) { throw 'Unrecognized SDCC memory report format' }
    # Arduino's anchored size regex consumes LF-delimited output on every host.
    [Console]::Out.Write("STC_PROGRAM_BYTES $Program`n")
    [Console]::Out.Write('STC_RAM_BYTES ' + ($Internal + $Paged + $External) + "`n")
}

try {
    # Single dispatch keeps all recipes on the same argument and native-process handling.
    switch -CaseSensitive ($RecipeArguments[0]) {
        'compile' {
            if ($RecipeArguments.Count -lt 5) { throw 'compile requires compiler, source, object and probe mode' }
            exit (Invoke-StcCompile $RecipeArguments[1] $RecipeArguments[2] $RecipeArguments[3] $RecipeArguments[4] @($RecipeArguments | Select-Object -Skip 5))
        }
        'archive' {
            if ($RecipeArguments.Count -lt 4) { throw 'archive requires archiver, archive and object' }
            exit (Invoke-StcArchive $RecipeArguments[1] $RecipeArguments[2] $RecipeArguments[3] @($RecipeArguments | Select-Object -Skip 4))
        }
        'link' {
            if ($RecipeArguments.Count -lt 2) { throw 'link requires a compiler' }
            exit (Invoke-StcLink $RecipeArguments[1] @($RecipeArguments | Select-Object -Skip 2))
        }
        'size' {
            if ($RecipeArguments.Count -ne 2) { throw 'size requires one memory report' }
            Write-StcSize $RecipeArguments[1]
            exit 0
        }
        default { throw 'Expected compile, archive, link or size' }
    }
} catch {
    [Console]::Error.WriteLine($_.Exception.Message)
    exit 4
}

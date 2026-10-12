#Requires -Version 5.1
<#
.SYNOPSIS
  Register TiaOpenness.Server.exe in the Siemens Openness firewall AllowList / Whitelist.

.DESCRIPTION
  Siemens shows "An application wants to access TIA Portal" unless HKLM whitelist
  Path + DateModified (UTC) + SHA256 FileHash match the exe. Rebuilds change hash,
  so this must be re-run after every Openness build (Start-ResearchOS does that).

  Writes the primary key ...\Whitelist\<exe>\Entry (not "Entry (n)"). TIA reads Entry.
  Requires one UAC elevation when the fingerprint is stale; later starts are silent.

.PARAMETER Exe
  Full path to TiaOpenness.Server.exe. Default: Release then Debug under the repo.

.PARAMETER NoElevate
  Do not relaunch as Administrator (used by the elevated child).
#>
[CmdletBinding()]
param(
    [string] $Exe = "",
    [switch] $NoElevate
)

$ErrorActionPreference = "Stop"
$Root = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path

function Test-IsAdmin {
    $id = [Security.Principal.WindowsIdentity]::GetCurrent()
    $principal = New-Object Security.Principal.WindowsPrincipal($id)
    return $principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
}

function Resolve-OpennessExe([string] $PathHint) {
    if ($PathHint -and (Test-Path -LiteralPath $PathHint)) {
        return (Get-Item -LiteralPath $PathHint).FullName
    }
    $candidates = @(
        (Join-Path $Root "tools\industrial-mcp\tia-openness\src\TiaOpenness.Server\bin\Release\net481\TiaOpenness.Server.exe"),
        (Join-Path $Root "tools\industrial-mcp\tia-openness\src\TiaOpenness.Server\bin\Debug\net481\TiaOpenness.Server.exe")
    )
    foreach ($c in $candidates) {
        if (Test-Path -LiteralPath $c) { return (Get-Item -LiteralPath $c).FullName }
    }
    throw "TiaOpenness.Server.exe not found. Build tools/industrial-mcp/tia-openness first."
}

function Get-ExeFingerprint([string] $Path) {
    $item = Get-Item -LiteralPath $Path
    $sha = [System.Security.Cryptography.SHA256]::Create()
    $stream = [System.IO.File]::OpenRead($Path)
    try {
        $hash = [Convert]::ToBase64String($sha.ComputeHash($stream))
    }
    finally {
        $stream.Dispose()
        $sha.Dispose()
    }
    return [pscustomobject]@{
        Path         = $item.FullName
        DateModified = $item.LastWriteTimeUtc.ToString(
            "yyyy/MM/dd HH:mm:ss.fff",
            [Globalization.CultureInfo]::InvariantCulture
        )
        FileHash     = $hash
    }
}

function Test-EntryMatches([string] $EntryKey, $Fingerprint) {
    if (-not (Test-Path -LiteralPath $EntryKey)) { return $false }
    $props = Get-ItemProperty -LiteralPath $EntryKey -ErrorAction SilentlyContinue
    if (-not $props) { return $false }
    return (
        [string]$props.Path -eq $Fingerprint.Path -and
        [string]$props.DateModified -eq $Fingerprint.DateModified -and
        [string]$props.FileHash -eq $Fingerprint.FileHash
    )
}

function Get-WhitelistHives {
    $hives = @(
        "HKLM:\SOFTWARE\Siemens\Automation\Openness",
        "HKLM:\SOFTWARE\WOW6432Node\Siemens\Automation\Openness"
    )
    $found = @()
    foreach ($hive in $hives) {
        if (Test-Path -LiteralPath $hive) { $found += $hive }
    }
    if ($found.Count -eq 0) {
        $found = @("HKLM:\SOFTWARE\Siemens\Automation\Openness")
    }
    return $found
}

function Get-TargetEntryKeys([string] $ExeName) {
    $keys = New-Object System.Collections.Generic.List[string]
    foreach ($hive in Get-WhitelistHives) {
        $versioned = @()
        if (Test-Path -LiteralPath $hive) {
            $versioned = @(Get-ChildItem -LiteralPath $hive -ErrorAction SilentlyContinue |
                Where-Object { $_.PSChildName -match '^\d+\.\d+$' } |
                ForEach-Object { $_.PSChildName })
        }
        if ($versioned.Count -eq 0) { $versioned = @("19.0") }
        foreach ($ver in $versioned) {
            $keys.Add("$hive\$ver\Whitelist\$ExeName\Entry")
        }
        $allow = Join-Path $hive "AllowList\$ExeName\Entry"
        if ((Test-Path -LiteralPath (Join-Path $hive "AllowList")) -or $versioned -contains "21.0") {
            $keys.Add($allow)
        }
    }
    return @($keys | Select-Object -Unique)
}

function Write-Entry([string] $EntryKey, $Fingerprint) {
    $parent = Split-Path $EntryKey -Parent
    if (-not (Test-Path -LiteralPath $parent)) {
        New-Item -Path $parent -Force | Out-Null
    }
    if (-not (Test-Path -LiteralPath $EntryKey)) {
        New-Item -Path $EntryKey -Force | Out-Null
    }
    New-ItemProperty -LiteralPath $EntryKey -Name "Path" -Value $Fingerprint.Path -PropertyType String -Force | Out-Null
    New-ItemProperty -LiteralPath $EntryKey -Name "DateModified" -Value $Fingerprint.DateModified -PropertyType String -Force | Out-Null
    New-ItemProperty -LiteralPath $EntryKey -Name "FileHash" -Value $Fingerprint.FileHash -PropertyType String -Force | Out-Null
}

$exePath = Resolve-OpennessExe $Exe
$fp = Get-ExeFingerprint $exePath
$exeName = [IO.Path]::GetFileName($exePath)
$targets = Get-TargetEntryKeys $exeName

$stale = @($targets | Where-Object { -not (Test-EntryMatches $_ $fp) })
if ($stale.Count -eq 0) {
    Write-Host "Openness firewall whitelist already matches:"
    Write-Host "  $exePath"
    Write-Host "  DateModified=$($fp.DateModified)"
    exit 0
}

if (-not (Test-IsAdmin)) {
    if ($NoElevate) {
        Write-Error "Administrator rights required to write HKLM Openness whitelist."
        exit 2
    }
    Write-Host "Updating Siemens Openness whitelist (one UAC prompt)..."
    $arg = @(
        "-NoProfile",
        "-ExecutionPolicy", "Bypass",
        "-File", "`"$PSCommandPath`"",
        "-Exe", "`"$exePath`"",
        "-NoElevate"
    ) -join " "
    $proc = Start-Process -FilePath "powershell.exe" -Verb RunAs -ArgumentList $arg -Wait -PassThru
    if ($null -eq $proc) { exit 2 }
    exit $proc.ExitCode
}

foreach ($key in $stale) {
    Write-Entry $key $fp
    Write-Host "Wrote $key"
}

Write-Host "Openness firewall whitelist updated for $exePath"
Write-Host "  DateModified=$($fp.DateModified)"
Write-Host "  FileHash=$($fp.FileHash)"
exit 0

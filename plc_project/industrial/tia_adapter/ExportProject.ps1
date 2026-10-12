<#
.SYNOPSIS
  TIA Portal Openness adapter — export a TIA project to SimaticML XML.

.DESCRIPTION
  Part of the ResearchOS PLC Agent pipeline:
      TIA Project -> [this script / Openness] -> SimaticML exports
                   -> agents.plc.tia (PLC-IR -> Knowledge Graph -> SCL)

  Requires: TIA Portal V17+ installed, user in the
  "Siemens TIA Portal Openness" Windows group, and project opened
  with Openness access enabled.

.PARAMETER ProjectPath
  Path to the .ap1x TIA project file.
.PARAMETER ExportDir
  Output directory for SimaticML XML files (feed this to the PLC Agent).
.PARAMETER PlcName
  PLC device name inside the project (default: first PLC found).
.PARAMETER TiaVersion
  Portal version folder suffix (V17|V18|V19|V20). Used to locate PublicAPI.

.EXAMPLE
  .\ExportProject.ps1 -ProjectPath C:\Proj\Line1.ap17 -ExportDir C:\Export\Line1

.EXAMPLE
  .\ExportProject.ps1 -ProjectPath C:\Proj\Line1.ap19 -ExportDir C:\Export\Line1 -TiaVersion V19 -PlcName "PLC_1"
#>
param(
    [Parameter(Mandatory = $true)] [string] $ProjectPath,
    [Parameter(Mandatory = $true)] [string] $ExportDir,
    [string] $PlcName = "",
    [ValidateSet("V17", "V18", "V19", "V20")] [string] $TiaVersion = "V17"
)

$ErrorActionPreference = "Stop"

function Find-EngineeringDll {
    param([string] $Version)
    $portalRoot = "C:\Program Files\Siemens\Automation\Portal $Version"
    $ordered = @(
        (Join-Path $portalRoot "PublicAPI\$Version\Siemens.Engineering.dll"),
        (Join-Path $portalRoot "PublicAPI\Siemens.Engineering.dll")
    )
    # Also probe sibling PublicAPI version folders under the same Portal install.
    $publicApi = Join-Path $portalRoot "PublicAPI"
    if (Test-Path $publicApi) {
        Get-ChildItem -Path $publicApi -Directory -ErrorAction SilentlyContinue |
            Sort-Object Name -Descending |
            ForEach-Object {
                $ordered += (Join-Path $_.FullName "Siemens.Engineering.dll")
            }
    }
    foreach ($path in $ordered) {
        if (Test-Path $path) { return $path }
    }
    return $null
}

function Export-BlockGroup {
    param($Group, [string] $BlocksDir, [string] $Relative = "")
    $exported = 0
    foreach ($block in @($Group.Blocks)) {
        $safe = ($block.Name -replace '[\\/:*?"<>|]', '_')
        $sub = if ($Relative) { Join-Path $BlocksDir $Relative } else { $BlocksDir }
        New-Item -ItemType Directory -Force -Path $sub | Out-Null
        $target = [System.IO.FileInfo]::new((Join-Path $sub ($safe + ".xml")))
        $block.Export($target, [Siemens.Engineering.ExportOptions]::WithDefaults)
        Write-Host ("  exported block: " + $(if ($Relative) { "$Relative/$($block.Name)" } else { $block.Name }))
        $exported++
    }
    foreach ($child in @($Group.Groups)) {
        $childRel = if ($Relative) { Join-Path $Relative $child.Name } else { $child.Name }
        $exported += Export-BlockGroup -Group $child -BlocksDir $BlocksDir -Relative $childRel
    }
    return $exported
}

function Export-TagTableGroup {
    param($Group, [string] $TagsDir, [string] $Relative = "")
    $exported = 0
    foreach ($table in @($Group.TagTables)) {
        $safe = ($table.Name -replace '[\\/:*?"<>|]', '_')
        $sub = if ($Relative) { Join-Path $TagsDir $Relative } else { $TagsDir }
        New-Item -ItemType Directory -Force -Path $sub | Out-Null
        $target = [System.IO.FileInfo]::new((Join-Path $sub ($safe + ".xml")))
        $table.Export($target, [Siemens.Engineering.ExportOptions]::WithDefaults)
        Write-Host ("  exported tag table: " + $(if ($Relative) { "$Relative/$($table.Name)" } else { $table.Name }))
        $exported++
    }
    foreach ($child in @($Group.Groups)) {
        $childRel = if ($Relative) { Join-Path $Relative $child.Name } else { $child.Name }
        $exported += Export-TagTableGroup -Group $child -TagsDir $TagsDir -Relative $childRel
    }
    return $exported
}

if (-not (Test-Path $ProjectPath)) {
    throw "Project file not found: $ProjectPath"
}

$dll = Find-EngineeringDll -Version $TiaVersion
if (-not $dll) {
    throw "Siemens.Engineering.dll not found under Portal $TiaVersion. Install TIA Portal Openness / PublicAPI."
}
Write-Host "Using Openness DLL: $dll"

# Openness Engineering.dll depends on Siemens.Engineering.Contract under
# Portal\Bin\PublicAPI. Stage Engineering + Contract into a private folder so
# CLR probing finds dependencies without a recursive AssemblyResolve hook.
$portalRoot = "C:\Program Files\Siemens\Automation\Portal $TiaVersion"
$binPublicApi = Join-Path $portalRoot "Bin\PublicAPI"
$binDir = Join-Path $portalRoot "Bin"
$stage = Join-Path $env:TEMP ("researchos_openness_" + $TiaVersion)
New-Item -ItemType Directory -Force -Path $stage | Out-Null
Copy-Item -Force $dll (Join-Path $stage "Siemens.Engineering.dll")
foreach ($depName in @(
    "Siemens.Engineering.Contract.dll",
    "Siemens.Engineering.ClientAdapter.Interfaces.dll"
)) {
    $src = Join-Path $binPublicApi $depName
    if (Test-Path $src) {
        Copy-Item -Force $src (Join-Path $stage $depName)
    }
}
# Keep PATH/cwd on Bin for native/sidecar deps used when TiaPortal starts.
$env:PATH = "$stage;$binPublicApi;$binDir;$env:PATH"
[System.IO.Directory]::SetCurrentDirectory($binDir)
foreach ($depName in @(
    "Siemens.Engineering.Contract.dll",
    "Siemens.Engineering.ClientAdapter.Interfaces.dll",
    "Siemens.Engineering.dll"
)) {
    $p = Join-Path $stage $depName
    if (Test-Path $p) {
        [void][System.Reflection.Assembly]::LoadFrom($p)
    }
}
Add-Type -AssemblyName System.IO
Write-Host "Openness assemblies staged at: $stage"

New-Item -ItemType Directory -Force -Path $ExportDir | Out-Null
$blocksDir = Join-Path $ExportDir "Blocks"
$tagsDir   = Join-Path $ExportDir "TagTables"
New-Item -ItemType Directory -Force -Path $blocksDir | Out-Null
New-Item -ItemType Directory -Force -Path $tagsDir | Out-Null

function Get-EngineeringService {
    param($Provider, [Type]$ServiceType)
    if ($null -eq $Provider -or $null -eq $ServiceType) { return $null }
    $method = $Provider.GetType().GetMethods() |
        Where-Object {
            $_.Name -eq "GetService" -and
            $_.IsGenericMethodDefinition -and
            $_.GetParameters().Count -eq 0
        } |
        Select-Object -First 1
    if ($null -eq $method) { return $null }
    try {
        return $method.MakeGenericMethod($ServiceType).Invoke($Provider, @())
    } catch {
        return $null
    }
}

function Find-PlcSoftwareInItem {
    param($Item, [string]$WantedName, [string]$DeviceName)
    $candidates = @(
        [Type]::GetType("Siemens.Engineering.HW.Features.SoftwareContainer, Siemens.Engineering"),
        [Type]::GetType("Siemens.Engineering.Software.SoftwareContainer, Siemens.Engineering")
    ) | Where-Object { $_ -ne $null }
    # Fallback: resolve from already-loaded Engineering assembly
    if ($candidates.Count -eq 0) {
        $engAsm = [AppDomain]::CurrentDomain.GetAssemblies() |
            Where-Object { $_.GetName().Name -eq "Siemens.Engineering" } |
            Select-Object -First 1
        if ($engAsm) {
            foreach ($tn in @(
                "Siemens.Engineering.HW.Features.SoftwareContainer",
                "Siemens.Engineering.Software.SoftwareContainer"
            )) {
                $t = $engAsm.GetType($tn)
                if ($t) { $candidates += $t }
            }
        }
    }
    foreach ($svcType in $candidates) {
        $container = Get-EngineeringService -Provider $Item -ServiceType $svcType
        if ($null -eq $container) { continue }
        $software = $container.Software
        if ($null -eq $software) { continue }
        if ($software -is [Siemens.Engineering.SW.PlcSoftware]) {
            if ($WantedName -eq "" -or $DeviceName -eq $WantedName -or $software.Name -eq $WantedName -or $Item.Name -eq $WantedName) {
                return $software
            }
        }
    }
    foreach ($child in @($Item.DeviceItems)) {
        $found = Find-PlcSoftwareInItem -Item $child -WantedName $WantedName -DeviceName $DeviceName
        if ($null -ne $found) { return $found }
    }
    return $null
}

Write-Host "Starting TIA Portal (no UI)..."
$portal = New-Object Siemens.Engineering.TiaPortal([Siemens.Engineering.TiaPortalMode]::WithoutUserInterface)

try {
    Write-Host "Opening project: $ProjectPath"
    $project = $portal.Projects.Open([System.IO.FileInfo]::new($ProjectPath))

    $plcSoftware = $null
    $plcDeviceName = ""
    foreach ($device in $project.Devices) {
        foreach ($item in $device.DeviceItems) {
            $sw = Find-PlcSoftwareInItem -Item $item -WantedName $PlcName -DeviceName $device.Name
            if ($null -ne $sw) {
                $plcSoftware = $sw
                $plcDeviceName = $device.Name
                break
            }
        }
        if ($null -ne $plcSoftware) { break }
    }
    if ($null -eq $plcSoftware) { throw "No PLC software found (PlcName='$PlcName')" }
    Write-Host ("Using PLC device='$plcDeviceName' software='$($plcSoftware.Name)'")

    $blockCount = Export-BlockGroup -Group $plcSoftware.BlockGroup -BlocksDir $blocksDir
    $tagCount = Export-TagTableGroup -Group $plcSoftware.TagTableGroup -TagsDir $tagsDir

    Write-Host ""
    Write-Host "Export summary: blocks=$blockCount tag_tables=$tagCount -> $ExportDir"
    if ($blockCount -eq 0) {
        Write-Warning "No blocks exported. Check PlcName / project groups / Openness permissions."
    }
    Write-Host "Next step — analyze with ResearchOS PLC Agent:"
    Write-Host "  researchos-tia-cli --exports `"$ExportDir`" --out .\scl_out --kg kg.json"
    Write-Host "  # or: python -m agents.plc.tia_cli --exports `"$ExportDir`""
}
finally {
    if ($null -ne $portal) { $portal.Dispose() }
}

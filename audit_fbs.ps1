$dll = "C:\Program Files\Siemens\Automation\Portal V19\PublicAPI\V19\Siemens.Engineering.dll"
$eng = [System.Reflection.Assembly]::LoadFrom($dll)
$portal = [Siemens.Engineering.TiaPortal]::new([Siemens.Engineering.TiaPortalMode]::WithoutUserInterface)
try {
    $projPath = [System.IO.FileInfo]::new("C:\Users\vboxuser\Desktop\Project\Code\PLC_chat\PLC_Openness_data\hr001\HR001_AF_Refactored\HR001_PLC_20260509.ap19")
    $project = $portal.Projects.Open($projPath)
    
    $containerType = $eng.GetType("Siemens.Engineering.HW.Features.SoftwareContainer")
    $deviceItemType = $eng.GetType("Siemens.Engineering.HW.DeviceItem")
    $plcSoftwareType = $eng.GetType("Siemens.Engineering.SW.PlcSoftware")
    
    $getServiceMethod = $null
    foreach ($m in $deviceItemType.GetMethods()) {
        if ($m.Name -eq "GetService" -and $m.IsGenericMethodDefinition) {
            $getServiceMethod = $m.MakeGenericMethod(@($containerType))
            break
        }
    }
    function FindPlc($item) {
        $c = $getServiceMethod.Invoke($item, $null)
        if ($c) {
            $sw = $c.Software
            if ($sw -and $plcSoftwareType.IsAssignableFrom($sw.GetType())) { return $sw }
        }
        foreach ($sub in $item.DeviceItems) { $r = FindPlc $sub; if ($r) { return $r } }
        return $null
    }
    $plc = $null
    foreach ($d in $project.Devices) {
        foreach ($di in $d.DeviceItems) { $plc = FindPlc $di; if ($plc) { break } }
        if ($plc) { break }
    }
    
    $fbs = [System.Collections.Generic.List[object]]::new()
    function CollectBlocks($g, $path = "") {
        foreach ($b in $g.Blocks) {
            $type = $b.GetType().Name
            if ($type -eq "FB") {
                $item = [PSCustomObject]@{
                    Name = $b.Name
                    Number = $b.Number
                    Language = $b.ProgrammingLanguage.ToString()
                    Path = ($path + "/" + $b.Name)
                }
                $script:fbs.Add($item)
            }
        }
        foreach ($sub in $g.Groups) {
            CollectBlocks $sub ($path + "/" + $sub.Name)
        }
    }
    CollectBlocks $plc.BlockGroup ""
    
    Write-Output "==================== AUDIT RESULTS ===================="
    Write-Output ("Total FBs Found: " + $fbs.Count)
    $sclCount = ($fbs | Where-Object { $_.Language -eq "SCL" }).Count
    $ladCount = ($fbs | Where-Object { $_.Language -eq "LAD" }).Count
    Write-Output ("SCL FBs: " + $sclCount)
    Write-Output ("LAD FBs: " + $ladCount)
    Write-Output ""
    Write-Output "--- AF EQUIPMENT MODULE GROUPS ---"
    foreach ($g in $plc.BlockGroup.Groups) {
        Write-Output ("  Group: " + $g.Name)
    }
    Write-Output ""
    Write-Output "--- ALL 41 FBs IN PROJECT ---"
    $sortedFBs = $fbs | Sort-Object Number
    foreach ($fb in $sortedFBs) {
        Write-Output ("  FB " + $fb.Number.ToString().PadLeft(4) + " | " + $fb.Name.PadRight(35) + " | " + $fb.Language)
    }
    Write-Output "========================================================"
} finally {
    $portal.Dispose()
    Write-Output "Portal disposed."
}

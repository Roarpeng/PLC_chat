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
            if ($sw -and $plcSoftwareType.IsAssignableFrom($sw.GetType())) {
                return $sw
            }
        }
        foreach ($sub in $item.DeviceItems) {
            $r = FindPlc $sub
            if ($r) { return $r }
        }
        return $null
    }
    
    $plc = $null
    foreach ($d in $project.Devices) {
        foreach ($di in $d.DeviceItems) {
            $plc = FindPlc $di
            if ($plc) { break }
        }
        if ($plc) { break }
    }
    
    $compilableType = $eng.GetType("Siemens.Engineering.Compiler.ICompilable")
    $getCompService = $null
    foreach ($m in $plc.GetType().GetMethods()) {
        if ($m.Name -eq "GetService" -and $m.IsGenericMethodDefinition) {
            $getCompService = $m.MakeGenericMethod(@($compilableType))
            break
        }
    }
    
    $compilable = $getCompService.Invoke($plc, $null)
    $res = $compilable.Compile()
    
    function Walk($node, $indent = "") {
        if ($node.ErrorCount -gt 0) {
            Write-Output ($indent + "ERR NODE: [" + $node.Path + "] (err=" + $node.ErrorCount + ", warn=" + $node.WarningCount + ") " + $node.Description)
        }
        foreach ($m in $node.Messages) {
            Walk $m ($indent + "  ")
        }
    }
    Walk $res
} finally {
    $portal.Dispose()
    Write-Output "Portal disposed"
}

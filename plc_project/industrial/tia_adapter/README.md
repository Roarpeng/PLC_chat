# TIA Portal Openness Adapter

Exports a Siemens TIA Portal project to SimaticML XML for the ResearchOS PLC Offline Analyzer.

## Preferred user command

You provide `.apxx`; ResearchOS runs export + parse + SCL automatically:

```powershell
researchos-tia-cli --project "C:\Projects\MyLine.ap19" --result-dir .\ResearchOS_PLC_Result
```

## Manual export only

```powershell
cd industrial\tia_adapter
.\ExportProject.ps1 `
  -ProjectPath "C:\Projects\MyLine.ap19" `
  -ExportDir "C:\Export\MyLine" `
  -TiaVersion V19 `
  -PlcName "PLC_1"   # optional
```

## Prerequisites

1. TIA Portal **V17+** with Openness / PublicAPI
2. Windows user in **Siemens TIA Portal Openness**
3. Project path to `.ap17` / `.ap18` / `.ap19` / `.ap20`

## Safety

Exports XML and analyzes offline. Never downloads programs to a PLC.

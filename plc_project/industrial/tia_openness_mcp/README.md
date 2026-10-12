# TIA Openness MCP Server

ResearchOS industrial MCP for Siemens **TIA Portal V19** via official Openness
(Windows HostGateway / C# `TiaOpenness.Server`). Python on Linux can **stage**
XML/SCL; GenerateBlocksFromSource / Retrieve / Archive run on Windows.

```text
ResearchOS Agent
        |
       MCP / one-shot CLI
        |
TIA Openness Server   ← this package (net481)
        |
TIA Portal V19 PublicAPI
```

Export XML feeds the offline stack:

```text
XML → PLC Parser → PLC-IR → Neo4j → PLC Agent
```

Write-back (HITL, fail-closed compile):

```text
tia.open_project → import-xml and/or generate-from-source
  → tia.compile_plc (must ok) → tia.save_project → tia.archive_project
```

**License:** Export / Import / Archive / Retrieve need a valid STEP 7 / TIA license.

## Implemented CLI / MCP tools

| Command / tool | Official Openness API | Notes |
|----------------|----------------------|--------|
| `status` / `tia.get_status` | process + PublicAPI probe | No project required |
| `tia.open_project` | `Projects.Open(FileInfo)` | `.ap17`–`.ap20` |
| `tia.list_blocks` | `PlcSoftware.BlockGroup` + `SystemBlockGroup` + software units | OB/FB/FC/DB |
| `tia.export_block` | `PlcBlock.Export(FileInfo, ExportOptions.WithDefaults)` | |
| `export-project` / `tia.export_project` | chapter-6 walkers (see below) | default `--full` |
| `import-block` / `tia.import_block` | `BlockGroup.Blocks.Import(FileInfo, ImportOptions)` | Refuses F-XML |
| `import-xml` / `tia.import_xml` | `Import` on Types / TagTables / WatchTables / ForceTables; HMI / CAx AML / CFC / TO **only if** that composition actually has `Import` | Fail closed `no_import` |
| `generate-from-source` / `tia.generate_from_source` | `ExternalSourceGroup.ExternalSources.CreateFromFile` + `PlcExternalSource.GenerateBlocksFromSource()` | Refuses F-SCL |
| `generate-source-from-block` / `tia.generate_source_from_block` | `PlcBlock.GenerateSourceFromBlocks(FileInfo)` (5.11.3.18) | Reverse of GenerateBlocksFromSource; refuses F-blocks; missing method → `dependency_unavailable` |
| `compile-plc` / `tia.compile_plc` | `ICompilable.Compile()` | Fail closed — **never** archive `.zap` if this fails or API missing |
| `tia.save_project` | `Project.Save()` | |
| `archive-project` / `tia.archive_project` | `Project.Archive(DirectoryInfo, string, ProjectArchivationMode.Compressed)` | |
| `retrieve` / `tia.retrieve_project` | `Projects.Retrieve(FileInfo, DirectoryInfo)` | Official `.zap*` unpack; Python unzip is fallback only |
| `create-project` / `tia.create_project` | `Projects.Create(DirectoryInfo, string)` | Skip/`dependency_unavailable` if member absent |
| `close-project` / `tia.close_project` | `Project.Close()` | Skip if member absent |
| `create-to` / `delete-to` | `TechnologicalObjectGroup.Create` / `TechnologicalObject.Delete` | **Only** if those methods exist on this build |

Reflection never guesses extra enum overloads. If the member is not on the installed Openness type, the result is `no_export` / `no_import` / `dependency_unavailable` with the official API name in `api`.

## Out of scope (hard refuse)

Documented with the official API name. **Do not implement** these in this product:

| Topic | Official API (do not call) | Reason |
|-------|----------------------------|--------|
| Download program to PLC | `plc.program.download` (ResearchOS MCP) / Openness online download | Device write; stays not-implemented |
| Upload / online / run-stop / compare-to-PLC | `OnlineProvider`, `DownloadProvider`, `Compare` to target | Device / online session |
| Know-how decrypt | `KnowHowProtectionService` / password unlock | Never decrypt protected bodies |
| Password decrypt (CFC charts) | chart password APIs | List + `password_protected` skip only |
| Safety / F-block body write | `Blocks.Import` / `GenerateBlocksFromSource` / `GenerateSourceFromBlocks` on F-OB/FB/FC/DB | Keep `XmlLooksLikeSafety` / name refuse |
| Global libraries | `GlobalLibrary`, `LibraryType` Import/Export extras | Out of scope |
| Teamcenter | Teamcenter Openness adapters | Out of scope |
| VCI / Multiuser / UMAC | `MultiuserProvider`, VCI, UMAC | Out of scope |
| SINAMICS extras | SINAMICS-specific Openness types | Out of scope unless they appear as normal `PlcSoftware` children |
| UI automation | block editor, devices editor, firewall dialogs | Out of scope |
| Binary project graphics dump | project graphics blobs when Export yields opaque binaries | Skip; not pixel layout |

HMI export is **structure only** (tags, screens/templates/popups/slide-ins/faceplates/permanent, scripts, lists, connections, cycles if `CycleFolder` exists). **No pixel layout.** Hardware GSD / IO-Link / topology are **not** claimed complete.

## Official Openness export / parse surface (chapter 6, 11/2023)

Source of truth: *TIA Portal Openness API for automation of engineering workflows* (do **not** commit the PDF).
C# walks compositions with reflection (`Export(FileInfo, ExportOptions.WithDefaults)`). Know-how / inconsistent / no-license / missing Export are recorded in `manifest.json` and never crash the job.

Default CLI: `--full`. Old `Blocks/` only: `--blocks-only` (or `RESEARCHOS_TIA_EXPORT_BLOCKS_ONLY=1`). Python ingest accepts both layouts.

```text
export_dir/
  plc/<plcName>/blocks|types|tags|watch|force|to|alarms|cfc|safety/
  plc/<plcName>/blocks/system/   # SystemBlockGroup (6.4.2.10)
  plc/<plcName>/units/<unit>/    # Software units (5.11.6) when the type exists
  hardware/          # devices.xml always; project.aml when CAx exists
  hmi/<hmiName>/     # tags, scripts, lists, connections, screens, cycles
  opcua/             # optional
  project/texts.xml  # multilingual project texts when Export exists
  manifest.json      # counts + skipped (know_how, inconsistent, no_export, …)
  _exported.jsonl    # incremental Python parse journal
```

| Manual | Object | Export | Parse | Skip-with-reason |
|--------|--------|--------|-------|------------------|
| 6.4.2 | Blocks OB/FB/FC/DB (SCL, GRAPH, F-blocks, snapshots) | `BlockGroup` | PLC-IR | `know_how`, `inconsistent`, `no_license` |
| 6.4.2.10 | System blocks | dedicated `SystemBlockGroup` walker → `blocks/system/` | PLC-IR | `no_export` if composition absent |
| 5.11.6 | Software units | walk `SoftwareUnitGroup` when the CLR type exists | unit `blocks/types/tags` | `no_export` if type absent |
| 6.4.2 GRAPH | GRAPH bodies | same block Export | steps/transitions as IR evidence; SCL stays **non-executable** comments | do not invent GRAPH runtime |
| 6.4.2.27–31 | PlcTypes / UDT (`TypeGroup`) | yes | IR UDT | same skip vocab |
| 6.4.4 | PLC tag tables + constants | all groups | `tag_tables` | `no_export` |
| 6.4.2.26 | Watch & Force tables | yes | `watch_tables` / `force_tables` | `no_export` |
| 6.4.3 | Technology objects | yes | `technology_objects[]` | `no_export` / `no_license`; Create/Delete only if methods exist |
| 6.4.2.19–25 | Alarms / ProDiag | yes | `alarms[]` / `prodiag[]` | `no_export` |
| 6.4.1 | CFC charts | yes | name + blocks/wires | `password_protected`; Import only if `Charts.Import` exists |
| 5.11.7 / 6.4.2.9 / 6.5.39 | SafetyUnit / F-program | enumerate + supervisions | `safety_units[]`, F-blocks flagged | `safety_login` / `no_export`; **no F-body write** |
| 6.4.2.29 | OPC UA XML | if API present | `opcua_nodes` | `no_export` |
| 6.5 | Hardware AML + device tree | `devices.xml`; `project.aml` if CAx | devices, modules, network interfaces | missing AML does **not** fail block parse; GSD/IO-Link/topology not claimed full |
| 6.3 | HMI / HmiUnified | tags, scripts, lists, connections, screen **structure**, cycles if API exists | `hmi_devices[]` | `no_export`; **no pixel layout**; HMI Import only if `Import` is on the folder |
| 6.2 | Project texts | `project/texts.xml` if Export exists | `project_texts` | `no_export`; binary graphics dump skipped |

Skip-reason vocabulary (C# ↔ `coverage.json`): `know_how` · `inconsistent` · `no_license` · `no_export` · `no_import` · `password_protected` · `safety_login` · `openness_error`.

Every `OFFICIAL_CATEGORIES` slot is export+parse **or** an explicit skip reason (never silent empty).

## Layout

```text
tia-openness/
├── README.md
├── TiaOpenness.sln
├── src/
│   ├── TiaOpenness.Server/
│   │   ├── Program.cs
│   │   ├── TiaConnection.cs
│   │   ├── ProjectService.cs
│   │   ├── BlockService.cs
│   │   ├── ExportSurface.cs
│   │   ├── OpennessExport.cs
│   │   └── OpennessMutate.cs
│   └── TiaOpenness.Models/
└── tests/
    └── TiaOpenness.Tests/
```

## Prerequisites

1. Windows + **TIA Portal V19** with Openness / PublicAPI
2. User in Windows group **Siemens TIA Openness**
3. **Sign out and sign back in** after being added (`tia.get_status` → `opennessGroupInToken` must be `true`)
4. .NET **8 SDK** + **.NET Framework 4.8.1 targeting pack** (server targets `net481`)
5. Optional env: `TIA_VERSION` (default `V19`), `TIA_PORTAL_ROOT`
6. **Openness firewall**: **Yes to all**, or `.\scripts\Register-TiaOpennessWhitelist.ps1`

## Build & test

```powershell
cd tools\industrial-mcp\tia-openness
dotnet build -c Release
dotnet test
```

## Run (stdio MCP)

```powershell
dotnet run --project src\TiaOpenness.Server -c Release
```

## Run (one-shot CLI — Python importer)

```powershell
dotnet run --project src\TiaOpenness.Server -c Release -- --cli status
dotnet run --project src\TiaOpenness.Server -c Release -- `
  --cli retrieve --archive "C:\In\Line.zap19" --out-dir "C:\Projects"
dotnet run --project src\TiaOpenness.Server -c Release -- `
  --cli export-project --project "C:\Projects\Line.ap19" --export-dir "C:\Export\Line"
dotnet run --project src\TiaOpenness.Server -c Release -- `
  --cli import-xml --project "C:\Projects\Line.ap19" --xml "C:\Export\UDT_Motor.xml" --kind type
dotnet run --project src\TiaOpenness.Server -c Release -- `
  --cli generate-source-from-block --project "C:\Projects\Line.ap19" --block FB_Motor --out C:\Out\FB_Motor.scl
dotnet run --project src\TiaOpenness.Server -c Release -- `
  --cli archive-project --project "C:\Projects\Line.ap19" --out-dir "C:\Out" --name "Line.zap19"
```

Then:

```powershell
uv run researchos-tia-cli --exports C:\Export\Line --result-dir .\ResearchOS_PLC_Result
```

## Safety

- Openness surface: open / list / export XML, plus HITL SimaticML **import + save** / SCL generate / retrieve / archive on Windows HostGateway.
- Does **not** download programs to a PLC (`plc.program.download` stays not-implemented).
- Prefer attaching is disabled for MCP open; CLI starts `WithoutUserInterface`.
- F-block XML/SCL and `GenerateSourceFromBlocks` on F names are refused.

## Relation to existing adapters

- PowerShell bulk export remains at `industrial/tia_adapter/ExportProject.ps1`
- Python offline analyzer: `researchos-tia-cli` / `agents.plc.tia`
- C# write tools: this package (`TiaOpenness.Server` CLI + MCP). `industrial/README.md` is **not** read-only for HostGateway write-back.

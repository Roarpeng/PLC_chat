using System.Reflection;
using System.Text;
using System.Text.Json;
using System.Xml.Linq;
using TiaOpenness.Models;

namespace TiaOpenness.Server;

/// <summary>
/// Official Openness chapter-6 export surface (PlcSoftware, hardware AML, HMI structure).
/// Know-how / inconsistent / no-license / missing Export are recorded, never crash the job.
/// </summary>
public sealed class ExportSurface
{
    private readonly ProjectService _projects;
    private readonly BlockService _blocks;
    private readonly Dictionary<string, ExportCategoryCount> _counts = new(StringComparer.OrdinalIgnoreCase);
    private readonly List<ExportSkip> _skipped = new();
    private string _journalPath = "";

    public ExportSurface(ProjectService projects, BlockService blocks)
    {
        _projects = projects;
        _blocks = blocks;
    }

    public ExportBlockResult Export(string exportDir, bool skipCompile = false, bool blocksOnly = false)
    {
        if (_projects.PlcSoftware is null && _projects.Project is null)
        {
            return Fail("invalid_argument", "No project open. Call tia.open_project first.");
        }

        if (blocksOnly)
        {
            return _blocks.ExportAllBlocks(exportDir, skipCompile);
        }

        try
        {
            var root = Path.GetFullPath(exportDir);
            Directory.CreateDirectory(root);
            _journalPath = Path.Combine(root, "_exported.jsonl");
            File.WriteAllText(_journalPath, string.Empty, new UTF8Encoding(encoderShouldEmitUTF8Identifier: false));
            foreach (var cat in OpennessExport.OfficialCategories)
            {
                _counts[cat] = new ExportCategoryCount();
            }

            if (!skipCompile && _projects.PlcSoftware is not null)
            {
                _blocks.CompilePlcSoftware();
            }

            ExportProjectTexts(root);
            ExportHardware(root);

            var targets = _projects.EnumerateSoftware();
            if (targets.Count == 0 && _projects.PlcSoftware is not null)
            {
                targets.Add(("plc", _projects.DeviceName ?? "PLC", _projects.PlcName ?? "PLC", _projects.PlcSoftware, _projects.Project!));
            }

            foreach (var (kind, deviceName, softwareName, software, device) in targets)
            {
                var safePlc = OpennessExport.Sanitize(softwareName);
                if (kind == "plc")
                {
                    var plcRoot = Path.Combine(root, "plc", safePlc);
                    Directory.CreateDirectory(plcRoot);
                    ExportPlcSoftware(software, plcRoot, root);
                }
                else
                {
                    var hmiRoot = Path.Combine(root, "hmi", OpennessExport.Sanitize(softwareName));
                    Directory.CreateDirectory(hmiRoot);
                    ExportHmiSoftware(software, hmiRoot, kind);
                    _ = device;
                    _ = deviceName;
                }
            }

            var exported = _counts.Values.Sum(c => c.Exported);
            var failed = _counts.Values.Sum(c => c.Failed);
            var skipped = _skipped.Count;
            var manifest = new
            {
                ok = exported > 0 || failed == 0,
                mode = "full",
                projectName = _projects.ProjectName,
                projectPath = _projects.ProjectPath,
                counts = _counts,
                skipped = _skipped,
                layout = "plc/<plc>/blocks(+system)|types|tags|watch|force|to|alarms|cfc|safety|units + hardware/ + hmi/<hmi>/ + project/",
            };
            var manifestPath = Path.Combine(root, "manifest.json");
            File.WriteAllText(
                manifestPath,
                JsonSerializer.Serialize(manifest, JsonDefaults.Options),
                new UTF8Encoding(encoderShouldEmitUTF8Identifier: false));

            var message =
                $"Full Openness export: exported={exported} failed={failed} skipped={skipped} → {root}";
            return new ExportBlockResult
            {
                Ok = exported > 0 || failed == 0,
                BlockName = "*",
                BlockType = "FULL",
                ExportPath = root,
                ExportedCount = exported,
                FailedCount = failed,
                Message = message,
                Error = exported == 0 && failed > 0
                    ? new ToolError
                    {
                        Code = _skipped.Any(s => s.Reason == "no_license")
                            ? "license_missing"
                            : _skipped.Any(s => s.Reason == "inconsistent")
                                ? "inconsistent_blocks"
                                : "export_failed",
                        Message = _skipped.FirstOrDefault()?.Detail ?? "no objects exported",
                    }
                    : null,
            };
        }
        catch (Exception ex)
        {
            return Fail("openness_error", OpennessExport.Unwrap(ex).Message);
        }
    }

    private void ExportPlcSoftware(object plc, string plcRoot, string exportRoot)
    {
        ExportGroupTree(
            OpennessExport.GetFirstProp(plc, "BlockGroup"),
            Path.Combine(plcRoot, "blocks"),
            OpennessExport.CatBlocks,
            new[] { "Blocks" });
        // Official 6.4.2.10 SystemBlockGroup — dedicated walker, not BlockGroup.
        var systemBlocks = OpennessExport.GetFirstProp(plc, "SystemBlockGroup");
        if (systemBlocks is not null)
        {
            ExportGroupTree(
                systemBlocks,
                Path.Combine(plcRoot, "blocks", "system"),
                OpennessExport.CatBlocks,
                new[] { "Blocks" });
        }
        else
        {
            NoteMissing(OpennessExport.CatBlocks, "SystemBlockGroup", "no_export");
        }

        ExportSoftwareUnits(plc, plcRoot);

        ExportGroupTree(
            OpennessExport.GetFirstProp(plc, "TypeGroup"),
            Path.Combine(plcRoot, "types"),
            OpennessExport.CatTypes,
            new[] { "Types", "PlcTypes", "DataTypes" });
        ExportGroupTree(
            OpennessExport.GetFirstProp(plc, "TagTableGroup"),
            Path.Combine(plcRoot, "tags"),
            OpennessExport.CatTags,
            new[] { "TagTables", "ConstantTables" });

        var watchRoot = OpennessExport.GetFirstProp(
            plc, "WatchAndForceTableGroup", "WatchAndForceTableSystemGroup", "PlcWatchAndForceTableGroup");
        if (watchRoot is not null)
        {
            ExportGroupTree(watchRoot, Path.Combine(plcRoot, "watch"), OpennessExport.CatWatch, new[] { "WatchTables", "PlcWatchTables" });
            ExportGroupTree(watchRoot, Path.Combine(plcRoot, "force"), OpennessExport.CatForce, new[] { "ForceTables", "PlcForceTables" });
        }
        else
        {
            NoteMissing(OpennessExport.CatWatch, "WatchAndForceTableGroup", "no_export");
            NoteMissing(OpennessExport.CatForce, "WatchAndForceTableGroup", "no_export");
        }

        var toGroup = OpennessExport.GetFirstProp(
            plc, "TechnologicalObjectGroup", "TechnologyObjectGroup", "TechnologicalObjects");
        ExportGroupTree(
            toGroup,
            Path.Combine(plcRoot, "to"),
            OpennessExport.CatTo,
            new[] { "TechnologicalObjects", "TechnologyObjects", "Objects" });

        ExportNamedCompositions(
            plc,
            Path.Combine(plcRoot, "alarms"),
            OpennessExport.CatAlarms,
            new[]
            {
                "AlarmTextListGroup", "PlcAlarmTextListGroup", "AlarmClassGroup",
                "AlarmInstanceTextGroup", "UserAlarmProvider", "SupervisionProvider",
                "ProDiagGroup", "ProDiagSettings",
            },
            new[] { "AlarmTextLists", "AlarmClasses", "AlarmInstanceTexts", "Supervisions", "Settings", "Items", "Texts" });

        var cfc = OpennessExport.GetFirstProp(plc, "ChartFolder", "CfcChartFolder", "Charts");
        if (cfc is not null)
        {
            ExportGroupTree(cfc, Path.Combine(plcRoot, "cfc"), OpennessExport.CatCfc, new[] { "Charts", "Blocks" }, groupProperty: "Groups");
        }
        else
        {
            NoteMissing(OpennessExport.CatCfc, "ChartFolder", "no_export");
        }

        ExportSafety(plc, Path.Combine(plcRoot, "safety"));
        ExportOpcUa(plc, Path.Combine(exportRoot, "opcua"));
    }

    private void ExportSafety(object plc, string dir)
    {
        object? safety = OpennessExport.GetFirstProp(plc, "SafetyUnit", "Failsafe")
            ?? TryGetService(plc, "Siemens.Engineering.SW.Safety.SafetyPlcOS")
            ?? TryGetService(plc, "Siemens.Engineering.Safety.SafetyProvider");
        if (safety is null)
        {
            NoteMissing(OpennessExport.CatSafety, "SafetyUnit", "no_export");
            return;
        }

        Directory.CreateDirectory(dir);
        ExportOne(safety, Path.Combine(dir, "safety_unit.xml"), OpennessExport.CatSafety, "SafetyUnit");
        foreach (var (item, rel) in OpennessExport.WalkGroups(
                     safety,
                     new[] { "Supervisions", "FailsafeBlocks", "Items" }))
        {
            var target = Path.Combine(dir, OpennessExport.Sanitize(rel) + ".xml");
            ExportOne(item, target, OpennessExport.CatSafety, rel);
        }
    }

    private void ExportOpcUa(object plc, string dir)
    {
        var opc = OpennessExport.GetFirstProp(plc, "OpcUa")
            ?? TryGetService(plc, "Siemens.Engineering.SW.OpcUa.OpcUaProvider")
            ?? TryGetService(plc, "Siemens.Engineering.OpcUa.OpcUaExport");
        if (opc is null)
        {
            NoteMissing(OpennessExport.CatOpcua, "OpcUa", "no_export");
            return;
        }

        Directory.CreateDirectory(dir);
        ExportOne(opc, Path.Combine(dir, "opcua.xml"), OpennessExport.CatOpcua, "OpcUa");
        foreach (var (item, rel) in OpennessExport.WalkGroups(opc, new[] { "Nodes", "ServerInterfaces", "Items" }))
        {
            ExportOne(item, Path.Combine(dir, OpennessExport.Sanitize(rel) + ".xml"), OpennessExport.CatOpcua, rel);
        }
    }

    private void ExportHmiSoftware(object hmi, string hmiRoot, string kind)
    {
        _ = kind;
        ExportGroupTree(OpennessExport.GetProp(hmi, "TagFolder") ?? OpennessExport.GetProp(hmi, "TagTableFolder"),
            Path.Combine(hmiRoot, "tags"), OpennessExport.CatHmi, new[] { "TagTables", "Tags", "Folders" });
        ExportGroupTree(OpennessExport.GetProp(hmi, "VBScriptFolder") ?? OpennessExport.GetProp(hmi, "ScriptFolder"),
            Path.Combine(hmiRoot, "scripts"), OpennessExport.CatHmi, new[] { "VBScripts", "Scripts" });
        ExportGroupTree(OpennessExport.GetProp(hmi, "TextListFolder"),
            Path.Combine(hmiRoot, "textlists"), OpennessExport.CatHmi, new[] { "TextLists" });
        ExportGroupTree(OpennessExport.GetProp(hmi, "GraphicListFolder"),
            Path.Combine(hmiRoot, "graphiclists"), OpennessExport.CatHmi, new[] { "GraphicLists" });
        ExportGroupTree(OpennessExport.GetProp(hmi, "ConnectionsFolder") ?? OpennessExport.GetProp(hmi, "Connections"),
            Path.Combine(hmiRoot, "connections"), OpennessExport.CatHmi, new[] { "Connections" });
        foreach (var (prop, folder) in new[]
                 {
                     ("ScreenFolder", "screens"),
                     ("TemplateFolder", "templates"),
                     ("PopupScreenFolder", "popups"),
                     ("SlideInScreenFolder", "slideins"),
                     ("FaceplateFolder", "faceplates"),
                     ("PermanentAreaFolder", "permanent"),
                     ("CycleFolder", "cycles"),
                     ("CyclesFolder", "cycles"),
                 })
        {
            var group = OpennessExport.GetProp(hmi, prop);
            if (group is null) continue;
            ExportGroupTree(
                group,
                Path.Combine(hmiRoot, folder),
                OpennessExport.CatHmi,
                new[] { "Screens", "Templates", "Popups", "SlideIns", "Faceplates", "PermanentAreas", "Cycles", "Items" });
        }
    }

    private void ExportSoftwareUnits(object plc, string plcRoot)
    {
        var units = OpennessExport.GetFirstProp(plc, "SoftwareUnitGroup", "SoftwareUnits", "UnitGroup");
        if (units is null)
        {
            NoteMissing(OpennessExport.CatBlocks, "SoftwareUnitGroup", "no_export");
            return;
        }

        var any = false;
        foreach (var unit in OpennessExport.Enumerate(units, "SoftwareUnits", "Units", "Items"))
        {
            any = true;
            var uname = OpennessExport.Sanitize(OpennessExport.GetPropString(unit, "Name") ?? "Unit");
            var unitRoot = Path.Combine(plcRoot, "units", uname);
            Directory.CreateDirectory(unitRoot);
            ExportGroupTree(
                OpennessExport.GetFirstProp(unit, "BlockGroup"),
                Path.Combine(unitRoot, "blocks"),
                OpennessExport.CatBlocks,
                new[] { "Blocks" });
            ExportGroupTree(
                OpennessExport.GetFirstProp(unit, "TypeGroup"),
                Path.Combine(unitRoot, "types"),
                OpennessExport.CatTypes,
                new[] { "Types", "PlcTypes", "DataTypes" });
            ExportGroupTree(
                OpennessExport.GetFirstProp(unit, "TagTableGroup"),
                Path.Combine(unitRoot, "tags"),
                OpennessExport.CatTags,
                new[] { "TagTables", "ConstantTables" });
        }

        if (!any && !OpennessExport.HasExport(units))
        {
            NoteMissing(OpennessExport.CatBlocks, "SoftwareUnitGroup", "no_export");
        }
    }

    private void ExportHardware(string root)
    {
        var project = _projects.Project;
        if (project is null)
        {
            NoteMissing(OpennessExport.CatHardware, "Project.Devices", "no_export");
            return;
        }

        var hwDir = Path.Combine(root, "hardware");
        Directory.CreateDirectory(hwDir);
        try
        {
            var tree = BuildHardwareTreeXml(project);
            var path = Path.Combine(hwDir, "devices.xml");
            tree.Save(path);
            Bump(OpennessExport.CatHardware, exported: true);
            Journal(OpennessExport.CatHardware, "devices", path, ok: true, error: null);
        }
        catch (Exception ex)
        {
            RecordSkip(OpennessExport.CatHardware, "devices.xml", "openness_error", OpennessExport.Unwrap(ex).Message);
        }

        TryCaxAml(project, Path.Combine(hwDir, "project.aml"));
    }

    private void TryCaxAml(object project, string amlPath)
    {
        object? cax = TryGetService(project, "Siemens.Engineering.CAx.CAxProvider")
            ?? TryGetService(project, "Siemens.Engineering.HW.Features.CAxExporter")
            ?? OpennessExport.GetProp(project, "CAx");
        if (cax is null)
        {
            NoteMissing(OpennessExport.CatHardware, "CAx/AML", "no_export");
            return;
        }

        var reason = OpennessExport.TryExport(cax, amlPath);
        if (reason is null)
        {
            Bump(OpennessExport.CatHardware, exported: true);
            Journal(OpennessExport.CatHardware, "project.aml", amlPath, ok: true, error: null);
            return;
        }

        // Some CAx APIs use Export(FileInfo) without ExportOptions.
        try
        {
            var export = cax.GetType().GetMethods(BindingFlags.Public | BindingFlags.Instance)
                .FirstOrDefault(m => m.Name == "Export" && m.GetParameters().Length is 1 or 2);
            if (export is null)
            {
                RecordSkip(OpennessExport.CatHardware, "project.aml", reason, "CAx Export not found");
                return;
            }
            var p0 = export.GetParameters()[0].ParameterType;
            var arg0 = p0 == typeof(string) ? amlPath : Activator.CreateInstance(p0, amlPath)!;
            if (export.GetParameters().Length == 1)
            {
                export.Invoke(cax, new[] { arg0 });
            }
            else
            {
                export.Invoke(cax, new[] { arg0, export.GetParameters()[1].DefaultValue });
            }
            Bump(OpennessExport.CatHardware, exported: true);
            Journal(OpennessExport.CatHardware, "project.aml", amlPath, ok: true, error: null);
        }
        catch (Exception ex)
        {
            RecordSkip(OpennessExport.CatHardware, "project.aml", OpennessExport.ClassifySkipReason(OpennessExport.Unwrap(ex).Message, cax), OpennessExport.Unwrap(ex).Message);
        }
    }

    private static XElement BuildHardwareTreeXml(object project)
    {
        var root = new XElement("HardwareTree");
        foreach (var device in OpennessExport.Enumerate(project, "Devices"))
        {
            root.Add(DeviceElement(device));
        }
        return new XDocument(new XDeclaration("1.0", "utf-8", "yes"), root).Root!;
    }

    private static XElement DeviceElement(object device)
    {
        var el = new XElement(
            "Device",
            new XAttribute("Name", OpennessExport.GetPropString(device, "Name") ?? ""),
            new XAttribute("TypeIdentifier", OpennessExport.GetPropString(device, "TypeIdentifier") ?? OpennessExport.GetPropString(device, "TypeName") ?? ""),
            new XAttribute("Failsafe", OpennessExport.LooksFailsafe(device) ? "true" : "false"));
        var addr = FirstAddress(device);
        if (!string.IsNullOrEmpty(addr)) el.SetAttributeValue("Address", addr);
        foreach (var item in OpennessExport.Enumerate(device, "DeviceItems"))
        {
            el.Add(DeviceItemElement(item));
        }
        foreach (var net in OpennessExport.Enumerate(device, "Subnets", "NetworkInterfaces", "IoSystems"))
        {
            el.Add(NetworkElement(net, "Subnet"));
        }
        return el;
    }

    private static XElement DeviceItemElement(object item)
    {
        var el = new XElement(
            "DeviceItem",
            new XAttribute("Name", OpennessExport.GetPropString(item, "Name") ?? ""),
            new XAttribute("TypeIdentifier", OpennessExport.GetPropString(item, "TypeIdentifier") ?? ""),
            new XAttribute("Slot", OpennessExport.GetPropString(item, "PositionNumber") ?? OpennessExport.GetPropString(item, "Slot") ?? ""),
            new XAttribute("Failsafe", OpennessExport.LooksFailsafe(item) ? "true" : "false"));
        var addr = FirstAddress(item);
        if (!string.IsNullOrEmpty(addr)) el.SetAttributeValue("Address", addr);
        foreach (var child in OpennessExport.Enumerate(item, "DeviceItems"))
        {
            el.Add(DeviceItemElement(child));
        }
        foreach (var net in OpennessExport.Enumerate(item, "Subnets", "NetworkInterfaces", "IoSystems", "Addresses"))
        {
            el.Add(NetworkElement(net, "Subnet"));
        }
        return el;
    }

    private static XElement NetworkElement(object net, string fallbackTag)
    {
        var typeName = net.GetType().Name;
        var tag = typeName.IndexOf("NetworkInterface", StringComparison.OrdinalIgnoreCase) >= 0
            ? "NetworkInterface"
            : typeName.IndexOf("Address", StringComparison.OrdinalIgnoreCase) >= 0
                ? "Address"
                : fallbackTag;
        var name = OpennessExport.GetPropString(net, "Name")
                   ?? OpennessExport.GetPropString(net, "Address")
                   ?? OpennessExport.GetPropString(net, "IpAddress")
                   ?? net.ToString()
                   ?? "";
        var el = new XElement(
            tag,
            new XAttribute("Name", name),
            new XAttribute("Kind", typeName));
        var ip = OpennessExport.GetPropString(net, "IpAddress")
                 ?? OpennessExport.GetPropString(net, "Address")
                 ?? OpennessExport.GetPropString(net, "LogicalAddress");
        if (!string.IsNullOrWhiteSpace(ip)) el.SetAttributeValue("Address", ip);
        var iface = OpennessExport.GetPropString(net, "InterfaceType")
                    ?? OpennessExport.GetPropString(net, "TypeIdentifier");
        if (!string.IsNullOrWhiteSpace(iface)) el.SetAttributeValue("InterfaceType", iface);
        return el;
    }

    private static string FirstAddress(object item)
    {
        foreach (var addr in OpennessExport.Enumerate(item, "Addresses", "NetworkInterfaces"))
        {
            var text = OpennessExport.GetPropString(addr, "Address")
                ?? OpennessExport.GetPropString(addr, "LogicalAddress")
                ?? OpennessExport.GetPropString(addr, "IpAddress");
            if (!string.IsNullOrWhiteSpace(text)) return text!;
        }
        return OpennessExport.GetPropString(item, "Address") ?? "";
    }

    private void ExportProjectTexts(string root)
    {
        var project = _projects.Project;
        if (project is null) return;
        var texts = OpennessExport.GetProp(project, "ProjectTexts")
            ?? OpennessExport.GetProp(project, "LanguageSettings")
            ?? OpennessExport.GetProp(project, "Texts");
        if (texts is null)
        {
            NoteMissing(OpennessExport.CatProject, "ProjectTexts", "no_export");
            return;
        }

        var dir = Path.Combine(root, "project");
        Directory.CreateDirectory(dir);
        ExportOne(texts, Path.Combine(dir, "texts.xml"), OpennessExport.CatProject, "texts");
    }

    private void ExportNamedCompositions(
        object owner,
        string dir,
        string category,
        string[] ownerProps,
        string[] itemProps)
    {
        var found = false;
        foreach (var prop in ownerProps)
        {
            var group = OpennessExport.GetProp(owner, prop);
            if (group is null) continue;
            found = true;
            ExportGroupTree(group, dir, category, itemProps);
        }
        if (!found)
        {
            NoteMissing(category, ownerProps[0], "no_export");
        }
    }

    private void ExportGroupTree(
        object? group,
        string dir,
        string category,
        string[] itemProperties,
        string groupProperty = "Groups")
    {
        if (group is null)
        {
            NoteMissing(category, Path.GetFileName(dir), "no_export");
            return;
        }

        var any = false;
        foreach (var (item, rel) in OpennessExport.WalkGroups(group, itemProperties, groupProperty: groupProperty))
        {
            any = true;
            var target = Path.Combine(dir, OpennessExport.Sanitize(rel) + ".xml");
            ExportOne(item, target, category, rel);
        }
        if (!any && !OpennessExport.HasExport(group))
        {
            // Empty composition — not a failure.
            Bump(category, skipped: false);
        }
    }

    private void ExportOne(object item, string target, string category, string name)
    {
        var consistent = OpennessExport.GetProp(item, "IsConsistent");
        if (consistent is bool ok && !ok)
        {
            RecordSkip(category, name, "inconsistent", "IsConsistent=false");
            Journal(category, name, target, ok: false, error: "inconsistent");
            return;
        }

        var reason = OpennessExport.TryExport(item, target);
        if (reason is null)
        {
            Bump(category, exported: true);
            Journal(category, name, target, ok: true, error: null);
            return;
        }

        RecordSkip(category, name, reason, reason);
        Journal(category, name, target, ok: false, error: reason);
    }

    private object? TryGetService(object provider, string typeName)
    {
        try
        {
            return _projects.Connection.GetService(provider, typeName);
        }
        catch
        {
            return null;
        }
    }

    private void NoteMissing(string category, string name, string reason)
    {
        // Missing composition is skip-with-reason, not a hard failure.
        RecordSkip(category, name, reason, "API member not present on this Portal version / option pack");
    }

    private void RecordSkip(string category, string name, string reason, string? detail)
    {
        _skipped.Add(new ExportSkip
        {
            Category = category,
            Name = name,
            Reason = reason,
            Detail = detail,
        });
        Bump(category, skipped: true);
        if (reason is "inconsistent" or "no_license" or "openness_error")
        {
            Bump(category, failed: true);
        }
    }

    private void Bump(string category, bool exported = false, bool failed = false, bool skipped = false)
    {
        if (!_counts.TryGetValue(category, out var row))
        {
            row = new ExportCategoryCount();
            _counts[category] = row;
        }
        if (exported) row.Exported++;
        if (failed) row.Failed++;
        if (skipped) row.Skipped++;
    }

    private void Journal(string category, string name, string path, bool ok, string? error)
    {
        if (string.IsNullOrEmpty(_journalPath)) return;
        try
        {
            var line = JsonSerializer.Serialize(new
            {
                name,
                type = category,
                category,
                path,
                ok,
                error,
            });
            using var fs = new FileStream(_journalPath, FileMode.Append, FileAccess.Write, FileShare.ReadWrite);
            using var writer = new StreamWriter(fs, new UTF8Encoding(encoderShouldEmitUTF8Identifier: false));
            writer.WriteLine(line);
            writer.Flush();
        }
        catch
        {
            // journal is best-effort
        }
    }

    private static ExportBlockResult Fail(string code, string message) => new()
    {
        Ok = false,
        Error = new ToolError { Code = code, Message = message },
    };
}

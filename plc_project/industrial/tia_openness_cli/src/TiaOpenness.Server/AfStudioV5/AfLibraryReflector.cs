using System;
using System.Collections;
using System.Collections.Generic;
using System.Globalization;
using System.IO;
using System.Linq;
using System.Runtime.CompilerServices;
using System.Text;
using System.Text.Json;
using System.Text.Json.Serialization;
using System.Text.RegularExpressions;
using System.Xml;
using TiaOpenness.Models;

namespace TiaOpenness.Server;

/// <summary>
/// Reflects AF driver mother-class signatures (<c>FB_AF_*</c>) from:
///   1) Connected TIA Portal <c>GlobalLibraries</c> and <c>Project.ProjectLibrary</c>
///      (<c>MasterCopies</c> / <c>Types</c>) plus open PLC <c>FB_AF_*</c> blocks via reflection;
///   2) Local offline <c>.scl</c> / SimaticML <c>.xml</c> library directories;
///   3) Built-in standard AF mother-class catalog (<c>source = "builtin_af_standard"</c>)
///      when neither a TIA Portal instance nor an external library directory is provided.
/// Never falsifies live TIA evidence.
/// </summary>
public sealed class AfLibraryReflector
{
    private static readonly Regex FbStartRegex = new(
        @"^\s*FUNCTION_BLOCK\s+(?:""([^""]+)""|([A-Za-z_][A-Za-z0-9_]*))",
        RegexOptions.IgnoreCase | RegexOptions.Compiled);

    private static readonly Regex FbEndRegex = new(
        @"^\s*END_FUNCTION_BLOCK\b",
        RegexOptions.IgnoreCase | RegexOptions.Compiled);

    private static readonly Regex VarSectionStartRegex = new(
        @"^\s*(VAR_INPUT|VAR_OUTPUT|VAR_IN_OUT|VAR_TEMP|VAR_STAT|VAR)\b",
        RegexOptions.IgnoreCase | RegexOptions.Compiled);

    private static readonly Regex VarSectionEndRegex = new(
        @"^\s*END_VAR\b",
        RegexOptions.IgnoreCase | RegexOptions.Compiled);

    private static readonly Regex SclPinDeclRegex = new(
        @"^\s*(?:""([^""]+)""|([A-Za-z_][A-Za-z0-9_]*))(?:\s*\{[^}]*\})?\s*:\s*([^;:=]+?)(?:\s*:=[^;]*)?;",
        RegexOptions.Compiled);

    private readonly TiaConnection? _connection;
    private readonly ProjectService? _projects;

    public AfLibraryReflector()
    {
    }

    public AfLibraryReflector(TiaConnection? connection, ProjectService? projects)
    {
        _connection = connection;
        _projects = projects;
    }

    public MotherClassRegistryPayload ReflectRegistry(AfLibraryReflectRequest? request = null)
    {
        return ReflectRegistryCore(request, portalOverride: null, projectOverride: null, plcOverride: null);
    }

    internal MotherClassRegistryPayload ReflectFromLiveObjects(
        object? portal,
        object? project,
        object? plcSoftware,
        AfLibraryReflectRequest? request = null) =>
        ReflectRegistryCore(request ?? new AfLibraryReflectRequest(), portal, project, plcSoftware);

    private MotherClassRegistryPayload ReflectRegistryCore(
        AfLibraryReflectRequest? request,
        object? portalOverride,
        object? projectOverride,
        object? plcOverride)
    {
        request ??= new AfLibraryReflectRequest();
        var payload = new MotherClassRegistryPayload
        {
            Ok = true,
            GeneratedAtUtc = DateTime.UtcNow.ToString("o", CultureInfo.InvariantCulture),
        };

        var discovered = new Dictionary<string, AfMotherClassDefinition>(StringComparer.OrdinalIgnoreCase);

        // 1) Connected TIA Portal reflection (GlobalLibraries + ProjectLibrary + open PLC blocks).
        var portal = portalOverride ?? _connection?.Portal;
        var project = projectOverride ?? _projects?.Project;
        var plcSoftware = plcOverride ?? _projects?.PlcSoftware;
        if (!string.IsNullOrWhiteSpace(request.GlobalLibraryPath) && _projects is not null)
        {
            var openLibRes = _projects.OpenGlobalLibrary(request.GlobalLibraryPath!, readOnly: true);
            if (!openLibRes.Ok)
            {
                payload.Warnings.Add(
                    $"Failed to open global library '{request.GlobalLibraryPath}': {openLibRes.Error?.Message ?? openLibRes.Message}");
            }
            else
            {
                portal = _connection?.Portal ?? portal;
            }
        }

        var hadLiveTiaScan = false;
        if (portal is not null || project is not null || plcSoftware is not null)
        {
            hadLiveTiaScan = ScanLiveTiaLibraries(portal, project, plcSoftware, discovered, payload);
        }

        if (hadLiveTiaScan && discovered.Count > 0)
        {
            payload.Source = "tia_openness_library";
            payload.EvidenceLevel = "tia_live";
            payload.Classes = OrderClasses(discovered.Values);
            return payload;
        }

        // 2) Offline .scl / .xml directory scan.
        if (!string.IsNullOrWhiteSpace(request.LibraryDirectory))
        {
            var fullDir = Path.GetFullPath(request.LibraryDirectory!);
            if (!Directory.Exists(fullDir))
            {
                payload.Ok = false;
                payload.Source = "none";
                payload.EvidenceLevel = "offline";
                payload.Error = new ToolError
                {
                    Code = "not_found",
                    Message = $"Offline library directory not found: {fullDir}",
                };
                payload.Warnings.Add(payload.Error.Message);
                return payload;
            }

            ScanOfflineDirectory(fullDir, discovered, payload);
            if (discovered.Count > 0)
            {
                payload.Source = "offline_scl_xml_directory";
                payload.EvidenceLevel = "offline_library";
                payload.Classes = OrderClasses(discovered.Values);
                return payload;
            }

            payload.Warnings.Add($"No FB_AF_* definitions found in '{fullDir}'.");
        }

        // 3) Built-in standard AF mother-class fallback (honestly tagged).
        if (!request.IncludeBuiltinFallback)
        {
            payload.Source = hadLiveTiaScan ? "tia_openness_library" : "none";
            payload.EvidenceLevel = hadLiveTiaScan ? "tia_live" : "offline";
            payload.Classes = OrderClasses(discovered.Values);
            return payload;
        }

        payload.Source = "builtin_af_standard";
        payload.EvidenceLevel = "offline";
        payload.ScannedLocations.Add("builtin://af_standard_v5");
        payload.Classes = BuildBuiltinStandardClasses();
        return payload;
    }

    public static List<AfMotherClassDefinition> ParseSclContent(string sclContent, string? sourcePath = null)
    {
        var results = new List<AfMotherClassDefinition>();
        if (string.IsNullOrWhiteSpace(sclContent)) return results;

        var lines = sclContent.Replace("\r\n", "\n").Replace('\r', '\n')
            .Split(new[] { '\n' }, StringSplitOptions.None);

        AfMotherClassDefinition? current = null;
        string? currentSection = null;

        foreach (var rawLine in lines)
        {
            var line = rawLine.Trim();
            if (line.Length == 0 || line.StartsWith("//", StringComparison.Ordinal))
            {
                continue;
            }

            if (current is null)
            {
                var startMatch = FbStartRegex.Match(line);
                if (!startMatch.Success) continue;

                var fbName = startMatch.Groups[1].Success
                    ? startMatch.Groups[1].Value
                    : startMatch.Groups[2].Value;
                if (!IsAfMotherBlockName(fbName)) continue;

                current = CreateBaseDefinition(fbName, sourcePath);
                currentSection = null;
                continue;
            }

            if (FbEndRegex.IsMatch(line))
            {
                FinalizeParsedDefinition(current);
                results.Add(current);
                current = null;
                currentSection = null;
                continue;
            }

            if (currentSection is null)
            {
                var secMatch = VarSectionStartRegex.Match(line);
                if (secMatch.Success)
                {
                    currentSection = secMatch.Groups[1].Value.ToUpperInvariant();
                }
                continue;
            }

            if (VarSectionEndRegex.IsMatch(line))
            {
                currentSection = null;
                continue;
            }

            if (currentSection is "VAR_INPUT" or "VAR_OUTPUT" or "VAR_IN_OUT")
            {
                var decl = SclPinDeclRegex.Match(line);
                if (decl.Success)
                {
                    var pinName = decl.Groups[1].Success ? decl.Groups[1].Value : decl.Groups[2].Value;
                    var dataType = CollapseWhitespace(decl.Groups[3].Value);
                    AddParsedPin(current, currentSection, pinName, dataType);
                }
            }
        }

        if (current is not null)
        {
            FinalizeParsedDefinition(current);
            results.Add(current);
        }

        return results;
    }

    public static List<AfMotherClassDefinition> ParseSimaticXmlContent(string xmlContent, string? sourcePath = null)
    {
        var results = new List<AfMotherClassDefinition>();
        if (string.IsNullOrWhiteSpace(xmlContent)) return results;

        var doc = new XmlDocument();
        doc.LoadXml(xmlContent);

        var fbNodes = doc.SelectNodes("//*[local-name()='SW.Blocks.FB']");
        if (fbNodes is null || fbNodes.Count == 0) return results;

        foreach (XmlNode fbNode in fbNodes)
        {
            var nameNode = fbNode.SelectSingleNode("./*[local-name()='AttributeList']/*[local-name()='Name']");
            var fbName = nameNode?.InnerText?.Trim();
            if (string.IsNullOrWhiteSpace(fbName) || !IsAfMotherBlockName(fbName!))
            {
                continue;
            }

            var def = CreateBaseDefinition(fbName!, sourcePath);
            var sectionNodes = fbNode.SelectNodes(".//*[local-name()='Interface']//*[local-name()='Section']");
            if (sectionNodes is not null)
            {
                foreach (XmlNode secNode in sectionNodes)
                {
                    var secName = secNode.Attributes?["Name"]?.Value?.Trim() ?? "";
                    var mappedSection = secName.ToUpperInvariant() switch
                    {
                        "INPUT" => "VAR_INPUT",
                        "OUTPUT" => "VAR_OUTPUT",
                        "INOUT" => "VAR_IN_OUT",
                        _ => "",
                    };
                    if (mappedSection.Length == 0) continue;

                    var members = secNode.SelectNodes("./*[local-name()='Member']");
                    if (members is null) continue;
                    foreach (XmlNode member in members)
                    {
                        var pinName = member.Attributes?["Name"]?.Value?.Trim();
                        var dataType = member.Attributes?["Datatype"]?.Value?.Trim() ?? "Variant";
                        if (!string.IsNullOrWhiteSpace(pinName))
                        {
                            AddParsedPin(def, mappedSection, pinName!, dataType);
                        }
                    }
                }
            }

            FinalizeParsedDefinition(def);
            results.Add(def);
        }

        return results;
    }

    public static List<AfMotherClassDefinition> BuildBuiltinStandardClasses()
    {
        return new List<AfMotherClassDefinition>
        {
            BuildBuiltinAxisMotion(),
            BuildBuiltinActuator2Pos(),
            BuildBuiltinGripper(),
            BuildBuiltinVisionSensor(),
        };
    }

    private static bool ScanLiveTiaLibraries(
        object? portal,
        object? project,
        object? plcSoftware,
        Dictionary<string, AfMotherClassDefinition> discovered,
        MotherClassRegistryPayload payload)
    {
        var scannedAny = false;
        var seen = new HashSet<int>();

        if (portal is not null)
        {
            var globalLibs = OpennessExport.GetProp(portal, "GlobalLibraries");
            if (globalLibs is IEnumerable libs && globalLibs is not string)
            {
                scannedAny = true;
                foreach (var lib in libs)
                {
                    if (lib is null) continue;
                    var libName = OpennessExport.GetPropString(lib, "Name") ?? "GlobalLibrary";
                    payload.ScannedLocations.Add($"tia://GlobalLibraries/{libName}");
                    ScanOpennessLibraryObject(lib, $"GlobalLibraries/{libName}", discovered, payload, seen);
                }
            }
        }

        if (project is not null)
        {
            var projLib = OpennessExport.GetProp(project, "ProjectLibrary");
            if (projLib is not null)
            {
                scannedAny = true;
                var libName = OpennessExport.GetPropString(projLib, "Name") ?? "ProjectLibrary";
                payload.ScannedLocations.Add($"tia://ProjectLibrary/{libName}");
                ScanOpennessLibraryObject(projLib, $"ProjectLibrary/{libName}", discovered, payload, seen);
            }
        }

        if (plcSoftware is not null)
        {
            var rootGroup = OpennessExport.GetProp(plcSoftware, "BlockGroup");
            if (rootGroup is not null)
            {
                scannedAny = true;
                payload.ScannedLocations.Add("tia://PlcSoftware/BlockGroup");
                foreach (var (block, rel) in OpennessExport.WalkGroups(rootGroup, new[] { "Blocks" }))
                {
                    var name = OpennessExport.GetPropString(block, "Name");
                    if (string.IsNullOrWhiteSpace(name) || !IsAfMotherBlockName(name!)) continue;
                    TryExtractFromOpennessItem(block, name!, $"PlcSoftware/BlockGroup/{rel}", discovered, payload);
                }
            }
        }

        return scannedAny;
    }

    private static void ScanOpennessLibraryObject(
        object library,
        string prefix,
        Dictionary<string, AfMotherClassDefinition> discovered,
        MotherClassRegistryPayload payload,
        HashSet<int> seen)
    {
        var mcFolder = OpennessExport.GetProp(library, "MasterCopyFolder");
        if (mcFolder is not null)
        {
            WalkLibraryFolder(mcFolder, "MasterCopies", prefix, discovered, payload, seen);
        }

        var typeFolder = OpennessExport.GetProp(library, "TypeFolder");
        if (typeFolder is not null)
        {
            WalkLibraryFolder(typeFolder, "Types", prefix, discovered, payload, seen);
        }
    }

    private static void WalkLibraryFolder(
        object folder,
        string itemProperty,
        string prefix,
        Dictionary<string, AfMotherClassDefinition> discovered,
        MotherClassRegistryPayload payload,
        HashSet<int> seen)
    {
        if (!seen.Add(RuntimeHelpers.GetHashCode(folder))) return;

        foreach (var item in OpennessExport.Enumerate(folder, itemProperty))
        {
            var name = OpennessExport.GetPropString(item, "Name") ?? "";
            var itemPath = $"{prefix}/{name}";

            if (IsAfMotherBlockName(name))
            {
                TryExtractFromOpennessItem(item, name, itemPath, discovered, payload);
            }

            // LibraryType objects expose Versions (check latest/default version as well).
            if (OpennessExport.GetProp(item, "Versions") is IEnumerable versions && versions is not string)
            {
                foreach (var ver in versions)
                {
                    if (ver is null) continue;
                    var verName = OpennessExport.GetPropString(ver, "Name") ?? name;
                    if (IsAfMotherBlockName(verName))
                    {
                        TryExtractFromOpennessItem(ver, verName, itemPath, discovered, payload);
                    }
                }
            }
        }

        foreach (var sub in OpennessExport.Enumerate(folder, "Folders"))
        {
            var subName = OpennessExport.GetPropString(sub, "Name") ?? "Folder";
            WalkLibraryFolder(sub, itemProperty, $"{prefix}/{subName}", discovered, payload, seen);
        }
    }

    private static void TryExtractFromOpennessItem(
        object item,
        string blockName,
        string sourcePath,
        Dictionary<string, AfMotherClassDefinition> discovered,
        MotherClassRegistryPayload payload)
    {
        // 1) Direct SCL property (supported by test doubles or custom wrappers).
        var directScl = OpennessExport.GetFirstProp(item, "SclSource", "SourceCode", "SourceText")?.ToString();
        if (!string.IsNullOrWhiteSpace(directScl))
        {
            var parsed = ParseSclContent(directScl!, sourcePath);
            if (parsed.Count > 0)
            {
                foreach (var def in parsed) discovered[def.DriverClass] = def;
                return;
            }
        }

        // 2) Try official GenerateSourceFromBlocks / Export into a temporary file.
        var tempDir = Path.Combine(Path.GetTempPath(), "af_studio_v5_lib_reflect");
        Directory.CreateDirectory(tempDir);
        var tempScl = Path.Combine(tempDir, $"{OpennessExport.Sanitize(blockName)}_{Guid.NewGuid():N}.scl");
        var tempXml = Path.Combine(tempDir, $"{OpennessExport.Sanitize(blockName)}_{Guid.NewGuid():N}.xml");
        try
        {
            var (genSkip, _) = OpennessMutate.TryGenerateSourceFromBlocks(item, tempScl);
            if (genSkip is null && File.Exists(tempScl))
            {
                var parsed = ParseSclContent(File.ReadAllText(tempScl), sourcePath);
                if (parsed.Count > 0)
                {
                    foreach (var def in parsed) discovered[def.DriverClass] = def;
                    return;
                }
            }

            if (OpennessExport.HasExport(item))
            {
                var expSkip = OpennessExport.TryExport(item, tempXml);
                if (expSkip is null && File.Exists(tempXml))
                {
                    var parsed = ParseSimaticXmlContent(File.ReadAllText(tempXml), sourcePath);
                    if (parsed.Count > 0)
                    {
                        foreach (var def in parsed) discovered[def.DriverClass] = def;
                        return;
                    }
                }
            }
        }
        catch (Exception ex)
        {
            payload.Warnings.Add($"Reflection export skipped for '{blockName}': {OpennessExport.Unwrap(ex).Message}");
        }
        finally
        {
            try { if (File.Exists(tempScl)) File.Delete(tempScl); } catch { /* ignore */ }
            try { if (File.Exists(tempXml)) File.Delete(tempXml); } catch { /* ignore */ }
        }

        // 3) Direct Parameters / Pins reflection property.
        var defFromProps = TryExtractFromReflectedMembers(item, blockName, sourcePath);
        if (defFromProps is not null)
        {
            discovered[defFromProps.DriverClass] = defFromProps;
            return;
        }

        // 4) Recognized FB_AF_* symbol in TIA library without exportable body (e.g. Know-How protected MasterCopy).
        var fallback = CreateBaseDefinition(blockName, sourcePath);
        FinalizeParsedDefinition(fallback);
        payload.Warnings.Add($"Discovered '{blockName}' at '{sourcePath}' without exportable source; enriched with standard AF metadata.");
        discovered[fallback.DriverClass] = fallback;
    }

    private static AfMotherClassDefinition? TryExtractFromReflectedMembers(
        object item,
        string blockName,
        string sourcePath)
    {
        var pinsProp = OpennessExport.GetFirstProp(item, "Parameters", "Pins", "InterfaceMembers");
        if (pinsProp is not IEnumerable pinList || pinsProp is string) return null;

        var def = CreateBaseDefinition(blockName, sourcePath);
        var count = 0;
        foreach (var pin in pinList)
        {
            if (pin is null) continue;
            var name = OpennessExport.GetPropString(pin, "Name");
            if (string.IsNullOrWhiteSpace(name)) continue;

            var section = OpennessExport.GetFirstProp(pin, "Section", "Direction")?.ToString() ?? "VAR_INPUT";
            var dataType = OpennessExport.GetFirstProp(pin, "DataType", "Datatype")?.ToString() ?? "Bool";
            var normalizedSec = section.ToUpperInvariant() switch
            {
                "IN" or "INPUT" or "VAR_INPUT" => "VAR_INPUT",
                "OUT" or "OUTPUT" or "VAR_OUTPUT" => "VAR_OUTPUT",
                "INOUT" or "IN_OUT" or "VAR_IN_OUT" => "VAR_IN_OUT",
                _ => "VAR_INPUT",
            };
            AddParsedPin(def, normalizedSec, name!, dataType);
            count++;
        }

        if (count == 0) return null;
        FinalizeParsedDefinition(def);
        return def;
    }

    private static void ScanOfflineDirectory(
        string directory,
        Dictionary<string, AfMotherClassDefinition> discovered,
        MotherClassRegistryPayload payload)
    {
        payload.ScannedLocations.Add(directory);

        foreach (var sclFile in Directory.EnumerateFiles(directory, "*.scl", SearchOption.AllDirectories)
                     .OrderBy(p => p, StringComparer.OrdinalIgnoreCase))
        {
            try
            {
                var content = File.ReadAllText(sclFile);
                foreach (var def in ParseSclContent(content, sclFile))
                {
                    discovered[def.DriverClass] = def;
                }
            }
            catch (Exception ex)
            {
                payload.Warnings.Add($"Failed parsing SCL '{sclFile}': {ex.Message}");
            }
        }

        foreach (var xmlFile in Directory.EnumerateFiles(directory, "*.xml", SearchOption.AllDirectories)
                     .OrderBy(p => p, StringComparer.OrdinalIgnoreCase))
        {
            try
            {
                var content = File.ReadAllText(xmlFile);
                foreach (var def in ParseSimaticXmlContent(content, xmlFile))
                {
                    discovered[def.DriverClass] = def;
                }
            }
            catch (Exception ex)
            {
                payload.Warnings.Add($"Failed parsing SimaticML XML '{xmlFile}': {ex.Message}");
            }
        }
    }

    private static bool IsAfMotherBlockName(string name) =>
        name.Trim().StartsWith("FB_AF_", StringComparison.OrdinalIgnoreCase);

    private static AfMotherClassDefinition CreateBaseDefinition(string fbName, string? sourcePath)
    {
        var builtin = BuildBuiltinStandardClasses()
            .FirstOrDefault(c => string.Equals(c.DriverClass, fbName.Trim(), StringComparison.OrdinalIgnoreCase));

        return new AfMotherClassDefinition
        {
            DriverClass = fbName.Trim(),
            Title = builtin?.Title ?? fbName.Trim(),
            Category = builtin?.Category ?? InferCategory(fbName),
            InitialHomeState = builtin?.InitialHomeState ?? "AtHome",
            DefaultStates = builtin is not null
                ? new List<string>(builtin.DefaultStates)
                : new List<string> { "AtHome", "AtWork", "Error" },
            RadialMethods = builtin is not null
                ? builtin.RadialMethods.Select(CloneMethod).ToList()
                : new List<AfRadialMethodSpec>
                {
                    new()
                    {
                        MethodId = "ExecuteWork",
                        ActionLabel = "执行动作",
                        TargetDiscreteState = "AtWork",
                        SclTemplate = "#{instanceDb}.i_bExecute := TRUE;",
                        WaitPredicateTemplate = "#{instanceDb}.q_bDone",
                    },
                    new()
                    {
                        MethodId = "ReturnHome",
                        ActionLabel = "回安全原位",
                        TargetDiscreteState = "AtHome",
                        SclTemplate = "#{instanceDb}.i_bHomeReq := TRUE;",
                        WaitPredicateTemplate = "#{instanceDb}.q_bAtHome",
                    },
                },
            SourcePath = sourcePath,
        };
    }

    private static void AddParsedPin(
        AfMotherClassDefinition def,
        string section,
        string pinName,
        string dataType)
    {
        var portType = ClassifyPortType(pinName, section);
        var portId = MapSemanticPortId(pinName, section, portType);

        var spec = new AfLibraryPortSpec
        {
            Id = portId,
            Label = pinName,
            Type = portType,
            DataType = dataType,
            PinName = pinName,
            Direction = section switch
            {
                "VAR_OUTPUT" => "OUT",
                "VAR_IN_OUT" => "IN_OUT",
                _ => "IN",
            },
        };

        if (string.Equals(section, "VAR_OUTPUT", StringComparison.OrdinalIgnoreCase))
        {
            def.OutPorts.Add(spec);
        }
        else
        {
            def.InPorts.Add(spec);
        }
    }

    private static void FinalizeParsedDefinition(AfMotherClassDefinition def)
    {
        var builtin = BuildBuiltinStandardClasses()
            .FirstOrDefault(c => string.Equals(c.DriverClass, def.DriverClass, StringComparison.OrdinalIgnoreCase));
        if (builtin is not null)
        {
            if (def.InPorts.Count == 0) def.InPorts = builtin.InPorts.Select(ClonePort).ToList();
            if (def.OutPorts.Count == 0) def.OutPorts = builtin.OutPorts.Select(ClonePort).ToList();
        }
    }

    private static string ClassifyPortType(string pinName, string section)
    {
        if (pinName.IndexOf("Interlock", StringComparison.OrdinalIgnoreCase) >= 0 ||
            pinName.IndexOf("Guard", StringComparison.OrdinalIgnoreCase) >= 0 ||
            pinName.IndexOf("AtHome", StringComparison.OrdinalIgnoreCase) >= 0 ||
            pinName.IndexOf("Safe", StringComparison.OrdinalIgnoreCase) >= 0 ||
            pinName.IndexOf("Opened", StringComparison.OrdinalIgnoreCase) >= 0 ||
            pinName.IndexOf("Holding", StringComparison.OrdinalIgnoreCase) >= 0)
        {
            return "GUARD";
        }

        if (pinName.IndexOf("Diag", StringComparison.OrdinalIgnoreCase) >= 0 ||
            pinName.IndexOf("Error", StringComparison.OrdinalIgnoreCase) >= 0 ||
            pinName.IndexOf("Di", StringComparison.OrdinalIgnoreCase) >= 0 ||
            pinName.IndexOf("PartPresent", StringComparison.OrdinalIgnoreCase) >= 0)
        {
            return "STATUS";
        }

        if (pinName.IndexOf("Pos", StringComparison.OrdinalIgnoreCase) >= 0 ||
            pinName.IndexOf("Speed", StringComparison.OrdinalIgnoreCase) >= 0 ||
            pinName.IndexOf("Timeout", StringComparison.OrdinalIgnoreCase) >= 0)
        {
            return section == "VAR_INPUT" ? "PARAM" : "STATUS";
        }

        return "SEQ";
    }

    private static string MapSemanticPortId(string pinName, string section, string portType)
    {
        if (portType == "GUARD" && section == "VAR_INPUT") return "IN_GUARD";
        if (portType == "GUARD" && section == "VAR_OUTPUT") return "OUT_AT_HOME";
        var cleaned = Regex.Replace(pinName, @"^(?:i|q|iq)_[a-z]?", "", RegexOptions.IgnoreCase);
        if (string.IsNullOrWhiteSpace(cleaned)) cleaned = pinName;
        var prefix = section == "VAR_OUTPUT" ? "OUT_" : "IN_";
        return prefix + Regex.Replace(cleaned, @"[^A-Za-z0-9]+", "_").Trim('_').ToUpperInvariant();
    }

    private static string InferCategory(string fbName)
    {
        if (fbName.IndexOf("Axis", StringComparison.OrdinalIgnoreCase) >= 0) return "MOTION_AXIS";
        if (fbName.IndexOf("Gripper", StringComparison.OrdinalIgnoreCase) >= 0) return "GRIPPER";
        if (fbName.IndexOf("Vision", StringComparison.OrdinalIgnoreCase) >= 0) return "VISION_SENSOR";
        if (fbName.IndexOf("Actuator", StringComparison.OrdinalIgnoreCase) >= 0) return "TWO_POS_ACTUATOR";
        return "CUSTOM_AF_DRIVER";
    }

    private static string CollapseWhitespace(string value) =>
        Regex.Replace((value ?? "").Trim(), @"\s+", " ");

    private static List<AfMotherClassDefinition> OrderClasses(IEnumerable<AfMotherClassDefinition> items) =>
        items.OrderBy(c => c.DriverClass, StringComparer.OrdinalIgnoreCase).ToList();

    private static AfLibraryPortSpec ClonePort(AfLibraryPortSpec p) => new()
    {
        Id = p.Id,
        Label = p.Label,
        Type = p.Type,
        DataType = p.DataType,
        PinName = p.PinName,
        Direction = p.Direction,
    };

    private static AfRadialMethodSpec CloneMethod(AfRadialMethodSpec m) => new()
    {
        MethodId = m.MethodId,
        ActionLabel = m.ActionLabel,
        TargetDiscreteState = m.TargetDiscreteState,
        SclTemplate = m.SclTemplate,
        WaitPredicateTemplate = m.WaitPredicateTemplate,
    };

    private static AfMotherClassDefinition BuildBuiltinAxisMotion() => new()
    {
        DriverClass = "FB_AF_AxisMotion",
        Title = "伺服运动轴 (Standard AF Axis)",
        Category = "MOTION_AXIS",
        InitialHomeState = "Pos_Home_0",
        DefaultStates = new List<string> { "Pos_Home_0", "Pos_Pick_120", "Pos_Press_245" },
        InPorts = new List<AfLibraryPortSpec>
        {
            new() { Id = "IN_SEQ", Label = "步序触发", Type = "SEQ", DataType = "Bool", PinName = "i_bExecute", Direction = "IN" },
            new() { Id = "IN_GUARD", Label = "安全互锁", Type = "GUARD", DataType = "Bool", PinName = "i_bInterlockOK", Direction = "IN" },
            new() { Id = "IN_TARGET_POS", Label = "目标位置", Type = "PARAM", DataType = "Real", PinName = "i_rTargetPos", Direction = "IN" },
            new() { Id = "IN_HOME_REQ", Label = "回原位请求", Type = "SEQ", DataType = "Bool", PinName = "i_bHomeReq", Direction = "IN" },
        },
        OutPorts = new List<AfLibraryPortSpec>
        {
            new() { Id = "OUT_DONE", Label = "定位完成", Type = "SEQ", DataType = "Bool", PinName = "q_bDone", Direction = "OUT" },
            new() { Id = "OUT_AT_HOME", Label = "原位安全位", Type = "GUARD", DataType = "Bool", PinName = "q_bAtHome", Direction = "OUT" },
            new() { Id = "OUT_DIAG", Label = "轴诊断字", Type = "STATUS", DataType = "Word", PinName = "q_wDiagCode", Direction = "OUT" },
        },
        RadialMethods = new List<AfRadialMethodSpec>
        {
            new()
            {
                MethodId = "MoveHome",
                ActionLabel = "回安全原位 (0mm)",
                TargetDiscreteState = "Pos_Home_0",
                SclTemplate = "\"#{instanceDb}\"(i_bHomeReq := TRUE, i_rTargetPos := 0.0);",
                WaitPredicateTemplate = "\"#{instanceDb}\".q_bAtHome",
            },
            new()
            {
                MethodId = "MovePick",
                ActionLabel = "移至取料位 (120mm)",
                TargetDiscreteState = "Pos_Pick_120",
                SclTemplate = "\"#{instanceDb}\"(i_bExecute := TRUE, i_rTargetPos := 120.0);",
                WaitPredicateTemplate = "\"#{instanceDb}\".q_bDone",
            },
            new()
            {
                MethodId = "MovePress",
                ActionLabel = "移至压装位 (245mm)",
                TargetDiscreteState = "Pos_Press_245",
                SclTemplate = "\"#{instanceDb}\"(i_bExecute := TRUE, i_rTargetPos := 245.0);",
                WaitPredicateTemplate = "\"#{instanceDb}\".q_bDone",
            },
            new()
            {
                MethodId = "SetSafetyGuard",
                ActionLabel = "设为永久防撞护栏",
                TargetDiscreteState = "Pos_Home_0",
                SclTemplate = "\"#{instanceDb}\".i_bInterlockOK := #{guardExpr};",
                WaitPredicateTemplate = "\"#{instanceDb}\".q_bAtHome",
            },
        },
    };

    private static AfMotherClassDefinition BuildBuiltinActuator2Pos() => new()
    {
        DriverClass = "FB_AF_Actuator2Pos",
        Title = "两位执行器 / 气缸 (Standard AF 2-Pos Actuator)",
        Category = "TWO_POS_ACTUATOR",
        InitialHomeState = "AtHome",
        DefaultStates = new List<string> { "AtHome", "AtWork" },
        InPorts = new List<AfLibraryPortSpec>
        {
            new() { Id = "IN_SEQ", Label = "步序伸出", Type = "SEQ", DataType = "Bool", PinName = "i_bWorkCmd", Direction = "IN" },
            new() { Id = "IN_HOME_CMD", Label = "步序缩回", Type = "SEQ", DataType = "Bool", PinName = "i_bHomeCmd", Direction = "IN" },
            new() { Id = "IN_GUARD", Label = "安全互锁", Type = "GUARD", DataType = "Bool", PinName = "i_bInterlockOK", Direction = "IN" },
            new() { Id = "IN_DI_HOME", Label = "原位磁开关", Type = "STATUS", DataType = "Bool", PinName = "i_bDiHome", Direction = "IN" },
            new() { Id = "IN_DI_WORK", Label = "动点磁开关", Type = "STATUS", DataType = "Bool", PinName = "i_bDiWork", Direction = "IN" },
        },
        OutPorts = new List<AfLibraryPortSpec>
        {
            new() { Id = "OUT_AT_WORK", Label = "动点到位", Type = "SEQ", DataType = "Bool", PinName = "q_bAtWork", Direction = "OUT" },
            new() { Id = "OUT_AT_HOME", Label = "原位安全位", Type = "GUARD", DataType = "Bool", PinName = "q_bAtHome", Direction = "OUT" },
            new() { Id = "OUT_DO_WORK", Label = "工作电磁阀", Type = "STATUS", DataType = "Bool", PinName = "q_bDoWork", Direction = "OUT" },
            new() { Id = "OUT_DIAG", Label = "超时诊断字", Type = "STATUS", DataType = "Word", PinName = "q_wDiagCode", Direction = "OUT" },
        },
        RadialMethods = new List<AfRadialMethodSpec>
        {
            new()
            {
                MethodId = "ExtendWork",
                ActionLabel = "伸出至工作位",
                TargetDiscreteState = "AtWork",
                SclTemplate = "\"#{instanceDb}\"(i_bWorkCmd := TRUE, i_bHomeCmd := FALSE);",
                WaitPredicateTemplate = "\"#{instanceDb}\".q_bAtWork",
            },
            new()
            {
                MethodId = "RetractHome",
                ActionLabel = "缩回至安全原位",
                TargetDiscreteState = "AtHome",
                SclTemplate = "\"#{instanceDb}\"(i_bWorkCmd := FALSE, i_bHomeCmd := TRUE);",
                WaitPredicateTemplate = "\"#{instanceDb}\".q_bAtHome",
            },
            new()
            {
                MethodId = "SetSafetyGuard",
                ActionLabel = "设为永久防撞护栏",
                TargetDiscreteState = "AtHome",
                SclTemplate = "\"#{instanceDb}\".i_bInterlockOK := #{guardExpr};",
                WaitPredicateTemplate = "\"#{instanceDb}\".q_bAtHome",
            },
        },
    };

    private static AfMotherClassDefinition BuildBuiltinGripper() => new()
    {
        DriverClass = "FB_AF_Gripper",
        Title = "伺服/气动夹爪 (Standard AF Gripper)",
        Category = "GRIPPER",
        InitialHomeState = "Opened",
        DefaultStates = new List<string> { "Opened", "Clamped", "HoldingPart" },
        InPorts = new List<AfLibraryPortSpec>
        {
            new() { Id = "IN_SEQ", Label = "夹紧触发", Type = "SEQ", DataType = "Bool", PinName = "i_bClampCmd", Direction = "IN" },
            new() { Id = "IN_OPEN_CMD", Label = "松开触发", Type = "SEQ", DataType = "Bool", PinName = "i_bOpenCmd", Direction = "IN" },
            new() { Id = "IN_GUARD", Label = "安全互锁", Type = "GUARD", DataType = "Bool", PinName = "i_bInterlockOK", Direction = "IN" },
            new() { Id = "IN_PART_PRESENT", Label = "带料检测", Type = "STATUS", DataType = "Bool", PinName = "i_bPartPresent", Direction = "IN" },
        },
        OutPorts = new List<AfLibraryPortSpec>
        {
            new() { Id = "OUT_CLAMPED", Label = "夹紧到位", Type = "SEQ", DataType = "Bool", PinName = "q_bClamped", Direction = "OUT" },
            new() { Id = "OUT_OPENED", Label = "松开原位", Type = "GUARD", DataType = "Bool", PinName = "q_bOpened", Direction = "OUT" },
            new() { Id = "OUT_HOLDING", Label = "带料保持中", Type = "GUARD", DataType = "Bool", PinName = "q_bHoldingPart", Direction = "OUT" },
            new() { Id = "OUT_DIAG", Label = "夹爪诊断字", Type = "STATUS", DataType = "Word", PinName = "q_wDiagCode", Direction = "OUT" },
        },
        RadialMethods = new List<AfRadialMethodSpec>
        {
            new()
            {
                MethodId = "ClampGrip",
                ActionLabel = "夹紧工件",
                TargetDiscreteState = "Clamped",
                SclTemplate = "\"#{instanceDb}\"(i_bClampCmd := TRUE, i_bOpenCmd := FALSE);",
                WaitPredicateTemplate = "\"#{instanceDb}\".q_bClamped",
            },
            new()
            {
                MethodId = "OpenGrip",
                ActionLabel = "安全松开夹爪",
                TargetDiscreteState = "Opened",
                SclTemplate = "\"#{instanceDb}\"(i_bClampCmd := FALSE, i_bOpenCmd := TRUE);",
                WaitPredicateTemplate = "\"#{instanceDb}\".q_bOpened",
            },
            new()
            {
                MethodId = "MaintainGrip",
                ActionLabel = "带料保压保持",
                TargetDiscreteState = "HoldingPart",
                SclTemplate = "IF \"#{instanceDb}\".i_bPartPresent THEN \"#{instanceDb}\".i_bClampCmd := TRUE; END_IF;",
                WaitPredicateTemplate = "\"#{instanceDb}\".q_bHoldingPart",
            },
            new()
            {
                MethodId = "SetSafetyGuard",
                ActionLabel = "设为永久防撞护栏",
                TargetDiscreteState = "Opened",
                SclTemplate = "\"#{instanceDb}\".i_bInterlockOK := #{guardExpr};",
                WaitPredicateTemplate = "\"#{instanceDb}\".q_bOpened",
            },
        },
    };

    private static AfMotherClassDefinition BuildBuiltinVisionSensor() => new()
    {
        DriverClass = "FB_AF_VisionSensor",
        Title = "视觉检测传感器 (Standard AF Vision)",
        Category = "VISION_SENSOR",
        InitialHomeState = "Idle",
        DefaultStates = new List<string> { "Idle", "Pass_OK", "Reject_NG" },
        InPorts = new List<AfLibraryPortSpec>
        {
            new() { Id = "IN_SEQ", Label = "拍照触发", Type = "SEQ", DataType = "Bool", PinName = "i_bTrigger", Direction = "IN" },
            new() { Id = "IN_GUARD", Label = "触发互锁", Type = "GUARD", DataType = "Bool", PinName = "i_bInterlockOK", Direction = "IN" },
        },
        OutPorts = new List<AfLibraryPortSpec>
        {
            new() { Id = "OUT_OK", Label = "检测合格 (OK)", Type = "SEQ", DataType = "Bool", PinName = "q_bResultOk", Direction = "OUT" },
            new() { Id = "OUT_NG", Label = "检测不良 (NG)", Type = "SEQ", DataType = "Bool", PinName = "q_bResultNg", Direction = "OUT" },
            new() { Id = "OUT_READY", Label = "传感器就绪", Type = "GUARD", DataType = "Bool", PinName = "q_bReady", Direction = "OUT" },
        },
        RadialMethods = new List<AfRadialMethodSpec>
        {
            new()
            {
                MethodId = "TriggerInspect",
                ActionLabel = "触发拍照检测 (OK分支)",
                TargetDiscreteState = "Pass_OK",
                SclTemplate = "\"#{instanceDb}\"(i_bTrigger := TRUE);",
                WaitPredicateTemplate = "\"#{instanceDb}\".q_bResultOk",
            },
            new()
            {
                MethodId = "BranchNg",
                ActionLabel = "不良品 NG 抛料分支",
                TargetDiscreteState = "Reject_NG",
                SclTemplate = "\"#{instanceDb}\"(i_bTrigger := TRUE);",
                WaitPredicateTemplate = "\"#{instanceDb}\".q_bResultNg",
            },
        },
    };
}

public sealed class AfLibraryReflectRequest
{
    [JsonPropertyName("libraryDirectory")]
    public string? LibraryDirectory { get; set; }

    [JsonPropertyName("globalLibraryPath")]
    public string? GlobalLibraryPath { get; set; }

    [JsonPropertyName("includeBuiltinFallback")]
    public bool IncludeBuiltinFallback { get; set; } = true;

    public static AfLibraryReflectRequest FromJson(JsonElement root)
    {
        var req = new AfLibraryReflectRequest
        {
            LibraryDirectory = GetString(root, "libraryDirectory")
                ?? GetString(root, "libraryDir")
                ?? GetString(root, "dir"),
            GlobalLibraryPath = GetString(root, "globalLibraryPath")
                ?? GetString(root, "library")
                ?? GetString(root, "libraryPath"),
            IncludeBuiltinFallback = GetBool(root, "includeBuiltinFallback") ?? true,
        };
        return req;
    }

    private static string? GetString(JsonElement root, string name) =>
        root.TryGetProperty(name, out var el) && el.ValueKind == JsonValueKind.String ? el.GetString() : null;

    private static bool? GetBool(JsonElement root, string name)
    {
        if (!root.TryGetProperty(name, out var el)) return null;
        return el.ValueKind switch
        {
            JsonValueKind.True => true,
            JsonValueKind.False => false,
            JsonValueKind.String when bool.TryParse(el.GetString(), out var b) => b,
            _ => null,
        };
    }
}

public sealed class AfLibraryPortSpec
{
    [JsonPropertyName("id")]
    public string Id { get; set; } = "";

    [JsonPropertyName("label")]
    public string Label { get; set; } = "";

    [JsonPropertyName("type")]
    public string Type { get; set; } = "SEQ";

    [JsonPropertyName("dataType")]
    public string DataType { get; set; } = "Bool";

    [JsonPropertyName("pinName")]
    public string PinName { get; set; } = "";

    [JsonPropertyName("direction")]
    public string Direction { get; set; } = "IN";
}

public sealed class AfRadialMethodSpec
{
    [JsonPropertyName("methodId")]
    public string MethodId { get; set; } = "";

    [JsonPropertyName("actionLabel")]
    public string ActionLabel { get; set; } = "";

    [JsonPropertyName("targetDiscreteState")]
    public string TargetDiscreteState { get; set; } = "";

    [JsonPropertyName("sclTemplate")]
    public string SclTemplate { get; set; } = "";

    [JsonPropertyName("waitPredicateTemplate")]
    public string WaitPredicateTemplate { get; set; } = "";
}

public sealed class AfMotherClassDefinition
{
    [JsonPropertyName("driverClass")]
    public string DriverClass { get; set; } = "";

    [JsonPropertyName("title")]
    public string Title { get; set; } = "";

    [JsonPropertyName("category")]
    public string Category { get; set; } = "";

    [JsonPropertyName("initialHomeState")]
    public string InitialHomeState { get; set; } = "AtHome";

    [JsonPropertyName("defaultStates")]
    public List<string> DefaultStates { get; set; } = new();

    [JsonPropertyName("inPorts")]
    public List<AfLibraryPortSpec> InPorts { get; set; } = new();

    [JsonPropertyName("outPorts")]
    public List<AfLibraryPortSpec> OutPorts { get; set; } = new();

    [JsonPropertyName("radialMethods")]
    public List<AfRadialMethodSpec> RadialMethods { get; set; } = new();

    [JsonPropertyName("sourcePath")]
    public string? SourcePath { get; set; }
}

public sealed class MotherClassRegistryPayload
{
    [JsonPropertyName("ok")]
    public bool Ok { get; set; } = true;

    [JsonPropertyName("source")]
    public string Source { get; set; } = "builtin_af_standard";

    [JsonPropertyName("evidenceLevel")]
    public string EvidenceLevel { get; set; } = "offline";

    [JsonPropertyName("generatedAtUtc")]
    public string GeneratedAtUtc { get; set; } = "";

    [JsonPropertyName("scannedLocations")]
    public List<string> ScannedLocations { get; set; } = new();

    [JsonPropertyName("warnings")]
    public List<string> Warnings { get; set; } = new();

    [JsonPropertyName("classes")]
    public List<AfMotherClassDefinition> Classes { get; set; } = new();

    [JsonPropertyName("error")]
    public ToolError? Error { get; set; }
}

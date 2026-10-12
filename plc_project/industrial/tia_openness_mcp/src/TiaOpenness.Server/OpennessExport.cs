using System.Collections;
using System.Reflection;
using System.Text.RegularExpressions;

namespace TiaOpenness.Server;

/// <summary>
/// Reflection helpers for TIA Openness Export (chapter 6). V17–V20 assemblies differ;
/// never hard-crash the job when a member or Export method is missing.
/// </summary>
public static class OpennessExport
{
    public const string CatBlocks = "blocks";
    public const string CatTypes = "types";
    public const string CatTags = "tags";
    public const string CatWatch = "watch";
    public const string CatForce = "force";
    public const string CatTo = "to";
    public const string CatAlarms = "alarms";
    public const string CatCfc = "cfc";
    public const string CatSafety = "safety";
    public const string CatHardware = "hardware";
    public const string CatHmi = "hmi";
    public const string CatOpcua = "opcua";
    public const string CatProject = "project";

    public static readonly string[] OfficialCategories =
    {
        CatBlocks, CatTypes, CatTags, CatWatch, CatForce, CatTo, CatAlarms,
        CatCfc, CatSafety, CatHardware, CatHmi, CatOpcua, CatProject,
    };

    public static string Sanitize(string name) =>
        Regex.Replace(name ?? "", @"[\\/:*?""<>|]", "_");

    public static object? GetProp(object? obj, string name)
    {
        if (obj is null || string.IsNullOrEmpty(name)) return null;
        try
        {
            return obj.GetType().GetProperty(name, BindingFlags.Public | BindingFlags.Instance)?.GetValue(obj);
        }
        catch
        {
            return null;
        }
    }

    /// <summary>First non-null public instance property among candidate names (V17–V20 aliases).</summary>
    public static object? GetFirstProp(object? obj, params string[] names)
    {
        if (obj is null || names is null) return null;
        foreach (var name in names)
        {
            var value = GetProp(obj, name);
            if (value is not null) return value;
        }
        return null;
    }

    public static string? GetPropString(object? obj, string name) =>
        GetProp(obj, name)?.ToString();

    public static bool IsTruthy(object? val)
    {
        if (val is null) return false;
        if (val is bool b) return b;
        var t = val.ToString() ?? "";
        return t.Equals("True", StringComparison.OrdinalIgnoreCase)
            || t.Equals("1", StringComparison.OrdinalIgnoreCase)
            || t.Equals("Yes", StringComparison.OrdinalIgnoreCase);
    }

    public static IEnumerable<object> Enumerate(object? obj, params string[] propertyNames)
    {
        if (obj is null) yield break;
        foreach (var name in propertyNames)
        {
            object? value;
            try { value = GetProp(obj, name); }
            catch { continue; }
            if (value is IEnumerable seq and not string)
            {
                foreach (var item in seq)
                {
                    if (item is not null) yield return item;
                }
            }
        }
    }

    /// <summary>Walk a user-group tree: item compositions + nested Groups.</summary>
    public static IEnumerable<(object Item, string Relative)> WalkGroups(
        object? group,
        string[] itemProperties,
        string relative = "",
        string groupProperty = "Groups")
    {
        if (group is null) yield break;
        foreach (var item in Enumerate(group, itemProperties))
        {
            var name = GetPropString(item, "Name") ?? "item";
            var rel = string.IsNullOrEmpty(relative) ? name : relative + "/" + name;
            yield return (item, rel);
        }

        foreach (var child in Enumerate(group, groupProperty))
        {
            var name = GetPropString(child, "Name") ?? "Group";
            var childRel = string.IsNullOrEmpty(relative) ? name : relative + "/" + name;
            foreach (var nested in WalkGroups(child, itemProperties, childRel, groupProperty))
            {
                yield return nested;
            }
        }
    }

    public static MethodInfo? FindExportMethod(object item)
    {
        if (item is null) return null;
        try
        {
            return item.GetType().GetMethods(BindingFlags.Public | BindingFlags.Instance)
                .FirstOrDefault(m =>
                    m.Name == "Export" &&
                    m.GetParameters().Length == 2);
        }
        catch
        {
            return null;
        }
    }

    public static bool HasExport(object item) => FindExportMethod(item) is not null;

    /// <summary>
    /// Invoke Export(FileInfo, ExportOptions.WithDefaults) when present.
    /// Returns skip reason: null on success.
    /// </summary>
    public static string? TryExport(object item, string outPath)
    {
        try
        {
            var export = FindExportMethod(item);
            if (export is null) return "no_export";

            var dir = Path.GetDirectoryName(outPath);
            if (!string.IsNullOrEmpty(dir)) Directory.CreateDirectory(dir);

            var exportOptionsType = item.GetType().Assembly.GetType("Siemens.Engineering.ExportOptions")
                ?? Type.GetType("Siemens.Engineering.ExportOptions, Siemens.Engineering");
            if (exportOptionsType is null) return "no_export";

            object withDefaults;
            try
            {
                withDefaults = Enum.Parse(exportOptionsType, "WithDefaults");
            }
            catch (ArgumentException)
            {
                withDefaults = Enum.GetValues(exportOptionsType).GetValue(0)!;
            }

            var fileInfoType = export.GetParameters()[0].ParameterType;
            var fileInfo = Activator.CreateInstance(fileInfoType, outPath)!;
            export.Invoke(item, new[] { fileInfo, withDefaults });
            return null;
        }
        catch (Exception ex)
        {
            return ClassifySkipReason(Unwrap(ex).Message, item);
        }
    }

    public static string ClassifySkipReason(string message, object? item = null)
    {
        var t = message ?? "";
        if (t.IndexOf("license", StringComparison.OrdinalIgnoreCase) >= 0)
            return "no_license";
        if (t.IndexOf("inconsistent", StringComparison.OrdinalIgnoreCase) >= 0
            || t.IndexOf("IsConsistent=false", StringComparison.OrdinalIgnoreCase) >= 0)
            return "inconsistent";
        if (t.IndexOf("know-how", StringComparison.OrdinalIgnoreCase) >= 0
            || t.IndexOf("knowhow", StringComparison.OrdinalIgnoreCase) >= 0)
            return "know_how";
        if (t.IndexOf("password", StringComparison.OrdinalIgnoreCase) >= 0)
            return "password_protected";
        if (t.IndexOf("safety", StringComparison.OrdinalIgnoreCase) >= 0
            && t.IndexOf("login", StringComparison.OrdinalIgnoreCase) >= 0)
            return "safety_login";
        if (item is not null && !HasExport(item))
            return "no_export";
        if (t.IndexOf("Import", StringComparison.OrdinalIgnoreCase) >= 0
            && t.IndexOf("not found", StringComparison.OrdinalIgnoreCase) >= 0)
            return "no_import";
        if (t.IndexOf("Export", StringComparison.OrdinalIgnoreCase) >= 0
            && t.IndexOf("not found", StringComparison.OrdinalIgnoreCase) >= 0)
            return "no_export";
        return "openness_error";
    }

    public static Exception Unwrap(Exception ex) =>
        ex is TargetInvocationException { InnerException: { } inner } ? inner : ex;

    /// <summary>Official SimaticML / AML category from CLR type or object name (chapter 6).</summary>
    public static string MapExportCategory(string? clrTypeName, string? objectName = null)
    {
        var t = clrTypeName ?? "";
        var n = objectName ?? "";
        if (Contains(t, "WatchTable") || Contains(n, "WatchTable")) return CatWatch;
        if (Contains(t, "ForceTable") || Contains(n, "ForceTable")) return CatForce;
        if (Contains(t, "TagTable") || Contains(t, "ConstantTable")) return CatTags;
        if (Contains(t, "PlcStruct") || Contains(t, "PlcType") || Contains(t, "DataType")
            || Contains(t, "TypeTable") || t.IndexOf("UDT", StringComparison.OrdinalIgnoreCase) >= 0)
            return CatTypes;
        if (Contains(t, "Technological") || Contains(t, "TechnologyObject") || Contains(t, "TO_"))
            return CatTo;
        if (Contains(t, "Alarm") || Contains(t, "ProDiag") || Contains(t, "Supervision"))
            return CatAlarms;
        if (Contains(t, "Chart") && (Contains(t, "Cfc") || Contains(t, "CFC")))
            return CatCfc;
        if (Contains(t, "Safety") || Contains(t, "Failsafe") || Contains(t, "SafetyUnit"))
            return CatSafety;
        if (Contains(t, "OpcUa") || Contains(t, "OPCUA"))
            return CatOpcua;
        if (Contains(t, "Hmi") || Contains(t, "HMI") || Contains(t, "Screen") || Contains(t, "Faceplate"))
            return CatHmi;
        if (Contains(t, "OrganizationBlock") || Contains(t, "FunctionBlock")
            || (Contains(t, "Function") && !Contains(t, "FunctionBlock"))
            || Contains(t, "DataBlock") || Contains(t, "PlcBlock")
            || Contains(t, "GlobalDB") || Contains(t, "InstanceDB") || Contains(t, "ArrayDB"))
            return CatBlocks;
        return "other";
    }

    public static string FolderForCategory(string category) => category switch
    {
        CatBlocks => "blocks",
        CatTypes => "types",
        CatTags => "tags",
        CatWatch => "watch",
        CatForce => "force",
        CatTo => "to",
        CatAlarms => "alarms",
        CatCfc => "cfc",
        CatSafety => "safety",
        CatHardware => "hardware",
        CatHmi => "hmi",
        CatOpcua => "opcua",
        CatProject => "project",
        _ => category,
    };

    public static bool LooksFailsafe(object? item)
    {
        if (item is null) return false;
        foreach (var name in new[]
                 {
                     "IsFailsafe", "Failsafe", "IsSafety", "Safety", "FailsafeEnabled",
                 })
        {
            if (IsTruthy(GetProp(item, name))) return true;
        }
        var typeId = GetPropString(item, "TypeIdentifier") ?? "";
        var nameStr = GetPropString(item, "Name") ?? "";
        return typeId.IndexOf("F-CPU", StringComparison.OrdinalIgnoreCase) >= 0
            || typeId.IndexOf("Failsafe", StringComparison.OrdinalIgnoreCase) >= 0
            || nameStr.StartsWith("F-", StringComparison.OrdinalIgnoreCase);
    }

    private static bool Contains(string haystack, string needle) =>
        haystack.IndexOf(needle, StringComparison.OrdinalIgnoreCase) >= 0;
}

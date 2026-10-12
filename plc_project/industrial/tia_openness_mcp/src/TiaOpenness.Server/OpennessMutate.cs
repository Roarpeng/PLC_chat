using System.Collections;
using System.Reflection;
using TiaOpenness.Models;

namespace TiaOpenness.Server;

/// <summary>
/// Reflection helpers for official Openness write APIs (Import / Retrieve / Create / Close /
/// GenerateSourceFromBlocks). Never invent a method name: missing members fail closed
/// with <c>no_import</c> / <c>dependency_unavailable</c>.
/// </summary>
public static class OpennessMutate
{
    public const string ApiRetrieve = "Projects.Retrieve(FileInfo, DirectoryInfo)";
    public const string ApiCreate = "Projects.Create(DirectoryInfo, string)";
    public const string ApiClose = "Project.Close()";
    public const string ApiGenerateSource = "PlcBlock.GenerateSourceFromBlocks(FileInfo)";
    public const string ApiImport = "Import(FileInfo, ImportOptions)";
    public const string ApiCaxImport = "CAxProvider.Import(FileInfo)";
    public const string ApiCreateDevice = "Devices.CreateWithItem(typeIdentifier, name, deviceName)";
    public const string ApiOpenLibrary = "GlobalLibraries.Open(FileInfo, FileAccess)";
    public const string ApiCopyLibrary = "MasterCopy.CreateCopy(destination) / Type.CreateCopy(destination)";

    public static Exception Unwrap(Exception ex) =>
        ex is TargetInvocationException { InnerException: { } inner } ? inner : ex;

    public static MethodInfo? FindMethod(object? item, string name, int? argc = null)
    {
        if (item is null || string.IsNullOrEmpty(name)) return null;
        try
        {
            return item.GetType().GetMethods(BindingFlags.Public | BindingFlags.Instance)
                .FirstOrDefault(m =>
                    m.Name == name &&
                    (argc is null || m.GetParameters().Length == argc.Value));
        }
        catch
        {
            return null;
        }
    }

    /// <summary>Official <c>Import(FileInfo, ImportOptions)</c>; some builds are <c>Import(FileInfo)</c>.</summary>
    public static MethodInfo? FindImportMethod(object? composition)
    {
        if (composition is null) return null;
        try
        {
            var methods = composition.GetType().GetMethods(BindingFlags.Public | BindingFlags.Instance)
                .Where(m => m.Name == "Import")
                .ToList();
            var withOptions = methods.FirstOrDefault(m =>
            {
                var ps = m.GetParameters();
                return ps.Length == 2 &&
                       ps[0].ParameterType.Name.IndexOf("FileInfo", StringComparison.Ordinal) >= 0 &&
                       ps[1].ParameterType.Name.IndexOf("ImportOptions", StringComparison.Ordinal) >= 0;
            });
            if (withOptions is not null) return withOptions;
            return methods.FirstOrDefault(m =>
            {
                var ps = m.GetParameters();
                return ps.Length == 1 &&
                       (ps[0].ParameterType == typeof(string) ||
                        ps[0].ParameterType.Name.IndexOf("FileInfo", StringComparison.Ordinal) >= 0);
            });
        }
        catch
        {
            return null;
        }
    }

    public static bool HasImport(object? composition) => FindImportMethod(composition) is not null;

    public static object? ResolveImportOption(Type importOptionsType, bool overwrite, out string optionName)
    {
        optionName = overwrite ? "Override" : "None";
        try
        {
            return Enum.Parse(importOptionsType, optionName);
        }
        catch (ArgumentException)
        {
            if (!overwrite) return null;
            try
            {
                optionName = "Overwrite";
                return Enum.Parse(importOptionsType, optionName);
            }
            catch (ArgumentException)
            {
                optionName = overwrite ? "Override" : "None";
                return null;
            }
        }
    }

    /// <summary>
    /// Invoke composition.Import when the official method exists.
    /// Returns skip reason: null on success; <c>no_import</c> when the member is absent.
    /// </summary>
    public static (object? Imported, string? SkipReason, string Api) TryImport(
        object composition,
        string filePath,
        bool overwrite)
    {
        var import = FindImportMethod(composition);
        if (import is null)
        {
            return (null, "no_import", ApiImport);
        }

        var ps = import.GetParameters();
        var args = new object?[ps.Length];
        var api = $"Import({string.Join(", ", ps.Select(p => p.ParameterType.Name))})";
        try
        {
            args[0] = CoerceFileOrPath(ps[0].ParameterType, filePath);
            if (ps.Length >= 2)
            {
                var option = ResolveImportOption(ps[1].ParameterType, overwrite, out var optionName);
                if (option is null)
                {
                    return (null, "no_import", $"{api} — ImportOptions.{optionName} missing");
                }
                args[1] = option;
                api = $"Import(FileInfo, ImportOptions.{optionName})";
            }

            var imported = import.Invoke(composition, args);
            return (imported, null, api);
        }
        catch (Exception ex)
        {
            return (null, OpennessExport.ClassifySkipReason(Unwrap(ex).Message, composition), api);
        }
    }

    public static object CoerceFileOrPath(Type parameterType, string path)
    {
        if (parameterType == typeof(string)) return path;
        return Activator.CreateInstance(parameterType, path)!;
    }

    public static object CoerceDirectory(Type parameterType, string path)
    {
        if (parameterType == typeof(string)) return path;
        return Activator.CreateInstance(parameterType, path)!;
    }

    /// <summary>Official <c>Projects.Retrieve(FileInfo source, DirectoryInfo target)</c>.</summary>
    public static (object? Project, string? SkipReason, string Api) TryRetrieve(
        object projects,
        string archivePath,
        string targetDirectory)
    {
        var methods = projects.GetType().GetMethods(BindingFlags.Public | BindingFlags.Instance)
            .Where(m => m.Name == "Retrieve")
            .OrderBy(m => m.GetParameters().Length)
            .ToList();
        if (methods.Count == 0)
        {
            return (null, "no_import", ApiRetrieve + " not found on this Openness build");
        }

        foreach (var retrieve in methods)
        {
            var ps = retrieve.GetParameters();
            if (ps.Length < 2) continue;
            try
            {
                var args = new object?[ps.Length];
                args[0] = CoerceFileOrPath(ps[0].ParameterType, archivePath);
                args[1] = CoerceDirectory(ps[1].ParameterType, targetDirectory);
                var ok = true;
                for (var i = 2; i < ps.Length; i++)
                {
                    if (ps[i].HasDefaultValue)
                    {
                        args[i] = ps[i].DefaultValue;
                        continue;
                    }
                    // Do not guess Retrieve option enums — skip this overload.
                    ok = false;
                    break;
                }
                if (!ok) continue;
                var project = retrieve.Invoke(projects, args);
                var api = $"Projects.Retrieve({string.Join(", ", ps.Take(2).Select(p => p.ParameterType.Name))})";
                return (project, null, api);
            }
            catch (Exception ex)
            {
                return (null, OpennessExport.ClassifySkipReason(Unwrap(ex).Message), ApiRetrieve);
            }
        }

        return (null, "no_import", ApiRetrieve + " overload not usable without guessed extra arguments");
    }

    /// <summary>Official <c>Projects.Create(DirectoryInfo, string)</c> when present.</summary>
    public static (object? Project, string? SkipReason, string Api) TryCreate(
        object projects,
        string targetDirectory,
        string projectName)
    {
        var methods = projects.GetType().GetMethods(BindingFlags.Public | BindingFlags.Instance)
            .Where(m => m.Name == "Create")
            .ToList();
        if (methods.Count == 0)
        {
            return (null, "no_import", ApiCreate + " not found on this Openness build");
        }

        var twoArg = methods.FirstOrDefault(m => m.GetParameters().Length == 2);
        if (twoArg is not null)
        {
            var ps = twoArg.GetParameters();
            try
            {
                var arg0 = CoerceDirectory(ps[0].ParameterType, targetDirectory);
                object arg1 = ps[1].ParameterType == typeof(string)
                    ? projectName
                    : CoerceDirectory(ps[1].ParameterType, Path.Combine(targetDirectory, projectName));
                var project = twoArg.Invoke(projects, new[] { arg0, arg1 });
                return (project, null, $"Projects.Create({ps[0].ParameterType.Name}, {ps[1].ParameterType.Name})");
            }
            catch (Exception ex)
            {
                return (null, OpennessExport.ClassifySkipReason(Unwrap(ex).Message), ApiCreate);
            }
        }

        return (null, "no_import", ApiCreate + " two-argument overload not present");
    }

    /// <summary>Official <c>Project.Close()</c> when present.</summary>
    public static (bool Closed, string? SkipReason, string Api) TryClose(object project)
    {
        var close = FindMethod(project, "Close", 0)
                    ?? FindMethod(project, "Close", 1);
        if (close is null)
        {
            return (false, "no_import", ApiClose + " not found on this Openness build");
        }

        try
        {
            var ps = close.GetParameters();
            if (ps.Length == 0)
            {
                close.Invoke(project, null);
            }
            else if (ps[0].HasDefaultValue)
            {
                close.Invoke(project, new[] { ps[0].DefaultValue });
            }
            else if (ps[0].ParameterType == typeof(bool))
            {
                // Do not guess save-on-close; close without saving extra state.
                close.Invoke(project, new object[] { false });
            }
            else
            {
                return (false, "no_import", "Project.Close overload not usable without guessed arguments");
            }
            return (true, null, ps.Length == 0 ? ApiClose : $"Project.Close({ps[0].ParameterType.Name})");
        }
        catch (Exception ex)
        {
            return (false, OpennessExport.ClassifySkipReason(Unwrap(ex).Message), ApiClose);
        }
    }

    /// <summary>Official <c>Devices.CreateWithItem(typeIdentifier, name, deviceName)</c> when present.</summary>
    public static (object? Device, string? SkipReason, string Api) TryCreateDevice(
        object devicesComposition,
        string typeIdentifier,
        string name,
        string deviceName)
    {
        var methods = devicesComposition.GetType().GetMethods(BindingFlags.Public | BindingFlags.Instance)
            .Where(m => m.Name == "CreateWithItem")
            .ToList();
        if (methods.Count == 0)
        {
            return (null, "no_import", ApiCreateDevice + " not found on this Openness build");
        }

        var match = methods.FirstOrDefault(m => m.GetParameters().Length == 3);
        if (match is not null)
        {
            try
            {
                var device = match.Invoke(devicesComposition, new object[] { typeIdentifier, name, deviceName });
                return (device, null, ApiCreateDevice);
            }
            catch (Exception ex)
            {
                return (null, OpennessExport.ClassifySkipReason(Unwrap(ex).Message), ApiCreateDevice);
            }
        }

        return (null, "no_import", ApiCreateDevice + " 3-argument overload not present");
    }

    /// <summary>Official <c>GlobalLibraries.Open(FileInfo, FileAccess)</c> when present.</summary>
    public static (object? Library, string? SkipReason, string Api) TryOpenGlobalLibrary(
        object globalLibrariesComposition,
        string libraryPath,
        bool readOnly)
    {
        var methods = globalLibrariesComposition.GetType().GetMethods(BindingFlags.Public | BindingFlags.Instance)
            .Where(m => m.Name == "Open")
            .ToList();
        if (methods.Count == 0)
        {
            return (null, "no_import", ApiOpenLibrary + " not found on this Openness build");
        }

        foreach (var m in methods)
        {
            var ps = m.GetParameters();
            if (ps.Length < 1) continue;
            try
            {
                var arg0 = CoerceFileOrPath(ps[0].ParameterType, libraryPath);
                object? lib = null;
                if (ps.Length == 1)
                {
                    lib = m.Invoke(globalLibrariesComposition, new[] { arg0 });
                }
                else if (ps.Length == 2 && ps[1].ParameterType == typeof(System.IO.FileAccess))
                {
                    var access = readOnly ? System.IO.FileAccess.Read : System.IO.FileAccess.ReadWrite;
                    lib = m.Invoke(globalLibrariesComposition, new[] { arg0, access });
                }
                if (lib is not null)
                {
                    return (lib, null, ApiOpenLibrary);
                }
            }
            catch (Exception ex)
            {
                return (null, OpennessExport.ClassifySkipReason(Unwrap(ex).Message), ApiOpenLibrary);
            }
        }

        return (null, "no_import", ApiOpenLibrary + " overload not matching");
    }

    /// <summary>Copy master copy or library type to target project folder/group.</summary>
    public static (bool Ok, string? SkipReason, string Api) TryCopyFromLibrary(
        object sourceItem,
        object targetDestination)
    {
        var createCopy = FindMethod(targetDestination, "CreateCopy", 1)
                         ?? FindMethod(sourceItem, "CreateCopy", 1);
        if (createCopy is null)
        {
            return (false, "no_import", ApiCopyLibrary + " not found on this Openness build");
        }

        try
        {
            if (createCopy.DeclaringType?.IsInstanceOfType(targetDestination) == true)
            {
                createCopy.Invoke(targetDestination, new[] { sourceItem });
            }
            else
            {
                createCopy.Invoke(sourceItem, new[] { targetDestination });
            }
            return (true, null, ApiCopyLibrary);
        }
        catch (Exception ex)
        {
            return (false, OpennessExport.ClassifySkipReason(Unwrap(ex).Message), ApiCopyLibrary);
        }
    }

    /// <summary>
    /// Official 5.11.3.18 <c>GenerateSourceFromBlocks(FileInfo)</c> on the block
    /// (or a one-arg <c>GenerateSource</c> alias if that is the only member).
    /// </summary>
    public static (string? SkipReason, string Api) TryGenerateSourceFromBlocks(object block, string outPath)
    {
        var methods = block.GetType().GetMethods(BindingFlags.Public | BindingFlags.Instance)
            .Where(m => m.Name is "GenerateSourceFromBlocks" or "GenerateSource")
            .ToList();
        var preferred = methods.FirstOrDefault(m => m.Name == "GenerateSourceFromBlocks")
                        ?? methods.FirstOrDefault();
        if (preferred is null)
        {
            return ("no_export", ApiGenerateSource + " not found on this Openness build");
        }

        var ps = preferred.GetParameters();
        var api = $"{preferred.Name}({string.Join(", ", ps.Select(p => p.ParameterType.Name))})";
        try
        {
            var dir = Path.GetDirectoryName(outPath);
            if (!string.IsNullOrEmpty(dir)) Directory.CreateDirectory(dir);

            if (ps.Length == 1)
            {
                preferred.Invoke(block, new[] { CoerceFileOrPath(ps[0].ParameterType, outPath) });
                return (null, api);
            }

            if (ps.Length == 0)
            {
                preferred.Invoke(block, null);
                return (null, api);
            }

            // Extra args: only fill trailing defaults; never guess enum values.
            var args = new object?[ps.Length];
            args[0] = CoerceFileOrPath(ps[0].ParameterType, outPath);
            for (var i = 1; i < ps.Length; i++)
            {
                if (!ps[i].HasDefaultValue)
                {
                    return ("no_export", api + " extra non-default parameters not invoked");
                }
                args[i] = ps[i].DefaultValue;
            }
            preferred.Invoke(block, args);
            return (null, api);
        }
        catch (Exception ex)
        {
            return (OpennessExport.ClassifySkipReason(Unwrap(ex).Message, block), api);
        }
    }

    /// <summary>Official Create on a composition (e.g. TechnologicalObjectGroup) when present.</summary>
    public static (object? Created, string? SkipReason, string Api) TryCreateOn(
        object composition,
        string name,
        string? typeIdentifier)
    {
        var methods = composition.GetType().GetMethods(BindingFlags.Public | BindingFlags.Instance)
            .Where(m => m.Name == "Create")
            .ToList();
        if (methods.Count == 0)
        {
            return (null, "no_import", $"{composition.GetType().Name}.Create not found");
        }

        var two = methods.FirstOrDefault(m =>
            m.GetParameters().Length == 2 &&
            m.GetParameters()[0].ParameterType == typeof(string) &&
            m.GetParameters()[1].ParameterType == typeof(string));
        if (two is not null && !string.IsNullOrWhiteSpace(typeIdentifier))
        {
            try
            {
                var created = two.Invoke(composition, new object[] { name, typeIdentifier! });
                return (created, null, $"{composition.GetType().Name}.Create(string, string)");
            }
            catch (Exception ex)
            {
                return (null, OpennessExport.ClassifySkipReason(Unwrap(ex).Message), $"{composition.GetType().Name}.Create");
            }
        }

        var one = methods.FirstOrDefault(m =>
            m.GetParameters().Length == 1 &&
            m.GetParameters()[0].ParameterType == typeof(string));
        if (one is not null)
        {
            try
            {
                var created = one.Invoke(composition, new object[] { name });
                return (created, null, $"{composition.GetType().Name}.Create(string)");
            }
            catch (Exception ex)
            {
                return (null, OpennessExport.ClassifySkipReason(Unwrap(ex).Message), $"{composition.GetType().Name}.Create");
            }
        }

        return (null, "no_import", $"{composition.GetType().Name}.Create overload not usable");
    }

    public static (bool Deleted, string? SkipReason, string Api) TryDelete(object item)
    {
        var delete = FindMethod(item, "Delete", 0);
        if (delete is null)
        {
            return (false, "no_import", $"{item.GetType().Name}.Delete() not found");
        }

        try
        {
            delete.Invoke(item, null);
            return (true, null, $"{item.GetType().Name}.Delete()");
        }
        catch (Exception ex)
        {
            return (false, OpennessExport.ClassifySkipReason(Unwrap(ex).Message), $"{item.GetType().Name}.Delete()");
        }
    }

    public static List<string> ExtractNames(object? imported)
    {
        var names = new List<string>();
        if (imported is null) return names;
        if (imported is IEnumerable enumerable and not string)
        {
            foreach (var item in enumerable)
            {
                if (item is null) continue;
                var name = OpennessExport.GetPropString(item, "Name");
                if (string.IsNullOrWhiteSpace(name))
                {
                    var nested = OpennessExport.GetProp(item, "ImportedObject")
                                 ?? OpennessExport.GetProp(item, "Object");
                    name = OpennessExport.GetPropString(nested, "Name");
                }
                if (!string.IsNullOrWhiteSpace(name)) names.Add(name!);
            }
            return names;
        }

        var single = OpennessExport.GetPropString(imported, "Name");
        if (!string.IsNullOrWhiteSpace(single)) names.Add(single!);
        return names;
    }

    /// <summary>
    /// Classify SimaticML / AML / HMI XML from a short head (fail closed → block).
    /// </summary>
    public static string ClassifyXmlKind(string head, string fileName = "")
    {
        var blob = (head ?? "") + " " + (fileName ?? "");
        if (Contains(blob, "CAEXFile") || Contains(blob, "HardwareTree")) return "hardware";
        if (Contains(blob, "PlcWatchTable") || Contains(blob, "SW.WatchAndForceTables.PlcWatchTable")) return "watch";
        if (Contains(blob, "PlcForceTable") || Contains(blob, "SW.WatchAndForceTables.PlcForceTable")) return "force";
        if (Contains(blob, "SW.Types.PlcStruct") || Contains(blob, "PlcStruct") || Contains(blob, "TypeTable")) return "type";
        if (Contains(blob, "SW.Tags.PlcTagTable") || Contains(blob, "PlcTagTable")) return "tag";
        if (Contains(blob, "Hmi.") || Contains(blob, "HmiUnified") || Contains(blob, "HMI.")) return "hmi";
        if (Contains(blob, "CfcChart") || Contains(blob, "SW.Cfc")) return "cfc";
        if (Contains(blob, "TechnologicalObject") || Contains(blob, "TO_PositioningAxis") || Contains(blob, "TO_PID")) return "to";
        if (Contains(blob, "SW.Blocks.") || Contains(blob, "DocumentType") || Contains(blob, "Simatic.ML")) return "block";
        return "block";
    }

    private static bool Contains(string haystack, string needle) =>
        haystack.IndexOf(needle, StringComparison.OrdinalIgnoreCase) >= 0;
}

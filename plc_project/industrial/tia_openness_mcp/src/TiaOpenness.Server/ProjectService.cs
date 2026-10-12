using System.Collections;
using System.Reflection;
using TiaOpenness.Models;

namespace TiaOpenness.Server;

/// <summary>Opens / tracks a TIA project and resolves PLC software.</summary>
public sealed class ProjectService
{
    private readonly TiaConnection _connection;
    private object? _project;
    private object? _plcSoftware;
    private string? _projectPath;
    private string? _projectName;
    private string? _plcName;
    private string? _deviceName;
    private readonly Dictionary<string, object> _openLibraries = new(StringComparer.OrdinalIgnoreCase);

    public ProjectService(TiaConnection connection)
    {
        _connection = connection;
    }

    public bool IsProjectOpen => _project is not null;
    public string? ProjectPath => _projectPath;
    public string? ProjectName => _projectName;
    public string? PlcName => _plcName;
    public string? DeviceName => _deviceName;
    public object? Project => _project;
    public object? PlcSoftware => _plcSoftware;
    public TiaConnection Connection => _connection;

    /// <summary>All PLC / HMI software containers under Project.Devices (chapter 6.2 / 6.3 / 6.4).</summary>
    public List<(string Kind, string DeviceName, string SoftwareName, object Software, object Device)> EnumerateSoftware()
    {
        var list = new List<(string, string, string, object, object)>();
        if (_project is null) return list;
        var seen = new HashSet<int>();
        if (GetProp(_project, "Devices") is not IEnumerable devices) return list;
        foreach (var device in devices)
        {
            CollectSoftware(device, GetPropString(device, "Name") ?? "", list, seen);
        }
        return list;
    }

    private void CollectSoftware(
        object deviceOrItem,
        string deviceName,
        List<(string Kind, string DeviceName, string SoftwareName, object Software, object Device)> sink,
        HashSet<int> seen)
    {
        foreach (var typeName in new[]
                 {
                     "Siemens.Engineering.HW.Features.SoftwareContainer",
                     "Siemens.Engineering.Software.SoftwareContainer",
                 })
        {
            var container = _connection.GetService(deviceOrItem, typeName);
            if (container is null) continue;
            var software = GetProp(container, "Software");
            if (software is null) continue;
            var id = System.Runtime.CompilerServices.RuntimeHelpers.GetHashCode(software);
            if (!seen.Add(id)) continue;
            var full = software.GetType().FullName ?? software.GetType().Name;
            var kind = "other";
            if (full.IndexOf("PlcSoftware", StringComparison.OrdinalIgnoreCase) >= 0)
                kind = "plc";
            else if (full.IndexOf("HmiUnified", StringComparison.OrdinalIgnoreCase) >= 0)
                kind = "hmi_unified";
            else if (full.IndexOf("Hmi", StringComparison.OrdinalIgnoreCase) >= 0)
                kind = "hmi";
            else
                continue;
            var softName = GetPropString(software, "Name")
                ?? GetPropString(deviceOrItem, "Name")
                ?? deviceName;
            sink.Add((kind, deviceName, softName, software, deviceOrItem));
        }

        if (GetProp(deviceOrItem, "DeviceItems") is IEnumerable children)
        {
            foreach (var child in children)
            {
                CollectSoftware(child, deviceName, sink, seen);
            }
        }
    }

    /// <summary>Official <c>Projects.Retrieve(FileInfo, DirectoryInfo)</c> for <c>.zap*</c>.</summary>
    public RetrieveProjectResult RetrieveProject(string archivePath, string targetDirectory, string? plcName = null)
    {
        if (string.IsNullOrWhiteSpace(archivePath))
        {
            return FailRetrieve("invalid_argument", "archive_path is required.");
        }

        var full = Path.GetFullPath(archivePath);
        if (!File.Exists(full))
        {
            return FailRetrieve("not_found", $"Archive not found: {full}");
        }

        var ext = Path.GetExtension(full);
        if (ext.IndexOf("zap", StringComparison.OrdinalIgnoreCase) < 0)
        {
            return FailRetrieve("invalid_argument", $"Expected a Siemens .zap* archive, got: {ext}");
        }

        try
        {
            if (!TiaConnection.IsOpennessGroupInCurrentToken())
            {
                return FailRetrieve(
                    "openness_group_token_missing",
                    "Current logon token lacks 'Siemens TIA Openness'. Sign out/in after joining the group, then retry.");
            }

            var dest = Path.GetFullPath(string.IsNullOrWhiteSpace(targetDirectory)
                ? Path.Combine(Path.GetTempPath(), "researchos-tia-retrieve")
                : targetDirectory);
            Directory.CreateDirectory(dest);

            _connection.Connect(preferAttach: false, withoutUi: true);
            var projects = GetProjectsComposition();
            if (projects is null)
            {
                return FailRetrieve("dependency_unavailable", "TiaPortal.Projects not found.");
            }

            var retrieved = OpennessMutate.TryRetrieve(projects, full, dest);
            if (retrieved.SkipReason is not null)
            {
                return new RetrieveProjectResult
                {
                    Ok = false,
                    ArchivePath = full,
                    TargetDirectory = dest,
                    Api = retrieved.Api,
                    Error = new ToolError
                    {
                        Code = retrieved.SkipReason == "no_import" ? "dependency_unavailable" : "openness_error",
                        Message = retrieved.SkipReason == "no_import"
                            ? retrieved.Api
                            : retrieved.SkipReason + ": " + retrieved.Api,
                    },
                };
            }

            AdoptProject(retrieved.Project, dest);
            TryResolvePlc(plcName);

            return new RetrieveProjectResult
            {
                Ok = _project is not null,
                ArchivePath = full,
                TargetDirectory = dest,
                ProjectPath = _projectPath,
                ProjectName = _projectName,
                PlcName = _plcName,
                Api = retrieved.Api,
                Message = _project is not null
                    ? $"Retrieved via {retrieved.Api} → {_projectPath}"
                    : "Retrieve returned no project object.",
                Error = _project is null
                    ? new ToolError { Code = "openness_error", Message = "Projects.Retrieve returned null." }
                    : null,
            };
        }
        catch (Exception ex)
        {
            return FailRetrieve("openness_error", OpennessMutate.Unwrap(ex).Message);
        }
    }

    /// <summary>Official <c>Projects.Create(DirectoryInfo, string)</c> when present.</summary>
    public CreateProjectResult CreateProject(string targetDirectory, string projectName)
    {
        if (string.IsNullOrWhiteSpace(targetDirectory) || string.IsNullOrWhiteSpace(projectName))
        {
            return FailCreate("invalid_argument", "target_directory and project_name are required.");
        }

        try
        {
            if (!TiaConnection.IsOpennessGroupInCurrentToken())
            {
                return FailCreate(
                    "openness_group_token_missing",
                    "Current logon token lacks 'Siemens TIA Openness'. Sign out/in after joining the group, then retry.");
            }

            var dest = Path.GetFullPath(targetDirectory);
            Directory.CreateDirectory(dest);
            _connection.Connect(preferAttach: false, withoutUi: true);
            var projects = GetProjectsComposition();
            if (projects is null)
            {
                return FailCreate("dependency_unavailable", "TiaPortal.Projects not found.");
            }

            var created = OpennessMutate.TryCreate(projects, dest, projectName.Trim());
            if (created.SkipReason is not null)
            {
                return new CreateProjectResult
                {
                    Ok = false,
                    Api = created.Api,
                    Error = new ToolError
                    {
                        Code = "dependency_unavailable",
                        Message = created.Api,
                    },
                };
            }

            AdoptProject(created.Project, dest);
            return new CreateProjectResult
            {
                Ok = _project is not null,
                ProjectPath = _projectPath,
                ProjectName = _projectName,
                Api = created.Api,
                Message = _project is not null
                    ? $"Created via {created.Api}"
                    : "Projects.Create returned null.",
                Error = _project is null
                    ? new ToolError { Code = "openness_error", Message = "Projects.Create returned null." }
                    : null,
            };
        }
        catch (Exception ex)
        {
            return FailCreate("openness_error", OpennessMutate.Unwrap(ex).Message);
        }
    }

    /// <summary>Official <c>Project.Close()</c> when present.</summary>
    public CloseProjectResult CloseProject()
    {
        if (_project is null)
        {
            return FailClose("invalid_argument", "No project open. Call tia.open_project first.");
        }

        try
        {
            var closed = OpennessMutate.TryClose(_project);
            if (closed.SkipReason is not null)
            {
                return new CloseProjectResult
                {
                    Ok = false,
                    Api = closed.Api,
                    Error = new ToolError { Code = "dependency_unavailable", Message = closed.Api },
                };
            }

            ClearProject();
            return new CloseProjectResult
            {
                Ok = true,
                Api = closed.Api,
                Message = "Project closed.",
            };
        }
        catch (Exception ex)
        {
            return FailClose("openness_error", OpennessMutate.Unwrap(ex).Message);
        }
    }

    /// <summary>Official <c>Devices.CreateWithItem(typeIdentifier, name, deviceName)</c>.</summary>
    public CreateDeviceResult CreateDevice(string typeIdentifier, string name, string? deviceName = null)
    {
        if (string.IsNullOrWhiteSpace(typeIdentifier) || string.IsNullOrWhiteSpace(name))
        {
            return new CreateDeviceResult
            {
                Ok = false,
                Error = new ToolError { Code = "invalid_argument", Message = "typeIdentifier and name are required." },
            };
        }

        if (_project is null)
        {
            return new CreateDeviceResult
            {
                Ok = false,
                Error = new ToolError { Code = "invalid_argument", Message = "No project open. Call tia.open_project or tia.create_project first." },
            };
        }

        try
        {
            var devices = GetProp(_project, "Devices");
            if (devices is null)
            {
                return new CreateDeviceResult
                {
                    Ok = false,
                    Error = new ToolError { Code = "dependency_unavailable", Message = "Project.Devices composition not found." },
                };
            }

            var dName = string.IsNullOrWhiteSpace(deviceName) ? name.Trim() : deviceName.Trim();
            var created = OpennessMutate.TryCreateDevice(devices, typeIdentifier.Trim(), name.Trim(), dName);
            if (created.SkipReason is not null || created.Device is null)
            {
                return new CreateDeviceResult
                {
                    Ok = false,
                    Api = created.Api,
                    Error = new ToolError { Code = created.SkipReason ?? "openness_error", Message = created.Api },
                };
            }

            TryResolvePlc(dName);

            string? orderNo = null;
            string? ver = null;
            var parts = typeIdentifier.Split('/');
            if (parts.Length > 0)
            {
                orderNo = parts[0].Replace("OrderNumber:", "").Trim();
            }
            if (parts.Length > 1)
            {
                ver = parts[1].Trim();
            }

            return new CreateDeviceResult
            {
                Ok = true,
                Api = created.Api,
                DeviceName = dName,
                TypeIdentifier = typeIdentifier,
                OrderNumber = orderNo,
                Version = ver,
                Message = $"Device '{dName}' ({typeIdentifier}) created successfully.",
            };
        }
        catch (Exception ex)
        {
            return new CreateDeviceResult
            {
                Ok = false,
                Error = new ToolError { Code = "openness_error", Message = OpennessMutate.Unwrap(ex).Message },
            };
        }
    }

    /// <summary>Official <c>GlobalLibraries.Open(FileInfo, FileAccess)</c>.</summary>
    public OpenLibraryResult OpenGlobalLibrary(string libraryPath, bool readOnly = true)
    {
        if (string.IsNullOrWhiteSpace(libraryPath))
        {
            return new OpenLibraryResult
            {
                Ok = false,
                Error = new ToolError { Code = "invalid_argument", Message = "libraryPath is required." },
            };
        }

        var full = Path.GetFullPath(libraryPath);
        if (!File.Exists(full))
        {
            return new OpenLibraryResult
            {
                Ok = false,
                Error = new ToolError { Code = "not_found", Message = $"Library not found: {full}" },
            };
        }

        try
        {
            _connection.Connect(preferAttach: true, withoutUi: true);
            var portal = _connection.Portal;
            if (portal is null)
            {
                return new OpenLibraryResult
                {
                    Ok = false,
                    Error = new ToolError { Code = "dependency_unavailable", Message = "TiaPortal instance not connected." },
                };
            }

            var globalLibs = portal.GetType().GetProperty("GlobalLibraries")?.GetValue(portal);
            if (globalLibs is null)
            {
                return new OpenLibraryResult
                {
                    Ok = false,
                    Error = new ToolError { Code = "dependency_unavailable", Message = "TiaPortal.GlobalLibraries composition not found." },
                };
            }

            var opened = OpennessMutate.TryOpenGlobalLibrary(globalLibs, full, readOnly);
            if (opened.SkipReason is not null || opened.Library is null)
            {
                return new OpenLibraryResult
                {
                    Ok = false,
                    Api = opened.Api,
                    Error = new ToolError { Code = opened.SkipReason ?? "openness_error", Message = opened.Api },
                };
            }

            var lib = opened.Library;
            var libName = GetPropString(lib, "Name") ?? Path.GetFileNameWithoutExtension(full);
            _openLibraries[full] = lib;
            _openLibraries[libName] = lib;

            var masterCopies = new List<string>();
            var types = new List<string>();

            var mcFolder = GetProp(lib, "MasterCopyFolder");
            if (mcFolder is not null)
            {
                CollectMasterCopyNames(mcFolder, masterCopies);
            }

            var typeFolder = GetProp(lib, "TypeFolder");
            if (typeFolder is not null)
            {
                CollectTypeNames(typeFolder, types);
            }

            return new OpenLibraryResult
            {
                Ok = true,
                Api = opened.Api,
                LibraryPath = full,
                LibraryName = libName,
                MasterCopiesCount = masterCopies.Count,
                TypesCount = types.Count,
                MasterCopies = masterCopies,
                Types = types,
                Message = $"Global library '{libName}' opened successfully.",
            };
        }
        catch (Exception ex)
        {
            return new OpenLibraryResult
            {
                Ok = false,
                Error = new ToolError { Code = "openness_error", Message = OpennessMutate.Unwrap(ex).Message },
            };
        }
    }

    /// <summary>Copy a MasterCopy or LibraryType from an open library into project.</summary>
    public CopyLibraryResult CopyFromLibrary(string libraryPathOrName, string itemName, string? targetGroup = null)
    {
        if (string.IsNullOrWhiteSpace(libraryPathOrName) || string.IsNullOrWhiteSpace(itemName))
        {
            return new CopyLibraryResult
            {
                Ok = false,
                Error = new ToolError { Code = "invalid_argument", Message = "libraryPathOrName and itemName are required." },
            };
        }

        if (_project is null)
        {
            return new CopyLibraryResult
            {
                Ok = false,
                Error = new ToolError { Code = "invalid_argument", Message = "No project open. Call tia.open_project first." },
            };
        }

        if (!_openLibraries.TryGetValue(libraryPathOrName, out var lib))
        {
            var openRes = OpenGlobalLibrary(libraryPathOrName);
            if (!openRes.Ok || !_openLibraries.TryGetValue(libraryPathOrName, out lib))
            {
                return new CopyLibraryResult
                {
                    Ok = false,
                    Error = new ToolError { Code = "not_found", Message = $"Library '{libraryPathOrName}' not open or not found." },
                };
            }
        }

        try
        {
            object? sourceItem = null;
            var mcFolder = GetProp(lib, "MasterCopyFolder");
            if (mcFolder is not null)
            {
                sourceItem = FindMasterCopy(mcFolder, itemName);
            }

            if (sourceItem is null)
            {
                return new CopyLibraryResult
                {
                    Ok = false,
                    Error = new ToolError { Code = "not_found", Message = $"Library item '{itemName}' not found in master copies." },
                };
            }

            object target = _plcSoftware is not null
                ? (GetProp(_plcSoftware, "BlockGroup") ?? _project)
                : _project;

            var copied = OpennessMutate.TryCopyFromLibrary(sourceItem, target);
            return new CopyLibraryResult
            {
                Ok = copied.Ok,
                Api = copied.Api,
                ItemName = itemName,
                TargetGroup = targetGroup ?? "Root",
                Message = copied.Ok ? $"Copied '{itemName}' into project." : "Failed to copy from library.",
                Error = copied.Ok ? null : new ToolError { Code = copied.SkipReason ?? "openness_error", Message = copied.Api },
            };
        }
        catch (Exception ex)
        {
            return new CopyLibraryResult
            {
                Ok = false,
                Error = new ToolError { Code = "openness_error", Message = OpennessMutate.Unwrap(ex).Message },
            };
        }
    }

    private void CollectMasterCopyNames(object folder, List<string> sink)
    {
        var copies = GetProp(folder, "MasterCopies");
        if (copies is IEnumerable list)
        {
            foreach (var item in list)
            {
                var name = GetPropString(item, "Name");
                if (!string.IsNullOrEmpty(name)) sink.Add(name);
            }
        }
        var subFolders = GetProp(folder, "Folders");
        if (subFolders is IEnumerable subList)
        {
            foreach (var sub in subList)
            {
                CollectMasterCopyNames(sub, sink);
            }
        }
    }

    private void CollectTypeNames(object folder, List<string> sink)
    {
        var types = GetProp(folder, "Types");
        if (types is IEnumerable list)
        {
            foreach (var item in list)
            {
                var name = GetPropString(item, "Name");
                if (!string.IsNullOrEmpty(name)) sink.Add(name);
            }
        }
        var subFolders = GetProp(folder, "Folders");
        if (subFolders is IEnumerable subList)
        {
            foreach (var sub in subList)
            {
                CollectTypeNames(sub, sink);
            }
        }
    }

    private object? FindMasterCopy(object folder, string name)
    {
        var copies = GetProp(folder, "MasterCopies");
        if (copies is IEnumerable list)
        {
            foreach (var item in list)
            {
                if (string.Equals(GetPropString(item, "Name"), name, StringComparison.OrdinalIgnoreCase))
                {
                    return item;
                }
            }
        }
        var subFolders = GetProp(folder, "Folders");
        if (subFolders is IEnumerable subList)
        {
            foreach (var sub in subList)
            {
                var found = FindMasterCopy(sub, name);
                if (found is not null) return found;
            }
        }
        return null;
    }

    public OpenProjectResult OpenProject(string projectPath, string? plcName = null, bool withoutUi = true)
    {
        if (string.IsNullOrWhiteSpace(projectPath))
        {
            return Fail("invalid_argument", "project_path is required.");
        }

        var full = Path.GetFullPath(projectPath);
        if (!File.Exists(full))
        {
            return Fail("not_found", $"Project file not found: {full}");
        }

        var ext = Path.GetExtension(full);
        if (!ext.StartsWith(".ap", StringComparison.OrdinalIgnoreCase))
        {
            return Fail("invalid_argument", $"Expected a TIA project (.ap19/.ap18/...), got: {ext}");
        }

        try
        {
            if (!TiaConnection.IsOpennessGroupInCurrentToken())
            {
                return Fail(
                    "openness_group_token_missing",
                    "Current logon token lacks 'Siemens TIA Openness'. Sign out/in after joining the group, then retry.");
            }

            // Prefer a dedicated WithoutUserInterface session for MCP open_project.
            // Attaching to an existing UI Portal often fails with Openness security checks.
            _connection.Connect(preferAttach: false, withoutUi: withoutUi);
            var portal = _connection.Portal
                ?? throw new InvalidOperationException("TIA Portal connection is not available.");

            var projectsProp = portal.GetType().GetProperty("Projects")
                ?? throw new MissingMemberException("TiaPortal.Projects");
            var projects = projectsProp.GetValue(portal)
                ?? throw new InvalidOperationException("TiaPortal.Projects is null.");

            var open = projects.GetType().GetMethods(BindingFlags.Public | BindingFlags.Instance)
                .FirstOrDefault(m =>
                    m.Name == "Open" &&
                    m.GetParameters().Length == 1 &&
                    m.GetParameters()[0].ParameterType.Name.Contains("FileInfo"));

            if (open is null)
            {
                // fallback: Open(string) / Open(FileInfo) any single-arg
                open = projects.GetType().GetMethods(BindingFlags.Public | BindingFlags.Instance)
                    .FirstOrDefault(m => m.Name == "Open" && m.GetParameters().Length == 1);
            }

            if (open is null)
            {
                return Fail("dependency_unavailable", "Projects.Open method not found on Openness API.");
            }

            object arg = open.GetParameters()[0].ParameterType == typeof(string)
                ? full
                : Activator.CreateInstance(open.GetParameters()[0].ParameterType, full)!;

            _project = open.Invoke(projects, new[] { arg });
            _projectPath = full;
            _projectName = GetPropString(_project, "Name") ?? Path.GetFileNameWithoutExtension(full);

            var wanted = plcName?.Trim() ?? "";
            if (!TryResolvePlcSoftware(_project!, wanted, out _plcSoftware, out _deviceName, out _plcName))
            {
                return new OpenProjectResult
                {
                    Ok = false,
                    ProjectPath = full,
                    ProjectName = _projectName,
                    Error = new ToolError
                    {
                        Code = "not_found",
                        Message = string.IsNullOrEmpty(wanted)
                            ? "No PLC software found in project."
                            : $"No PLC software found matching '{wanted}'.",
                    },
                };
            }

            return new OpenProjectResult
            {
                Ok = true,
                ProjectPath = full,
                ProjectName = _projectName,
                PlcName = _plcName,
                DeviceName = _deviceName,
                Message = "Project opened via TIA Openness.",
            };
        }
        catch (TargetInvocationException ex)
        {
            var inner = ex.InnerException ?? ex;
            return Fail("openness_error", inner.Message, retryable: false);
        }
        catch (Exception ex)
        {
            return Fail("openness_error", ex.Message, retryable: false);
        }
    }

    public SaveProjectResult SaveProject()
    {
        if (_project is null)
        {
            return FailSave("invalid_argument", "No project open. Call tia.open_project first.");
        }

        try
        {
            var save = _project.GetType().GetMethods(BindingFlags.Public | BindingFlags.Instance)
                .FirstOrDefault(m =>
                    m.Name == "Save" &&
                    m.GetParameters().Length == 0);

            if (save is null)
            {
                return new SaveProjectResult
                {
                    Ok = false,
                    ProjectPath = _projectPath,
                    ProjectName = _projectName,
                    Error = new ToolError
                    {
                        Code = "dependency_unavailable",
                        Message = "Project.Save() not found on Openness API.",
                    },
                };
            }

            save.Invoke(_project, null);

            return new SaveProjectResult
            {
                Ok = true,
                ProjectPath = _projectPath,
                ProjectName = _projectName,
                Message = "Project saved.",
            };
        }
        catch (TargetInvocationException ex)
        {
            var inner = ex.InnerException ?? ex;
            return new SaveProjectResult
            {
                Ok = false,
                ProjectPath = _projectPath,
                ProjectName = _projectName,
                Error = new ToolError { Code = "openness_error", Message = inner.Message },
            };
        }
        catch (Exception ex)
        {
            return new SaveProjectResult
            {
                Ok = false,
                ProjectPath = _projectPath,
                ProjectName = _projectName,
                Error = new ToolError { Code = "openness_error", Message = ex.Message },
            };
        }
    }

    /// <summary>
    /// Archive the open project to a compressed .zap* via Project.Archive(DirectoryInfo, name, ProjectArchivationMode).
    /// </summary>
    public ArchiveProjectResult ArchiveProject(string targetDirectory, string? targetName = null)
    {
        if (_project is null)
        {
            return FailArchive("invalid_argument", "No project open. Call tia.open_project first.");
        }

        try
        {
            var dir = Path.GetFullPath(string.IsNullOrWhiteSpace(targetDirectory)
                ? Path.GetTempPath()
                : targetDirectory);
            Directory.CreateDirectory(dir);

            var name = string.IsNullOrWhiteSpace(targetName)
                ? InferZapName(_projectPath, _projectName)
                : Path.GetFileName(targetName);

            var archiveMethod = _project.GetType().GetMethods(BindingFlags.Public | BindingFlags.Instance)
                .FirstOrDefault(m =>
                    m.Name == "Archive" &&
                    m.GetParameters().Length == 3);

            if (archiveMethod is null)
            {
                return FailArchive(
                    "dependency_unavailable",
                    "Project.Archive(DirectoryInfo, string, ProjectArchivationMode) not found.");
            }

            var parms = archiveMethod.GetParameters();
            var dirInfoType = parms[0].ParameterType;
            var modeType = parms[2].ParameterType;
            object mode;
            try
            {
                mode = Enum.Parse(modeType, "Compressed");
            }
            catch
            {
                // Older enums may use different naming
                mode = Enum.GetValues(modeType).Cast<object>().First();
            }

            var dirInfo = Activator.CreateInstance(dirInfoType, dir)!;
            archiveMethod.Invoke(_project, new[] { dirInfo, name, mode });

            var archivePath = Path.Combine(dir, name);
            if (!File.Exists(archivePath))
            {
                // Openness may append extension; search for newest matching zap*
                var stem = Path.GetFileNameWithoutExtension(name);
                var candidates = Directory.GetFiles(dir, stem + "*")
                    .Concat(Directory.GetFiles(dir, "*.zap*"))
                    .Distinct()
                    .OrderByDescending(File.GetLastWriteTimeUtc)
                    .ToList();
                if (candidates.Count > 0)
                {
                    archivePath = candidates[0];
                }
            }

            return new ArchiveProjectResult
            {
                Ok = File.Exists(archivePath),
                ProjectPath = _projectPath,
                ArchivePath = archivePath,
                Message = File.Exists(archivePath)
                    ? $"Project archived to {archivePath}"
                    : "Archive completed but output file was not found.",
                Error = File.Exists(archivePath)
                    ? null
                    : new ToolError { Code = "archive_missing", Message = $"Expected archive under {dir}" },
            };
        }
        catch (TargetInvocationException ex)
        {
            var inner = ex.InnerException ?? ex;
            return FailArchive("openness_error", inner.Message);
        }
        catch (Exception ex)
        {
            return FailArchive("openness_error", ex.Message);
        }
    }

    private static string InferZapName(string? projectPath, string? projectName)
    {
        var stem = projectName;
        var ver = "19";
        if (!string.IsNullOrWhiteSpace(projectPath))
        {
            stem ??= Path.GetFileNameWithoutExtension(projectPath);
            var ext = Path.GetExtension(projectPath);
            if (ext.StartsWith(".ap", StringComparison.OrdinalIgnoreCase) && ext.Length > 3)
            {
                ver = ext[3..];
            }
        }
        stem ??= "project";
        return $"{stem}.zap{ver}";
    }

    public void ApplyStatus(TiaStatusResult status)
    {
        status.ProjectOpen = IsProjectOpen;
        status.ProjectPath = _projectPath;
        status.ProjectName = _projectName;
        status.Connected = _connection.IsConnected;
    }

    private bool TryResolvePlcSoftware(
        object project,
        string wantedName,
        out object? plcSoftware,
        out string? deviceName,
        out string? softwareName)
    {
        plcSoftware = null;
        deviceName = null;
        softwareName = null;

        var devicesProp = project.GetType().GetProperty("Devices");
        if (devicesProp?.GetValue(project) is not IEnumerable devices) return false;

        foreach (var device in devices)
        {
            var dName = GetPropString(device, "Name") ?? "";
            var itemsProp = device.GetType().GetProperty("DeviceItems");
            if (itemsProp?.GetValue(device) is not IEnumerable items) continue;

            foreach (var item in items)
            {
                var found = FindPlcSoftwareInItem(item, wantedName, dName);
                if (found is null) continue;
                plcSoftware = found;
                deviceName = dName;
                softwareName = GetPropString(found, "Name") ?? dName;
                return true;
            }
        }

        return false;
    }

    private object? FindPlcSoftwareInItem(object item, string wantedName, string deviceName)
    {
        foreach (var typeName in new[]
                 {
                     "Siemens.Engineering.HW.Features.SoftwareContainer",
                     "Siemens.Engineering.Software.SoftwareContainer",
                 })
        {
            var container = _connection.GetService(item, typeName);
            if (container is null) continue;
            var software = GetProp(container, "Software");
            if (software is null) continue;

            var isPlc = software.GetType().FullName?.Contains("PlcSoftware") == true
                        || software.GetType().Name.Contains("PlcSoftware");
            if (!isPlc) continue;

            var itemName = GetPropString(item, "Name") ?? "";
            var softName = GetPropString(software, "Name") ?? "";
            if (wantedName == "" ||
                string.Equals(deviceName, wantedName, StringComparison.OrdinalIgnoreCase) ||
                string.Equals(softName, wantedName, StringComparison.OrdinalIgnoreCase) ||
                string.Equals(itemName, wantedName, StringComparison.OrdinalIgnoreCase))
            {
                return software;
            }
        }

        var childrenProp = item.GetType().GetProperty("DeviceItems");
        if (childrenProp?.GetValue(item) is IEnumerable children)
        {
            foreach (var child in children)
            {
                var found = FindPlcSoftwareInItem(child, wantedName, deviceName);
                if (found is not null) return found;
            }
        }

        return null;
    }

    private static OpenProjectResult Fail(string code, string message, bool retryable = false) => new()
    {
        Ok = false,
        Error = new ToolError { Code = code, Message = message, Retryable = retryable },
    };

    private static SaveProjectResult FailSave(string code, string message, bool retryable = false) => new()
    {
        Ok = false,
        Error = new ToolError { Code = code, Message = message, Retryable = retryable },
    };

    private static ArchiveProjectResult FailArchive(string code, string message, bool retryable = false) => new()
    {
        Ok = false,
        Error = new ToolError { Code = code, Message = message, Retryable = retryable },
    };

    private static RetrieveProjectResult FailRetrieve(string code, string message) => new()
    {
        Ok = false,
        Api = OpennessMutate.ApiRetrieve,
        Error = new ToolError { Code = code, Message = message },
    };

    private static CreateProjectResult FailCreate(string code, string message) => new()
    {
        Ok = false,
        Api = OpennessMutate.ApiCreate,
        Error = new ToolError { Code = code, Message = message },
    };

    private static CloseProjectResult FailClose(string code, string message) => new()
    {
        Ok = false,
        Api = OpennessMutate.ApiClose,
        Error = new ToolError { Code = code, Message = message },
    };

    private object? GetProjectsComposition()
    {
        var portal = _connection.Portal;
        if (portal is null) return null;
        return portal.GetType().GetProperty("Projects")?.GetValue(portal);
    }

    private void AdoptProject(object? project, string fallbackDir)
    {
        _project = project;
        _projectName = GetPropString(project, "Name");
        _projectPath = GetPropString(project, "Path")
                       ?? GetPropString(project, "FilePath")
                       ?? FindApxxUnder(fallbackDir);
        if (string.IsNullOrWhiteSpace(_projectName) && !string.IsNullOrWhiteSpace(_projectPath))
        {
            _projectName = Path.GetFileNameWithoutExtension(_projectPath);
        }
    }

    private void TryResolvePlc(string? plcName)
    {
        _plcSoftware = null;
        _deviceName = null;
        _plcName = null;
        if (_project is null) return;
        TryResolvePlcSoftware(_project, plcName?.Trim() ?? "", out _plcSoftware, out _deviceName, out _plcName);
    }

    private void ClearProject()
    {
        _project = null;
        _plcSoftware = null;
        _projectPath = null;
        _projectName = null;
        _plcName = null;
        _deviceName = null;
    }

    private static string? FindApxxUnder(string dir)
    {
        if (!Directory.Exists(dir)) return null;
        try
        {
            return Directory.EnumerateFiles(dir, "*.ap*", SearchOption.AllDirectories)
                .Where(p =>
                {
                    var ext = Path.GetExtension(p);
                    return ext.StartsWith(".ap", StringComparison.OrdinalIgnoreCase) && ext.Length > 3;
                })
                .OrderByDescending(File.GetLastWriteTimeUtc)
                .FirstOrDefault();
        }
        catch
        {
            return null;
        }
    }

    private static object? GetProp(object? obj, string name) =>
        obj?.GetType().GetProperty(name)?.GetValue(obj);

    private static string? GetPropString(object? obj, string name) =>
        GetProp(obj, name)?.ToString();
}

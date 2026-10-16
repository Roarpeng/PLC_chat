using System.Collections.Generic;
using System.Text.Json.Serialization;

namespace TiaOpenness.Models;

/// <summary>Stable MCP / agent-facing DTOs for TIA Openness Milestone 1.</summary>
public static class JsonDefaults
{
    public static readonly System.Text.Json.JsonSerializerOptions Options = new()
    {
        PropertyNamingPolicy = System.Text.Json.JsonNamingPolicy.CamelCase,
        DefaultIgnoreCondition = JsonIgnoreCondition.WhenWritingNull,
        WriteIndented = false,
    };
}

public sealed class ToolError
{
    [JsonPropertyName("code")]
    public string Code { get; set; } = "error";

    [JsonPropertyName("message")]
    public string Message { get; set; } = "";

    [JsonPropertyName("retryable")]
    public bool Retryable { get; set; }
}

public sealed class TiaStatusResult
{
    [JsonPropertyName("ok")]
    public bool Ok { get; set; }

    [JsonPropertyName("tiaRunning")]
    public bool TiaRunning { get; set; }

    [JsonPropertyName("processCount")]
    public int ProcessCount { get; set; }

    [JsonPropertyName("opennessAvailable")]
    public bool OpennessAvailable { get; set; }

    /// <summary>
    /// True when the current process token includes local group "Siemens TIA Openness".
    /// Account membership alone is not enough — re-login after being added to the group.
    /// </summary>
    [JsonPropertyName("opennessGroupInToken")]
    public bool OpennessGroupInToken { get; set; }

    [JsonPropertyName("tiaVersion")]
    public string? TiaVersion { get; set; }

    [JsonPropertyName("engineeringDll")]
    public string? EngineeringDll { get; set; }

    [JsonPropertyName("connected")]
    public bool Connected { get; set; }

    [JsonPropertyName("projectOpen")]
    public bool ProjectOpen { get; set; }

    [JsonPropertyName("projectPath")]
    public string? ProjectPath { get; set; }

    [JsonPropertyName("projectName")]
    public string? ProjectName { get; set; }

    [JsonPropertyName("mode")]
    public string? Mode { get; set; }

    [JsonPropertyName("message")]
    public string? Message { get; set; }

    [JsonPropertyName("error")]
    public ToolError? Error { get; set; }
}

public sealed class OpenProjectResult
{
    [JsonPropertyName("ok")]
    public bool Ok { get; set; }

    [JsonPropertyName("projectPath")]
    public string? ProjectPath { get; set; }

    [JsonPropertyName("projectName")]
    public string? ProjectName { get; set; }

    [JsonPropertyName("plcName")]
    public string? PlcName { get; set; }

    [JsonPropertyName("deviceName")]
    public string? DeviceName { get; set; }

    [JsonPropertyName("message")]
    public string? Message { get; set; }

    [JsonPropertyName("error")]
    public ToolError? Error { get; set; }
}

public sealed class BlockInfo
{
    [JsonPropertyName("name")]
    public string Name { get; set; } = "";

    /// <summary>OB | FB | FC | DB | OTHER</summary>
    [JsonPropertyName("type")]
    public string Type { get; set; } = "OTHER";

    [JsonPropertyName("path")]
    public string? Path { get; set; }

    [JsonPropertyName("programmingLanguage")]
    public string? ProgrammingLanguage { get; set; }

    [JsonPropertyName("number")]
    public int? Number { get; set; }

    [JsonPropertyName("knowHowProtected")]
    public bool KnowHowProtected { get; set; }
}

public sealed class ListBlocksResult
{
    [JsonPropertyName("ok")]
    public bool Ok { get; set; }

    [JsonPropertyName("plcName")]
    public string? PlcName { get; set; }

    [JsonPropertyName("count")]
    public int Count { get; set; }

    [JsonPropertyName("blocks")]
    public List<BlockInfo> Blocks { get; set; } = new();

    [JsonPropertyName("byType")]
    public Dictionary<string, int>? ByType { get; set; }

    [JsonPropertyName("error")]
    public ToolError? Error { get; set; }
}

public sealed class ExportBlockResult
{
    [JsonPropertyName("ok")]
    public bool Ok { get; set; }

    [JsonPropertyName("blockName")]
    public string? BlockName { get; set; }

    [JsonPropertyName("blockType")]
    public string? BlockType { get; set; }

    [JsonPropertyName("exportPath")]
    public string? ExportPath { get; set; }

    [JsonPropertyName("exportedCount")]
    public int? ExportedCount { get; set; }

    [JsonPropertyName("failedCount")]
    public int? FailedCount { get; set; }

    [JsonPropertyName("compileMs")]
    public long? CompileMs { get; set; }

    [JsonPropertyName("listMs")]
    public long? ListMs { get; set; }

    [JsonPropertyName("exportMs")]
    public long? ExportMs { get; set; }

    [JsonPropertyName("knowHowProtectedCount")]
    public int? KnowHowProtectedCount { get; set; }

    [JsonPropertyName("message")]
    public string? Message { get; set; }

    [JsonPropertyName("error")]
    public ToolError? Error { get; set; }
}

public sealed class ImportBlockResult
{
    [JsonPropertyName("ok")]
    public bool Ok { get; set; }

    [JsonPropertyName("xmlPath")]
    public string? XmlPath { get; set; }

    [JsonPropertyName("overwrite")]
    public bool Overwrite { get; set; }

    [JsonPropertyName("kind")]
    public string? Kind { get; set; }

    [JsonPropertyName("importedNames")]
    public List<string>? ImportedNames { get; set; }

    [JsonPropertyName("api")]
    public string? Api { get; set; }

    [JsonPropertyName("skipReason")]
    public string? SkipReason { get; set; }

    [JsonPropertyName("message")]
    public string? Message { get; set; }

    [JsonPropertyName("error")]
    public ToolError? Error { get; set; }
}

/// <summary>
/// Result of External Source SCL import via
/// <c>PlcSoftware.ExternalSourceGroup.ExternalSources.CreateFromFile</c>
/// + <c>PlcExternalSource.GenerateBlocksFromSource()</c>
/// (Siemens TIA Portal Openness: "Generating blocks from source").
/// </summary>
public sealed class GenerateFromSourceResult
{
    [JsonPropertyName("ok")]
    public bool Ok { get; set; }

    [JsonPropertyName("sclPath")]
    public string? SclPath { get; set; }

    [JsonPropertyName("sourceName")]
    public string? SourceName { get; set; }

    [JsonPropertyName("overwrite")]
    public bool Overwrite { get; set; }

    [JsonPropertyName("generatedNames")]
    public List<string>? GeneratedNames { get; set; }

    [JsonPropertyName("api")]
    public string? Api { get; set; }

    [JsonPropertyName("message")]
    public string? Message { get; set; }

    [JsonPropertyName("error")]
    public ToolError? Error { get; set; }
}

/// <summary>
/// Fail-closed PLC software compile via <c>ICompilable.Compile()</c>.
/// Unlike export's best-effort skip, writeback must not archive when this fails
/// or when the compile API is unreachable.
/// </summary>
public sealed class CompilePlcResult
{
    [JsonPropertyName("ok")]
    public bool Ok { get; set; }

    [JsonPropertyName("apiAvailable")]
    public bool ApiAvailable { get; set; }

    [JsonPropertyName("state")]
    public string? State { get; set; }

    [JsonPropertyName("errorCount")]
    public int? ErrorCount { get; set; }

    [JsonPropertyName("warningCount")]
    public int? WarningCount { get; set; }

    [JsonPropertyName("inconsistentBlocks")]
    public List<string>? InconsistentBlocks { get; set; }

    [JsonPropertyName("message")]
    public string? Message { get; set; }

    [JsonPropertyName("error")]
    public ToolError? Error { get; set; }
}

public sealed class SaveProjectResult
{
    [JsonPropertyName("ok")]
    public bool Ok { get; set; }

    [JsonPropertyName("projectPath")]
    public string? ProjectPath { get; set; }

    [JsonPropertyName("projectName")]
    public string? ProjectName { get; set; }

    [JsonPropertyName("message")]
    public string? Message { get; set; }

    [JsonPropertyName("error")]
    public ToolError? Error { get; set; }
}

public sealed class ArchiveProjectResult
{
    [JsonPropertyName("ok")]
    public bool Ok { get; set; }

    [JsonPropertyName("projectPath")]
    public string? ProjectPath { get; set; }

    [JsonPropertyName("archivePath")]
    public string? ArchivePath { get; set; }

    [JsonPropertyName("message")]
    public string? Message { get; set; }

    [JsonPropertyName("error")]
    public ToolError? Error { get; set; }
}

/// <summary>
/// Official Openness <c>Projects.Retrieve(FileInfo, DirectoryInfo)</c> (chapter 5.x).
/// Unpacks a compressed <c>.zap*</c> into an on-disk <c>.apxx</c> project.
/// </summary>
public sealed class RetrieveProjectResult
{
    [JsonPropertyName("ok")]
    public bool Ok { get; set; }

    [JsonPropertyName("archivePath")]
    public string? ArchivePath { get; set; }

    [JsonPropertyName("targetDirectory")]
    public string? TargetDirectory { get; set; }

    [JsonPropertyName("projectPath")]
    public string? ProjectPath { get; set; }

    [JsonPropertyName("projectName")]
    public string? ProjectName { get; set; }

    [JsonPropertyName("plcName")]
    public string? PlcName { get; set; }

    [JsonPropertyName("api")]
    public string? Api { get; set; }

    [JsonPropertyName("message")]
    public string? Message { get; set; }

    [JsonPropertyName("error")]
    public ToolError? Error { get; set; }
}

/// <summary>
/// Official reverse of GenerateBlocksFromSource:
/// <c>PlcBlock.GenerateSourceFromBlocks(FileInfo)</c> (Openness 5.11.3.18).
/// </summary>
public sealed class GenerateSourceFromBlockResult
{
    [JsonPropertyName("ok")]
    public bool Ok { get; set; }

    [JsonPropertyName("blockName")]
    public string? BlockName { get; set; }

    [JsonPropertyName("sourcePath")]
    public string? SourcePath { get; set; }

    [JsonPropertyName("api")]
    public string? Api { get; set; }

    [JsonPropertyName("message")]
    public string? Message { get; set; }

    [JsonPropertyName("error")]
    public ToolError? Error { get; set; }
}

public sealed class CreateProjectResult
{
    [JsonPropertyName("ok")]
    public bool Ok { get; set; }

    [JsonPropertyName("projectPath")]
    public string? ProjectPath { get; set; }

    [JsonPropertyName("projectName")]
    public string? ProjectName { get; set; }

    [JsonPropertyName("api")]
    public string? Api { get; set; }

    [JsonPropertyName("message")]
    public string? Message { get; set; }

    [JsonPropertyName("error")]
    public ToolError? Error { get; set; }
}

public sealed class CloseProjectResult
{
    [JsonPropertyName("ok")]
    public bool Ok { get; set; }

    [JsonPropertyName("api")]
    public string? Api { get; set; }

    [JsonPropertyName("message")]
    public string? Message { get; set; }

    [JsonPropertyName("error")]
    public ToolError? Error { get; set; }
}

public sealed class ExportSkip
{
    [JsonPropertyName("category")]
    public string Category { get; set; } = "";

    [JsonPropertyName("name")]
    public string Name { get; set; } = "";

    [JsonPropertyName("reason")]
    public string Reason { get; set; } = "";

    [JsonPropertyName("detail")]
    public string? Detail { get; set; }
}

public sealed class ExportCategoryCount
{
    [JsonPropertyName("exported")]
    public int Exported { get; set; }

    [JsonPropertyName("failed")]
    public int Failed { get; set; }

    [JsonPropertyName("skipped")]
    public int Skipped { get; set; }
}

public sealed class CreateDeviceResult
{
    [JsonPropertyName("ok")]
    public bool Ok { get; set; }

    [JsonPropertyName("api")]
    public string Api { get; set; } = "Devices.CreateWithItem(typeIdentifier, name, deviceName)";

    [JsonPropertyName("deviceName")]
    public string? DeviceName { get; set; }

    [JsonPropertyName("typeIdentifier")]
    public string? TypeIdentifier { get; set; }

    [JsonPropertyName("orderNumber")]
    public string? OrderNumber { get; set; }

    [JsonPropertyName("version")]
    public string? Version { get; set; }

    [JsonPropertyName("message")]
    public string? Message { get; set; }

    [JsonPropertyName("error")]
    public ToolError? Error { get; set; }
}

public sealed class OpenLibraryResult
{
    [JsonPropertyName("ok")]
    public bool Ok { get; set; }

    [JsonPropertyName("api")]
    public string Api { get; set; } = "GlobalLibraries.Open(FileInfo, FileAccess)";

    [JsonPropertyName("libraryPath")]
    public string? LibraryPath { get; set; }

    [JsonPropertyName("libraryName")]
    public string? LibraryName { get; set; }

    [JsonPropertyName("masterCopiesCount")]
    public int MasterCopiesCount { get; set; }

    [JsonPropertyName("typesCount")]
    public int TypesCount { get; set; }

    [JsonPropertyName("masterCopies")]
    public List<string>? MasterCopies { get; set; }

    [JsonPropertyName("types")]
    public List<string>? Types { get; set; }

    [JsonPropertyName("message")]
    public string? Message { get; set; }

    [JsonPropertyName("error")]
    public ToolError? Error { get; set; }
}

public sealed class CopyLibraryResult
{
    [JsonPropertyName("ok")]
    public bool Ok { get; set; }

    [JsonPropertyName("api")]
    public string Api { get; set; } = "MasterCopy.CreateCopy(destination) / Type.CreateCopy(destination)";

    [JsonPropertyName("itemName")]
    public string? ItemName { get; set; }

    [JsonPropertyName("targetGroup")]
    public string? TargetGroup { get; set; }

    [JsonPropertyName("message")]
    public string? Message { get; set; }

    [JsonPropertyName("error")]
    public ToolError? Error { get; set; }
}

public sealed class TagInfo
{
    [JsonPropertyName("name")]
    public string Name { get; set; } = "";

    [JsonPropertyName("dataType")]
    public string DataType { get; set; } = "";

    [JsonPropertyName("logicalAddress")]
    public string LogicalAddress { get; set; } = "";

    [JsonPropertyName("comment")]
    public string? Comment { get; set; }
}

public sealed class TagTableDetailsResult
{
    [JsonPropertyName("ok")]
    public bool Ok { get; set; }

    [JsonPropertyName("tableName")]
    public string? TableName { get; set; }

    [JsonPropertyName("count")]
    public int Count { get; set; }

    [JsonPropertyName("tags")]
    public List<TagInfo>? Tags { get; set; }

    [JsonPropertyName("message")]
    public string? Message { get; set; }

    [JsonPropertyName("error")]
    public ToolError? Error { get; set; }
}


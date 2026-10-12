using System.ComponentModel;
using System.Text.Json;
using Microsoft.Extensions.DependencyInjection;
using Microsoft.Extensions.Hosting;
using Microsoft.Extensions.Logging;
using ModelContextProtocol.Server;
using TiaOpenness.Models;

namespace TiaOpenness.Server;

public static class Program
{
    public static async Task<int> Main(string[] args)
    {
        if (args.Length > 0 && string.Equals(args[0], "--cli", StringComparison.OrdinalIgnoreCase))
        {
            return RunCli(args.Skip(1).ToArray());
        }

        var builder = Host.CreateApplicationBuilder(args);

        builder.Logging.ClearProviders();
        // MCP stdio: never write protocol noise to stdout.
        builder.Logging.AddConsole(options =>
        {
            options.LogToStandardErrorThreshold = LogLevel.Trace;
        });

        var tiaVersion = Environment.GetEnvironmentVariable("TIA_VERSION") ?? TiaConnection.DefaultVersion;
        builder.Services.AddSingleton(new TiaConnection(tiaVersion));
        builder.Services.AddSingleton<ProjectService>();
        builder.Services.AddSingleton<BlockService>();
        builder.Services.AddSingleton<TiaOpennessTools>();

        builder.Services
            .AddMcpServer(options =>
            {
                options.ServerInfo = new()
                {
                    Name = "researchos-tia-openness",
                    Version = "0.1.0",
                };
            })
            .WithStdioServerTransport()
            .WithTools<TiaOpennessTools>();

        await builder.Build().RunAsync();
        return 0;
    }

    /// <summary>
    /// One-shot CLI for Python importer / CI (avoids holding an MCP stdio session).
    /// Examples:
    ///   TiaOpenness.Server.exe --cli status
    ///   TiaOpenness.Server.exe --cli export-project --project C:\p\x.ap19 --export-dir C:\out [--skip-compile]
    ///   TiaOpenness.Server.exe --cli import-block --project C:\p\x.ap19 --xml C:\b.xml
    /// </summary>
    private static int RunCli(string[] args)
    {
        if (args.Length == 0)
        {
            Console.Error.WriteLine(
                "Usage: --cli status | export-project --project <ap19> --export-dir <dir> [--plc name] [--version V19] [--skip-compile] [--full|--blocks-only] | " +
                "import-block --project <ap19> --xml <file> [--plc name] [--no-overwrite] [--version V19] | " +
                "import-xml --project <ap19> --xml <file> [--kind auto|block|type|tag|watch|force|hmi|hardware|cfc|to] [--plc name] [--no-overwrite] | " +
                "generate-from-source --project <ap19> --scl <file.scl> [--plc name] [--no-overwrite] [--version V19] | " +
                "generate-source-from-block --project <ap19> --block <name> [--out file.scl] [--plc name] [--version V19] | " +
                "retrieve --archive <file.zap*> --out-dir <dir> [--plc name] [--version V19] | " +
                "create-project --dir <dir> --name <projectName> [--version V19] | " +
                "close-project --project <ap19> [--version V19] | " +
                "compile-plc --project <ap19> [--plc name] [--version V19] | " +
                "archive-project --project <ap19> --out-dir <dir> [--name file.zap19] [--version V19] | " +
                "create-device --project <ap19> --type-id <id> --name <name> [--device-name <dname>] | " +
                "open-library --path <al19> [--write] | " +
                "copy-from-library --library <al19> --item <name> [--project <ap19>] [--target <group>] | " +
                "get-tags [--project <ap19>] [--table <name>]");
            return 2;
        }

        var command = args[0].ToLowerInvariant();
        var opts = ParseOpts(args.Skip(1).ToArray());
        var version = Environment.GetEnvironmentVariable("TIA_VERSION") ?? TiaConnection.DefaultVersion;
        if (opts.TryGetValue("version", out var versionOpt) && !string.IsNullOrWhiteSpace(versionOpt))
        {
            version = versionOpt;
        }

        using var connection = new TiaConnection(version);
        var projects = new ProjectService(connection);
        var blocks = new BlockService(projects);

        try
        {
            if (command == "status")
            {
                var status = connection.GetStatus();
                projects.ApplyStatus(status);
                Console.WriteLine(JsonSerializer.Serialize(status, JsonDefaults.Options));
                return status.OpennessGroupInToken && status.OpennessAvailable ? 0 : 1;
            }

            if (command == "export-project")
            {
                if (!opts.TryGetValue("project", out var project) || string.IsNullOrWhiteSpace(project))
                {
                    Console.Error.WriteLine("Missing --project");
                    return 2;
                }
                if (!opts.TryGetValue("export-dir", out var exportDir) || string.IsNullOrWhiteSpace(exportDir))
                {
                    Console.Error.WriteLine("Missing --export-dir");
                    return 2;
                }

                opts.TryGetValue("plc", out var plc);
                var skipCompile = IsTruthyFlag(opts, "skip-compile")
                    || IsTruthyEnv("TIA_EXPORT_SKIP_COMPILE");
                var blocksOnly = IsTruthyFlag(opts, "blocks-only")
                    || IsTruthyEnv("RESEARCHOS_TIA_EXPORT_BLOCKS_ONLY");
                var openSw = System.Diagnostics.Stopwatch.StartNew();
                var opened = projects.OpenProject(project, plc, withoutUi: true);
                openSw.Stop();
                if (!opened.Ok)
                {
                    Console.WriteLine(JsonSerializer.Serialize(opened, JsonDefaults.Options));
                    return 3;
                }

                var surface = new ExportSurface(projects, blocks);
                var exported = surface.Export(exportDir, skipCompile, blocksOnly);
                var payload = new
                {
                    ok = exported.Ok,
                    openMs = openSw.ElapsedMilliseconds,
                    project = opened,
                    export = exported,
                };
                Console.WriteLine(JsonSerializer.Serialize(payload, JsonDefaults.Options));
                return exported.Ok ? 0 : 4;
            }

            if (command == "import-block")
            {
                if (!opts.TryGetValue("project", out var project) || string.IsNullOrWhiteSpace(project))
                {
                    Console.Error.WriteLine("Missing --project");
                    return 2;
                }
                if (!opts.TryGetValue("xml", out var xml) || string.IsNullOrWhiteSpace(xml))
                {
                    Console.Error.WriteLine("Missing --xml");
                    return 2;
                }

                opts.TryGetValue("plc", out var plc);
                var overwrite = !opts.ContainsKey("no-overwrite");

                var opened = projects.OpenProject(project, plc, withoutUi: true);
                if (!opened.Ok)
                {
                    Console.WriteLine(JsonSerializer.Serialize(opened, JsonDefaults.Options));
                    return 3;
                }

                var imported = blocks.ImportBlock(xml, overwrite);
                if (!imported.Ok)
                {
                    var failPayload = new
                    {
                        ok = false,
                        project = opened,
                        import = imported,
                    };
                    Console.WriteLine(JsonSerializer.Serialize(failPayload, JsonDefaults.Options));
                    return 4;
                }

                var saved = projects.SaveProject();
                var importPayload = new
                {
                    ok = saved.Ok,
                    project = opened,
                    import = imported,
                    save = saved,
                };
                Console.WriteLine(JsonSerializer.Serialize(importPayload, JsonDefaults.Options));
                return saved.Ok ? 0 : 5;
            }

            if (command == "generate-from-source")
            {
                if (!opts.TryGetValue("project", out var project) || string.IsNullOrWhiteSpace(project))
                {
                    Console.Error.WriteLine("Missing --project");
                    return 2;
                }
                if (!opts.TryGetValue("scl", out var scl) || string.IsNullOrWhiteSpace(scl))
                {
                    Console.Error.WriteLine("Missing --scl");
                    return 2;
                }

                opts.TryGetValue("plc", out var plc);
                var overwrite = !opts.ContainsKey("no-overwrite");

                var opened = projects.OpenProject(project, plc, withoutUi: true);
                if (!opened.Ok)
                {
                    Console.WriteLine(JsonSerializer.Serialize(opened, JsonDefaults.Options));
                    return 3;
                }

                var generated = blocks.GenerateBlocksFromSource(scl, overwrite);
                if (!generated.Ok)
                {
                    var failPayload = new
                    {
                        ok = false,
                        project = opened,
                        generate = generated,
                    };
                    Console.WriteLine(JsonSerializer.Serialize(failPayload, JsonDefaults.Options));
                    return 4;
                }

                var saved = projects.SaveProject();
                var genPayload = new
                {
                    ok = saved.Ok,
                    project = opened,
                    generate = generated,
                    save = saved,
                };
                Console.WriteLine(JsonSerializer.Serialize(genPayload, JsonDefaults.Options));
                return saved.Ok ? 0 : 5;
            }

            if (command == "compile-plc")
            {
                if (!opts.TryGetValue("project", out var project) || string.IsNullOrWhiteSpace(project))
                {
                    Console.Error.WriteLine("Missing --project");
                    return 2;
                }

                opts.TryGetValue("plc", out var plc);
                var opened = projects.OpenProject(project, plc, withoutUi: true);
                if (!opened.Ok)
                {
                    Console.WriteLine(JsonSerializer.Serialize(opened, JsonDefaults.Options));
                    return 3;
                }

                var compiled = blocks.CompilePlcSoftwareStrict();
                var compilePayload = new
                {
                    ok = compiled.Ok,
                    project = opened,
                    compile = compiled,
                };
                Console.WriteLine(JsonSerializer.Serialize(compilePayload, JsonDefaults.Options));
                return compiled.Ok ? 0 : 6;
            }

            if (command == "archive-project")
            {
                if (!opts.TryGetValue("project", out var project) || string.IsNullOrWhiteSpace(project))
                {
                    Console.Error.WriteLine("Missing --project");
                    return 2;
                }
                if (!opts.TryGetValue("out-dir", out var outDir) || string.IsNullOrWhiteSpace(outDir))
                {
                    Console.Error.WriteLine("Missing --out-dir");
                    return 2;
                }

                opts.TryGetValue("name", out var archiveName);
                opts.TryGetValue("plc", out var plc);

                var opened = projects.OpenProject(project, plc, withoutUi: true);
                if (!opened.Ok)
                {
                    Console.WriteLine(JsonSerializer.Serialize(opened, JsonDefaults.Options));
                    return 3;
                }

                var archived = projects.ArchiveProject(outDir, archiveName);
                var archivePayload = new
                {
                    ok = archived.Ok,
                    project = opened,
                    archive = archived,
                };
                Console.WriteLine(JsonSerializer.Serialize(archivePayload, JsonDefaults.Options));
                return archived.Ok ? 0 : 4;
            }

            if (command == "import-xml")
            {
                if (!opts.TryGetValue("project", out var project) || string.IsNullOrWhiteSpace(project))
                {
                    Console.Error.WriteLine("Missing --project");
                    return 2;
                }
                if (!opts.TryGetValue("xml", out var xml) || string.IsNullOrWhiteSpace(xml))
                {
                    Console.Error.WriteLine("Missing --xml");
                    return 2;
                }

                opts.TryGetValue("plc", out var plc);
                opts.TryGetValue("kind", out var kind);
                var overwrite = !opts.ContainsKey("no-overwrite");

                var opened = projects.OpenProject(project, plc, withoutUi: true);
                if (!opened.Ok)
                {
                    Console.WriteLine(JsonSerializer.Serialize(opened, JsonDefaults.Options));
                    return 3;
                }

                var imported = blocks.ImportXml(xml, overwrite, kind);
                if (!imported.Ok)
                {
                    Console.WriteLine(JsonSerializer.Serialize(new { ok = false, project = opened, import = imported }, JsonDefaults.Options));
                    return 4;
                }

                var saved = projects.SaveProject();
                Console.WriteLine(JsonSerializer.Serialize(new { ok = saved.Ok, project = opened, import = imported, save = saved }, JsonDefaults.Options));
                return saved.Ok ? 0 : 5;
            }

            if (command == "generate-source-from-block")
            {
                if (!opts.TryGetValue("project", out var project) || string.IsNullOrWhiteSpace(project))
                {
                    Console.Error.WriteLine("Missing --project");
                    return 2;
                }
                if (!opts.TryGetValue("block", out var blockName) || string.IsNullOrWhiteSpace(blockName))
                {
                    Console.Error.WriteLine("Missing --block");
                    return 2;
                }

                opts.TryGetValue("plc", out var plc);
                opts.TryGetValue("out", out var sourceOut);
                opts.TryGetValue("type", out var typeHint);

                var opened = projects.OpenProject(project, plc, withoutUi: true);
                if (!opened.Ok)
                {
                    Console.WriteLine(JsonSerializer.Serialize(opened, JsonDefaults.Options));
                    return 3;
                }

                var generated = blocks.GenerateSourceFromBlock(blockName, sourceOut, typeHint);
                Console.WriteLine(JsonSerializer.Serialize(new { ok = generated.Ok, project = opened, generate = generated }, JsonDefaults.Options));
                return generated.Ok ? 0 : 4;
            }

            if (command == "retrieve")
            {
                if (!opts.TryGetValue("archive", out var archive) || string.IsNullOrWhiteSpace(archive))
                {
                    Console.Error.WriteLine("Missing --archive");
                    return 2;
                }
                if (!opts.TryGetValue("out-dir", out var outDir) || string.IsNullOrWhiteSpace(outDir))
                {
                    Console.Error.WriteLine("Missing --out-dir");
                    return 2;
                }

                opts.TryGetValue("plc", out var plc);
                var retrieved = projects.RetrieveProject(archive, outDir, plc);
                Console.WriteLine(JsonSerializer.Serialize(new { ok = retrieved.Ok, retrieve = retrieved }, JsonDefaults.Options));
                return retrieved.Ok ? 0 : 4;
            }

            if (command == "create-project")
            {
                if (!opts.TryGetValue("dir", out var dir) || string.IsNullOrWhiteSpace(dir))
                {
                    Console.Error.WriteLine("Missing --dir");
                    return 2;
                }
                if (!opts.TryGetValue("name", out var name) || string.IsNullOrWhiteSpace(name))
                {
                    Console.Error.WriteLine("Missing --name");
                    return 2;
                }

                var created = projects.CreateProject(dir, name);
                Console.WriteLine(JsonSerializer.Serialize(new { ok = created.Ok, create = created }, JsonDefaults.Options));
                return created.Ok ? 0 : 4;
            }

            if (command == "close-project")
            {
                if (!opts.TryGetValue("project", out var project) || string.IsNullOrWhiteSpace(project))
                {
                    Console.Error.WriteLine("Missing --project");
                    return 2;
                }

                opts.TryGetValue("plc", out var plc);
                var opened = projects.OpenProject(project, plc, withoutUi: true);
                if (!opened.Ok)
                {
                    Console.WriteLine(JsonSerializer.Serialize(opened, JsonDefaults.Options));
                    return 3;
                }

                var closed = projects.CloseProject();
                Console.WriteLine(JsonSerializer.Serialize(new { ok = closed.Ok, project = opened, close = closed }, JsonDefaults.Options));
                return closed.Ok ? 0 : 4;
            }

            if (command == "create-to")
            {
                if (!opts.TryGetValue("project", out var project) || string.IsNullOrWhiteSpace(project))
                {
                    Console.Error.WriteLine("Missing --project");
                    return 2;
                }
                if (!opts.TryGetValue("name", out var toName) || string.IsNullOrWhiteSpace(toName))
                {
                    Console.Error.WriteLine("Missing --name");
                    return 2;
                }
                opts.TryGetValue("plc", out var plc);
                opts.TryGetValue("type-id", out var typeId);
                var opened = projects.OpenProject(project, plc, withoutUi: true);
                if (!opened.Ok)
                {
                    Console.WriteLine(JsonSerializer.Serialize(opened, JsonDefaults.Options));
                    return 3;
                }
                var created = blocks.CreateTechnologicalObject(toName, typeId);
                var saved = created.Ok ? projects.SaveProject() : null;
                Console.WriteLine(JsonSerializer.Serialize(new { ok = created.Ok && (saved is null || saved.Ok), project = opened, create = created, save = saved }, JsonDefaults.Options));
                return created.Ok ? 0 : 4;
            }

            if (command == "delete-to")
            {
                if (!opts.TryGetValue("project", out var project) || string.IsNullOrWhiteSpace(project))
                {
                    Console.Error.WriteLine("Missing --project");
                    return 2;
                }
                if (!opts.TryGetValue("name", out var toName) || string.IsNullOrWhiteSpace(toName))
                {
                    Console.Error.WriteLine("Missing --name");
                    return 2;
                }
                opts.TryGetValue("plc", out var plc);
                var opened = projects.OpenProject(project, plc, withoutUi: true);
                if (!opened.Ok)
                {
                    Console.WriteLine(JsonSerializer.Serialize(opened, JsonDefaults.Options));
                    return 3;
                }
                var deleted = blocks.DeleteTechnologicalObject(toName);
                var saved = deleted.Ok ? projects.SaveProject() : null;
                Console.WriteLine(JsonSerializer.Serialize(new { ok = deleted.Ok && (saved is null || saved.Ok), project = opened, delete = deleted, save = saved }, JsonDefaults.Options));
                return deleted.Ok ? 0 : 4;
            }

            if (command == "create-device")
            {
                if (!opts.TryGetValue("project", out var project) || string.IsNullOrWhiteSpace(project))
                {
                    Console.Error.WriteLine("Missing --project");
                    return 2;
                }
                if (!opts.TryGetValue("type-id", out var typeId) || string.IsNullOrWhiteSpace(typeId))
                {
                    Console.Error.WriteLine("Missing --type-id (e.g. OrderNumber:6ES7 511-1AK01-0AB0/V2.5)");
                    return 2;
                }
                if (!opts.TryGetValue("name", out var dName) || string.IsNullOrWhiteSpace(dName))
                {
                    Console.Error.WriteLine("Missing --name");
                    return 2;
                }
                opts.TryGetValue("device-name", out var deviceName);
                opts.TryGetValue("plc", out var plc);

                var opened = projects.OpenProject(project, plc, withoutUi: true);
                if (!opened.Ok)
                {
                    Console.WriteLine(JsonSerializer.Serialize(opened, JsonDefaults.Options));
                    return 3;
                }

                var created = projects.CreateDevice(typeId, dName, deviceName);
                var saved = created.Ok ? projects.SaveProject() : null;
                Console.WriteLine(JsonSerializer.Serialize(new { ok = created.Ok && (saved is null || saved.Ok), project = opened, create = created, save = saved }, JsonDefaults.Options));
                return created.Ok ? 0 : 4;
            }

            if (command == "open-library")
            {
                if (!opts.TryGetValue("path", out var libPath) || string.IsNullOrWhiteSpace(libPath))
                {
                    Console.Error.WriteLine("Missing --path");
                    return 2;
                }
                var readOnly = !IsTruthyFlag(opts, "write");
                var opened = projects.OpenGlobalLibrary(libPath, readOnly);
                Console.WriteLine(JsonSerializer.Serialize(new { ok = opened.Ok, library = opened }, JsonDefaults.Options));
                return opened.Ok ? 0 : 4;
            }

            if (command == "copy-from-library")
            {
                if (!opts.TryGetValue("library", out var libPath) || string.IsNullOrWhiteSpace(libPath))
                {
                    Console.Error.WriteLine("Missing --library");
                    return 2;
                }
                if (!opts.TryGetValue("item", out var itemName) || string.IsNullOrWhiteSpace(itemName))
                {
                    Console.Error.WriteLine("Missing --item");
                    return 2;
                }
                opts.TryGetValue("target", out var targetGroup);
                if (opts.TryGetValue("project", out var project) && !string.IsNullOrWhiteSpace(project))
                {
                    opts.TryGetValue("plc", out var plc);
                    var opened = projects.OpenProject(project, plc, withoutUi: true);
                    if (!opened.Ok)
                    {
                        Console.WriteLine(JsonSerializer.Serialize(opened, JsonDefaults.Options));
                        return 3;
                    }
                }
                var copied = projects.CopyFromLibrary(libPath, itemName, targetGroup);
                var saved = copied.Ok && projects.IsProjectOpen ? projects.SaveProject() : null;
                Console.WriteLine(JsonSerializer.Serialize(new { ok = copied.Ok && (saved is null || saved.Ok), copy = copied, save = saved }, JsonDefaults.Options));
                return copied.Ok ? 0 : 4;
            }

            if (command == "get-tags")
            {
                if (opts.TryGetValue("project", out var project) && !string.IsNullOrWhiteSpace(project))
                {
                    opts.TryGetValue("plc", out var plc);
                    var opened = projects.OpenProject(project, plc, withoutUi: true);
                    if (!opened.Ok)
                    {
                        Console.WriteLine(JsonSerializer.Serialize(opened, JsonDefaults.Options));
                        return 3;
                    }
                }
                opts.TryGetValue("table", out var tableName);
                var details = blocks.GetTagTable(tableName);
                Console.WriteLine(JsonSerializer.Serialize(new { ok = details.Ok, tags = details }, JsonDefaults.Options));
                return details.Ok ? 0 : 4;
            }

            Console.Error.WriteLine("Unknown CLI command: " + command);
            return 2;
        }
        finally
        {
            connection.Disconnect();
        }
    }

    private static Dictionary<string, string> ParseOpts(string[] args)
    {
        var map = new Dictionary<string, string>(StringComparer.OrdinalIgnoreCase);
        for (var i = 0; i < args.Length; i++)
        {
            var a = args[i];
            if (!a.StartsWith("--", StringComparison.Ordinal)) continue;
            var key = a[2..];
            var value = "true";
            if (i + 1 < args.Length && !args[i + 1].StartsWith("--", StringComparison.Ordinal))
            {
                value = args[++i];
            }
            map[key] = value;
        }
        return map;
    }

    private static bool IsTruthyFlag(Dictionary<string, string> opts, string key)
    {
        if (!opts.TryGetValue(key, out var raw) || string.IsNullOrWhiteSpace(raw)) return false;
        return IsTruthy(raw);
    }

    private static bool IsTruthyEnv(string name)
    {
        var raw = Environment.GetEnvironmentVariable(name);
        return !string.IsNullOrWhiteSpace(raw) && IsTruthy(raw);
    }

    private static bool IsTruthy(string raw)
    {
        var v = raw.Trim();
        return v.Equals("1", StringComparison.OrdinalIgnoreCase)
            || v.Equals("true", StringComparison.OrdinalIgnoreCase)
            || v.Equals("yes", StringComparison.OrdinalIgnoreCase)
            || v.Equals("on", StringComparison.OrdinalIgnoreCase);
    }
}

[McpServerToolType]
public sealed class TiaOpennessTools
{
    private static readonly JsonSerializerOptions Json = JsonDefaults.Options;

    private readonly TiaConnection _connection;
    private readonly ProjectService _projects;
    private readonly BlockService _blocks;

    public TiaOpennessTools(TiaConnection connection, ProjectService projects, BlockService blocks)
    {
        _connection = connection;
        _projects = projects;
        _blocks = blocks;
    }

    [McpServerTool(Name = "tia.get_status"), Description(
        "Detect whether TIA Portal is running and whether Openness PublicAPI is available. " +
        "Also reports whether this MCP server currently holds a Portal/project connection.")]
    public string GetStatus()
    {
        var status = _connection.GetStatus();
        _projects.ApplyStatus(status);
        return JsonSerializer.Serialize(status, Json);
    }

    [McpServerTool(Name = "tia.open_project"), Description(
        "Open a Siemens TIA Portal project (.ap19 preferred for Milestone 1) via Openness. " +
        "Optionally select a PLC by device/software name.")]
    public string OpenProject(
        [Description("Absolute path to the TIA project file (.ap19 / .ap18 / .ap17 / .ap20).")] string project_path,
        [Description("Optional PLC device or software name. Empty = first PLC found.")] string? plc_name = null,
        [Description("Start Portal without UI when attach is unavailable (default true).")] bool without_ui = true)
    {
        var result = _projects.OpenProject(project_path, plc_name, without_ui);
        return JsonSerializer.Serialize(result, Json);
    }

    [McpServerTool(Name = "tia.list_blocks"), Description(
        "List PLC blocks from the open project. Types: OB, FB, FC, DB. " +
        "Requires a successful tia.open_project call first.")]
    public string ListBlocks(
        [Description("Optional type filter: OB | FB | FC | DB. Omit or * for all.")] string? type = null)
    {
        try
        {
            var result = _blocks.ListBlocks(type);
            return JsonSerializer.Serialize(result, Json);
        }
        catch (ArgumentException ex)
        {
            var fail = new ListBlocksResult
            {
                Ok = false,
                Error = new ToolError { Code = "invalid_argument", Message = ex.Message },
            };
            return JsonSerializer.Serialize(fail, Json);
        }
    }

    [McpServerTool(Name = "tia.export_block"), Description(
        "Export one PLC block to SimaticML XML via Openness Export(WithDefaults). " +
        "Downstream: XML → PLC Parser → PLC-IR → Neo4j → PLC Agent.")]
    public string ExportBlock(
        [Description("Block name, e.g. OB1, FB_Motor, FC10, DB_Data.")] string block_name,
        [Description("Output XML path. Default: %TEMP%/researchos-tia-export/<block>.xml")] string? export_path = null,
        [Description("Optional type hint OB|FB|FC|DB when names collide.")] string? type = null)
    {
        var result = _blocks.ExportBlock(block_name, export_path, type);
        return JsonSerializer.Serialize(result, Json);
    }

    [McpServerTool(Name = "tia.export_project"), Description(
        "Export the official Openness chapter-6 surface (PLC groups, hardware, HMI structure) " +
        "into export_dir (plc/<name>/..., hardware/, hmi/, manifest.json). " +
        "blocks_only=true keeps the legacy Blocks/ layout. Feed the directory to plc.tia.analyze / plc.tia.ingest.")]
    public string ExportProject(
        [Description("Output directory for SimaticML / AML XML (full layout or Blocks/).")] string export_dir,
        [Description("Skip ICompilable compile before export (default false).")] bool skip_compile = false,
        [Description("When true, only export OB/FB/FC/DB into Blocks/ (legacy). Default false = full official surface.")] bool blocks_only = false)
    {
        var surface = new ExportSurface(_projects, _blocks);
        var result = surface.Export(export_dir, skip_compile, blocks_only);
        return JsonSerializer.Serialize(result, Json);
    }

    [McpServerTool(Name = "tia.import_block"), Description(
        "Import a SimaticML block XML into the open project via Blocks.Import(FileInfo, ImportOptions). " +
        "Does not persist — call tia.save_project afterwards. overwrite=true uses ImportOptions.Override.")]
    public string ImportBlock(
        [Description("Absolute path to SimaticML block XML.")] string xml_path,
        [Description("When true, use ImportOptions.Override; when false, ImportOptions.None.")] bool overwrite = true)
    {
        var result = _blocks.ImportBlock(xml_path, overwrite);
        return JsonSerializer.Serialize(result, Json);
    }

    [McpServerTool(Name = "tia.generate_from_source"), Description(
        "Import an SCL external source via PlcSoftware.ExternalSourceGroup.ExternalSources.CreateFromFile " +
        "then PlcExternalSource.GenerateBlocksFromSource(). Refuses Safety/F-block SCL. " +
        "Does not persist — call tia.save_project afterwards. Windows HostGateway only.")]
    public string GenerateFromSource(
        [Description("Absolute path to an ASCII .scl external source.")] string scl_path,
        [Description("When true, replace an existing external source of the same name.")] bool overwrite = true)
    {
        var result = _blocks.GenerateBlocksFromSource(scl_path, overwrite);
        return JsonSerializer.Serialize(result, Json);
    }

    [McpServerTool(Name = "tia.compile_plc"), Description(
        "Compile the open PLC software via ICompilable.Compile(). Fail-closed: if the compile API " +
        "is unreachable or ErrorCount>0, ok=false and callers must not archive .zap.")]
    public string CompilePlc()
    {
        var result = _blocks.CompilePlcSoftwareStrict();
        return JsonSerializer.Serialize(result, Json);
    }

    [McpServerTool(Name = "tia.save_project"), Description(
        "Save the currently open TIA project via Project.Save(). Call after tia.import_block.")]
    public string SaveProject()
    {
        var result = _projects.SaveProject();
        return JsonSerializer.Serialize(result, Json);
    }

    [McpServerTool(Name = "tia.archive_project"), Description(
        "Archive the open TIA project to a compressed .zap* file via Project.Archive(..., Compressed). " +
        "Use after import+save when the caller needs a downloadable Siemens archive.")]
    public string ArchiveProject(
        [Description("Target directory for the archive file.")] string out_dir,
        [Description("Archive file name, e.g. Line.zap19. Empty = derive from .apxx stem/version.")] string? name = null)
    {
        var result = _projects.ArchiveProject(out_dir, name);
        return JsonSerializer.Serialize(result, Json);
    }

    [McpServerTool(Name = "tia.import_xml"), Description(
        "Import SimaticML / AML / HMI XML into the matching Openness composition when Import exists " +
        "(types, tag tables, watch/force, HMI, CAx AML, CFC, TO). Missing Import fails closed with no_import. " +
        "Refuses Safety/F-block XML. Does not persist — call tia.save_project afterwards.")]
    public string ImportXml(
        [Description("Absolute path to SimaticML / AML / HMI XML.")] string xml_path,
        [Description("auto | block | type | tag | watch | force | hmi | hardware | cfc | to")] string? kind = "auto",
        [Description("When true, use ImportOptions.Override; when false, ImportOptions.None.")] bool overwrite = true)
    {
        var result = _blocks.ImportXml(xml_path, overwrite, kind);
        return JsonSerializer.Serialize(result, Json);
    }

    [McpServerTool(Name = "tia.generate_source_from_block"), Description(
        "Generate an SCL external source FROM a writable non-safety PLC block via " +
        "PlcBlock.GenerateSourceFromBlocks(FileInfo) (Openness 5.11.3.18). Refuses F-blocks. " +
        "Fails closed if the method is absent on this Openness build.")]
    public string GenerateSourceFromBlock(
        [Description("Block name, e.g. FB_Motor.")] string block_name,
        [Description("Output .scl path. Default: %TEMP%/researchos-tia-source/<block>.scl")] string? source_path = null,
        [Description("Optional type hint OB|FB|FC|DB when names collide.")] string? type = null)
    {
        var result = _blocks.GenerateSourceFromBlock(block_name, source_path, type);
        return JsonSerializer.Serialize(result, Json);
    }

    [McpServerTool(Name = "tia.retrieve_project"), Description(
        "Retrieve a Siemens .zap* archive via official Openness Projects.Retrieve(FileInfo, DirectoryInfo). " +
        "Writes an on-disk .apxx under out_dir. Windows HostGateway only.")]
    public string RetrieveProject(
        [Description("Absolute path to a .zap / .zap19 archive.")] string archive_path,
        [Description("Directory that will receive the retrieved .apxx project.")] string out_dir,
        [Description("Optional PLC device or software name.")] string? plc_name = null)
    {
        var result = _projects.RetrieveProject(archive_path, out_dir, plc_name);
        return JsonSerializer.Serialize(result, Json);
    }

    [McpServerTool(Name = "tia.create_project"), Description(
        "Create an empty TIA project via Projects.Create(DirectoryInfo, string) when that member exists. " +
        "Fails closed if the API is absent.")]
    public string CreateProject(
        [Description("Target directory for the new project.")] string target_directory,
        [Description("Project name.")] string project_name)
    {
        var result = _projects.CreateProject(target_directory, project_name);
        return JsonSerializer.Serialize(result, Json);
    }

    [McpServerTool(Name = "tia.close_project"), Description(
        "Close the currently open TIA project via Project.Close() when that member exists.")]
    public string CloseProject()
    {
        var result = _projects.CloseProject();
        return JsonSerializer.Serialize(result, Json);
    }

    [McpServerTool(Name = "tia.create_device"), Description(
        "Create a hardware device/CPU via Devices.CreateWithItem(typeIdentifier, name, deviceName). " +
        "Example type_identifier: 'OrderNumber:6ES7 511-1AK01-0AB0/V2.5' or 'OrderNumber:6ES7 516-3AN02-0AB0/V2.9'.")]
    public string CreateDevice(
        [Description("Device TypeIdentifier (OrderNumber:xxxx/Vxx)")] string type_identifier,
        [Description("Device or CPU name in project")] string name,
        [Description("Optional station/device name")] string? device_name = null)
    {
        var result = _projects.CreateDevice(type_identifier, name, device_name);
        return JsonSerializer.Serialize(result, Json);
    }

    [McpServerTool(Name = "tia.open_library"), Description(
        "Open a Siemens Global Library (.al14-.al20) via GlobalLibraries.Open(FileInfo, FileAccess) " +
        "and list available MasterCopies and Types.")]
    public string OpenLibrary(
        [Description("Absolute path to .al17/.al18/.al19 global library file.")] string library_path,
        [Description("Open in read-only mode (default true)")] bool read_only = true)
    {
        var result = _projects.OpenGlobalLibrary(library_path, read_only);
        return JsonSerializer.Serialize(result, Json);
    }

    [McpServerTool(Name = "tia.copy_from_library"), Description(
        "Copy a MasterCopy or LibraryType from an open Global Library into the current project.")]
    public string CopyFromLibrary(
        [Description("Library path or library name previously opened.")] string library_path_or_name,
        [Description("Name of the master copy or type to copy.")] string item_name,
        [Description("Target folder/group name in project (optional)")] string? target_group = null)
    {
        var result = _projects.CopyFromLibrary(library_path_or_name, item_name, target_group);
        return JsonSerializer.Serialize(result, Json);
    }

    [McpServerTool(Name = "tia.get_tag_table"), Description(
        "Inspect and list PLC tags from a TagTable in the open project.")]
    public string GetTagTable(
        [Description("Optional tag table name (empty = default/first table)")] string? table_name = null)
    {
        var result = _blocks.GetTagTable(table_name);
        return JsonSerializer.Serialize(result, Json);
    }
}

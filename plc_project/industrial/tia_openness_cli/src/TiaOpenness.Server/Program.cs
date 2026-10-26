using System.Text.Json;
using TiaOpenness.Models;

namespace TiaOpenness.Server;

/// <summary>
/// Siemens TIA Portal Openness one-shot CLI (PublicAPI V19).
/// Wraps official Openness calls (Projects.Open / Retrieve / Archive, PlcBlock.Export,
/// Blocks.Import, GenerateBlocksFromSource, ICompilable.Compile, …). No MCP / no agent session.
/// </summary>
public static class Program
{
    public static int Main(string[] args)
    {
        // Keep optional `--cli` prefix so existing Python callers keep working.
        if (args.Length > 0 && string.Equals(args[0], "--cli", StringComparison.OrdinalIgnoreCase))
        {
            args = args.Skip(1).ToArray();
        }
        if (args.Length > 0 && string.Equals(args[0], "serve", StringComparison.OrdinalIgnoreCase))
        {
            return RunServe(args.Skip(1).ToArray());
        }
        var rc = RunCli(args);
        Environment.Exit(rc);
        return rc;
    }

    private static int RunServe(string[] args)
    {
        var opts = ParseOpts(args);
        var host = opts.TryGetValue("host", out var h) && !string.IsNullOrWhiteSpace(h) ? h : "127.0.0.1";
        var port = 8791;
        if (opts.TryGetValue("port", out var p) && int.TryParse(p, out var parsed))
            port = parsed;
        opts.TryGetValue("token", out var token);
        token ??= Environment.GetEnvironmentVariable("RESEARCHOS_TIA_SESSION_TOKEN");
        using var server = new SessionServer(host, port, token);
        server.Run();
        return 0;
    }

    /// <summary>
    /// One-shot JSON CLI for gateway import / writeback / CI.
    /// Examples:
    ///   TiaOpenness.Server.exe status
    ///   TiaOpenness.Server.exe export-project --project C:\p\x.ap19 --export-dir C:\out
    ///   TiaOpenness.Server.exe retrieve --archive C:\In\Line.zap19 --out-dir C:\Projects
    /// </summary>
    private static int RunCli(string[] args)
    {
        if (args.Length == 0)
        {
            Console.Error.WriteLine(
                "Usage: TiaOpenness.Server.exe [--cli] <command> [options]\n" +
                "Commands (Siemens Openness PublicAPI):\n" +
                "  status\n" +
                "  open-project --project <ap19> [--plc name] [--version V19]\n" +
                "  list-blocks --project <ap19> [--type OB|FB|FC|DB] [--plc name]\n" +
                "  export-block --project <ap19> --block <name> [--out file.xml] [--type OB|FB|FC|DB] [--plc name]\n" +
                "  export-project --project <ap19> --export-dir <dir> [--plc name] [--skip-compile] [--blocks-only|--canvas|--full]\n" +
                "  import-block --project <ap19> --xml <file> [--plc name] [--no-overwrite]\n" +
                "  import-xml --project <ap19> --xml <file> [--kind auto|block|type|tag|watch|force|hmi|hardware|cfc|to] [--no-overwrite]\n" +
                "  generate-from-source --project <ap19> --scl <file.scl> [--plc name] [--no-overwrite]\n" +
                "  generate-source-from-block --project <ap19> --block <name> [--out file.scl] [--plc name]\n" +
                "  retrieve --archive <file.zap*> --out-dir <dir> [--plc name]\n" +
                "  create-project --dir <dir> --name <projectName>\n" +
                "  close-project --project <ap19>\n" +
                "  compile-plc --project <ap19> [--plc name]\n" +
                "  compile-hmi --project <ap19> [--hmi name]\n" +
                "  hmi-unified-apply --project <ap19> --ops <ops.json> [--hmi name]\n" +
                "  serve [--host 127.0.0.1] [--port 8791] [--token secret]\n" +
                "  archive-project --project <ap19> --out-dir <dir> [--name file.zap19]\n" +
                "  create-device --project <ap19> --type-id <id> --name <name> [--device-name <dname>]\n" +
                "  probe-device-types --project <ap19> --type-ids <id1|id2|...> (probe only, never saves)\n" +
                "  open-library --path <al19> [--write]\n" +
                "  copy-from-library --library <al19> --item <name> [--project <ap19>] [--target <group>]\n" +
                "  get-tags --project <ap19> [--table <name>]");
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

            // Projects.Open — one-shot probe/open (process exits after JSON; Portal may stay if without UI)
            if (command == "open-project")
            {
                if (!opts.TryGetValue("project", out var project) || string.IsNullOrWhiteSpace(project))
                {
                    Console.Error.WriteLine("Missing --project");
                    return 2;
                }
                opts.TryGetValue("plc", out var plc);
                var opened = projects.OpenProject(project, plc, withoutUi: true);
                Console.WriteLine(JsonSerializer.Serialize(opened, JsonDefaults.Options));
                return opened.Ok ? 0 : 3;
            }

            // List OB/FB/FC/DB from PlcSoftware.BlockGroup (opens + lists + closes)
            if (command == "list-blocks")
            {
                if (!opts.TryGetValue("project", out var project) || string.IsNullOrWhiteSpace(project))
                {
                    Console.Error.WriteLine("Missing --project");
                    return 2;
                }
                opts.TryGetValue("plc", out var plc);
                opts.TryGetValue("type", out var typeFilter);
                var opened = projects.OpenProject(project, plc, withoutUi: true);
                if (!opened.Ok)
                {
                    Console.WriteLine(JsonSerializer.Serialize(opened, JsonDefaults.Options));
                    return 3;
                }
                try
                {
                    var listed = blocks.ListBlocks(typeFilter);
                    projects.CloseProject();
                    Console.WriteLine(JsonSerializer.Serialize(new { ok = listed.Ok, project = opened, blocks = listed }, JsonDefaults.Options));
                    return listed.Ok ? 0 : 4;
                }
                catch (ArgumentException ex)
                {
                    projects.CloseProject();
                    Console.WriteLine(JsonSerializer.Serialize(new
                    {
                        ok = false,
                        project = opened,
                        error = new { code = "invalid_argument", message = ex.Message },
                    }, JsonDefaults.Options));
                    return 4;
                }
            }

            // PlcBlock.Export(FileInfo, ExportOptions.WithDefaults)
            if (command == "export-block")
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
                opts.TryGetValue("out", out var exportPath);
                opts.TryGetValue("type", out var typeHint);
                var opened = projects.OpenProject(project, plc, withoutUi: true);
                if (!opened.Ok)
                {
                    Console.WriteLine(JsonSerializer.Serialize(opened, JsonDefaults.Options));
                    return 3;
                }
                var exported = blocks.ExportBlock(blockName, exportPath, typeHint);
                projects.CloseProject();
                Console.WriteLine(JsonSerializer.Serialize(new { ok = exported.Ok, project = opened, export = exported }, JsonDefaults.Options));
                return exported.Ok ? 0 : 4;
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
                var canvasMode = IsTruthyFlag(opts, "canvas")
                    || string.Equals(Environment.GetEnvironmentVariable("RESEARCHOS_TIA_EXPORT_MODE"), "canvas", StringComparison.OrdinalIgnoreCase);
                var fullMode = IsTruthyFlag(opts, "full");
                var blocksOnly = !canvasMode && !fullMode && (
                    IsTruthyFlag(opts, "blocks-only")
                    || IsTruthyEnv("RESEARCHOS_TIA_EXPORT_BLOCKS_ONLY"));
                // --canvas wins over blocks-only; --full exports everything
                if (fullMode)
                {
                    blocksOnly = false;
                    canvasMode = false;
                }
                var openSw = System.Diagnostics.Stopwatch.StartNew();
                var opened = projects.OpenProject(project, plc, withoutUi: true);
                openSw.Stop();
                if (!opened.Ok)
                {
                    Console.WriteLine(JsonSerializer.Serialize(opened, JsonDefaults.Options));
                    return 3;
                }

                var surface = new ExportSurface(projects, blocks);
                var exported = surface.Export(exportDir, skipCompile, blocksOnly, canvasMode);
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

                opts.TryGetValue("unit", out var unit);
                if (string.IsNullOrWhiteSpace(unit)) opts.TryGetValue("software-unit", out unit);
                var imported = blocks.ImportBlock(xml, overwrite, unit);
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

                opts.TryGetValue("unit", out var unit);
                if (string.IsNullOrWhiteSpace(unit)) opts.TryGetValue("software-unit", out unit);
                var generated = blocks.GenerateBlocksFromSource(scl, overwrite, unit);
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

            if (command == "probe-groups")
            {
                opts.TryGetValue("project", out var project);
                opts.TryGetValue("plc", out var plc);
                var opened = projects.OpenProject(project!, plc, withoutUi: true);
                var rootGroup = OpennessExport.GetFirstProp(projects.PlcSoftware, "BlockGroup");
                var groups = OpennessExport.GetFirstProp(rootGroup, "Groups");
                Console.WriteLine($"groups type: {groups?.GetType().FullName}");
                if (groups != null)
                {
                    foreach (var m in groups.GetType().GetMethods(System.Reflection.BindingFlags.Public | System.Reflection.BindingFlags.Instance))
                    {
                        if (m.DeclaringType != typeof(object))
                            Console.WriteLine($"Method: {m.Name}({string.Join(", ", m.GetParameters().Select(param => param.ParameterType.Name))})");
                    }
                }
                return 0;
            }

            if (command == "create-block-group")
            {
                if (!opts.TryGetValue("project", out var project) || string.IsNullOrWhiteSpace(project))
                {
                    Console.Error.WriteLine("Missing --project");
                    return 2;
                }
                if (!opts.TryGetValue("group", out var group) || string.IsNullOrWhiteSpace(group))
                {
                    Console.Error.WriteLine("Missing --group");
                    return 2;
                }
                opts.TryGetValue("plc", out var plc);
                var opened = projects.OpenProject(project, plc, withoutUi: true);
                if (!opened.Ok)
                {
                    Console.WriteLine(JsonSerializer.Serialize(opened, JsonDefaults.Options));
                    return 3;
                }
                var created = blocks.FindOrCreateBlockGroup(group);
                var saved = projects.SaveProject();
                var payload = new { ok = created is not null, group, saved = saved.Ok };
                Console.WriteLine(JsonSerializer.Serialize(payload, JsonDefaults.Options));
                return created is not null ? 0 : 4;
            }

            if (command == "move-block")
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
                if (!opts.TryGetValue("group", out var group) || string.IsNullOrWhiteSpace(group))
                {
                    Console.Error.WriteLine("Missing --group");
                    return 2;
                }
                opts.TryGetValue("plc", out var plc);
                var opened = projects.OpenProject(project, plc, withoutUi: true);
                if (!opened.Ok)
                {
                    Console.WriteLine(JsonSerializer.Serialize(opened, JsonDefaults.Options));
                    return 3;
                }
                var moveRes = blocks.MoveBlockToGroup(blockName, group);
                var saved = projects.SaveProject();
                var payload = new { ok = moveRes.Ok, error = moveRes.Error, block = blockName, group, saved = saved.Ok };
                Console.WriteLine(JsonSerializer.Serialize(payload, JsonDefaults.Options));
                return moveRes.Ok ? 0 : 4;
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

            if (command == "compile-hmi")
            {
                if (!opts.TryGetValue("project", out var project) || string.IsNullOrWhiteSpace(project))
                {
                    Console.Error.WriteLine("Missing --project");
                    return 2;
                }
                opts.TryGetValue("hmi", out var hmi);
                opts.TryGetValue("plc", out var plc);
                var opened = projects.OpenProject(project, plc, withoutUi: true);
                if (!opened.Ok)
                {
                    Console.WriteLine(JsonSerializer.Serialize(opened, JsonDefaults.Options));
                    return 3;
                }
                var compiled = HmiCompile.Compile(projects, hmi);
                var compiledJson = JsonSerializer.Serialize(compiled, JsonDefaults.Options);
                Console.WriteLine(compiledJson);
                using (var compiledDoc = JsonDocument.Parse(compiledJson))
                {
                    return compiledDoc.RootElement.TryGetProperty("ok", out var okEl) && okEl.GetBoolean() ? 0 : 6;
                }
            }

            if (command == "hmi-unified-apply")
            {
                if (!opts.TryGetValue("project", out var project) || string.IsNullOrWhiteSpace(project))
                {
                    Console.Error.WriteLine("Missing --project");
                    return 2;
                }
                if (!opts.TryGetValue("ops", out var opsPath) || string.IsNullOrWhiteSpace(opsPath))
                {
                    Console.Error.WriteLine("Missing --ops");
                    return 2;
                }
                opts.TryGetValue("hmi", out var hmi);
                opts.TryGetValue("plc", out var plc);
                var opened = projects.OpenProject(project, plc, withoutUi: true);
                if (!opened.Ok)
                {
                    Console.WriteLine(JsonSerializer.Serialize(opened, JsonDefaults.Options));
                    return 3;
                }
                var applied = HmiUnifiedApplyOps.Apply(projects, hmi, opsPath);
                var appliedJson = JsonSerializer.Serialize(applied, JsonDefaults.Options);
                Console.WriteLine(appliedJson);
                var applyOk = false;
                using (var appliedDoc = JsonDocument.Parse(appliedJson))
                {
                    applyOk = appliedDoc.RootElement.TryGetProperty("ok", out var okEl) && okEl.GetBoolean();
                }
                if (applyOk)
                {
                    // Persist the applied ops: without SaveProject the writeback
                    // lives only in the open session and is lost on close.
                    var saved = projects.SaveProject();
                    Console.WriteLine(JsonSerializer.Serialize(new { ok = saved.Ok, save = saved }, JsonDefaults.Options));
                    return saved.Ok ? 0 : 5;
                }
                return 7;
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

                opts.TryGetValue("unit", out var unit);
                if (string.IsNullOrWhiteSpace(unit)) opts.TryGetValue("software-unit", out unit);
                var imported = blocks.ImportXml(xml, overwrite, kind, unit);
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
                // 空工程尚无 PLC 设备时 open 会报 not_found，但工程本身已打开——
                // create-device 正是为此存在：放行并继续（CreateDevice 内部会再次解析 PLC）。
                if (!opened.Ok && !(opened.Error is not null && opened.Error.Code == "not_found"))
                {
                    Console.WriteLine(JsonSerializer.Serialize(opened, JsonDefaults.Options));
                    return 3;
                }

                var created = projects.CreateDevice(typeId, dName, deviceName);
                var saved = created.Ok ? projects.SaveProject() : null;
                Console.WriteLine(JsonSerializer.Serialize(new { ok = created.Ok && (saved is null || saved.Ok), project = opened, create = created, save = saved }, JsonDefaults.Options));
                return created.Ok ? 0 : 4;
            }

            if (command == "hmi-create-screen")
            {
                if (!opts.TryGetValue("project", out var project) || string.IsNullOrWhiteSpace(project))
                {
                    Console.Error.WriteLine("Missing --project");
                    return 2;
                }
                if (!opts.TryGetValue("name", out var screenName) || string.IsNullOrWhiteSpace(screenName))
                {
                    Console.Error.WriteLine("Missing --name <screenName>");
                    return 2;
                }
                opts.TryGetValue("hmi", out var hmi);
                opts.TryGetValue("plc", out var plc);
                var opened = projects.OpenProject(project, plc, withoutUi: true);
                if (!opened.Ok)
                {
                    Console.WriteLine(JsonSerializer.Serialize(opened, JsonDefaults.Options));
                    return 3;
                }
                var created = HmiScreenOps.CreateScreen(projects, hmi, screenName);
                var createdJson = JsonSerializer.Serialize(created, JsonDefaults.Options);
                Console.WriteLine(createdJson);
                var ok = false;
                using (var doc = JsonDocument.Parse(createdJson))
                {
                    ok = doc.RootElement.TryGetProperty("ok", out var okEl) && okEl.GetBoolean();
                }
                if (!ok) return 7;
                var saved = projects.SaveProject();
                Console.WriteLine(JsonSerializer.Serialize(new { ok = saved.Ok, save = saved }, JsonDefaults.Options));
                return saved.Ok ? 0 : 5;
            }

            if (command == "probe-device-types")
            {
                if (!opts.TryGetValue("project", out var project) || string.IsNullOrWhiteSpace(project))
                {
                    Console.Error.WriteLine("Missing --project");
                    return 2;
                }
                if (!opts.TryGetValue("type-ids", out var typeIdsRaw) || string.IsNullOrWhiteSpace(typeIdsRaw))
                {
                    Console.Error.WriteLine("Missing --type-ids <id1|id2|...> ('|'-separated, ids contain spaces/versions)");
                    return 2;
                }
                opts.TryGetValue("plc", out var plc);
                var typeIds = typeIdsRaw.Split('|').Select(s => s.Trim()).Where(s => s.Length > 0).ToArray();

                var opened = projects.OpenProject(project, plc, withoutUi: true);
                if (!opened.Ok && !(opened.Error is not null && opened.Error.Code == "not_found"))
                {
                    Console.WriteLine(JsonSerializer.Serialize(opened, JsonDefaults.Options));
                    return 3;
                }

                // Probe only: DeviceComposition.CreateWithItem per candidate id,
                // each raw error reported verbatim; CloseProject() never saves,
                // so probe devices are discarded (never persisted).
                var probed = new List<object>();
                var devices = projects.Project?.GetType()
                    .GetProperty("Devices", System.Reflection.BindingFlags.Public | System.Reflection.BindingFlags.Instance | System.Reflection.BindingFlags.IgnoreCase)
                    ?.GetValue(projects.Project);
                if (devices is null)
                {
                    probed.Add(new { typeId = (string?)"", ok = false, api = "", code = "dependency_unavailable", error = "Project.Devices composition not found" });
                }
                else
                {
                    var index = 0;
                    foreach (var typeId in typeIds)
                    {
                        index++;
                        var created = OpennessMutate.TryCreateDevice(devices, typeId, $"PROBE_{index}", $"PROBE_{index}");
                        probed.Add(new
                        {
                            typeId,
                            ok = created.Device is not null,
                            api = created.Api,
                            code = created.SkipReason,
                            error = created.RawError,
                        });
                    }
                }
                var closed = projects.CloseProject();
                var probeOk = probed.Any(p => p.GetType().GetProperty("ok")?.GetValue(p) is true);
                Console.WriteLine(JsonSerializer.Serialize(new { ok = probeOk, project = opened, probe = probed, close = closed }, JsonDefaults.Options));
                return 0;
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
            var key = a.Substring(2);
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

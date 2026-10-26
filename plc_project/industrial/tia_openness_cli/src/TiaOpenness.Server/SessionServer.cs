using System.Collections.Concurrent;
using System.Net;
using System.Text;
using System.Text.Json;
using System.Threading;
using TiaOpenness.Models;

namespace TiaOpenness.Server;

/// <summary>
/// Resident Openness session: single STA worker thread, HTTP on 127.0.0.1.
/// Keeps one project open across write/compile rounds.
/// </summary>
public sealed class SessionServer : IDisposable
{
    private readonly HttpListener _listener = new();
    private readonly string? _token;
    private readonly ConcurrentQueue<Action> _queue = new();
    private readonly AutoResetEvent _signal = new(false);
    private readonly Thread _sta;
    private volatile bool _running = true;

    private TiaConnection? _connection;
    private ProjectService? _projects;
    private BlockService? _blocks;
    private string? _openProjectPath;

    public SessionServer(string host, int port, string? token)
    {
        _token = string.IsNullOrWhiteSpace(token) ? null : token.Trim();
        var prefix = $"http://{host}:{port}/";
        _listener.Prefixes.Add(prefix);
        _sta = new Thread(StaLoop)
        {
            IsBackground = true,
            Name = "TiaOpenness.STA",
        };
        try
        {
            _sta.SetApartmentState(ApartmentState.STA);
        }
        catch
        {
            // already started / not supported — continue
        }
    }

    public void Run()
    {
        _sta.Start();
        _listener.Start();
        Console.Error.WriteLine($"TiaOpenness serve listening on {string.Join(",", _listener.Prefixes)}");
        while (_running)
        {
            HttpListenerContext ctx;
            try
            {
                ctx = _listener.GetContext();
            }
            catch (HttpListenerException)
            {
                break;
            }
            catch (ObjectDisposedException)
            {
                break;
            }

            ThreadPool.QueueUserWorkItem(_ => Handle(ctx));
        }
    }

    private void StaLoop()
    {
        while (_running)
        {
            _signal.WaitOne(500);
            while (_queue.TryDequeue(out var work))
            {
                try
                {
                    work();
                }
                catch
                {
                    // swallow — callers get error via callback
                }
            }
        }
    }

    private void RunOnSta(Action action)
    {
        using var done = new ManualResetEventSlim(false);
        Exception? caught = null;
        _queue.Enqueue(() =>
        {
            try
            {
                action();
            }
            catch (Exception ex)
            {
                caught = ex;
            }
            finally
            {
                done.Set();
            }
        });
        _signal.Set();
        done.Wait();
        if (caught is not null) throw caught;
    }

    private T RunOnSta<T>(Func<T> func)
    {
        T? result = default;
        RunOnSta(() => { result = func(); });
        return result!;
    }

    private void Handle(HttpListenerContext ctx)
    {
        try
        {
            if (_token is not null)
            {
                var auth = ctx.Request.Headers["Authorization"] ?? "";
                if (!auth.Equals($"Bearer {_token}", StringComparison.Ordinal))
                {
                    WriteJson(ctx, 401, new { ok = false, error = "unauthorized" });
                    return;
                }
            }

            var path = (ctx.Request.Url?.AbsolutePath ?? "/").TrimEnd('/').ToLowerInvariant();
            if (path.Length == 0) path = "/";

            if (ctx.Request.HttpMethod == "GET" && path is "/health" or "/")
            {
                WriteJson(ctx, 200, new
                {
                    ok = true,
                    status = "ok",
                    openProject = _openProjectPath,
                });
                return;
            }

            var body = ReadBody(ctx.Request);
            using var doc = string.IsNullOrWhiteSpace(body)
                ? JsonDocument.Parse("{}")
                : JsonDocument.Parse(body);
            var root = doc.RootElement;

            object payload = path switch
            {
                "/open" => RunOnSta(() => Open(root)),
                "/compile-plc" => RunOnSta(() => CompilePlc(root)),
                "/compile-hmi" => RunOnSta(() => CompileHmi(root)),
                "/save" => RunOnSta(() => Save(root)),
                "/close" => RunOnSta(() => Close()),
                "/generate-from-source" => RunOnSta(() => GenerateFromSource(root)),
                "/import-xml" => RunOnSta(() => ImportXml(root)),
                "/hmi-unified-apply" => RunOnSta(() => HmiUnifiedApply(root)),
                _ => new { ok = false, error = $"unknown path {path}" },
            };
            WriteJson(ctx, 200, payload);
        }
        catch (Exception ex)
        {
            WriteJson(ctx, 500, new { ok = false, error = ex.Message });
        }
    }

    private void EnsureCore()
    {
        if (_connection is not null) return;
        var version = Environment.GetEnvironmentVariable("TIA_VERSION") ?? TiaConnection.DefaultVersion;
        _connection = new TiaConnection(version);
        _projects = new ProjectService(_connection);
        _blocks = new BlockService(_projects);
    }

    private object Open(JsonElement root)
    {
        EnsureCore();
        var project = GetString(root, "project");
        if (string.IsNullOrWhiteSpace(project))
            return new { ok = false, error = "project required" };
        var plc = GetString(root, "plc");
        if (string.Equals(_openProjectPath, project, StringComparison.OrdinalIgnoreCase)
            && _projects?.Project is not null)
        {
            return new { ok = true, reused = true, project };
        }
        if (_projects?.Project is not null)
        {
            try { _projects.CloseProject(); } catch { /* ignore */ }
            _openProjectPath = null;
        }
        var opened = _projects!.OpenProject(project, plc, withoutUi: true);
        if (opened.Ok) _openProjectPath = project;
        return new { ok = opened.Ok, project = opened, path = project };
    }

    private object CompilePlc(JsonElement root)
    {
        EnsureCore();
        EnsureOpen(root);
        var compiled = _blocks!.CompilePlcSoftwareStrict();
        return new { ok = compiled.Ok, compile = compiled };
    }

    private object CompileHmi(JsonElement root)
    {
        EnsureCore();
        EnsureOpen(root);
        var hmiName = GetString(root, "hmi");
        return HmiCompile.Compile(_projects!, hmiName);
    }

    private object Save(JsonElement _)
    {
        EnsureCore();
        if (_projects?.Project is null)
            return new { ok = false, error = "no project open" };
        try
        {
            var proj = _projects.Project!;
            var save = proj.GetType().GetMethod("Save", Type.EmptyTypes);
            save?.Invoke(proj, null);
            return new { ok = true };
        }
        catch (Exception ex)
        {
            return new { ok = false, error = ex.Message };
        }
    }

    private object Close()
    {
        try
        {
            _projects?.CloseProject();
        }
        catch { /* ignore */ }
        _openProjectPath = null;
        return new { ok = true };
    }

    private object GenerateFromSource(JsonElement root)
    {
        EnsureCore();
        EnsureOpen(root);
        var scl = GetString(root, "scl");
        var unit = GetString(root, "unit") ?? GetString(root, "software_unit");
        if (string.IsNullOrWhiteSpace(scl) || !File.Exists(scl))
            return new { ok = false, error = "scl file required" };
        var generated = _blocks!.GenerateBlocksFromSource(scl, overwrite: true, softwareUnit: unit);
        return new { ok = generated.Ok, generate = generated };
    }

    private object ImportXml(JsonElement root)
    {
        EnsureCore();
        EnsureOpen(root);
        var xml = GetString(root, "xml");
        var kind = GetString(root, "kind") ?? "auto";
        var unit = GetString(root, "unit") ?? GetString(root, "software_unit");
        if (string.IsNullOrWhiteSpace(xml) || !File.Exists(xml))
            return new { ok = false, error = "xml file required" };
        var imported = _blocks!.ImportXml(xml, overwrite: true, kindHint: kind, softwareUnit: unit);
        return new { ok = imported.Ok, import = imported };
    }

    private object HmiUnifiedApply(JsonElement root)
    {
        EnsureCore();
        EnsureOpen(root);
        var opsPath = GetString(root, "ops");
        var hmiName = GetString(root, "hmi");
        if (string.IsNullOrWhiteSpace(opsPath) || !File.Exists(opsPath))
            return new { ok = false, error = "ops file required" };
        return HmiUnifiedApplyOps.Apply(_projects!, hmiName, opsPath);
    }

    private void EnsureOpen(JsonElement root)
    {
        var project = GetString(root, "project");
        if (!string.IsNullOrWhiteSpace(project)
            && !string.Equals(_openProjectPath, project, StringComparison.OrdinalIgnoreCase))
        {
            Open(root);
        }
        if (_projects?.Project is null)
            throw new InvalidOperationException("no project open");
    }

    private static string? GetString(JsonElement root, string name)
    {
        if (root.TryGetProperty(name, out var el) && el.ValueKind == JsonValueKind.String)
            return el.GetString();
        return null;
    }

    private static string ReadBody(HttpListenerRequest req)
    {
        using var reader = new StreamReader(req.InputStream, req.ContentEncoding);
        return reader.ReadToEnd();
    }

    private static void WriteJson(HttpListenerContext ctx, int code, object payload)
    {
        var json = JsonSerializer.Serialize(payload, JsonDefaults.Options);
        var bytes = Encoding.UTF8.GetBytes(json);
        ctx.Response.StatusCode = code;
        ctx.Response.ContentType = "application/json; charset=utf-8";
        ctx.Response.ContentLength64 = bytes.Length;
        ctx.Response.OutputStream.Write(bytes, 0, bytes.Length);
        ctx.Response.Close();
    }

    public void Dispose()
    {
        _running = false;
        try { _listener.Stop(); } catch { /* ignore */ }
        try { _listener.Close(); } catch { /* ignore */ }
        _signal.Set();
        try { _projects?.CloseProject(); } catch { /* ignore */ }
        try { _connection?.Dispose(); } catch { /* ignore */ }
    }
}

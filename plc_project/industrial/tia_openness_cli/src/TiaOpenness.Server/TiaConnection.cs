using System.Diagnostics;
using System.Reflection;
using TiaOpenness.Models;

namespace TiaOpenness.Server;

/// <summary>
/// Hosts a Siemens TIA Portal Openness session (V19 by default).
/// Loads Siemens.Engineering via reflection so the MCP server builds without
/// a compile-time dependency on Portal PublicAPI.
/// Must run on .NET Framework (net481) — Engineering uses Remoting.
/// </summary>
public sealed class TiaConnection : IDisposable
{
    public const string DefaultVersion = "V19";

    private readonly object _gate = new();
    private Assembly? _engineering;
    private ResolveEventHandler? _resolveHandler;
    private object? _portal;
    private bool _ownsPortal;
    private bool _disposed;
    private string? _stageDir;
    private string? _binPublicApi;
    private string? _binDir;

    public string TiaVersion { get; }
    public string? EngineeringDllPath { get; private set; }
    public bool IsConnected => _portal is not null;
    public object? Portal => _portal;
    public Assembly? EngineeringAssembly => _engineering;

    public TiaConnection(string tiaVersion = DefaultVersion)
    {
        TiaVersion = string.IsNullOrWhiteSpace(tiaVersion) ? DefaultVersion : tiaVersion.Trim();
    }

    public static bool IsPortalProcessRunning(out int processCount)
    {
        var names = new HashSet<string>(StringComparer.OrdinalIgnoreCase)
        {
            "Siemens.Automation.Portal",
            "Siemens.Automation.Portal.exe",
            "Siemens.Automation.ObjectFrame.AppBase",
        };

        var procs = Process.GetProcesses()
            .Where(p =>
            {
                try { return names.Contains(p.ProcessName); }
                catch { return false; }
            })
            .ToList();

        processCount = procs.Count;
        foreach (var p in procs) p.Dispose();
        return processCount > 0;
    }

    public string? FindEngineeringDll()
    {
        var portalRoot = Environment.GetEnvironmentVariable("TIA_PORTAL_ROOT");
        if (string.IsNullOrWhiteSpace(portalRoot))
        {
            portalRoot = $@"C:\Program Files\Siemens\Automation\Portal {TiaVersion}";
        }

        var ordered = new List<string>
        {
            Path.Combine(portalRoot, "PublicAPI", TiaVersion, "Siemens.Engineering.dll"),
            Path.Combine(portalRoot, "PublicAPI", "Siemens.Engineering.dll"),
        };

        var publicApi = Path.Combine(portalRoot, "PublicAPI");
        if (Directory.Exists(publicApi))
        {
            foreach (var dir in Directory.GetDirectories(publicApi).OrderByDescending(d => d, StringComparer.OrdinalIgnoreCase))
            {
                ordered.Add(Path.Combine(dir, "Siemens.Engineering.dll"));
            }
        }

        return ordered.FirstOrDefault(File.Exists);
    }

    public static bool IsOpennessGroupInCurrentToken()
    {
        try
        {
            var identity = System.Security.Principal.WindowsIdentity.GetCurrent();
            var principal = new System.Security.Principal.WindowsPrincipal(identity);
            // Prefer well-known local group name used by TIA Openness installer.
            if (principal.IsInRole("Siemens TIA Openness")) return true;
            if (principal.IsInRole(@"BUILTIN\Siemens TIA Openness")) return true;
            var machine = Environment.MachineName;
            if (principal.IsInRole($@"{machine}\Siemens TIA Openness")) return true;
            var groups = identity.Groups;
            if (groups is null) return false;
            foreach (System.Security.Principal.IdentityReference claim in groups)
            {
                try
                {
                    var name = claim.Translate(typeof(System.Security.Principal.NTAccount)).ToString();
                    if (name.EndsWith(@"\Siemens TIA Openness", StringComparison.OrdinalIgnoreCase) ||
                        name.Equals("Siemens TIA Openness", StringComparison.OrdinalIgnoreCase))
                    {
                        return true;
                    }
                }
                catch
                {
                    // ignore untranslatable SIDs
                }
            }
        }
        catch
        {
            return false;
        }

        return false;
    }

    public TiaStatusResult GetStatus()
    {
        var running = IsPortalProcessRunning(out var count);
        var dll = FindEngineeringDll();
        EngineeringDllPath = dll;
        var inToken = IsOpennessGroupInCurrentToken();

        string message;
        if (dll is null)
        {
            message = $"Siemens.Engineering.dll not found for Portal {TiaVersion}. Install TIA Openness / PublicAPI.";
        }
        else if (!inToken)
        {
            message = "Account may be in 'Siemens TIA Openness', but the current logon token does not include it. Sign out and sign back in, then retry.";
        }
        else if (running)
        {
            message = "TIA Portal process detected.";
        }
        else
        {
            message = "TIA Portal process not detected (Openness can still start WithoutUserInterface).";
        }

        return new TiaStatusResult
        {
            Ok = true,
            TiaRunning = running,
            ProcessCount = count,
            OpennessAvailable = dll is not null,
            OpennessGroupInToken = inToken,
            TiaVersion = TiaVersion,
            EngineeringDll = dll,
            Connected = IsConnected,
            Mode = IsConnected ? (_ownsPortal ? "hosted" : "attached") : null,
            Message = message,
            Error = inToken || dll is null
                ? null
                : new ToolError
                {
                    Code = "openness_group_token_missing",
                    Message = message,
                    Retryable = false,
                },
        };
    }

    public void EnsureLoaded()
    {
        lock (_gate)
        {
            if (_engineering is not null) return;

            var dll = FindEngineeringDll()
                ?? throw new FileNotFoundException(
                    $"Siemens.Engineering.dll not found under Portal {TiaVersion}. Set TIA_PORTAL_ROOT or install Openness.");

            EngineeringDllPath = dll;
            StageAndLoad(dll);
        }
    }

    public void Connect(bool preferAttach = true, bool withoutUi = true)
    {
        lock (_gate)
        {
            ThrowIfDisposed();
            if (_portal is not null) return;

            EnsureLoaded();

            if (preferAttach)
            {
                var attached = TryAttach();
                if (attached is not null)
                {
                    _portal = attached;
                    _ownsPortal = false;
                    return;
                }
            }

            var modeType = _engineering!.GetType("Siemens.Engineering.TiaPortalMode", throwOnError: true)!;
            var mode = Enum.Parse(modeType, withoutUi ? "WithoutUserInterface" : "WithUserInterface");
            var portalType = _engineering.GetType("Siemens.Engineering.TiaPortal", throwOnError: true)!;
            _portal = Activator.CreateInstance(portalType, mode)
                ?? throw new InvalidOperationException("Failed to create TiaPortal instance.");
            _ownsPortal = true;
        }
    }

    public void Disconnect()
    {
        lock (_gate)
        {
            if (_portal is null) return;

            var portal = _portal;
            var owns = _ownsPortal;
            _portal = null;
            _ownsPortal = false;

            if (!owns || portal is not IDisposable disposable)
            {
                return;
            }

            // TiaPortal.Dispose() can block for a very long time after Openness work.
            // Dispose on a background thread with a timeout so MCP/stdio hosts exit cleanly.
            var done = new ManualResetEventSlim(false);
            var thread = new Thread(() =>
            {
                try { disposable.Dispose(); }
                catch { /* ignore dispose failures during shutdown */ }
                finally { done.Set(); }
            })
            {
                IsBackground = true,
                Name = "tia-portal-dispose",
            };
            thread.Start();
            done.Wait(TimeSpan.FromSeconds(20));
        }
    }

    public object? GetService(object provider, string serviceTypeFullName)
    {
        if (provider is null || _engineering is null) return null;
        var serviceType = _engineering.GetType(serviceTypeFullName, throwOnError: false)
            ?? Type.GetType($"{serviceTypeFullName}, Siemens.Engineering");
        if (serviceType is null) return null;

        var method = provider.GetType().GetMethods(BindingFlags.Instance | BindingFlags.Public)
            .FirstOrDefault(m =>
                m.Name == "GetService" &&
                m.IsGenericMethodDefinition &&
                m.GetParameters().Length == 0);
        if (method is null) return null;

        try
        {
            return method.MakeGenericMethod(serviceType).Invoke(provider, null);
        }
        catch
        {
            return null;
        }
    }

    public void Dispose()
    {
        if (_disposed) return;
        Disconnect();
        if (_resolveHandler is not null)
        {
            AppDomain.CurrentDomain.AssemblyResolve -= _resolveHandler;
            _resolveHandler = null;
        }
        _engineering = null;
        _disposed = true;
        GC.SuppressFinalize(this);
    }

    private object? TryAttach()
    {
        var portalType = _engineering!.GetType("Siemens.Engineering.TiaPortal", throwOnError: true)!;
        var getProcesses = portalType.GetMethod("GetProcesses", BindingFlags.Public | BindingFlags.Static);
        if (getProcesses is null) return null;

        if (getProcesses.Invoke(null, null) is not System.Collections.IEnumerable processes)
            return null;

        foreach (var proc in processes)
        {
            var attach = proc.GetType().GetMethod("Attach", BindingFlags.Public | BindingFlags.Instance);
            if (attach is null) continue;
            try
            {
                return attach.Invoke(proc, null);
            }
            catch
            {
                // try next process
            }
        }

        return null;
    }

    private void StageAndLoad(string engineeringDll)
    {
        // Path: Portal V19\PublicAPI\V19\Siemens.Engineering.dll
        // dll dir = PublicAPI\V19 → parent PublicAPI → parent Portal root
        var portalRoot = Directory.GetParent(Path.GetDirectoryName(engineeringDll)!)!.Parent!.FullName;

        _binPublicApi = Path.Combine(portalRoot, "Bin", "PublicAPI");
        _binDir = Path.Combine(portalRoot, "Bin");
        _stageDir = Path.Combine(Path.GetTempPath(), $"researchos_openness_{TiaVersion}_{Process.GetCurrentProcess().Id}");
        Directory.CreateDirectory(_stageDir);

        File.Copy(engineeringDll, Path.Combine(_stageDir, "Siemens.Engineering.dll"), overwrite: true);
        foreach (var dep in new[]
                 {
                     "Siemens.Engineering.Contract.dll",
                     "Siemens.Engineering.ClientAdapter.Interfaces.dll",
                 })
        {
            var src = Path.Combine(_binPublicApi, dep);
            if (File.Exists(src))
            {
                File.Copy(src, Path.Combine(_stageDir, dep), overwrite: true);
            }
        }

        var path = Environment.GetEnvironmentVariable("PATH") ?? "";
        Environment.SetEnvironmentVariable("PATH", $"{_stageDir};{_binPublicApi};{_binDir};{path}");
        Directory.SetCurrentDirectory(_binDir);

        _resolveHandler = (_, args) =>
        {
            var name = new AssemblyName(args.Name).Name;
            if (string.IsNullOrEmpty(name)) return null;
            foreach (var dir in new[] { _stageDir!, _binPublicApi!, _binDir! })
            {
                var candidate = Path.Combine(dir, name + ".dll");
                if (File.Exists(candidate))
                {
                    return Assembly.LoadFrom(candidate);
                }
            }
            return null;
        };
        AppDomain.CurrentDomain.AssemblyResolve += _resolveHandler;

        foreach (var dep in new[]
                 {
                     "Siemens.Engineering.Contract.dll",
                     "Siemens.Engineering.ClientAdapter.Interfaces.dll",
                 })
        {
            var p = Path.Combine(_stageDir, dep);
            if (File.Exists(p))
            {
                try { Assembly.LoadFrom(p); } catch { /* optional */ }
            }
        }

        _engineering = Assembly.LoadFrom(Path.Combine(_stageDir, "Siemens.Engineering.dll"));
    }

    private void ThrowIfDisposed()
    {
        if (_disposed) throw new ObjectDisposedException(nameof(TiaConnection));
    }
}

using System.Reflection;

namespace TiaOpenness.Server;

/// <summary>
/// Create a Unified HMI screen via reflection, probing the available
/// Screens.Create signatures the same way HmiUnifiedApplyOps probes
/// ScreenItems.Create: bind by parameter name/type, report diagnostics,
/// never guess silently.
/// </summary>
public static class HmiScreenOps
{
    public static object CreateScreen(ProjectService projects, string? hmiName, string screenName)
    {
        if (string.IsNullOrWhiteSpace(screenName))
            return new { ok = false, error = "screen name required", code = "invalid_argument" };

        var targets = projects.EnumerateSoftware()
            .Where(t => t.Kind is "hmi_unified" or "hmi")
            .ToList();
        if (!string.IsNullOrWhiteSpace(hmiName))
        {
            targets = targets
                .Where(t => string.Equals(t.SoftwareName, hmiName, StringComparison.OrdinalIgnoreCase)
                    || string.Equals(t.DeviceName, hmiName, StringComparison.OrdinalIgnoreCase))
                .ToList();
        }
        if (targets.Count == 0)
            return new { ok = false, error = "no_hmi", code = "no_hmi" };

        var software = targets[0].Software;

        // Candidate Create hosts, in probe order:
        //   software.Screens            (Unified: HmiSoftware exposes Screens directly on some versions)
        //   software.ScreenFolder.Screens (documented Unified path)
        //   software.ScreenFolder       (Comfort-era folder composition itself)
        var hosts = new List<object>();
        var screens = GetProp(software, "Screens");
        if (screens is not null) hosts.Add(screens);
        var folder = GetProp(software, "ScreenFolder");
        if (folder is not null)
        {
            var folderScreens = GetProp(folder, "Screens");
            if (folderScreens is not null) hosts.Add(folderScreens);
            hosts.Add(folder);
        }
        if (hosts.Count == 0)
            return new { ok = false, error = "no Screens/ScreenFolder composition on HMI software", code = "no_api" };

        var attempted = new List<object>();
        foreach (var host in hosts)
        {
            var methods = host.GetType()
                .GetMethods(BindingFlags.Public | BindingFlags.Instance)
                .Where(m => m.Name == "Create")
                .OrderBy(m => m.GetParameters().Length)
                .ToList();
            var signatures = string.Join(" | ", methods.Select(Describe));
            if (methods.Count == 0)
            {
                attempted.Add(new { host = host.GetType().Name, ok = false, reason = "no Create method", code = "no_api" });
                continue;
            }

            var lastDetail = "";
            foreach (var method in methods)
            {
                if (!TryBindArgs(method.GetParameters(), screenName, out var args, out var detail))
                {
                    lastDetail = detail;
                    continue;
                }
                try
                {
                    var screen = method.Invoke(host, args);
                    return new
                    {
                        ok = true,
                        host = host.GetType().Name,
                        signature = Describe(method),
                        screen = screen?.GetType().Name,
                        name = GetProp(screen, "Name")?.ToString(),
                    };
                }
                catch (Exception ex)
                {
                    lastDetail = $"Create({args.Length} args) threw: {Unwrap(ex).Message}";
                }
            }

            attempted.Add(new
            {
                host = host.GetType().Name,
                ok = false,
                reason = string.IsNullOrEmpty(lastDetail) ? $"signatures unsupported: {signatures}" : $"{lastDetail}; available: {signatures}",
                code = "create_unsupported",
            });
        }

        return new { ok = false, error = "all Create hosts failed", code = "create_failed", attempted };
    }

    private static string Describe(MethodInfo method)
    {
        var ps = method.GetParameters().Select(p => $"{p.ParameterType.Name} {p.Name}");
        return $"Create({string.Join(", ", ps)})";
    }

    private static bool TryBindArgs(ParameterInfo[] parameters, string screenName, out object?[] args, out string detail)
    {
        args = new object?[parameters.Length];
        detail = "";
        for (var i = 0; i < parameters.Length; i++)
        {
            var p = parameters[i];
            var type = p.ParameterType;
            if (type == typeof(string))
            {
                args[i] = screenName;
            }
            else if (type == typeof(int) || type == typeof(uint) || type == typeof(short) || type == typeof(double))
            {
                args[i] = Activator.CreateInstance(type)!;
            }
            else if (type == typeof(bool))
            {
                args[i] = false;
            }
            else if (type.IsEnum)
            {
                args[i] = Activator.CreateInstance(type)!;
            }
            else
            {
                detail = $"unsupported parameter '{p.Name}:{type.Name}'";
                return false;
            }
        }
        return true;
    }

    private static Exception Unwrap(Exception ex)
    {
        return ex is TargetInvocationException { InnerException: not null } tie ? tie.InnerException! : ex;
    }

    private static object? GetProp(object target, string name)
    {
        try
        {
            return target.GetType()
                .GetProperty(name, BindingFlags.Public | BindingFlags.Instance | BindingFlags.IgnoreCase)
                ?.GetValue(target);
        }
        catch
        {
            return null;
        }
    }
}

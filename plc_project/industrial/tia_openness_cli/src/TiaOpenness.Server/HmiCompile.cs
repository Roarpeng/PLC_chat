using System.Reflection;
using System.Text.Json.Nodes;

namespace TiaOpenness.Server;

/// <summary>Compile HMI software via ICompilable when available.</summary>
public static class HmiCompile
{
    public static object Compile(ProjectService projects, string? hmiName)
    {
        var targets = projects.EnumerateSoftware();
        var hmiTargets = targets
            .Where(t => !string.Equals(t.Kind, "plc", StringComparison.OrdinalIgnoreCase))
            .ToList();
        if (!string.IsNullOrWhiteSpace(hmiName))
        {
            hmiTargets = hmiTargets
                .Where(t => string.Equals(t.SoftwareName, hmiName, StringComparison.OrdinalIgnoreCase)
                    || string.Equals(t.DeviceName, hmiName, StringComparison.OrdinalIgnoreCase))
                .ToList();
        }
        if (hmiTargets.Count == 0)
        {
            return new { ok = false, error = "no_hmi", message = "No HMI software found", messages = Array.Empty<object>() };
        }

        var messages = new JsonArray();
        var allOk = true;
        foreach (var t in hmiTargets)
        {
            try
            {
                var software = t.Software;
                // ICompilable.Compile() via reflection
                var compileMethod = software.GetType().GetMethod("Compile", Type.EmptyTypes)
                    ?? software.GetType().GetInterfaces()
                        .SelectMany(i => i.GetMethods())
                        .FirstOrDefault(m => m.Name == "Compile" && m.GetParameters().Length == 0);
                if (compileMethod is null)
                {
                    allOk = false;
                    messages.Add(new JsonObject
                    {
                        ["path"] = t.SoftwareName,
                        ["description"] = "ICompilable.Compile not available",
                        ["severity"] = "error",
                    });
                    continue;
                }
                var result = compileMethod.Invoke(software, null);
                var state = result?.GetType().GetProperty("State")?.GetValue(result)?.ToString() ?? "";
                var ok = state.IndexOf("Success", StringComparison.OrdinalIgnoreCase) >= 0
                    || state.IndexOf("Warning", StringComparison.OrdinalIgnoreCase) >= 0;
                if (!ok) allOk = false;
                // Messages collection
                var msgsProp = result?.GetType().GetProperty("Messages");
                var msgs = msgsProp?.GetValue(result) as System.Collections.IEnumerable;
                if (msgs is not null)
                {
                    foreach (var m in msgs)
                    {
                        if (m is null) continue;
                        var path = m.GetType().GetProperty("Path")?.GetValue(m)?.ToString() ?? t.SoftwareName;
                        var desc = m.GetType().GetProperty("Description")?.GetValue(m)?.ToString()
                            ?? m.GetType().GetProperty("Message")?.GetValue(m)?.ToString()
                            ?? m.ToString();
                        var sev = m.GetType().GetProperty("State")?.GetValue(m)?.ToString()
                            ?? m.GetType().GetProperty("Severity")?.GetValue(m)?.ToString()
                            ?? "Error";
                        messages.Add(new JsonObject
                        {
                            ["path"] = path,
                            ["description"] = desc,
                            ["severity"] = sev.IndexOf("Warning", StringComparison.OrdinalIgnoreCase) >= 0 ? "warning" : "error",
                            ["hmi"] = t.SoftwareName,
                        });
                    }
                }
            }
            catch (Exception ex)
            {
                allOk = false;
                messages.Add(new JsonObject
                {
                    ["path"] = t.SoftwareName,
                    ["description"] = ex.Message,
                    ["severity"] = "error",
                });
            }
        }

        return new
        {
            ok = allOk,
            target = "hmi",
            state = allOk ? "Success" : "Error",
            messages = messages,
        };
    }
}

using System.Reflection;
using System.Text.Json;

namespace TiaOpenness.Server;

/// <summary>Apply Unified HMI ops JSON via reflection (Create/SetAttribute/Delete).</summary>
public static class HmiUnifiedApplyOps
{
    public static object Apply(ProjectService projects, string? hmiName, string opsPath)
    {
        using var doc = JsonDocument.Parse(File.ReadAllText(opsPath));
        var root = doc.RootElement;
        var ops = root.TryGetProperty("ops", out var opsEl) ? opsEl : root;
        if (ops.ValueKind != JsonValueKind.Array)
            return new { ok = false, error = "ops must be array", code = "invalid_ops" };

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
        var applied = 0;
        var skipped = new List<object>();
        foreach (var op in ops.EnumerateArray())
        {
            var action = op.TryGetProperty("action", out var a) ? a.GetString() ?? "" : "";
            var screenName = op.TryGetProperty("screen", out var s) ? s.GetString() : null;
            var name = op.TryGetProperty("name", out var n) ? n.GetString() : null;
            try
            {
                var screen = FindScreen(software, screenName);
                if (screen is null)
                {
                    skipped.Add(new { action, name, reason = "screen_not_found" });
                    continue;
                }
                if (string.Equals(action, "create", StringComparison.OrdinalIgnoreCase))
                {
                    var items = GetProp(screen, "ScreenItems");
                    if (items is null)
                    {
                        skipped.Add(new { action, name, reason = "no_api", code = "no_api" });
                        continue;
                    }
                    var create = items.GetType().GetMethod("Create", BindingFlags.Public | BindingFlags.Instance);
                    if (create is null)
                    {
                        skipped.Add(new { action, name, reason = "no_api", code = "no_api" });
                        continue;
                    }
                    // Best-effort: Create may need type args — mark no_api if signature unknown
                    var parameters = create.GetParameters();
                    if (parameters.Length == 0)
                    {
                        create.Invoke(items, null);
                        applied++;
                    }
                    else
                    {
                        skipped.Add(new { action, name, reason = "no_api", code = "no_api", detail = "Create signature unsupported" });
                    }
                }
                else if (string.Equals(action, "update", StringComparison.OrdinalIgnoreCase))
                {
                    var item = FindItem(screen, name);
                    if (item is null)
                    {
                        skipped.Add(new { action, name, reason = "item_not_found" });
                        continue;
                    }
                    SetIfPresent(item, "Left", op, "left");
                    SetIfPresent(item, "Top", op, "top");
                    SetIfPresent(item, "Width", op, "width");
                    SetIfPresent(item, "Height", op, "height");
                    SetIfPresent(item, "Text", op, "text");
                    applied++;
                }
                else if (string.Equals(action, "delete", StringComparison.OrdinalIgnoreCase))
                {
                    var item = FindItem(screen, name);
                    if (item is null)
                    {
                        skipped.Add(new { action, name, reason = "item_not_found" });
                        continue;
                    }
                    var del = item.GetType().GetMethod("Delete", Type.EmptyTypes);
                    if (del is null)
                    {
                        skipped.Add(new { action, name, reason = "no_api", code = "no_api" });
                        continue;
                    }
                    del.Invoke(item, null);
                    applied++;
                }
                else
                {
                    skipped.Add(new { action, name, reason = "unknown_action" });
                }
            }
            catch (Exception ex)
            {
                skipped.Add(new { action, name, reason = ex.Message });
            }
        }

        return new { ok = skipped.Count == 0, applied, skipped };
    }

    private static object? FindScreen(object software, string? screenName)
    {
        var screens = GetProp(software, "Screens") ?? GetProp(software, "ScreenFolder");
        if (screens is null) return null;
        foreach (var s in Enumerate(screens))
        {
            if (s is null) continue;
            var n = GetProp(s, "Name")?.ToString();
            if (string.IsNullOrWhiteSpace(screenName) || string.Equals(n, screenName, StringComparison.OrdinalIgnoreCase))
                return s;
        }
        return null;
    }

    private static object? FindItem(object screen, string? name)
    {
        var items = GetProp(screen, "ScreenItems") ?? GetProp(screen, "Items");
        foreach (var item in Enumerate(items))
        {
            if (item is null) continue;
            var n = GetProp(item, "Name")?.ToString();
            if (string.Equals(n, name, StringComparison.OrdinalIgnoreCase))
                return item;
        }
        return null;
    }

    private static void SetIfPresent(object target, string propName, JsonElement op, string jsonName)
    {
        if (!op.TryGetProperty(jsonName, out var el)) return;
        var p = target.GetType().GetProperty(propName, BindingFlags.Public | BindingFlags.Instance | BindingFlags.IgnoreCase);
        if (p is null || !p.CanWrite) return;
        try
        {
            if (el.ValueKind == JsonValueKind.Number && p.PropertyType == typeof(int))
                p.SetValue(target, el.GetInt32());
            else if (el.ValueKind == JsonValueKind.Number && p.PropertyType == typeof(double))
                p.SetValue(target, el.GetDouble());
            else if (el.ValueKind == JsonValueKind.String)
                p.SetValue(target, el.GetString());
        }
        catch
        {
            // ignore set failures
        }
    }

    private static object? GetProp(object target, string name)
    {
        return target.GetType().GetProperty(name, BindingFlags.Public | BindingFlags.Instance | BindingFlags.IgnoreCase)
            ?.GetValue(target);
    }

    private static IEnumerable<object?> Enumerate(object? collection)
    {
        if (collection is null) yield break;
        if (collection is System.Collections.IEnumerable en)
        {
            foreach (var x in en) yield return x;
            yield break;
        }
        var items = GetProp(collection, "Items");
        if (items is System.Collections.IEnumerable en2)
        {
            foreach (var x in en2) yield return x;
        }
    }
}

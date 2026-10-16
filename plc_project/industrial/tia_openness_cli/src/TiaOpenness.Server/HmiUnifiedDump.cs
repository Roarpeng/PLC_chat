using System.Reflection;
using System.Text.Json;
using System.Text.Json.Nodes;

namespace TiaOpenness.Server;

/// <summary>
/// Reflection-based dump of Unified Comfort HMI screens / ScreenItems to JSON.
/// Returns false (no throw) when APIs are missing on the installed Openness version.
/// </summary>
public static class HmiUnifiedDump
{
    private static readonly JsonSerializerOptions JsonOpts = new()
    {
        WriteIndented = true,
        PropertyNamingPolicy = JsonNamingPolicy.CamelCase,
    };

    public static bool TryDump(object hmiSoftware, string outPath)
    {
        try
        {
            var screensNode = new JsonArray();
            var screens = GetProp(hmiSoftware, "Screens") ?? GetProp(hmiSoftware, "ScreenFolder");
            if (screens is null)
            {
                return false;
            }

            foreach (var screen in Enumerate(screens))
            {
                if (screen is null) continue;
                var screenObj = new JsonObject
                {
                    ["name"] = GetString(screen, "Name") ?? "Screen",
                    ["width"] = GetInt(screen, "Width"),
                    ["height"] = GetInt(screen, "Height"),
                    ["startScreen"] = GetBool(screen, "IsStartScreen") || GetBool(screen, "StartScreen"),
                };
                var itemsArr = new JsonArray();
                var items = GetProp(screen, "ScreenItems") ?? GetProp(screen, "Items");
                foreach (var item in Enumerate(items))
                {
                    if (item is null) continue;
                    var typeName = item.GetType().Name;
                    itemsArr.Add(new JsonObject
                    {
                        ["name"] = GetString(item, "Name") ?? typeName,
                        ["type"] = typeName,
                        ["typeName"] = typeName,
                        ["left"] = GetInt(item, "Left"),
                        ["top"] = GetInt(item, "Top"),
                        ["width"] = GetInt(item, "Width"),
                        ["height"] = GetInt(item, "Height"),
                        ["text"] = GetString(item, "Text") ?? GetString(item, "Caption") ?? "",
                        ["tag"] = GetString(item, "ProcessTag") ?? GetNestedTag(item),
                    });
                }
                screenObj["items"] = itemsArr;
                screensNode.Add(screenObj);
            }

            var root = new JsonObject
            {
                ["kind"] = "unified",
                ["screens"] = screensNode,
            };
            Directory.CreateDirectory(Path.GetDirectoryName(Path.GetFullPath(outPath))!);
            File.WriteAllText(outPath, root.ToJsonString(JsonOpts));
            return true;
        }
        catch
        {
            return false;
        }
    }

    private static object? GetProp(object target, string name)
    {
        var t = target.GetType();
        var p = t.GetProperty(name, BindingFlags.Public | BindingFlags.Instance | BindingFlags.IgnoreCase);
        return p?.GetValue(target);
    }

    private static string? GetString(object target, string name)
    {
        try
        {
            var v = GetProp(target, name);
            return v?.ToString();
        }
        catch
        {
            return null;
        }
    }

    private static int GetInt(object target, string name)
    {
        try
        {
            var v = GetProp(target, name);
            if (v is null) return 0;
            return Convert.ToInt32(v);
        }
        catch
        {
            return 0;
        }
    }

    private static bool GetBool(object target, string name)
    {
        try
        {
            var v = GetProp(target, name);
            if (v is null) return false;
            return Convert.ToBoolean(v);
        }
        catch
        {
            return false;
        }
    }

    private static string GetNestedTag(object item)
    {
        try
        {
            var dyn = GetProp(item, "Dynamization") ?? GetProp(item, "Tag");
            if (dyn is null) return "";
            return GetString(dyn, "Name") ?? GetString(dyn, "TagName") ?? dyn.ToString() ?? "";
        }
        catch
        {
            return "";
        }
    }

    private static IEnumerable<object?> Enumerate(object? collection)
    {
        if (collection is null) yield break;
        if (collection is System.Collections.IEnumerable en)
        {
            foreach (var x in en)
            {
                yield return x;
            }
            yield break;
        }
        // Some Openness folders expose .Items
        var items = GetProp(collection, "Items") ?? GetProp(collection, "ScreenItems");
        if (items is System.Collections.IEnumerable en2)
        {
            foreach (var x in en2)
            {
                yield return x;
            }
        }
    }
}

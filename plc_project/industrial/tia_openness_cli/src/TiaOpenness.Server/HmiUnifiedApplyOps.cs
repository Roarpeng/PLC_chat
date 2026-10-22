using System.Reflection;
using System.Text.Json;

namespace TiaOpenness.Server;

/// <summary>Apply Unified HMI ops JSON via reflection (Create/SetAttribute/Delete).</summary>
public static class HmiUnifiedApplyOps
{
    // TIA Unified exposes the tag binding under one of these names depending on
    // the item kind / Openness version. Probe in this order, never guess.
    private static readonly string[] BindingPropertyNames = { "ProcessTag", "PlcTag", "Tag" };

    // Colour channels of the ops payload → candidate item property names, in
    // probe order. Mirrors _COLOR_WRITE_TARGETS of the classic XML chain
    // (plc_engine/hmi_writeback.py) so both chains write the same attribute.
    private static readonly (string JsonKey, string[] PropertyNames)[] ColorChannels =
    {
        ("backColor",   new[] { "BackColor", "BgColor", "BackgroundColor", "Background", "FillColor" }),
        ("foreColor",   new[] { "ForeColor", "FgColor", "ForegroundColor", "FontColor", "TextColor", "Foreground" }),
        ("borderColor", new[] { "BorderColor", "FrameColor", "LineColor" }),
    };

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
        var total = 0;
        // skipped = capability/resolution gaps (no_api, unknown action, missing item);
        // failed  = real errors (Create invoked and threw, setter threw, ...).
        var skipped = new List<object>();
        var failed = new List<object>();
        var notes = new List<object>();

        foreach (var op in ops.EnumerateArray())
        {
            total++;
            var action = op.TryGetProperty("action", out var a) ? a.GetString() ?? "" : "";
            var screenName = op.TryGetProperty("screen", out var s) ? s.GetString() : null;
            var name = op.TryGetProperty("name", out var n) ? n.GetString() : null;
            try
            {
                var screen = FindScreen(software, screenName);
                if (screen is null)
                {
                    failed.Add(new { action, name, reason = "screen_not_found", code = "screen_not_found" });
                    continue;
                }
                if (string.Equals(action, "create", StringComparison.OrdinalIgnoreCase))
                {
                    var items = GetProp(screen, "ScreenItems");
                    if (items is null)
                    {
                        skipped.Add(new { action, name, reason = "ScreenItems not exposed", code = "no_api" });
                        continue;
                    }

                    var outcome = TryCreateItem(items, op);
                    if (!outcome.Applied)
                    {
                        skipped.Add(new
                        {
                            action,
                            name,
                            reason = outcome.Detail,
                            // no_api only when the API is genuinely absent; a
                            // signature/type mismatch is reported as unsupported.
                            code = outcome.NoApi ? "no_api" : "create_unsupported",
                        });
                        continue;
                    }

                    applied++;
                    if (outcome.Note is not null)
                        notes.Add(new { action, name, note = outcome.Note });
                    var created = outcome.Item ?? FindItem(screen, name);
                    if (created is not null)
                    {
                        ApplyGeometry(created, op);
                        var bindingNote = ApplyBinding(created, op);
                        if (bindingNote is not null)
                            RecordBindingGap(skipped, action, name, bindingNote);
                        RecordColorGaps(skipped, action, name, ApplyColors(created, op));
                    }
                    else if (op.TryGetProperty("tag", out var tagEl) && tagEl.ValueKind == JsonValueKind.String
                             && !string.IsNullOrWhiteSpace(tagEl.GetString()))
                    {
                        skipped.Add(new
                        {
                            action,
                            name,
                            reason = "created item could not be located to set the tag binding",
                            code = "binding_unverified",
                        });
                    }
                }
                else if (string.Equals(action, "update", StringComparison.OrdinalIgnoreCase))
                {
                    var item = FindItem(screen, name);
                    if (item is null)
                    {
                        failed.Add(new { action, name, reason = "item_not_found", code = "item_not_found" });
                        continue;
                    }
                    ApplyGeometry(item, op);
                    var bindingNote = ApplyBinding(item, op);
                    if (bindingNote is not null)
                        RecordBindingGap(skipped, action, name, bindingNote);
                    RecordColorGaps(skipped, action, name, ApplyColors(item, op));
                    applied++;
                }
                else if (string.Equals(action, "delete", StringComparison.OrdinalIgnoreCase))
                {
                    var item = FindItem(screen, name);
                    if (item is null)
                    {
                        failed.Add(new { action, name, reason = "item_not_found", code = "item_not_found" });
                        continue;
                    }
                    var del = item.GetType().GetMethod("Delete", Type.EmptyTypes);
                    if (del is null)
                    {
                        skipped.Add(new { action, name, reason = "Delete not exposed", code = "no_api" });
                        continue;
                    }
                    del.Invoke(item, null);
                    applied++;
                }
                else
                {
                    failed.Add(new { action, name, reason = "unknown_action", code = "unknown_action" });
                }
            }
            catch (Exception ex)
            {
                failed.Add(new { action, name, reason = Unwrap(ex).Message, code = "exception" });
            }
        }

        // `ok` must not be `skipped.Count == 0`: a create that Openness cannot
        // express is a capability gap, not a reason to report every run as failed.
        // An all-skipped batch, however, did not do anything and is not `ok`.
        var ok = failed.Count == 0 && !(applied == 0 && total > 0);
        return new
        {
            ok,
            applied,
            unapplied = total - applied,
            partial = applied > 0 && (skipped.Count > 0 || failed.Count > 0),
            code = ok ? null : failed.Count > 0 ? "apply_failed" : "nothing_applied",
            skipped,
            failed,
            notes,
        };
    }

    private static void RecordBindingGap(List<object> skipped, string action, string? name, string note)
    {
        var noApi = note == "binding_api_missing";
        skipped.Add(new
        {
            action,
            name,
            reason = note,
            code = noApi ? "no_api" : "binding_skipped",
        });
    }

    private static void ApplyGeometry(object item, JsonElement op)
    {
        SetIfPresent(item, "Left", op, "left");
        SetIfPresent(item, "Top", op, "top");
        SetIfPresent(item, "Width", op, "width");
        SetIfPresent(item, "Height", op, "height");
        SetIfPresent(item, "Text", op, "text");
    }

    /// <summary>
    /// Set the process/tag binding when the item exposes a writable string
    /// property. Returns null on success/no-op, otherwise a diagnostic code.
    /// Nothing is written unless the property is a string, so a failed probe
    /// cannot leave the TIA object in a half-modified (dirty) state.
    /// </summary>
    private static string? ApplyBinding(object item, JsonElement op)
    {
        if (!op.TryGetProperty("tag", out var el) || el.ValueKind != JsonValueKind.String)
            return null;
        var value = el.GetString();
        if (string.IsNullOrWhiteSpace(value))
            return null;

        foreach (var propName in BindingPropertyNames)
        {
            var property = item.GetType().GetProperty(
                propName,
                BindingFlags.Public | BindingFlags.Instance | BindingFlags.IgnoreCase);
            if (property is null || !property.CanWrite)
                continue;
            if (property.PropertyType != typeof(string))
                return $"binding_property_not_string:{propName}:{property.PropertyType.Name}";
            try
            {
                var current = property.GetValue(item) as string;
                if (string.Equals(current, value, StringComparison.Ordinal))
                    return null; // already correct: avoid marking the project dirty
                property.SetValue(item, value);
                return null;
            }
            catch (Exception ex)
            {
                return $"binding_set_failed:{propName}:{Unwrap(ex).Message}";
            }
        }
        return "binding_api_missing";
    }

    private static void RecordColorGaps(List<object> skipped, string action, string? name, List<string>? notes)
    {
        if (notes is null) return;
        foreach (var note in notes)
        {
            var noApi = note.StartsWith("color_api_missing", StringComparison.Ordinal);
            skipped.Add(new
            {
                action,
                name,
                reason = note,
                code = noApi ? "no_api" : "color_skipped",
            });
        }
    }

    /// <summary>
    /// Apply the backColor / foreColor / borderColor channels of an op.
    /// Returns null when every present channel applied cleanly (or none was
    /// present); otherwise one diagnostic note per unresolved channel.
    /// Internal for unit tests (InternalsVisibleTo TiaOpenness.Tests).
    /// </summary>
    internal static List<string>? ApplyColors(object item, JsonElement op)
    {
        List<string>? notes = null;
        foreach (var (jsonKey, propertyNames) in ColorChannels)
        {
            var note = TrySetColor(item, op, jsonKey, propertyNames);
            if (note is null) continue;
            notes ??= new List<string>();
            notes.Add(note);
        }
        return notes;
    }

    /// <summary>
    /// Set one colour channel. The ops payload carries normalised
    /// ``#RRGGBB`` strings (same representation as the classic XML chain).
    /// A property is only written when its type is understood: string keeps
    /// ``#RRGGBB``; uint/int receives the RGB decimal ``R&lt;&lt;16 | G&lt;&lt;8 | B``
    /// (the encoding the classic chain writes for decimal attributes).
    /// Anything else is reported, never guessed.
    /// </summary>
    private static string? TrySetColor(object item, JsonElement op, string jsonKey, string[] propertyNames)
    {
        if (!op.TryGetProperty(jsonKey, out var el) || el.ValueKind != JsonValueKind.String)
            return null; // channel not requested: no-op, not a gap
        var hex = el.GetString();
        if (!TryParseRgbHex(hex, out var red, out var green, out var blue))
            return $"color_invalid_value:{jsonKey}:{hex}";

        var rgb = (red << 16) | (green << 8) | blue;
        foreach (var propName in propertyNames)
        {
            var property = item.GetType().GetProperty(
                propName,
                BindingFlags.Public | BindingFlags.Instance | BindingFlags.IgnoreCase);
            if (property is null || !property.CanWrite)
                continue;
            var propertyType = property.PropertyType;
            try
            {
                object value;
                if (propertyType == typeof(string))
                    value = hex!;
                else if (propertyType == typeof(uint) || propertyType == typeof(int))
                    value = Convert.ChangeType(rgb, propertyType);
                else if (propertyType.Name == "Color" && propertyType.IsValueType)
                {
                    // Unified exposes e.g. BackColor as a Color struct (V19 real
                    // machine: color_property_unsupported:backColor:BackColor:Color).
                    // Build it via FromArgb(alpha, r, g, b); reflect the property's
                    // own type so non-Drawing Color structs work the same way.
                    var converted = TryFromArgb(propertyType, red, green, blue);
                    if (converted is null)
                        return $"color_invalid_value:{jsonKey}:FromArgb(255,{red},{green},{blue}) not usable on {propertyType.FullName}";
                    value = converted;
                }
                else
                    return $"color_property_unsupported:{jsonKey}:{propName}:{propertyType.Name}";
                var current = property.GetValue(item);
                if (Equals(current, value))
                    return null; // already correct: avoid marking the project dirty
                property.SetValue(item, value);
                return null;
            }
            catch (Exception ex)
            {
                return $"color_set_failed:{propName}:{Unwrap(ex).Message}";
            }
        }
        return $"color_api_missing:{jsonKey}";
    }

    /// <summary>
    /// Build a Color value from RGB via the property type's own FromArgb:
    /// prefer the (alpha, r, g, b) overload, fall back to (r, g, b).
    /// Returns null when no usable overload exists (reported as invalid value,
    /// never guessed).
    /// </summary>
    private static object? TryFromArgb(Type colorType, int red, int green, int blue)
    {
        if (colorType == typeof(System.Drawing.Color))
            return System.Drawing.Color.FromArgb(255, red, green, blue);
        foreach (var method in colorType.GetMethods(BindingFlags.Public | BindingFlags.Static))
        {
            if (!string.Equals(method.Name, "FromArgb", StringComparison.Ordinal))
                continue;
            var ps = method.GetParameters();
            try
            {
                if (ps.Length == 4 && ps.All(p => p.ParameterType == typeof(int)))
                    return method.Invoke(null, new object[] { 255, red, green, blue });
                if (ps.Length == 3 && ps.All(p => p.ParameterType == typeof(int)))
                    return method.Invoke(null, new object[] { red, green, blue });
            }
            catch
            {
                // try the next overload
            }
        }
        return null;
    }

    private static bool TryParseRgbHex(string? hex, out int red, out int green, out int blue)
    {
        red = green = blue = 0;
        if (hex is null || hex.Length != 7 || hex[0] != '#')
            return false;
        for (var i = 1; i < 7; i++)
        {
            if (!Uri.IsHexDigit(hex[i]))
                return false;
        }
        red = Convert.ToInt32(hex.Substring(1, 2), 16);
        green = Convert.ToInt32(hex.Substring(3, 2), 16);
        blue = Convert.ToInt32(hex.Substring(5, 2), 16);
        return true;
    }

    private sealed class CreateOutcome
    {
        public bool Applied;
        public bool NoApi;
        public string Detail = "";
        public string? Note;
        public object? Item;
    }

    /// <summary>
    /// Best-effort ScreenItems.Create. V19 Unified exposes generic overloads
    /// (Create&lt;T&gt;), so a MethodInfo with ContainsGenericParameters must first
    /// be closed via MakeGenericMethod(concrete item type) — the type is
    /// resolved from loaded HmiUnified assemblies against the op's `type`,
    /// filtered by the generic parameter's constraint when present. Unresolved
    /// candidates are reported for diagnostics.
    /// </summary>
    private static CreateOutcome TryCreateItem(object items, JsonElement op)
    {
        var outcome = new CreateOutcome();
        var methods = items.GetType()
            .GetMethods(BindingFlags.Public | BindingFlags.Instance)
            .Where(m => m.Name == "Create")
            .OrderBy(m => m.GetParameters().Length)
            .ToList();
        if (methods.Count == 0)
        {
            outcome.NoApi = true;
            outcome.Detail = "ScreenItems.Create is not exposed by this Openness version";
            return outcome;
        }

        var signatures = string.Join(" | ", methods.Select(DescribeSignature));
        var lastDetail = "";
        var lastThrow = "";
        foreach (var rawMethod in methods)
        {
            MethodInfo method = rawMethod;
            if (rawMethod.ContainsGenericParameters)
            {
                var genericArgs = rawMethod.GetGenericArguments();
                var constraintDesc = string.Join("; ", genericArgs
                    .Select(g => $"{g.Name}:" + string.Join(",", g.GetGenericParameterConstraints().Select(c => c.FullName))));
                var itemType = ResolveItemType(GetString(op, "tiaType") ?? GetString(op, "type"), genericArgs);
                if (itemType is null)
                {
                    if (string.IsNullOrEmpty(lastDetail))
                    {
                        lastDetail = $"generic Create<{string.Join(",", genericArgs.Select(g => g.Name))}> [{constraintDesc}] "
                            + $"could not resolve item type for '{GetString(op, "type")}'; candidates: {ListItemTypeCandidates(genericArgs)}";
                    }
                    continue;
                }
                try
                {
                    method = rawMethod.MakeGenericMethod(itemType);
                }
                catch (Exception ex)
                {
                    if (string.IsNullOrEmpty(lastDetail))
                        lastDetail = $"MakeGenericMethod({itemType.FullName}) threw: {Unwrap(ex).Message}";
                    continue;
                }
                outcome.Note = $"closed Create<{itemType.FullName}> via MakeGenericMethod; constraints [{constraintDesc}]; open signature {DescribeSignature(rawMethod)}";
            }

            if (!TryBindCreateArgs(method.GetParameters(), op, out var args, out var bindDetail))
            {
                if (string.IsNullOrEmpty(lastDetail)) lastDetail = bindDetail;
                continue;
            }
            try
            {
                var returned = method.Invoke(items, args);
                outcome.Applied = true;
                outcome.Item = returned;
                return outcome;
            }
            catch (Exception ex)
            {
                // Keep the richest diagnostic: an invocation error outranks a
                // later overload's bind mismatch.
                lastThrow = $"Create({args.Length} args) threw: {Unwrap(ex).Message}";
            }
        }

        outcome.Detail = !string.IsNullOrEmpty(lastThrow)
            ? $"{lastThrow}; available: {signatures}"
            : string.IsNullOrEmpty(lastDetail)
                ? $"Create signatures unsupported: {signatures}"
                : $"{lastDetail}; available: {signatures}";
        return outcome;
    }

    private static string DescribeSignature(MethodInfo method)
    {
        var ps = method.GetParameters()
            .Select(p => $"{p.ParameterType.Name} {p.Name}")
            .ToArray();
        return $"{method.Name}({string.Join(", ", ps)})";
    }

    private static bool TryBindCreateArgs(
        ParameterInfo[] parameters,
        JsonElement op,
        out object?[] args,
        out string detail)
    {
        args = new object?[parameters.Length];
        detail = "";
        for (var i = 0; i < parameters.Length; i++)
        {
            var parameter = parameters[i];
            var name = (parameter.Name ?? "").ToLowerInvariant();
            var type = parameter.ParameterType;

            if (type == typeof(string))
            {
                if (name.Contains("name"))
                {
                    args[i] = GetString(op, "name") ?? "";
                }
                else if (name.Contains("type"))
                {
                    // e.g. Unified ScreenItems.Create(String name, String containedTypeValue):
                    // the item type is passed as a plain string, not a System.Type.
                    args[i] = GetString(op, "tiaType") ?? GetString(op, "type") ?? "";
                }
                else if (name.Contains("text") || name.Contains("caption"))
                {
                    args[i] = GetString(op, "text") ?? "";
                }
                else
                {
                    detail = $"unsupported string parameter '{parameter.Name}'";
                    return false;
                }
            }
            else if (type == typeof(int) || type == typeof(uint) || type == typeof(short))
            {
                var value = name switch
                {
                    var n when n.Contains("left") || n == "x" => GetInt(op, "left"),
                    var n when n.Contains("top") || n == "y" => GetInt(op, "top"),
                    var n when n.Contains("width") => GetInt(op, "width"),
                    var n when n.Contains("height") => GetInt(op, "height"),
                    _ => 0,
                };
                args[i] = Convert.ChangeType(value, type);
            }
            else if (type == typeof(bool))
            {
                args[i] = false;
            }
            else if (type == typeof(Type))
            {
                var resolved = ResolveItemType(GetString(op, "tiaType") ?? GetString(op, "type"));
                if (resolved is null)
                {
                    detail = $"cannot resolve Openness item type for '{GetString(op, "type")}' in loaded assemblies";
                    return false;
                }
                args[i] = resolved;
            }
            else if (type.IsEnum)
            {
                args[i] = Activator.CreateInstance(type);
            }
            else
            {
                detail = $"unsupported parameter '{parameter.Name}:{type.Name}'";
                return false;
            }
        }
        return true;
    }

    /// <summary>
    /// Resolve the concrete screen-item type for an op's `type` from loaded
    /// assemblies. Preference order: HmiUnified-namespace exact name, Hmi
    /// namespace exact name, then suffix/containment matches; when the generic
    /// parameter carries a constraint, candidates must be assignable to it.
    /// </summary>
    private static Type? ResolveItemType(string? typeName, Type[]? genericArgs = null)
    {
        if (string.IsNullOrWhiteSpace(typeName))
            return null;
        EnsureHmiAssembliesLoaded();
        var wanted = Normalize(typeName!);
        var candidates = new List<Type>();
        foreach (var assembly in AppDomain.CurrentDomain.GetAssemblies())
        {
            Type[] types;
            try
            {
                types = assembly.GetTypes();
            }
            catch (Exception)
            {
                continue; // dynamic/partially loadable assembly
            }
            foreach (var type in types)
            {
                if (!type.IsClass || type.IsAbstract || !type.IsPublic)
                    continue;
                var ns = type.Namespace ?? "";
                if (ns.IndexOf("Hmi", StringComparison.OrdinalIgnoreCase) < 0)
                    continue;
                var normalizedName = Normalize(type.Name);
                if (normalizedName != wanted && normalizedName != "hmi" + wanted
                    && !(normalizedName.Contains(wanted) && wanted.Length >= 4))
                    continue;
                if (!SatisfiesConstraints(type, genericArgs))
                    continue;
                candidates.Add(type);
            }
        }

        return candidates
            .OrderBy(t =>
            {
                var ns = t.Namespace ?? "";
                if (ns.IndexOf("HmiUnified", StringComparison.OrdinalIgnoreCase) >= 0) return 0;
                if (Normalize(t.Name) == wanted) return 1;
                return 2;
            })
            .ThenBy(t => t.Name.Length)
            .FirstOrDefault();
    }

    private static bool _hmiAssembliesLoadAttempted;

    /// <summary>
    /// The Unified screen-item types live in Siemens.Engineering.Hmi.dll,
    /// which TiaConnection does not preload (it stages only the core
    /// Siemens.Engineering.dll). Load it once on demand from the Portal
    /// PublicAPI directory so Create&lt;T&gt; can be closed with a real type.
    /// </summary>
    private static void EnsureHmiAssembliesLoaded()
    {
        if (_hmiAssembliesLoadAttempted) return;
        _hmiAssembliesLoadAttempted = true;
        try
        {
            if (AppDomain.CurrentDomain.GetAssemblies().Any(a => a.GetName().Name == "Siemens.Engineering.Hmi"))
                return;
        }
        catch { /* ignore */ }

        var roots = new List<string>();
        var portalRoot = Environment.GetEnvironmentVariable("TIA_PORTAL_ROOT");
        if (!string.IsNullOrWhiteSpace(portalRoot)) roots.Add(portalRoot);
        roots.Add(@"C:\Program Files\Siemens\Automation\Portal V19");
        roots.Add(@"C:\Program Files\Siemens\Automation\Portal V20");
        var eng = AppDomain.CurrentDomain.GetAssemblies()
            .FirstOrDefault(a => a.GetName().Name == "Siemens.Engineering");
        if (eng is not null && !string.IsNullOrEmpty(eng.Location))
        {
            // staged copy sits in a temp dir; the real PublicAPI tree is not
            // derivable from it, so also try the sibling PublicAPI layout.
            var stageDir = Path.GetDirectoryName(eng.Location);
            if (stageDir is not null) roots.Add(Path.GetFullPath(Path.Combine(stageDir, @"..\..\..")));
        }

        foreach (var root in roots)
        {
            foreach (var sub in new[] { @"PublicAPI\V19", @"PublicAPI\V20", @"PublicAPI", @"Bin\PublicAPI" })
            {
                var candidate = Path.Combine(root, sub, "Siemens.Engineering.Hmi.dll");
                try
                {
                    if (File.Exists(candidate))
                    {
                        Assembly.LoadFrom(candidate);
                        return;
                    }
                }
                catch
                {
                    // try next location
                }
            }
        }
    }

    private static bool SatisfiesConstraints(Type candidate, Type[]? genericArgs)
    {
        if (genericArgs is null || genericArgs.Length == 0) return true;
        foreach (var arg in genericArgs)
        {
            foreach (var constraint in arg.GetGenericParameterConstraints())
            {
                if (!constraint.IsAssignableFrom(candidate))
                    return false;
            }
        }
        return true;
    }

    /// <summary>Names of all constraint-satisfying item-type candidates (diagnostics).</summary>
    private static string ListItemTypeCandidates(Type[]? genericArgs)
    {
        var names = new List<string>();
        foreach (var assembly in AppDomain.CurrentDomain.GetAssemblies())
        {
            Type[] types;
            try
            {
                types = assembly.GetTypes();
            }
            catch (Exception)
            {
                continue;
            }
            foreach (var type in types)
            {
                if (!type.IsClass || type.IsAbstract || !type.IsPublic)
                    continue;
                var ns = type.Namespace ?? "";
                if (ns.IndexOf("Hmi", StringComparison.OrdinalIgnoreCase) < 0)
                    continue;
                if (!SatisfiesConstraints(type, genericArgs))
                    continue;
                names.Add(type.FullName ?? type.Name);
            }
        }
        return names.Count == 0
            ? "(none)"
            : string.Join(", ", names.Distinct().OrderBy(n => n).Take(30));
    }

    private static string Normalize(string value)
    {
        var chars = value.Where(char.IsLetterOrDigit).ToArray();
        return new string(chars).ToLowerInvariant();
    }

    private static string? GetString(JsonElement op, string name)
    {
        return op.TryGetProperty(name, out var el) && el.ValueKind == JsonValueKind.String
            ? el.GetString()
            : null;
    }

    private static int GetInt(JsonElement op, string name)
    {
        if (!op.TryGetProperty(name, out var el))
            return 0;
        if (el.ValueKind == JsonValueKind.Number && el.TryGetInt32(out var value))
            return value;
        if (el.ValueKind == JsonValueKind.String && int.TryParse(el.GetString(), out var parsed))
            return parsed;
        return 0;
    }

    private static Exception Unwrap(Exception ex)
    {
        return ex is TargetInvocationException { InnerException: not null } tie ? tie.InnerException! : ex;
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

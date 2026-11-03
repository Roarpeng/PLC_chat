using System.Security.Cryptography;
using System.Text.Json.Serialization;

namespace TiaOpenness.Server;

/// <summary>
/// V3.0 Tab5「Openness 研发级异常排故字典」里仍缺的护栏（纯函数 + 数据结构，
/// 不含任何强类型 Siemens.Engineering 引用）：
///   1) 白名单注册表路径生成 + 当前 exe SHA256（供 PowerShell 脚本写入）
///   2) LAD/FBD 导出分流判定（明文 GenerateSource vs Block.Export XML vs 黑盒拒绝）
///   3) IDB 接口刷新判定（改 FB 接口必须连带生成背景 DB 声明）
///   6) 多版本 Siemens.Engineering.dll 解析（程序集版本 + 目录名映射）
/// </summary>
public static class OpennessGuardrails
{
    public const string RoutePlainSource = "PlainSource";
    public const string RouteXmlExport = "XmlExport";
    public const string RouteReadOnlyBlackBox = "ReadOnly_BlackBox";

    /// <summary>
    /// 为什么改了 FB 的 VAR_INPUT/VAR 必须连带生成背景 DB 声明（Tab5 第 4 条）：
    /// GenerateBlocksFromSource 只重建 FB 本体，不会刷新已存在的 Instance DB (IDB)；
    /// FB 接口变化后旧 IDB 仍按旧接口时间戳/偏移量布局，编译期报「接口时间戳不一致」
    /// 或运行期读到错位数据。因此 interfaceChanged==true 时必须在 AF_Batch.scl 末尾
    /// 追加 DATA_BLOCK "IDB_XXX" "FB_XXX" BEGIN END_DATA_BLOCK 声明并重新 Compile()，
    /// 让 Openness 按新接口重新生成背景数据块。
    /// </summary>
    public const string InstanceDbRefreshReason =
        "GenerateBlocksFromSource 只重建 FB 本体，不会刷新已存在的 Instance DB (IDB)："
        + "FB 的 VAR_INPUT/VAR/VAR_OUTPUT 接口变化后，旧 IDB 仍按旧接口时间戳/偏移量布局，"
        + "编译期报『接口时间戳不一致』或运行期读到错位数据。"
        + "因此 interfaceChanged==true 时必须在 AF_Batch.scl 末尾追加 "
        + "DATA_BLOCK \"IDB_XXX\" \"FB_XXX\" BEGIN END_DATA_BLOCK 声明并重新 Compile()，"
        + "让 Openness 按新接口重新生成背景数据块。";

    // TIA 版本 -> (程序集版本, Openness 注册表 hive 版本)。
    // 目录名不另起一套：TiaConnection.FindEngineeringDll() 用 TiaVersion 作为
    // PublicAPI 子目录名（Path.Combine(portalRoot, "PublicAPI", TiaVersion, ...)），
    // 并用 "Portal {TiaVersion}" 作为安装根目录，这里原样沿用。
    private static readonly (string TiaVersion, string AssemblyVersion, string OpennessHiveVersion)[] VersionMap =
    {
        ("V14 SP1", "14.0.1.0", "14.0"),
        ("V15",     "15.0.0.0", "15.0"),
        ("V15.1",   "15.1.0.0", "15.1"),
        ("V16",     "16.0.0.0", "16.0"),
        ("V17",     "17.0.0.0", "17.0"),
        ("V18",     "18.0.0.0", "18.0"),
        ("V19",     "19.0.0.0", "19.0"),
    };

    // ---------------------------------------------------------------------
    // 6) 多版本 DLL 解析
    // ---------------------------------------------------------------------

    /// <summary>把常见别名（17 / 17.0 / v17 / 14.0.1.0 / V15.1 …）归一化为标准键。</summary>
    public static string NormalizeTiaVersion(string tiaVersion)
    {
        var s = (tiaVersion ?? "").Trim();
        if (s.Length == 0) return TiaConnection.DefaultVersion;
        var u = s.ToUpperInvariant();
        foreach (var row in VersionMap)
        {
            if (u == row.TiaVersion.ToUpperInvariant()) return row.TiaVersion;
        }
        if (u.Contains("15.1") || u.Contains("151")) return "V15.1";
        var digits = new string(s.SkipWhile(c => !char.IsDigit(c)).TakeWhile(c => char.IsDigit(c)).ToArray());
        if (int.TryParse(digits, out var major) && major >= 14 && major <= 19)
        {
            if (major == 14 && (u.Contains("SP1") || u.Contains("14.0.1"))) return "V14 SP1";
            return "V" + major;
        }
        // 未知版本原样返回，让 TiaConnection.FindEngineeringDll() 继续按原字符串探测。
        return s;
    }

    /// <summary>结构化的版本信息（程序集版本 + 沿用 FindEngineeringDll 的目录名）。</summary>
    public static EngineeringVersionInfo? TryResolveVersionInfo(string tiaVersion)
    {
        var key = NormalizeTiaVersion(tiaVersion);
        foreach (var row in VersionMap)
        {
            if (!string.Equals(row.TiaVersion, key, StringComparison.OrdinalIgnoreCase)) continue;
            return new EngineeringVersionInfo
            {
                TiaVersion = row.TiaVersion,
                AssemblyVersion = row.AssemblyVersion,
                // 与 TiaConnection.FindEngineeringDll() 完全一致：
                // Path.Combine(portalRoot, "PublicAPI", TiaVersion, "Siemens.Engineering.dll")
                PublicApiDirectory = row.TiaVersion,
                PortalInstallDirectory = "Portal " + row.TiaVersion,
                OpennessHiveVersion = row.OpennessHiveVersion,
            };
        }
        return null;
    }

    /// <summary>
    /// V14 SP1/V15/V15.1/V16/V17/V18/V19 → 程序集版本 + 目录名（单一来源，
    /// 与 FindEngineeringDll 的目录拼法一致，不另起一套）。
    /// </summary>
    public static string ResolveEngineeringDllVersion(string tiaVersion)
    {
        var info = TryResolveVersionInfo(tiaVersion);
        if (info is null)
        {
            return "unmapped: " + (tiaVersion ?? "")
                 + " (no assembly-version row; TiaConnection.FindEngineeringDll() will still probe "
                 + "PublicAPI/<TiaVersion> and env TIA_PORTAL_ROOT)";
        }
        return $"{info.TiaVersion} -> assembly {info.AssemblyVersion}, "
             + $"PublicAPI dir \"{info.PublicApiDirectory}\", "
             + $"install dir \"{info.PortalInstallDirectory}\", "
             + $"Openness hive \"{info.OpennessHiveVersion}\"";
    }

    /// <summary>实际 DLL 路径：直接委托既有实现，避免重复拼接逻辑。</summary>
    public static string? ResolveEngineeringDllPath(string tiaVersion) =>
        new TiaConnection(NormalizeTiaVersion(tiaVersion)).FindEngineeringDll();

    /// <summary>
    /// TiaPortal.ExclusiveAccess(string) 自 V14 SP1 起提供；V14 RTM 及更早显式降级。
    /// 供 FastWriteback.TryAcquireExclusiveAccess 前置判定，避免调用不存在的 API。
    /// </summary>
    public static bool IsPreExclusiveAccessVersion(string tiaVersion)
    {
        var v = NormalizeTiaVersion(tiaVersion);
        var digits = new string(v.SkipWhile(c => !char.IsDigit(c)).TakeWhile(c => char.IsDigit(c)).ToArray());
        if (!int.TryParse(digits, out var major)) return false;
        if (major < 14) return true;
        if (major > 14) return false;
        return !v.ToUpperInvariant().Contains("SP1");
    }

    // ---------------------------------------------------------------------
    // 1) 白名单注册表路径生成 + 当前 exe SHA256
    // ---------------------------------------------------------------------

    /// <summary>
    /// 返回白名单**父键**：HKLM\SOFTWARE\Siemens\Automation\Openness\{version}\Whitelist\{app}.exe
    /// 真实格式（已在 TIA Portal V19 本机核实）：父键下为 Entry / Entry (1) / Entry (N) **子键**，
    /// 每个子键含 Path / DateModified / FileHash 三个 REG_SZ 值，FileHash 是 SHA256 字节的 Base64。
    /// 追加编号由 tools/Register-OpennessWhitelist.ps1 计算，本函数只给出父键。
    /// </summary>
    public static string BuildWhitelistRegistryPath(string tiaVersion, string appExePath)
    {
        var info = TryResolveVersionInfo(tiaVersion);
        var hive = info?.OpennessHiveVersion ?? InferOpennessHive(tiaVersion);
        var app = string.IsNullOrWhiteSpace(appExePath) ? "{App}.exe" : Path.GetFileName(appExePath);
        return $@"HKLM\SOFTWARE\Siemens\Automation\Openness\{hive}\Whitelist\{app}";
    }

    /// <summary>
    /// 产出可供 tools/Register-OpennessWhitelist.ps1 写入的数据结构：
    /// 父键、Entry 子键格式、三个值名、当前 exe 的 SHA256（hex 与 Base64）、
    /// 最后修改时间和版本映射信息。不写注册表，只算数据（写操作交给 PowerShell 脚本）。
    /// </summary>
    public static OpennessWhitelistEntry BuildWhitelistEntry(string tiaVersion, string appExePath)
    {
        if (string.IsNullOrWhiteSpace(appExePath))
        {
            throw new ArgumentException("AppPath 不能为空。", nameof(appExePath));
        }
        var full = Path.GetFullPath(appExePath);
        if (!File.Exists(full))
        {
            throw new FileNotFoundException("找不到待注册的 exe：" + full, full);
        }

        var info = TryResolveVersionInfo(tiaVersion);
        var hive = info?.OpennessHiveVersion ?? InferOpennessHive(tiaVersion);
        var app = Path.GetFileName(full);
        var key = $@"SOFTWARE\Siemens\Automation\Openness\{hive}\Whitelist\{app}";
        // TIA 校验的是「Entry 子键里的三个值」，不是父键下名为 Entry 的值。
        return new OpennessWhitelistEntry
        {
            RegistryPath = $@"HKLM\{key}\Entry (N)",
            Hive = "HKLM",
            Key = key,
            ValueName = "Path",
            RegistryValueNames = "Path, DateModified, FileHash",
            AppPath = full,
            AppFileName = app,
            Sha256 = ComputeSha256(full),
            FileHashBase64 = ComputeSha256Base64(full),
            LastWriteTimeUtc = File.GetLastWriteTimeUtc(full)
                .ToString("yyyy/MM/dd HH:mm:ss.fff", System.Globalization.CultureInfo.InvariantCulture),
            TiaVersion = info?.TiaVersion ?? NormalizeTiaVersion(tiaVersion),
            OpennessHiveVersion = hive,
            AssemblyVersion = info?.AssemblyVersion ?? "unmapped",
            PublicApiDirectory = info?.PublicApiDirectory ?? NormalizeTiaVersion(tiaVersion),
        };
    }

    /// <summary>用 System.Security.Cryptography 计算文件 SHA256（小写十六进制）。</summary>
    public static string ComputeSha256(string filePath)
    {
        using var sha = SHA256.Create();
        using var stream = File.OpenRead(filePath);
        return string.Concat(sha.ComputeHash(stream).Select(b => b.ToString("x2")));
    }

    /// <summary>SHA256 原始字节的 Base64 —— TIA 注册表 FileHash 值用的正是这个格式。</summary>
    public static string ComputeSha256Base64(string filePath)
    {
        using var sha = SHA256.Create();
        using var stream = File.OpenRead(filePath);
        return Convert.ToBase64String(sha.ComputeHash(stream));
    }

    private static string InferOpennessHive(string tiaVersion)
    {
        var key = NormalizeTiaVersion(tiaVersion);
        var digits = new string(key.SkipWhile(c => !char.IsDigit(c)).TakeWhile(c => char.IsDigit(c)).ToArray());
        // 未映射版本兜底：文档示例用 17.0；已知版本一律走 VersionMap 精确值。
        return int.TryParse(digits, out var major) ? major + ".0" : "17.0";
    }

    // ---------------------------------------------------------------------
    // 2) LAD/FBD 导出分流判定
    // ---------------------------------------------------------------------

    /// <summary>
    /// 纯函数：true 表示该块必须走 Block.Export(xml, ExportOptions.WithDefaults)
    /// 导出 SimaticML XML（LAD/FBD）；false 表示走 GenerateSource() 明文
    /// （SCL/STL/DB/UDT），或该语言被判为黑盒不可导出（F_LAD/F_FBD，见
    /// ClassifyExportRoute）。Tab5 第 2、5 条。
    /// </summary>
    public static bool ShouldUseXmlExport(string programmingLanguage)
    {
        var lang = (programmingLanguage ?? "").Trim().ToUpperInvariant();
        // F_LAD / F_FBD 与故障安全语言 → 黑盒，不是 XML 导出（由 ClassifyExportRoute 拒绝）
        if (lang.StartsWith("F_", StringComparison.Ordinal)
            || lang.Contains("SAFETY") || lang.Contains("FAILSAFE"))
        {
            return false;
        }
        return lang is "LAD" or "FBD" or "LADDER" or "FUP" or "KOP" or "LAD_FBD";
    }

    /// <summary>
    /// 三态分流（含 KnowHowProtected 与 F_* 的拒绝）：
    ///   PlainSource      -> ExternalSourceGroup.GenerateSource() 明文
    ///   XmlExport        -> Block.Export() SimaticML XML
    ///   ReadOnly_BlackBox-> 拒绝导出，仅提取 IO 引脚供普通块调用
    /// ShouldUseXmlExport 只能表达「是否 XML」；黑盒拒绝在本函数给出明确落点。
    /// </summary>
    public static string ClassifyExportRoute(string programmingLanguage, bool knowHowProtected)
    {
        var lang = (programmingLanguage ?? "").Trim().ToUpperInvariant();
        if (knowHowProtected
            || lang.StartsWith("F_", StringComparison.Ordinal)
            || lang is "F_LAD" or "F_FBD"
            || lang.Contains("SAFETY") || lang.Contains("FAILSAFE"))
        {
            return RouteReadOnlyBlackBox;
        }
        return ShouldUseXmlExport(lang) ? RouteXmlExport : RoutePlainSource;
    }

    // ---------------------------------------------------------------------
    // 3) IDB 接口刷新判定
    // ---------------------------------------------------------------------

    /// <summary>
    /// interfaceChanged==true 时必须连带生成背景 DB 声明（原因见 InstanceDbRefreshReason）。
    /// 纯函数，直接返回入参，便于调用方与单测断言。
    /// </summary>
    public static bool NeedsInstanceDbRefresh(bool interfaceChanged) => interfaceChanged;

    /// <summary>批次块名是否像 UDT / GlobalDB（用于兜底判定是否需全量编译）。</summary>
    public static bool LooksLikeTypeOrGlobalDbName(string blockName)
    {
        var n = (blockName ?? "").Trim();
        if (n.Length == 0) return false;
        return n.StartsWith("UDT", StringComparison.OrdinalIgnoreCase)
            || n.StartsWith("TYPE_", StringComparison.OrdinalIgnoreCase)
            || n.EndsWith("_UDT", StringComparison.OrdinalIgnoreCase)
            || n.IndexOf("GlobalDB", StringComparison.OrdinalIgnoreCase) >= 0;
    }
}

// -------------------------------------------------------------------------
// 供 PowerShell 脚本 / 诊断使用的数据结构（camelCase JSON）
// -------------------------------------------------------------------------

public sealed class EngineeringVersionInfo
{
    [JsonPropertyName("tiaVersion")]
    public string TiaVersion { get; set; } = "";

    [JsonPropertyName("assemblyVersion")]
    public string AssemblyVersion { get; set; } = "";

    [JsonPropertyName("publicApiDirectory")]
    public string PublicApiDirectory { get; set; } = "";

    [JsonPropertyName("portalInstallDirectory")]
    public string PortalInstallDirectory { get; set; } = "";

    [JsonPropertyName("opennessHiveVersion")]
    public string OpennessHiveVersion { get; set; } = "";
}

public sealed class OpennessWhitelistEntry
{
    [JsonPropertyName("registryPath")]
    public string RegistryPath { get; set; } = "";

    [JsonPropertyName("hive")]
    public string Hive { get; set; } = "HKLM";

    [JsonPropertyName("key")]
    public string Key { get; set; } = "";

    [JsonPropertyName("valueName")]
    public string ValueName { get; set; } = "Path";

    [JsonPropertyName("registryValueNames")]
    public string RegistryValueNames { get; set; } = "Path, DateModified, FileHash";

    [JsonPropertyName("appPath")]
    public string AppPath { get; set; } = "";

    [JsonPropertyName("appFileName")]
    public string AppFileName { get; set; } = "";

    [JsonPropertyName("sha256")]
    public string Sha256 { get; set; } = "";

    [JsonPropertyName("fileHashBase64")]
    public string FileHashBase64 { get; set; } = "";

    [JsonPropertyName("lastWriteTimeUtc")]
    public string LastWriteTimeUtc { get; set; } = "";

    [JsonPropertyName("tiaVersion")]
    public string TiaVersion { get; set; } = "";

    [JsonPropertyName("opennessHiveVersion")]
    public string OpennessHiveVersion { get; set; } = "";

    [JsonPropertyName("assemblyVersion")]
    public string AssemblyVersion { get; set; } = "";

    [JsonPropertyName("publicApiDirectory")]
    public string PublicApiDirectory { get; set; } = "";
}

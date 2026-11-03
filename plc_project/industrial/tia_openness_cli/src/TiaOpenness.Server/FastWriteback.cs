using System.Collections;
using System.Diagnostics;
using System.Reflection;
using System.Text.Json;
using System.Text.Json.Serialization;
using System.Text.RegularExpressions;
using TiaOpenness.Models;

namespace TiaOpenness.Server;

/// <summary>
/// V3.0 Tab1 极速回写：单次 Mega-Source 导入 + ExclusiveAccess UI 冻结 +
/// 分级增量编译 + 结构化编译错误树 + 快照/回滚钩子。
///
/// 与本仓库其它文件一致，这里 **不静态引用 Siemens.Engineering.dll**：所有
/// Openness 成员（TiaPortal.ExclusiveAccess(string) / ICompilable / CompilerResult.Messages）
/// 都经反射或 TiaConnection.GetService() 调用，以兼容 V14 SP1 ~ V19 多版本。
/// 任何一步的 API 缺失都 fail-closed 或明确降级，绝不谎报成功。
/// </summary>
public static class FastWriteback
{
    private const string ICompilableFullName = "Siemens.Engineering.Compiler.ICompilable";
    private const string DefaultExclusiveAccessReason = "PLC_Chat 正在批量回写 AF 程序块...";

    // ---------------------------------------------------------------------
    // 入口
    // ---------------------------------------------------------------------

    /// <summary>由 SessionServer 的 /fast-writeback 路由在 STA 线程上调用。</summary>
    public static FastWritebackResult Execute(
        TiaConnection connection,
        ProjectService projects,
        BlockService blocks,
        FastWritebackRequest request)
    {
        var sw = Stopwatch.StartNew();
        var result = new FastWritebackResult();
        object? lease = null;

        try
        {
            // 0) 参数校验（fail-closed：SCL 缺失不碰项目）
            if (string.IsNullOrWhiteSpace(request.SclPath) || !File.Exists(request.SclPath))
            {
                result.Success = false;
                result.Error = new ToolError
                {
                    Code = "invalid_argument",
                    Message = "fast-writeback 需要有效的 scl（单个 Mega-Source .scl 文件路径）。",
                };
                return result;
            }

            // 1) 快照 / 回滚钩子（不复制 .zap，真实文件操作留给上层编排）
            var snapshot = CaptureSnapshot(projects, request.SclPath);
            result.Snapshot = snapshot;
            result.SnapshotHint = snapshot.RestoreHint;

            // 2) ExclusiveAccess（反射；V14 SP1 之前 / 无 UI 会话优雅降级）
            var (acquired, skipReason) = TryAcquireExclusiveAccess(connection, request.ExclusiveAccessReason);
            lease = acquired;
            result.ExclusiveAccessUsed = acquired is not null;
            result.ExclusiveAccessSkipReason = skipReason;

            // 3) 单次 Mega-Source 导入（锁内；绝不逐块循环）
            var generated = blocks.GenerateBlocksFromSource(
                request.SclPath, overwrite: true, softwareUnit: request.SoftwareUnit);

            // 与 V3.0 文档一致：独占锁只覆盖批量生成段，生成结束立即释放。
            if (lease is not null)
            {
                ReleaseExclusiveAccess(lease);
                lease = null;
            }

            result.GenerateApi = generated.Api;
            result.GeneratedNames = generated.GeneratedNames;
            var names = generated.GeneratedNames ?? new List<string>();
            result.WrittenBlockCount = request.WrittenBlockCount ?? names.Count;
            result.SkippedUnchangedBlocks = request.SkippedUnchangedBlocks ?? 0;

            if (!generated.Ok)
            {
                // GenerateBlocksFromSource 内含 Safety/F-block 拒绝逻辑，原样透传。
                result.Success = false;
                result.CompileScope = "not_run";
                result.Error = generated.Error ?? new ToolError
                {
                    Code = "generate_blocks_from_source_failed",
                    Message = generated.Message ?? "GenerateBlocksFromSource 未成功。",
                };
                result.Message = "单次 Mega-Source 导入失败，未执行编译。";
                return result;
            }

            // 3.1) 生成后即焚：删除本次创建的临时外部源，保持项目树整洁。
            // V3.0 文档 Tab1 的 megaSource.Delete()。best-effort：清理失败只记录，
            // 绝不因清理问题把已成功的回写误判为失败。
            result.ExternalSourceCleanup = CleanupExternalSource(projects, generated.SourceName);

            // 4) 分级增量编译（锁外）+ 5) 结构化编译错误树
            var compile = CompileWithScope(connection, projects, request);
            result.CompileScope = compile.Scope;
            result.CompileScopeNote = compile.Note;
            result.Errors = compile.Errors;
            result.Success = compile.Success;
            if (!compile.ApiAvailable)
            {
                result.Error = new ToolError
                {
                    Code = "compile_api_unavailable",
                    Message = "Fail closed：编译 API 不可用，不能判定回写成功。" + (compile.Note ?? ""),
                };
            }
            result.Message = result.Success
                ? $"Mega-Source 单次生成 {result.WrittenBlockCount} 块，编译范围={compile.Scope}，零错误。"
                : $"编译范围={compile.Scope}，发现 {result.Errors.Count} 条结构化错误。";
            return result;
        }
        catch (Exception ex)
        {
            result.Success = false;
            result.Error = new ToolError
            {
                Code = "openness_error",
                Message = OpennessMutate.Unwrap(ex).Message,
            };
            result.Message = "fast-writeback 异常收敛，未谎报成功。";
            return result;
        }
        finally
        {
            // 兜底：异常路径也要释放独占锁；并统一记录耗时（result 是引用，finally 修改对调用方可见）
            if (lease is not null) ReleaseExclusiveAccess(lease);
            sw.Stop();
            result.ElapsedMilliseconds = sw.ElapsedMilliseconds;
        }
    }

    // ---------------------------------------------------------------------
    // 1) ExclusiveAccess UI 冻结（纯反射 + 优雅降级）
    // ---------------------------------------------------------------------

    /// <summary>
    /// 反射找 TiaPortal.ExclusiveAccess(string)。返回对象后续按 IDisposable 或
    /// 反射 Dispose() 释放。V14 SP1 之前无此 API、无 UI 会话、反射失败都记录
    /// skip reason 并返回 null，绝不抛、绝不阻断回写。
    /// </summary>
    private static (object? Lease, string? SkipReason) TryAcquireExclusiveAccess(
        TiaConnection connection, string? reason)
    {
        // 前置降级：TiaPortal.ExclusiveAccess(string) 自 V14 SP1 引入。
        if (OpennessGuardrails.IsPreExclusiveAccessVersion(connection.TiaVersion))
        {
            return (null,
                "exclusive_access_skipped: Portal " + connection.TiaVersion
                + " predates V14 SP1 (ExclusiveAccess introduced in V14 SP1); continuing without UI freeze.");
        }

        var portal = connection.Portal;
        if (portal is null)
        {
            return (null,
                "exclusive_access_skipped: TiaPortal instance not connected "
                + "(WithoutUserInterface headless session needs no UI freeze); continuing without UI freeze.");
        }

        try
        {
            var methods = portal.GetType()
                .GetMethods(BindingFlags.Public | BindingFlags.Instance)
                .Where(m => m.Name == "ExclusiveAccess")
                .ToList();

            // 首选 ExclusiveAccess(string)；兼容无参重载与 <=1 参数变体。
            var method = methods.FirstOrDefault(m =>
                             m.GetParameters().Length == 1 &&
                             m.GetParameters()[0].ParameterType == typeof(string))
                         ?? methods.FirstOrDefault(m => m.GetParameters().Length == 0)
                         ?? methods.FirstOrDefault(m => m.GetParameters().Length <= 1);

            if (method is null)
            {
                return (null,
                    "exclusive_access_unavailable: TiaPortal.ExclusiveAccess(string) not found on this "
                    + "Openness build; continuing without UI freeze (graceful degradation).");
            }

            var ps = method.GetParameters();
            object?[] args;
            if (ps.Length == 0)
            {
                args = Array.Empty<object?>();
            }
            else if (ps[0].ParameterType == typeof(string))
            {
                args = new object?[]
                {
                    string.IsNullOrWhiteSpace(reason) ? DefaultExclusiveAccessReason : reason,
                };
            }
            else
            {
                return (null,
                    "exclusive_access_unavailable: unexpected ExclusiveAccess parameter type "
                    + ps[0].ParameterType.FullName + "; continuing without UI freeze.");
            }

            var lease = method.Invoke(portal, args);
            if (lease is null)
            {
                return (null,
                    "exclusive_access_noop: ExclusiveAccess returned null; continuing without UI freeze.");
            }
            return (lease, null);
        }
        catch (Exception ex)
        {
            // 优雅降级：反射/调用失败绝不阻断回写，只记录原因。
            return (null, "exclusive_access_skipped: " + OpennessMutate.Unwrap(ex).Message);
        }
    }

    /// <summary>优先转 IDisposable（mscorlib 类型跨程序集可识别），否则反射调 Dispose()。</summary>
    private static void ReleaseExclusiveAccess(object lease)
    {
        try
        {
            if (lease is IDisposable disposable)
            {
                disposable.Dispose();
                return;
            }
            var dispose = lease.GetType()
                .GetMethods(BindingFlags.Public | BindingFlags.Instance)
                .FirstOrDefault(m => m.Name == "Dispose" && m.GetParameters().Length == 0);
            dispose?.Invoke(lease, null);
        }
        catch
        {
            // 释放失败不阻断回写（与 TiaConnection.Disconnect 的 dispose 策略一致）。
        }
    }

    // ---------------------------------------------------------------------
    // 5) 快照 / 回滚钩子
    // ---------------------------------------------------------------------

    /// <summary>
    /// 生成后即焚：按 SourceName 找到并删除本次创建的外部源。
    /// 全部走反射（与 TiaConnection / BlockService 同风格，兼容 V14~V19）。
    /// 返回 null 表示删除成功；其余返回跳过原因，调用方只记录不阻断。
    /// </summary>
    private static string? CleanupExternalSource(ProjectService projects, string? sourceName)
    {
        if (string.IsNullOrWhiteSpace(sourceName))
            return "no_source_name";
        try
        {
            var plc = projects.PlcSoftware;
            if (plc is null)
                return "no_plc_software";

            var group = ReadProp(plc, "ExternalSourceGroup");
            var sources = group is null ? null : ReadProp(group, "ExternalSources");
            if (sources is null)
                return "no_external_sources_composition";

            var find = sources.GetType()
                .GetMethods(BindingFlags.Public | BindingFlags.Instance)
                .FirstOrDefault(m =>
                    m.Name == "Find" &&
                    m.GetParameters().Length == 1 &&
                    m.GetParameters()[0].ParameterType == typeof(string));
            if (find is null)
                return "find_api_unavailable";

            var existing = find.Invoke(sources, new object[] { sourceName! });
            if (existing is null)
                return "source_not_found";

            var delete = existing.GetType().GetMethod("Delete", Type.EmptyTypes);
            if (delete is null)
                return "delete_api_unavailable";

            delete.Invoke(existing, null);
            return null;
        }
        catch (Exception ex)
        {
            // 清理失败不影响已生成的块；错误只用于审计。
            return "cleanup_skipped: " + OpennessMutate.Unwrap(ex).Message;
        }
    }

    private static object? ReadProp(object? obj, string name)
    {
        if (obj is null) return null;
        return obj.GetType()
            .GetProperty(name, BindingFlags.Public | BindingFlags.Instance)
            ?.GetValue(obj);
    }

    private static WritebackSnapshot CaptureSnapshot(ProjectService projects, string sclPath)
    {
        var projectPath = projects.ProjectPath ?? "";
        var capturedAt = DateTime.UtcNow.ToString("o", System.Globalization.CultureInfo.InvariantCulture);
        string? lastWrite = null;
        try
        {
            if (!string.IsNullOrWhiteSpace(projectPath) && File.Exists(projectPath))
            {
                lastWrite = File.GetLastWriteTimeUtc(projectPath)
                    .ToString("o", System.Globalization.CultureInfo.InvariantCulture);
            }
        }
        catch
        {
            // 取时间戳失败不影响快照主体。
        }

        return new WritebackSnapshot
        {
            ProjectPath = projectPath,
            CapturedAtUtc = capturedAt,
            ProjectLastWriteUtc = lastWrite,
            SclPath = sclPath,
            RestoreHint = BuildRestoreHint(projectPath, capturedAt, sclPath, lastWrite),
        };
    }

    /// <summary>只给可执行的恢复指引；真实 .zap 复制/归档由上层编排负责。</summary>
    private static string BuildRestoreHint(
        string projectPath, string capturedAtUtc, string sclPath, string? lastWriteUtc)
    {
        var p = string.IsNullOrWhiteSpace(projectPath) ? "<项目路径未记录>" : projectPath;
        return
            "本层不复制 .zap、不改动任何项目文件；真实备份/归档由上层编排负责。"
            + "若需回滚本次回写，按以下顺序执行：\n"
            + "1) 首选：在 TIA Portal 中关闭项目并选择『不保存』，撤销尚未保存的 GenerateBlocksFromSource 变更；\n"
            + "2) 若已保存：用回写前由上层生成的 .zap* 归档，经 TIA Portal『项目 > 归档 > 恢复』"
            + "或 Openness Projects.Retrieve(FileInfo, DirectoryInfo) 覆盖 " + p + "；\n"
            + "3) 若使用版本管理：检出 " + p + " 在 " + capturedAtUtc + " 之前的提交；\n"
            + "4) 若仅需撤销本批次：删除外部源 " + sclPath + " 生成的程序块，再执行全量 PlcSoftware 编译。\n"
            + "快照捕获时间(UTC)：" + capturedAtUtc
            + "；项目最后写入(UTC)：" + (lastWriteUtc ?? "未知") + "。";
    }

    // ---------------------------------------------------------------------
    // 3) 分级增量编译（反射 ICompilable）+ 降级路径
    // ---------------------------------------------------------------------

    private sealed class CompileInvocation
    {
        public bool ApiAvailable;
        public object? Result;
        public string? Note;
    }

    private sealed class CompileOutcome
    {
        public string Scope = "unavailable";
        public string? Note;
        public bool Success;
        public bool ApiAvailable;
        public string? State;
        public int? ErrorCount;
        public int? WarningCount;
        public List<CompileErrorItem> Errors = new();
    }

    /// <summary>
    /// 无 UDT / GlobalDB / FB 接口变更 → 仅对受影响的 PlcBlockUserGroup 或单个
    /// PlcBlock 调 ICompilable.Compile()（文档承诺 6s→0.8s）；有接口变更 →
    /// 退回全量 PlcSoftware.Compile()。所有降级路径写入 Note / compileScope。
    /// </summary>
    private static CompileOutcome CompileWithScope(
        TiaConnection connection, ProjectService projects, FastWritebackRequest request)
    {
        var plc = projects.PlcSoftware;
        if (plc is null)
        {
            return new CompileOutcome
            {
                Scope = "unavailable",
                ApiAvailable = false,
                Note = "No PLC software open; fail closed (do not report success).",
            };
        }

        // 接口变更（UDT / GlobalDB / FB VAR_INPUT/VAR）→ 必须全量编译
        if (request.InterfaceChanged || request.HasUdtOrGlobalDbChange)
        {
            var note =
                "Interface/UDT/GlobalDB change in this batch: incremental block compile is unsafe "
                + "(callers' interfaces and instance DBs must be re-resolved); "
                + "falling back to full PlcSoftware.Compile(). "
                + OpennessGuardrails.InstanceDbRefreshReason;
            return BuildOutcome(InvokeCompileOn(connection, plc), "full_software_interface_changed", note);
        }

        // 无接口变更 → 增量编译受影响的块 / 块组
        var (byName, rootGroup) = CollectCompileTargets(plc);
        var affected = request.BlockNames ?? new List<string>();

        if (affected.Count > 0)
        {
            var errors = new List<CompileErrorItem>();
            var notes = new List<string>();
            var compiled = 0;
            string? lastState = null;
            var totalErrors = 0;
            var totalWarnings = 0;

            foreach (var name in affected)
            {
                if (!byName.TryGetValue(name, out var block))
                {
                    notes.Add($"block '{name}' not found under PlcSoftware.BlockGroup; skipped");
                    continue;
                }
                var inv = InvokeCompileOn(connection, block);
                if (!inv.ApiAvailable)
                {
                    notes.Add($"block '{name}': {inv.Note}");
                    continue;
                }
                compiled++;
                errors.AddRange(ExtractCompilerErrorTree(inv.Result, affected));
                lastState = OpennessExport.GetPropString(inv.Result, "State") ?? lastState;
                totalErrors += ParseCount(OpennessExport.GetProp(inv.Result, "ErrorCount")) ?? 0;
                totalWarnings += ParseCount(OpennessExport.GetProp(inv.Result, "WarningCount")) ?? 0;
            }

            if (compiled > 0)
            {
                var outcome = new CompileOutcome
                {
                    Scope = "incremental_blocks",
                    ApiAvailable = true,
                    State = lastState,
                    ErrorCount = totalErrors,
                    WarningCount = totalWarnings,
                    Errors = errors,
                    Note = "No UDT/GlobalDB change: compiled " + compiled
                         + " affected PlcBlock(s) via GetService<ICompilable>(). "
                         + (notes.Count > 0 ? "Skipped: " + string.Join("; ", notes) : ""),
                };
                outcome.Success = ComputeCompileSuccess(outcome);
                return outcome;
            }

            // 增量目标全部不可用 → 明确降级到全量
            return BuildOutcome(
                InvokeCompileOn(connection, plc),
                "full_software_fallback",
                "Incremental compile targets did not expose ICompilable (" + string.Join("; ", notes)
                + "); fell back to full PlcSoftware.Compile().");
        }

        // 未给出块名 → 尝试块组级增量（PlcBlockUserGroup 自身实现 ICompilable）
        if (rootGroup is not null)
        {
            var groupInv = InvokeCompileOn(connection, rootGroup);
            if (groupInv.ApiAvailable)
            {
                return BuildOutcome(
                    groupInv,
                    "incremental_group",
                    "No UDT/GlobalDB change and no explicit block list: compiled the affected "
                    + "PlcBlockUserGroup via GetService<ICompilable>().");
            }
            return BuildOutcome(
                InvokeCompileOn(connection, plc),
                "full_software_fallback",
                "PlcBlockUserGroup did not expose ICompilable (" + groupInv.Note
                + "); fell back to full PlcSoftware.Compile().");
        }

        return BuildOutcome(
            InvokeCompileOn(connection, plc),
            "full_software_fallback",
            "No block group resolved for incremental compile; fell back to full PlcSoftware.Compile().");
    }

    private static bool ComputeCompileSuccess(CompileOutcome o)
    {
        if (!o.ApiAvailable) return false;
        if (o.ErrorCount is > 0) return false;
        if (o.Errors.Count > 0) return false;
        var s = o.State ?? "";
        return s.IndexOf("Error", StringComparison.OrdinalIgnoreCase) < 0
            && s.IndexOf("Fail", StringComparison.OrdinalIgnoreCase) < 0;
    }

    private static CompileOutcome BuildOutcome(CompileInvocation inv, string attemptedScope, string note)
    {
        var outcome = new CompileOutcome { Scope = attemptedScope, Note = note };
        if (!inv.ApiAvailable)
        {
            outcome.ApiAvailable = false;
            outcome.Scope = "unavailable";
            outcome.Success = false;
            outcome.Note = "Fail closed: " + attemptedScope + " compile API unavailable. "
                          + (inv.Note ?? "") + " | " + note;
            return outcome;
        }

        outcome.ApiAvailable = true;
        var res = inv.Result;
        outcome.State = OpennessExport.GetPropString(res, "State");
        outcome.ErrorCount = ParseCount(OpennessExport.GetProp(res, "ErrorCount"));
        outcome.WarningCount = ParseCount(OpennessExport.GetProp(res, "WarningCount"));
        outcome.Errors = ExtractCompilerErrorTree(res, null);
        outcome.Success = ComputeCompileSuccess(outcome);
        if (!string.IsNullOrWhiteSpace(inv.Note))
        {
            outcome.Note = note + " | " + inv.Note;
        }
        return outcome;
    }

    /// <summary>
    /// 主路径：反射 GetService&lt;ICompilable&gt;()（与 TiaConnection.GetService /
    /// BlockService.InvokeCompile 同款）；降级：直接反射目标上的 Compile()。
    /// </summary>
    private static CompileInvocation InvokeCompileOn(TiaConnection connection, object target)
    {
        object? service;
        try
        {
            service = connection.GetService(target, ICompilableFullName);
        }
        catch (Exception ex)
        {
            return new CompileInvocation
            {
                Note = "GetService<ICompilable>() threw: " + OpennessMutate.Unwrap(ex).Message,
            };
        }

        if (service is not null)
        {
            var compile = service.GetType().GetMethod("Compile", Type.EmptyTypes);
            if (compile is not null)
            {
                try
                {
                    return new CompileInvocation
                    {
                        ApiAvailable = true,
                        Result = compile.Invoke(service, null),
                    };
                }
                catch (Exception ex)
                {
                    return new CompileInvocation
                    {
                        Note = "ICompilable.Compile() threw: " + OpennessMutate.Unwrap(ex).Message,
                    };
                }
            }
        }

        // 降级：某些构建直接在块/组上暴露 Compile()（参考 BlockService.CompileBlocksStrict）
        var direct = target.GetType().GetMethod("Compile", Type.EmptyTypes);
        if (direct is not null)
        {
            try
            {
                return new CompileInvocation
                {
                    ApiAvailable = true,
                    Result = direct.Invoke(target, null),
                    Note = "ICompilable service unavailable; used direct Compile() reflection fallback.",
                };
            }
            catch (Exception ex)
            {
                return new CompileInvocation
                {
                    Note = "direct Compile() threw: " + OpennessMutate.Unwrap(ex).Message,
                };
            }
        }

        return new CompileInvocation
        {
            Note = "GetService<ICompilable>() returned "
                 + (service is null ? "null" : "a service without parameterless Compile()")
                 + " and no direct Compile() on " + target.GetType().Name + ".",
        };
    }

    private static (Dictionary<string, object> ByName, object? RootGroup) CollectCompileTargets(object plc)
    {
        var byName = new Dictionary<string, object>(StringComparer.OrdinalIgnoreCase);
        var root = OpennessExport.GetProp(plc, "BlockGroup");
        foreach (var (item, _) in OpennessExport.WalkGroups(root, new[] { "Blocks" }))
        {
            var name = OpennessExport.GetPropString(item, "Name");
            if (!string.IsNullOrWhiteSpace(name) && !byName.ContainsKey(name!))
            {
                byName[name!] = item;
            }
        }
        return (byName, root);
    }

    private static int? ParseCount(object? value)
    {
        if (value is null) return null;
        if (value is int i) return i;
        return int.TryParse(value.ToString(), out var parsed) ? parsed : null;
    }

    // ---------------------------------------------------------------------
    // 4) 结构化编译错误树提取（对齐 Python 契约 CompileErrorItem）
    // ---------------------------------------------------------------------

    /// <summary>
    /// 递归遍历 CompilerResult.Messages（含嵌套 Messages），只提取 State==Error 的
    /// 条目，映射 Path / Description / DateTime 到 Python 侧
    /// CompileErrorItem(blockName, networkOrLine, tiaDescription, blockPath, timestamp)。
    /// </summary>
    public static List<CompileErrorItem> ExtractCompilerErrorTree(
        object? compilerResult, IReadOnlyList<string>? knownBlockNames = null)
    {
        var sink = new List<CompileErrorItem>();
        if (compilerResult is null) return sink;
        var rootMessages = OpennessExport.GetFirstProp(
            compilerResult, "Messages", "CompilerMessages", "Errors");
        if (rootMessages is IEnumerable seq && rootMessages is not string)
        {
            WalkMessageItems(seq, sink, knownBlockNames, 0);
        }
        return sink;
    }

    private static void WalkMessageItems(
        IEnumerable items,
        List<CompileErrorItem> sink,
        IReadOnlyList<string>? knownBlockNames,
        int depth)
    {
        if (depth > 16) return;
        foreach (var item in items)
        {
            if (item is null || sink.Count >= 200) break;
            CollectIfError(item, sink, knownBlockNames);
            // CompilerResultMessage 允许嵌套 Messages → 错误树递归
            var nested = OpennessExport.GetFirstProp(
                item, "Messages", "CompilerMessages", "ChildMessages");
            if (nested is IEnumerable nestedSeq && nested is not string)
            {
                WalkMessageItems(nestedSeq, sink, knownBlockNames, depth + 1);
            }
        }
    }

    private static void CollectIfError(
        object message, List<CompileErrorItem> sink, IReadOnlyList<string>? knownBlockNames)
    {
        var state = OpennessExport.GetPropString(message, "State");
        // 只提取 State==Error；老版本无 State 属性时宽容纳入（有文本即收）。
        if (state is not null && state.IndexOf("Error", StringComparison.OrdinalIgnoreCase) < 0)
        {
            return;
        }

        var path = OpennessExport.GetPropString(message, "Path") ?? "";
        var description = OpennessExport
            .GetFirstProp(message, "Description", "Message", "Text")?.ToString() ?? "";
        // 容器节点（只有 Path、没有 Description）不是具体编译错误；
        // "Compiling finished (errors: N; warnings: M)" 是编译汇总消息，同样不是错误。
        // 真机（TIA Portal V19 / HR001）验证：不过滤会让 3 条真实错误膨胀成 9 条噪声，
        // 自愈 LLM 会为 CPU / 块组 / 汇总消息重复生成无效补丁。
        if (string.IsNullOrWhiteSpace(description))
        {
            return;
        }
        if (description.TrimStart().StartsWith("Compiling finished", StringComparison.OrdinalIgnoreCase))
        {
            return;
        }

        var dt = OpennessExport.GetProp(message, "DateTime");
        var timestamp = dt is DateTime d
            ? d.ToString("o", System.Globalization.CultureInfo.InvariantCulture)
            : dt?.ToString() ?? "";

        var (blockName, networkOrLine) = SplitMessagePath(path, description, knownBlockNames);
        sink.Add(new CompileErrorItem
        {
            BlockName = blockName,
            NetworkOrLine = networkOrLine,
            TiaDescription = description,
            BlockPath = path,
            Timestamp = timestamp,
        });
    }

    /// <summary>
    /// Openness 消息没有独立的 blockName / networkOrLine 字段，需从 Path / Description
    /// 推断：优先匹配本次批次已知块名，否则按分隔符取最像块名的段；行号用正则提取。
    /// </summary>
    private static (string BlockName, string NetworkOrLine) SplitMessagePath(
        string path, string description, IReadOnlyList<string>? knownBlockNames)
    {
        var networkOrLine = ExtractNetworkOrLine(path + " " + description);

        if (knownBlockNames is not null)
        {
            foreach (var name in knownBlockNames)
            {
                if (!string.IsNullOrWhiteSpace(name)
                    && path.IndexOf(name, StringComparison.OrdinalIgnoreCase) >= 0)
                {
                    return (name, networkOrLine);
                }
            }
        }

        var segments = path
            .Split(new[] { '/', '\\', '>', '|', ':', ',', ';', '\r', '\n' },
                StringSplitOptions.RemoveEmptyEntries)
            .Select(s => s.Trim().Trim('"'))
            .Where(s => s.Length > 0)
            .ToList();
        for (var i = segments.Count - 1; i >= 0; i--)
        {
            var s = segments[i];
            if (LooksLikeLocation(s)) continue;
            if (LooksLikeBlockName(s)) return (s, networkOrLine);
        }
        return ("", networkOrLine);
    }

    private static bool LooksLikeLocation(string s) =>
        s.StartsWith("Network", StringComparison.OrdinalIgnoreCase)
        || s.StartsWith("NW", StringComparison.OrdinalIgnoreCase)
        || s.StartsWith("Line", StringComparison.OrdinalIgnoreCase)
        || s.StartsWith("行", StringComparison.Ordinal)
        || s.StartsWith("Zeile", StringComparison.OrdinalIgnoreCase)
        || s.IndexOf("Program blocks", StringComparison.OrdinalIgnoreCase) >= 0
        || s.IndexOf("Bausteine", StringComparison.OrdinalIgnoreCase) >= 0;

    private static bool LooksLikeBlockName(string s)
    {
        if (s.Length < 2 || s.Length > 128) return false;
        if (s.IndexOf(' ') >= 0) return false; // 块名不含空格
        return s.Any(char.IsLetterOrDigit) && (s.Contains("_") || s.Any(char.IsLetter));
    }

    private static string ExtractNetworkOrLine(string text)
    {
        var m = Regex.Match(text ?? "", @"(?i)(Network|NW|Line|Zeile|行)\s*[:#]?\s*(\d+)");
        if (m.Success)
        {
            var label = m.Groups[1].Value;
            if (label == "行") label = "Line";
            return label + " " + m.Groups[2].Value;
        }
        return "";
    }
}

// -------------------------------------------------------------------------
// DTO（camelCase 契约对齐 plc_engine/contracts.py 与 V3.0 WritebackResult.json）
// -------------------------------------------------------------------------

/// <summary>对齐 Python 契约 CompileErrorItem 的字段名。</summary>
public sealed class CompileErrorItem
{
    [JsonPropertyName("blockName")]
    public string BlockName { get; set; } = "";

    [JsonPropertyName("networkOrLine")]
    public string NetworkOrLine { get; set; } = "";

    [JsonPropertyName("tiaDescription")]
    public string TiaDescription { get; set; } = "";

    [JsonPropertyName("blockPath")]
    public string BlockPath { get; set; } = "";

    [JsonPropertyName("timestamp")]
    public string Timestamp { get; set; } = "";
}

/// <summary>回写前快照：只记录项目路径与时间戳，供上层生成可执行恢复指引。</summary>
public sealed class WritebackSnapshot
{
    [JsonPropertyName("projectPath")]
    public string ProjectPath { get; set; } = "";

    [JsonPropertyName("capturedAtUtc")]
    public string CapturedAtUtc { get; set; } = "";

    [JsonPropertyName("projectLastWriteUtc")]
    public string? ProjectLastWriteUtc { get; set; }

    [JsonPropertyName("sclPath")]
    public string SclPath { get; set; } = "";

    [JsonPropertyName("restoreHint")]
    public string RestoreHint { get; set; } = "";
}

/// <summary>
/// V3.0 WritebackResult 超集：success / elapsedMilliseconds / writtenBlockCount /
/// skippedUnchangedBlocks / errors / exclusiveAccessUsed / compileScope / snapshotHint。
/// </summary>
public sealed class FastWritebackResult
{
    [JsonPropertyName("success")]
    public bool Success { get; set; }

    [JsonPropertyName("elapsedMilliseconds")]
    public long ElapsedMilliseconds { get; set; }

    [JsonPropertyName("writtenBlockCount")]
    public int WrittenBlockCount { get; set; }

    [JsonPropertyName("skippedUnchangedBlocks")]
    public int SkippedUnchangedBlocks { get; set; }

    [JsonPropertyName("errors")]
    public List<CompileErrorItem> Errors { get; set; } = new();

    [JsonPropertyName("exclusiveAccessUsed")]
    public bool ExclusiveAccessUsed { get; set; }

    [JsonPropertyName("exclusiveAccessSkipReason")]
    public string? ExclusiveAccessSkipReason { get; set; }

    [JsonPropertyName("compileScope")]
    public string CompileScope { get; set; } = "none";

    [JsonPropertyName("compileScopeNote")]
    public string? CompileScopeNote { get; set; }

    /// <summary>
    /// 生成后即焚的结果：null 表示已成功删除临时外部源；其余值为跳过原因。
    /// 对应 V3.0 文档 Tab1 的 <c>megaSource.Delete()</c>。失败不阻断回写。
    /// </summary>
    [JsonPropertyName("externalSourceCleanup")]
    public string? ExternalSourceCleanup { get; set; }

    [JsonPropertyName("snapshotHint")]
    public string? SnapshotHint { get; set; }

    [JsonPropertyName("snapshot")]
    public WritebackSnapshot? Snapshot { get; set; }

    [JsonPropertyName("generateApi")]
    public string? GenerateApi { get; set; }

    [JsonPropertyName("generatedNames")]
    public List<string>? GeneratedNames { get; set; }

    [JsonPropertyName("message")]
    public string? Message { get; set; }

    [JsonPropertyName("error")]
    public ToolError? Error { get; set; }
}

/// <summary>/fast-writeback 请求：字段名兼容既有 session 约定与 snake_case 契约。</summary>
public sealed class FastWritebackRequest
{
    public string SclPath { get; set; } = "";
    public string? SoftwareUnit { get; set; }
    public bool InterfaceChanged { get; set; }
    public bool HasUdtOrGlobalDbChange { get; set; }
    public List<string> BlockNames { get; set; } = new();
    public int? SkippedUnchangedBlocks { get; set; }
    public int? WrittenBlockCount { get; set; }
    public string? ExclusiveAccessReason { get; set; }

    public static FastWritebackRequest FromJson(JsonElement root)
    {
        var req = new FastWritebackRequest
        {
            SclPath = GetString(root, "scl") ?? GetString(root, "scl_path") ?? "",
            SoftwareUnit = GetString(root, "unit") ?? GetString(root, "software_unit"),
            InterfaceChanged = GetBool(root, "interfaceChanged")
                               ?? GetBool(root, "interface_changed") ?? false,
            HasUdtOrGlobalDbChange = GetBool(root, "hasUdtOrGlobalDbChange")
                                     ?? GetBool(root, "has_udt_or_global_db_change")
                                     ?? GetBool(root, "udtOrGlobalDbChanged") ?? false,
            SkippedUnchangedBlocks = GetInt(root, "skippedUnchangedBlocks")
                                     ?? GetInt(root, "skipped_unchanged_blocks"),
            WrittenBlockCount = GetInt(root, "writtenBlockCount")
                                ?? GetInt(root, "written_block_count"),
            ExclusiveAccessReason = GetString(root, "exclusiveAccessReason")
                                    ?? GetString(root, "reason"),
            BlockNames = GetStringArray(root, "blockNames")
                         ?? GetStringArray(root, "block_names") ?? new List<string>(),
        };

        // 兜底：请求未显式标记类型变更时，从块名启发式推断 UDT / GlobalDB。
        if (!req.HasUdtOrGlobalDbChange
            && req.BlockNames.Any(OpennessGuardrails.LooksLikeTypeOrGlobalDbName))
        {
            req.HasUdtOrGlobalDbChange = true;
        }
        return req;
    }

    private static string? GetString(JsonElement root, string name) =>
        root.TryGetProperty(name, out var el) && el.ValueKind == JsonValueKind.String
            ? el.GetString()
            : null;

    private static bool? GetBool(JsonElement root, string name)
    {
        if (!root.TryGetProperty(name, out var el)) return null;
        return el.ValueKind switch
        {
            JsonValueKind.True => true,
            JsonValueKind.False => false,
            JsonValueKind.Number when el.TryGetInt32(out var n) => n != 0,
            JsonValueKind.String when bool.TryParse(el.GetString(), out var b) => b,
            _ => null,
        };
    }

    private static int? GetInt(JsonElement root, string name)
    {
        if (!root.TryGetProperty(name, out var el)) return null;
        if (el.ValueKind == JsonValueKind.Number && el.TryGetInt32(out var n)) return n;
        if (el.ValueKind == JsonValueKind.String && int.TryParse(el.GetString(), out var s)) return s;
        return null;
    }

    private static List<string>? GetStringArray(JsonElement root, string name)
    {
        if (!root.TryGetProperty(name, out var el)) return null;
        var list = new List<string>();
        if (el.ValueKind == JsonValueKind.Array)
        {
            foreach (var item in el.EnumerateArray())
            {
                if (item.ValueKind == JsonValueKind.String)
                {
                    var s = item.GetString();
                    if (!string.IsNullOrWhiteSpace(s)) list.Add(s!.Trim());
                }
            }
        }
        else if (el.ValueKind == JsonValueKind.String)
        {
            foreach (var part in (el.GetString() ?? "").Split('|'))
            {
                if (!string.IsNullOrWhiteSpace(part)) list.Add(part.Trim());
            }
        }
        return list.Count > 0 ? list : null;
    }
}

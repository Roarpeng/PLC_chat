using System;
using System.Collections.Concurrent;
using System.Collections.Generic;
using System.Diagnostics;
using System.Globalization;
using System.IO;
using System.Linq;
using System.Reflection;
using System.Security.Cryptography;
using System.Text;
using System.Text.Json;
using System.Text.Json.Serialization;
using System.Text.RegularExpressions;
using TiaOpenness.Models;

namespace TiaOpenness.Server;

/// <summary>
/// AF-Studio v5 block-level Merkle incremental sync service.
/// Normalizes SCL sources, computes full/short SHA-256 and interface section hashes,
/// cascades FB interface timestamp refreshes to declared Instance DBs (per
/// <see cref="OpennessGuardrails.InstanceDbRefreshReason"/>), and executes dirty blocks
/// fail-closed through <see cref="IMerkleBlockExecutor"/>.
/// </summary>
public sealed class MerkleBlockSyncService
{
    private static readonly Regex DecorativeTimestampMarkerRegex = new(
        @"(?:timestamp|generated\s+(?:at|on)|updated\s*at|build\s*time|export\s*time|生成时间|导出时间|时间戳|\d{4}[-/]\d{2}[-/]\d{2}[T\s_]+\d{2}:\d{2})",
        RegexOptions.IgnoreCase | RegexOptions.Compiled);

    private static bool IsDecorativeTimestampComment(string trimmedEnd)
    {
        var trimmedStart = trimmedEnd.TrimStart();
        var isSingleLineComment =
            trimmedStart.StartsWith("//", StringComparison.Ordinal) ||
            (trimmedStart.StartsWith("(*", StringComparison.Ordinal) &&
             trimmedStart.EndsWith("*)", StringComparison.Ordinal));
        return isSingleLineComment && DecorativeTimestampMarkerRegex.IsMatch(trimmedStart);
    }

    private static readonly Regex BlockHeaderRegex = new(
        @"^\s*(FUNCTION_BLOCK|FUNCTION|DATA_BLOCK|ORGANIZATION_BLOCK|TYPE)\s+(?:""([^""]+)""|([A-Za-z_][A-Za-z0-9_]*))",
        RegexOptions.IgnoreCase | RegexOptions.Compiled);

    private static readonly Regex InterfaceSectionStartRegex = new(
        @"^\s*(VAR_INPUT|VAR_OUTPUT|VAR_IN_OUT|VAR_STAT|VAR)\b",
        RegexOptions.IgnoreCase | RegexOptions.Compiled);

    private static readonly Regex AnyVarSectionStartRegex = new(
        @"^\s*VAR(?:_[A-Z0-9]+)?\b",
        RegexOptions.IgnoreCase | RegexOptions.Compiled);

    private static readonly Regex InterfaceSectionEndRegex = new(
        @"^\s*END_VAR\b",
        RegexOptions.IgnoreCase | RegexOptions.Compiled);

    private readonly ProjectService? _projects;
    private readonly BlockService? _blocks;

    /// <summary>
    /// Thread-safe cache of last successfully compiled block hashes,
    /// keyed by <c>{projectKey}::{blockName}</c>.
    /// </summary>
    public ConcurrentDictionary<string, BlockSyncHashEntry> LastSyncedBlockHashes { get; } =
        new(StringComparer.OrdinalIgnoreCase);

    public MerkleBlockSyncService()
    {
    }

    public MerkleBlockSyncService(ProjectService projects, BlockService blocks)
    {
        _projects = projects ?? throw new ArgumentNullException(nameof(projects));
        _blocks = blocks ?? throw new ArgumentNullException(nameof(blocks));
    }

    public static string BuildCacheKey(string projectKey, string blockName) =>
        $"{(string.IsNullOrWhiteSpace(projectKey) ? "default" : projectKey.Trim())}::{(blockName ?? "").Trim()}";

    /// <summary>
    /// Normalize SCL source: standardize line endings, strip trailing whitespace per line,
    /// ignore decorative timestamp comment lines, and collapse consecutive blank lines.
    /// </summary>
    public static string NormalizeSclSource(string? sclSource)
    {
        if (string.IsNullOrEmpty(sclSource)) return "";

        var unified = sclSource!
            .Replace("\r\n", "\n")
            .Replace('\r', '\n');
        var rawLines = unified.Split(new[] { '\n' }, StringSplitOptions.None);
        var normalized = new List<string>(rawLines.Length);
        var previousBlank = true; // trim leading blank lines

        foreach (var rawLine in rawLines)
        {
            var trimmedEnd = rawLine.TrimEnd();
            if (IsDecorativeTimestampComment(trimmedEnd))
            {
                continue;
            }

            if (trimmedEnd.Length == 0)
            {
                if (!previousBlank)
                {
                    normalized.Add(string.Empty);
                    previousBlank = true;
                }
                continue;
            }

            normalized.Add(trimmedEnd);
            previousBlank = false;
        }

        while (normalized.Count > 0 && normalized[normalized.Count - 1].Length == 0)
        {
            normalized.RemoveAt(normalized.Count - 1);
        }

        return string.Join("\n", normalized);
    }

    /// <summary>
    /// Extract canonicalized VAR_INPUT / VAR_OUTPUT / VAR_IN_OUT / VAR / VAR_STAT sections
    /// so interface timestamp changes can be detected separately from code body edits.
    /// </summary>
    public static string ExtractInterfaceSectionText(string? sclSource)
    {
        var normalized = NormalizeSclSource(sclSource);
        if (normalized.Length == 0) return "";

        var lines = normalized.Split(new[] { '\n' }, StringSplitOptions.None);
        var collected = new List<string>();
        var inTrackedInterfaceSection = false;
        var inUntrackedVarSection = false;

        foreach (var line in lines)
        {
            var trimmed = line.Trim();
            if (trimmed.Length == 0) continue;

            if (!inTrackedInterfaceSection && !inUntrackedVarSection)
            {
                if (InterfaceSectionStartRegex.IsMatch(trimmed))
                {
                    inTrackedInterfaceSection = true;
                    collected.Add(trimmed);
                }
                else if (AnyVarSectionStartRegex.IsMatch(trimmed))
                {
                    // VAR_TEMP / VAR_EXTERNAL / VAR_CONSTANT do not define the FB instance DB layout.
                    inUntrackedVarSection = true;
                }
                continue;
            }

            if (inUntrackedVarSection)
            {
                if (InterfaceSectionEndRegex.IsMatch(trimmed))
                {
                    inUntrackedVarSection = false;
                }
                continue;
            }

            collected.Add(trimmed);
            if (InterfaceSectionEndRegex.IsMatch(trimmed))
            {
                inTrackedInterfaceSection = false;
            }
        }

        return string.Join("\n", collected);
    }

    public static (string MerkleHash, string FullSha256, string InterfaceHash) ComputeHashes(string? sclSource)
    {
        var normalized = NormalizeSclSource(sclSource);
        var fullSha256 = ComputeSha256Hex(normalized);
        var merkleHash = fullSha256.Substring(0, 8);
        var interfaceText = ExtractInterfaceSectionText(normalized);
        var interfaceHash = ComputeSha256Hex(interfaceText).Substring(0, 8);
        return (merkleHash, fullSha256, interfaceHash);
    }

    public static string ComputeSha256Hex(string text)
    {
        var bytes = new UTF8Encoding(encoderShouldEmitUTF8Identifier: false).GetBytes(text ?? "");
        using (var sha = SHA256.Create())
        {
            var digest = sha.ComputeHash(bytes);
            return BitConverter.ToString(digest).Replace("-", "").ToLowerInvariant();
        }
    }

    public static string BuildInstanceDbDeclaration(string instanceDbName, string fbName) =>
        $"DATA_BLOCK \"{instanceDbName.Trim()}\" \"{fbName.Trim()}\" BEGIN END_DATA_BLOCK";

    public MerkleSyncResult SyncDirtyBlocks(MerkleSyncRequest request, IMerkleBlockExecutor? executor = null)
    {
        if (request is null) throw new ArgumentNullException(nameof(request));

        var sw = Stopwatch.StartNew();
        var result = new MerkleSyncResult();

        try
        {
            var projectKey = ResolveProjectKey(request);
            result.ProjectKey = projectKey;
            result.ProjectPath = string.IsNullOrWhiteSpace(request.ProjectPath)
                ? _projects?.ProjectPath
                : request.ProjectPath;

            var inputBlocks = request.Blocks ?? new List<MerkleBlockInput>();
            var resolved = new List<ResolvedBlockCandidate>(inputBlocks.Count);

            foreach (var rawBlock in inputBlocks)
            {
                if (rawBlock is null || string.IsNullOrWhiteSpace(rawBlock.BlockName))
                {
                    continue;
                }
                resolved.Add(ResolveCandidate(rawBlock, request.SoftwareUnit));
            }

            var statusByName = new Dictionary<string, MerkleBlockSyncStatus>(StringComparer.OrdinalIgnoreCase);
            var orderedNames = new List<string>();
            var dirtyBlocks = new List<MerkleDirtyBlock>();
            var dirtyByName = new Dictionary<string, MerkleDirtyBlock>(StringComparer.OrdinalIgnoreCase);
            var candidateByName = new Dictionary<string, ResolvedBlockCandidate>(StringComparer.OrdinalIgnoreCase);

            foreach (var item in resolved)
            {
                candidateByName[item.BlockName] = item;
                if (!statusByName.ContainsKey(item.BlockName))
                {
                    orderedNames.Add(item.BlockName);
                }

                var cacheKey = BuildCacheKey(projectKey, item.BlockName);
                LastSyncedBlockHashes.TryGetValue(cacheKey, out var previous);

                var hashChanged = previous is null ||
                                  !string.Equals(previous.MerkleHash, item.MerkleHash, StringComparison.OrdinalIgnoreCase);
                var interfaceChanged = previous is not null &&
                                       !string.Equals(previous.InterfaceHash, item.InterfaceHash, StringComparison.OrdinalIgnoreCase);
                var isDirty = request.Force || hashChanged;

                var reason = previous is null
                    ? "initial_sync_missing_cache"
                    : hashChanged
                        ? (interfaceChanged ? "interface_and_body_changed" : "scl_hash_changed")
                        : (request.Force ? "forced_resync" : "hash_unchanged");

                var blockStatus = new MerkleBlockSyncStatus
                {
                    BlockName = item.BlockName,
                    BlockType = item.BlockType,
                    Status = isDirty ? "DIRTY" : "UNCHANGED",
                    Action = isDirty ? "pending" : "skipped",
                    MerkleHash = item.MerkleHash,
                    FullSha256 = item.FullSha256,
                    PreviousHash = previous?.MerkleHash,
                    InterfaceHash = item.InterfaceHash,
                    PreviousInterfaceHash = previous?.InterfaceHash,
                    InterfaceChanged = interfaceChanged,
                    Reason = reason,
                };
                statusByName[item.BlockName] = blockStatus;

                if (isDirty)
                {
                    var dirty = new MerkleDirtyBlock
                    {
                        BlockName = item.BlockName,
                        BlockType = item.BlockType,
                        SclSource = item.SclSource,
                        MerkleHash = item.MerkleHash,
                        FullSha256 = item.FullSha256,
                        InterfaceHash = item.InterfaceHash,
                        InterfaceChanged = interfaceChanged,
                        SoftwareUnit = item.SoftwareUnit,
                        Reason = reason,
                    };
                    dirtyBlocks.Add(dirty);
                    dirtyByName[item.BlockName] = dirty;
                }
            }

            // Cascade FB interface changes to declared Instance DBs (OpennessGuardrails.InstanceDbRefreshReason).
            var anyInterfaceChanged = false;
            foreach (var item in resolved)
            {
                if (!statusByName.TryGetValue(item.BlockName, out var fbStatus)) continue;
                if (!fbStatus.InterfaceChanged) continue;

                anyInterfaceChanged = true;
                if (!string.Equals(item.BlockType, "FB", StringComparison.OrdinalIgnoreCase)) continue;
                if (string.IsNullOrWhiteSpace(item.InstanceDbName)) continue;

                var idbName = item.InstanceDbName!.Trim();
                var refreshReason =
                    $"接口时间戳刷新: FB '{item.BlockName}' 接口哈希由 {fbStatus.PreviousInterfaceHash} 变更为 {fbStatus.InterfaceHash}。" +
                    OpennessGuardrails.InstanceDbRefreshReason;

                if (dirtyByName.TryGetValue(idbName, out var existingDirtyIdb))
                {
                    existingDirtyIdb.Reason = $"{existingDirtyIdb.Reason}; {refreshReason}";
                    if (statusByName.TryGetValue(idbName, out var idbStatus))
                    {
                        idbStatus.Reason = existingDirtyIdb.Reason;
                        idbStatus.SourceBlock = item.BlockName;
                    }
                    continue;
                }

                if (candidateByName.TryGetValue(idbName, out var unchangedIdb))
                {
                    // DB was in the batch with unchanged SCL, promote it to DIRTY so TIA refreshes its timestamp.
                    var promoted = new MerkleDirtyBlock
                    {
                        BlockName = unchangedIdb.BlockName,
                        BlockType = string.IsNullOrWhiteSpace(unchangedIdb.BlockType) ? "DB" : unchangedIdb.BlockType,
                        SclSource = string.IsNullOrWhiteSpace(unchangedIdb.SclSource)
                            ? BuildInstanceDbDeclaration(idbName, item.BlockName)
                            : unchangedIdb.SclSource,
                        MerkleHash = unchangedIdb.MerkleHash,
                        FullSha256 = unchangedIdb.FullSha256,
                        InterfaceHash = unchangedIdb.InterfaceHash,
                        InterfaceChanged = true,
                        AutoGeneratedIdb = true,
                        SourceBlock = item.BlockName,
                        SoftwareUnit = unchangedIdb.SoftwareUnit ?? item.SoftwareUnit,
                        Reason = refreshReason,
                    };
                    dirtyBlocks.Add(promoted);
                    dirtyByName[idbName] = promoted;

                    var idbStatus = statusByName[idbName];
                    idbStatus.Status = "DIRTY";
                    idbStatus.Action = "pending";
                    idbStatus.InterfaceChanged = true;
                    idbStatus.AutoGeneratedIdb = true;
                    idbStatus.SourceBlock = item.BlockName;
                    idbStatus.Reason = refreshReason;
                }
                else
                {
                    var idbScl = BuildInstanceDbDeclaration(idbName, item.BlockName);
                    var (idbMerkle, idbSha, idbIface) = ComputeHashes(idbScl);
                    LastSyncedBlockHashes.TryGetValue(BuildCacheKey(projectKey, idbName), out var prevIdb);

                    var generatedIdb = new MerkleDirtyBlock
                    {
                        BlockName = idbName,
                        BlockType = "DB",
                        SclSource = idbScl,
                        MerkleHash = idbMerkle,
                        FullSha256 = idbSha,
                        InterfaceHash = idbIface,
                        InterfaceChanged = true,
                        AutoGeneratedIdb = true,
                        SourceBlock = item.BlockName,
                        SoftwareUnit = item.SoftwareUnit,
                        Reason = refreshReason,
                    };
                    dirtyBlocks.Add(generatedIdb);
                    dirtyByName[idbName] = generatedIdb;
                    orderedNames.Add(idbName);

                    statusByName[idbName] = new MerkleBlockSyncStatus
                    {
                        BlockName = idbName,
                        BlockType = "DB",
                        Status = "DIRTY",
                        Action = "pending",
                        MerkleHash = idbMerkle,
                        FullSha256 = idbSha,
                        PreviousHash = prevIdb?.MerkleHash,
                        InterfaceHash = idbIface,
                        PreviousInterfaceHash = prevIdb?.InterfaceHash,
                        InterfaceChanged = true,
                        AutoGeneratedIdb = true,
                        SourceBlock = item.BlockName,
                        Reason = refreshReason,
                    };
                }
            }

            result.InterfaceChanged = anyInterfaceChanged;
            result.TotalBlocks = orderedNames.Count;
            result.DirtyBlockNames = dirtyBlocks.Select(d => d.BlockName).ToList();
            result.DirtyCount = dirtyBlocks.Count;
            result.UnchangedCount = orderedNames.Count - dirtyBlocks.Count;

            var hasOpenProject = _projects is not null && _projects.IsProjectOpen && _projects.PlcSoftware is not null;
            var hasCustomExecutor = executor is not null;

            // Honest offline / dry-run path: never invoke TIA execution or claim writes happened.
            if (request.DryRun || (!hasOpenProject && !hasCustomExecutor))
            {
                foreach (var name in orderedNames)
                {
                    var st = statusByName[name];
                    if (string.Equals(st.Status, "DIRTY", StringComparison.Ordinal))
                    {
                        st.Action = "dry_run";
                    }
                    result.Blocks.Add(st);
                }

                result.Ok = true;
                result.Executed = false;
                result.CompileOk = null;
                result.CacheUpdated = false;
                result.Mode = "dry_run";
                result.EvidenceLevel = "offline";
                result.Message = request.DryRun
                    ? $"Dry-run Merkle diff: {result.DirtyCount} dirty, {result.UnchangedCount} unchanged (no TIA write)."
                    : $"No open TIA project and no custom executor; honest offline Merkle diff: {result.DirtyCount} dirty, {result.UnchangedCount} unchanged.";
                return result;
            }

            // 100% unchanged fast path: zero execution, zero TIA round-trip.
            if (dirtyBlocks.Count == 0)
            {
                foreach (var name in orderedNames)
                {
                    result.Blocks.Add(statusByName[name]);
                }

                result.Ok = true;
                result.Executed = false;
                result.CompileOk = true;
                result.CacheUpdated = false;
                result.Mode = "unchanged_skip";
                result.EvidenceLevel = hasCustomExecutor ? "custom_executor" : "tia_openness_sta";
                result.Message = $"All {result.UnchangedCount} block(s) unchanged; skipped TIA import and compile.";
                return result;
            }

            var missingSclBlocks = dirtyBlocks.Where(b => string.IsNullOrWhiteSpace(b.SclSource)).ToList();
            if (missingSclBlocks.Count > 0)
            {
                foreach (var name in orderedNames)
                {
                    var st = statusByName[name];
                    if (missingSclBlocks.Any(m => string.Equals(m.BlockName, name, StringComparison.OrdinalIgnoreCase)))
                    {
                        st.Action = "failed";
                        st.CompileOk = false;
                        st.Error = "Missing sclSource / sclPath for dirty block.";
                    }
                    result.Blocks.Add(st);
                }

                result.Ok = false;
                result.Executed = false;
                result.CompileOk = false;
                result.CacheUpdated = false;
                result.Mode = "failed";
                result.EvidenceLevel = hasCustomExecutor ? "custom_executor" : "tia_openness_sta";
                result.Error = new ToolError
                {
                    Code = "invalid_argument",
                    Message = $"Dirty block(s) missing SCL source: {string.Join(", ", missingSclBlocks.Select(m => m.BlockName))}",
                };
                result.Message = result.Error.Message;
                return result;
            }

            var effectiveExecutor = executor ?? new OpennessStaMerkleExecutor(_projects!, _blocks!);
            var batch = new MerkleExecutorBatch
            {
                ProjectKey = projectKey,
                ProjectPath = result.ProjectPath,
                SoftwareUnit = request.SoftwareUnit,
                InterfaceChanged = anyInterfaceChanged,
                DirtyBlocks = dirtyBlocks,
            };

            var execResult = effectiveExecutor.ExecuteSync(batch);
            var compileOk = execResult.Ok && execResult.CompileOk;

            result.Executed = true;
            result.CompileOk = compileOk;
            result.Mode = string.IsNullOrWhiteSpace(execResult.Mode) ? "merkle_sync" : execResult.Mode;
            result.EvidenceLevel = string.IsNullOrWhiteSpace(execResult.EvidenceLevel)
                ? (hasCustomExecutor ? "custom_executor" : "tia_openness_sta")
                : execResult.EvidenceLevel;
            result.GeneratedNames = execResult.GeneratedNames ?? new List<string>();
            result.CompileResults = execResult.CompileResults ?? new List<CompilePlcResult>();
            result.Errors = execResult.Errors ?? new List<string>();
            result.Error = execResult.Error;

            foreach (var name in orderedNames)
            {
                var st = statusByName[name];
                if (string.Equals(st.Status, "DIRTY", StringComparison.Ordinal))
                {
                    if (execResult.BlockStatuses is not null &&
                        execResult.BlockStatuses.TryGetValue(name, out var perBlock))
                    {
                        st.CompileOk = perBlock.CompileOk;
                        st.Error = perBlock.Error;
                        st.Action = compileOk && perBlock.CompileOk ? "synced" : "failed";
                    }
                    else
                    {
                        st.CompileOk = compileOk;
                        st.Action = compileOk ? "synced" : "failed";
                    }
                }
                result.Blocks.Add(st);
            }

            if (compileOk)
            {
                var now = DateTime.UtcNow.ToString("o", CultureInfo.InvariantCulture);
                foreach (var dirty in dirtyBlocks)
                {
                    LastSyncedBlockHashes[BuildCacheKey(projectKey, dirty.BlockName)] = new BlockSyncHashEntry
                    {
                        MerkleHash = dirty.MerkleHash,
                        FullSha256 = dirty.FullSha256,
                        InterfaceHash = dirty.InterfaceHash,
                        UpdatedAtUtc = now,
                    };
                }

                if (request.SaveAfterSync && hasOpenProject)
                {
                    var saved = _projects!.SaveProject();
                    if (!saved.Ok)
                    {
                        result.Ok = false;
                        result.Error = saved.Error;
                        result.Message = $"Compiled {dirtyBlocks.Count} dirty block(s), but SaveProject failed: {saved.Error?.Message}";
                        return result;
                    }
                }

                result.Ok = true;
                result.CacheUpdated = true;
                result.Message =
                    $"Merkle sync compiled {dirtyBlocks.Count} dirty block(s), skipped {result.UnchangedCount} unchanged block(s).";
            }
            else
            {
                // Fail-closed: never advance cached hashes when compile fails so the next sync retries.
                result.Ok = false;
                result.CacheUpdated = false;
                result.Error ??= new ToolError
                {
                    Code = "merkle_compile_failed",
                    Message = execResult.Errors is { Count: > 0 }
                        ? string.Join("; ", execResult.Errors)
                        : "Block sync/compile failed; LastSyncedBlockHashes left unchanged (fail-closed).",
                };
                result.Message = result.Error.Message;
            }

            return result;
        }
        catch (Exception ex)
        {
            result.Ok = false;
            result.CompileOk = false;
            result.CacheUpdated = false;
            result.Mode = "error";
            result.Error = new ToolError
            {
                Code = "merkle_sync_error",
                Message = OpennessMutate.Unwrap(ex).Message,
            };
            result.Message = result.Error.Message;
            return result;
        }
        finally
        {
            sw.Stop();
            result.ElapsedMilliseconds = sw.ElapsedMilliseconds;
        }
    }

    private string ResolveProjectKey(MerkleSyncRequest request)
    {
        if (!string.IsNullOrWhiteSpace(request.ProjectKey))
        {
            return request.ProjectKey!.Trim();
        }

        var path = !string.IsNullOrWhiteSpace(request.ProjectPath)
            ? request.ProjectPath!.Trim()
            : _projects?.ProjectPath;

        if (!string.IsNullOrWhiteSpace(path))
        {
            try
            {
                return Path.IsPathRooted(path!) ? Path.GetFullPath(path!) : path!;
            }
            catch
            {
                return path!;
            }
        }

        return "default";
    }

    private static ResolvedBlockCandidate ResolveCandidate(MerkleBlockInput input, string? defaultUnit)
    {
        var scl = input.SclSource ?? "";
        if (string.IsNullOrWhiteSpace(scl) && !string.IsNullOrWhiteSpace(input.SclPath) && File.Exists(input.SclPath))
        {
            scl = File.ReadAllText(input.SclPath);
        }

        string merkleHash;
        string fullSha256;
        string interfaceHash;
        if (!string.IsNullOrWhiteSpace(scl))
        {
            (merkleHash, fullSha256, interfaceHash) = ComputeHashes(scl);
        }
        else if (!string.IsNullOrWhiteSpace(input.ClientHash))
        {
            merkleHash = input.ClientHash!.Trim().ToLowerInvariant();
            fullSha256 = merkleHash;
            interfaceHash = string.IsNullOrWhiteSpace(input.ClientInterfaceHash)
                ? ""
                : input.ClientInterfaceHash!.Trim().ToLowerInvariant();
        }
        else
        {
            (merkleHash, fullSha256, interfaceHash) = ComputeHashes("");
        }

        var blockName = input.BlockName.Trim();
        var blockType = InferBlockType(input.BlockType, blockName, scl);
        var unit = string.IsNullOrWhiteSpace(input.SoftwareUnit) ? defaultUnit : input.SoftwareUnit;

        return new ResolvedBlockCandidate
        {
            BlockName = blockName,
            BlockType = blockType,
            SclSource = scl,
            MerkleHash = merkleHash,
            FullSha256 = fullSha256,
            InterfaceHash = interfaceHash,
            InstanceDbName = string.IsNullOrWhiteSpace(input.InstanceDbName) ? null : input.InstanceDbName!.Trim(),
            SoftwareUnit = string.IsNullOrWhiteSpace(unit) ? null : unit!.Trim(),
        };
    }

    public static string InferBlockType(string? explicitType, string blockName, string? scl)
    {
        if (!string.IsNullOrWhiteSpace(explicitType))
        {
            return explicitType!.Trim().ToUpperInvariant();
        }

        if (!string.IsNullOrWhiteSpace(scl))
        {
            foreach (var rawLine in scl!.Replace("\r\n", "\n").Split(new[] { '\n' }, StringSplitOptions.None))
            {
                var line = rawLine.Trim();
                if (line.Length == 0 || line.StartsWith("//", StringComparison.Ordinal)) continue;
                var m = BlockHeaderRegex.Match(line);
                if (m.Success)
                {
                    return m.Groups[1].Value.ToUpperInvariant() switch
                    {
                        "FUNCTION_BLOCK" => "FB",
                        "FUNCTION" => "FC",
                        "DATA_BLOCK" => "DB",
                        "ORGANIZATION_BLOCK" => "OB",
                        "TYPE" => "UDT",
                        _ => "OTHER",
                    };
                }
            }
        }

        var upper = (blockName ?? "").Trim().ToUpperInvariant();
        if (upper.StartsWith("FB_", StringComparison.Ordinal)) return "FB";
        if (upper.StartsWith("FC_", StringComparison.Ordinal)) return "FC";
        if (upper.StartsWith("DB_", StringComparison.Ordinal) || upper.StartsWith("IDB_", StringComparison.Ordinal)) return "DB";
        if (upper.StartsWith("OB", StringComparison.Ordinal)) return "OB";
        if (upper.StartsWith("UDT", StringComparison.Ordinal) || upper.StartsWith("TYPE_", StringComparison.Ordinal)) return "UDT";
        return "OTHER";
    }

    private sealed class ResolvedBlockCandidate
    {
        public string BlockName { get; set; } = "";
        public string BlockType { get; set; } = "OTHER";
        public string SclSource { get; set; } = "";
        public string MerkleHash { get; set; } = "";
        public string FullSha256 { get; set; } = "";
        public string InterfaceHash { get; set; } = "";
        public string? InstanceDbName { get; set; }
        public string? SoftwareUnit { get; set; }
    }
}

/// <summary>Executor abstraction for dirty block synchronization (allows unit testing without TIA).</summary>
public interface IMerkleBlockExecutor
{
    MerkleExecutionResult ExecuteSync(MerkleExecutorBatch batch);
}

/// <summary>
/// Default STA Openness reflection executor: writes UTF-8 BOM temporary SCL source,
/// imports via <see cref="BlockService.GenerateBlocksFromSource"/>, cleans up the temporary
/// external source, and compiles strictly via <see cref="BlockService.CompileBlocksStrict"/>.
/// </summary>
public sealed class OpennessStaMerkleExecutor : IMerkleBlockExecutor
{
    private readonly ProjectService _projects;
    private readonly BlockService _blocks;

    public OpennessStaMerkleExecutor(ProjectService projects, BlockService blocks)
    {
        _projects = projects ?? throw new ArgumentNullException(nameof(projects));
        _blocks = blocks ?? throw new ArgumentNullException(nameof(blocks));
    }

    public MerkleExecutionResult ExecuteSync(MerkleExecutorBatch batch)
    {
        if (batch is null) throw new ArgumentNullException(nameof(batch));

        var result = new MerkleExecutionResult
        {
            Mode = "tia_openness_sta",
            EvidenceLevel = "tia_openness_sta",
        };

        if (!_projects.IsProjectOpen || _projects.PlcSoftware is null)
        {
            result.Ok = false;
            result.CompileOk = false;
            result.Error = new ToolError
            {
                Code = "no_project_open",
                Message = "No open TIA Portal PLC software session; cannot execute Openness merkle sync.",
            };
            result.Errors.Add(result.Error.Message);
            return result;
        }

        if (batch.DirtyBlocks.Count == 0)
        {
            result.Ok = true;
            result.CompileOk = true;
            return result;
        }

        foreach (var dirty in batch.DirtyBlocks)
        {
            if (BlockService.LooksLikeSafetyName(dirty.BlockName) || BlockService.SclLooksLikeSafety(dirty.SclSource))
            {
                result.Ok = false;
                result.CompileOk = false;
                result.Error = new ToolError
                {
                    Code = "safety_block",
                    Message = $"Refusing Merkle sync for Safety/F-block '{dirty.BlockName}'.",
                };
                result.Errors.Add(result.Error.Message);
                return result;
            }
        }

        var ordered = batch.DirtyBlocks
            .OrderBy(b => ExecutionOrderRank(b.BlockType))
            .ThenBy(b => b.AutoGeneratedIdb ? 1 : 0)
            .ThenBy(b => b.BlockName, StringComparer.OrdinalIgnoreCase)
            .ToList();

        var groups = ordered.GroupBy(
            b => string.IsNullOrWhiteSpace(b.SoftwareUnit) ? (batch.SoftwareUnit ?? "") : b.SoftwareUnit!,
            StringComparer.OrdinalIgnoreCase);

        var allCompileTargets = new List<string>();
        foreach (var unitGroup in groups)
        {
            var unitName = string.IsNullOrWhiteSpace(unitGroup.Key) ? null : unitGroup.Key;
            var combinedScl = string.Join("\r\n\r\n", unitGroup.Select(b => b.SclSource.Trim()));
            var tempDir = Path.Combine(Path.GetTempPath(), "af_studio_v5_merkle");
            Directory.CreateDirectory(tempDir);
            var tempScl = Path.Combine(tempDir, $"merkle_{Guid.NewGuid():N}.scl");
            string? sourceName = null;

            try
            {
                // Siemens TIA Openness expects UTF-8 with BOM on external SCL files.
                File.WriteAllText(tempScl, combinedScl + "\r\n", new UTF8Encoding(encoderShouldEmitUTF8Identifier: true));
                result.TempSclPath = tempScl;

                var generated = _blocks.GenerateBlocksFromSource(tempScl, overwrite: true, softwareUnit: unitName);
                sourceName = generated.SourceName;
                if (generated.GeneratedNames is not null)
                {
                    result.GeneratedNames.AddRange(generated.GeneratedNames);
                }

                if (!generated.Ok)
                {
                    result.Ok = false;
                    result.CompileOk = false;
                    result.Error = generated.Error ?? new ToolError
                    {
                        Code = "generate_blocks_from_source_failed",
                        Message = generated.Message ?? "GenerateBlocksFromSource failed.",
                    };
                    result.Errors.Add(result.Error.Message);
                    foreach (var b in unitGroup)
                    {
                        result.BlockStatuses[b.BlockName] = new MerkleBlockExecutionOutcome
                        {
                            Generated = false,
                            CompileOk = false,
                            Error = result.Error.Message,
                        };
                    }
                    return result;
                }

                allCompileTargets.AddRange(unitGroup.Select(b => b.BlockName));
            }
            finally
            {
                TryCleanupExternalSource(sourceName, unitName);
                try
                {
                    if (File.Exists(tempScl)) File.Delete(tempScl);
                }
                catch
                {
                    // best-effort temp file cleanup
                }
            }
        }

        var compileResults = _blocks.CompileBlocksStrict(string.Join("|", allCompileTargets.Distinct(StringComparer.OrdinalIgnoreCase)));
        result.CompileResults.AddRange(compileResults);

        var allCompiled = compileResults.Count > 0 && compileResults.All(r => r.Ok);
        foreach (var dirty in ordered)
        {
            var cr = compileResults.FirstOrDefault(r =>
                string.Equals(r.BlockName, dirty.BlockName, StringComparison.OrdinalIgnoreCase));
            var blockOk = cr is not null ? cr.Ok : allCompiled;
            var errMsg = cr?.Error?.Message;
            if (!blockOk && !string.IsNullOrWhiteSpace(errMsg))
            {
                result.Errors.Add(errMsg!);
            }
            result.BlockStatuses[dirty.BlockName] = new MerkleBlockExecutionOutcome
            {
                Generated = true,
                CompileOk = blockOk,
                State = cr?.State,
                ErrorCount = cr?.ErrorCount,
                WarningCount = cr?.WarningCount,
                Message = cr?.Message,
                Error = errMsg,
            };
        }

        result.CompileOk = allCompiled;
        result.Ok = allCompiled;
        if (!allCompiled)
        {
            result.Error = compileResults.FirstOrDefault(r => !r.Ok)?.Error ?? new ToolError
            {
                Code = "compile_failed",
                Message = "CompileBlocksStrict reported errors.",
            };
        }

        return result;
    }

    private static int ExecutionOrderRank(string blockType) => (blockType ?? "").ToUpperInvariant() switch
    {
        "UDT" => 0,
        "TYPE" => 0,
        "FC" => 1,
        "FB" => 2,
        "OB" => 3,
        "DB" => 4,
        _ => 5,
    };

    private void TryCleanupExternalSource(string? sourceName, string? softwareUnit)
    {
        if (string.IsNullOrWhiteSpace(sourceName) || _projects.PlcSoftware is null) return;
        try
        {
            object? extGroup = null;
            if (!string.IsNullOrWhiteSpace(softwareUnit))
            {
                var unit = _blocks.FindSoftwareUnit(softwareUnit!);
                if (unit is not null)
                {
                    extGroup = OpennessExport.GetFirstProp(unit, "ExternalSourceGroup", "ExternalSources");
                }
            }
            extGroup ??= OpennessExport.GetProp(_projects.PlcSoftware, "ExternalSourceGroup");
            var sources = OpennessExport.GetProp(extGroup, "ExternalSources");
            if (sources is null) return;

            var find = sources.GetType().GetMethods(BindingFlags.Public | BindingFlags.Instance)
                .FirstOrDefault(m => m.Name == "Find" && m.GetParameters().Length == 1 && m.GetParameters()[0].ParameterType == typeof(string));
            var existing = find?.Invoke(sources, new object[] { sourceName! });
            existing?.GetType().GetMethod("Delete", Type.EmptyTypes)?.Invoke(existing, null);
        }
        catch
        {
            // best-effort external source cleanup
        }
    }
}

public sealed class BlockSyncHashEntry
{
    [JsonPropertyName("merkleHash")]
    public string MerkleHash { get; set; } = "";

    [JsonPropertyName("fullSha256")]
    public string FullSha256 { get; set; } = "";

    [JsonPropertyName("interfaceHash")]
    public string InterfaceHash { get; set; } = "";

    [JsonPropertyName("updatedAtUtc")]
    public string UpdatedAtUtc { get; set; } = "";
}

public sealed class MerkleBlockInput
{
    [JsonPropertyName("blockName")]
    public string BlockName { get; set; } = "";

    [JsonPropertyName("blockType")]
    public string? BlockType { get; set; }

    [JsonPropertyName("sclSource")]
    public string? SclSource { get; set; }

    [JsonPropertyName("sclPath")]
    public string? SclPath { get; set; }

    [JsonPropertyName("instanceDbName")]
    public string? InstanceDbName { get; set; }

    [JsonPropertyName("softwareUnit")]
    public string? SoftwareUnit { get; set; }

    [JsonPropertyName("clientHash")]
    public string? ClientHash { get; set; }

    [JsonPropertyName("clientInterfaceHash")]
    public string? ClientInterfaceHash { get; set; }
}

public sealed class MerkleSyncRequest
{
    [JsonPropertyName("projectPath")]
    public string? ProjectPath { get; set; }

    [JsonPropertyName("projectKey")]
    public string? ProjectKey { get; set; }

    [JsonPropertyName("softwareUnit")]
    public string? SoftwareUnit { get; set; }

    [JsonPropertyName("dryRun")]
    public bool DryRun { get; set; }

    [JsonPropertyName("force")]
    public bool Force { get; set; }

    [JsonPropertyName("saveAfterSync")]
    public bool SaveAfterSync { get; set; }

    [JsonPropertyName("blocks")]
    public List<MerkleBlockInput> Blocks { get; set; } = new();

    public static MerkleSyncRequest FromJson(JsonElement root)
    {
        var req = new MerkleSyncRequest
        {
            ProjectPath = GetString(root, "projectPath") ?? GetString(root, "project"),
            ProjectKey = GetString(root, "projectKey") ?? GetString(root, "project_key"),
            SoftwareUnit = GetString(root, "softwareUnit") ?? GetString(root, "software_unit") ?? GetString(root, "unit"),
            DryRun = GetBool(root, "dryRun") ?? GetBool(root, "dry_run") ?? false,
            Force = GetBool(root, "force") ?? false,
            SaveAfterSync = GetBool(root, "saveAfterSync") ?? GetBool(root, "save_after_sync") ?? false,
        };

        if (root.TryGetProperty("blocks", out var blocksEl) && blocksEl.ValueKind == JsonValueKind.Array)
        {
            foreach (var item in blocksEl.EnumerateArray())
            {
                if (item.ValueKind != JsonValueKind.Object) continue;
                req.Blocks.Add(new MerkleBlockInput
                {
                    BlockName = GetString(item, "blockName") ?? GetString(item, "block_name") ?? GetString(item, "name") ?? "",
                    BlockType = GetString(item, "blockType") ?? GetString(item, "block_type") ?? GetString(item, "type"),
                    SclSource = GetString(item, "sclSource") ?? GetString(item, "scl_source") ?? GetString(item, "scl"),
                    SclPath = GetString(item, "sclPath") ?? GetString(item, "scl_path"),
                    InstanceDbName = GetString(item, "instanceDbName") ?? GetString(item, "instance_db_name") ?? GetString(item, "instanceDb"),
                    SoftwareUnit = GetString(item, "softwareUnit") ?? GetString(item, "software_unit") ?? GetString(item, "unit"),
                    ClientHash = GetString(item, "clientHash") ?? GetString(item, "merkleHash") ?? GetString(item, "merkle_hash"),
                    ClientInterfaceHash = GetString(item, "clientInterfaceHash") ?? GetString(item, "interfaceHash") ?? GetString(item, "interface_hash"),
                });
            }
        }

        return req;
    }

    private static string? GetString(JsonElement root, string name) =>
        root.TryGetProperty(name, out var el) && el.ValueKind == JsonValueKind.String ? el.GetString() : null;

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
}

public sealed class MerkleDirtyBlock
{
    public string BlockName { get; set; } = "";
    public string BlockType { get; set; } = "OTHER";
    public string SclSource { get; set; } = "";
    public string MerkleHash { get; set; } = "";
    public string FullSha256 { get; set; } = "";
    public string InterfaceHash { get; set; } = "";
    public bool InterfaceChanged { get; set; }
    public bool AutoGeneratedIdb { get; set; }
    public string? SourceBlock { get; set; }
    public string? SoftwareUnit { get; set; }
    public string Reason { get; set; } = "";
}

public sealed class MerkleExecutorBatch
{
    public string ProjectKey { get; set; } = "";
    public string? ProjectPath { get; set; }
    public string? SoftwareUnit { get; set; }
    public bool InterfaceChanged { get; set; }
    public List<MerkleDirtyBlock> DirtyBlocks { get; set; } = new();
}

public sealed class MerkleBlockExecutionOutcome
{
    public bool Generated { get; set; }
    public bool CompileOk { get; set; }
    public string? State { get; set; }
    public int? ErrorCount { get; set; }
    public int? WarningCount { get; set; }
    public string? Message { get; set; }
    public string? Error { get; set; }
}

public sealed class MerkleExecutionResult
{
    public bool Ok { get; set; }
    public bool CompileOk { get; set; }
    public string Mode { get; set; } = "tia_openness_sta";
    public string EvidenceLevel { get; set; } = "tia_openness_sta";
    public string? TempSclPath { get; set; }
    public List<string> GeneratedNames { get; set; } = new();
    public List<CompilePlcResult> CompileResults { get; set; } = new();
    public Dictionary<string, MerkleBlockExecutionOutcome> BlockStatuses { get; set; } =
        new(StringComparer.OrdinalIgnoreCase);
    public List<string> Errors { get; set; } = new();
    public ToolError? Error { get; set; }
}

public sealed class MerkleBlockSyncStatus
{
    [JsonPropertyName("blockName")]
    public string BlockName { get; set; } = "";

    [JsonPropertyName("blockType")]
    public string BlockType { get; set; } = "";

    [JsonPropertyName("status")]
    public string Status { get; set; } = "UNCHANGED";

    [JsonPropertyName("action")]
    public string Action { get; set; } = "skipped";

    [JsonPropertyName("merkleHash")]
    public string MerkleHash { get; set; } = "";

    [JsonPropertyName("fullSha256")]
    public string FullSha256 { get; set; } = "";

    [JsonPropertyName("previousHash")]
    public string? PreviousHash { get; set; }

    [JsonPropertyName("interfaceHash")]
    public string InterfaceHash { get; set; } = "";

    [JsonPropertyName("previousInterfaceHash")]
    public string? PreviousInterfaceHash { get; set; }

    [JsonPropertyName("interfaceChanged")]
    public bool InterfaceChanged { get; set; }

    [JsonPropertyName("autoGeneratedIdb")]
    public bool AutoGeneratedIdb { get; set; }

    [JsonPropertyName("sourceBlock")]
    public string? SourceBlock { get; set; }

    [JsonPropertyName("compileOk")]
    public bool? CompileOk { get; set; }

    [JsonPropertyName("reason")]
    public string Reason { get; set; } = "";

    [JsonPropertyName("error")]
    public string? Error { get; set; }
}

public sealed class MerkleSyncResult
{
    [JsonPropertyName("ok")]
    public bool Ok { get; set; }

    [JsonPropertyName("mode")]
    public string Mode { get; set; } = "dry_run";

    [JsonPropertyName("evidenceLevel")]
    public string EvidenceLevel { get; set; } = "offline";

    [JsonPropertyName("executed")]
    public bool Executed { get; set; }

    [JsonPropertyName("compileOk")]
    public bool? CompileOk { get; set; }

    [JsonPropertyName("cacheUpdated")]
    public bool CacheUpdated { get; set; }

    [JsonPropertyName("interfaceChanged")]
    public bool InterfaceChanged { get; set; }

    [JsonPropertyName("projectKey")]
    public string ProjectKey { get; set; } = "";

    [JsonPropertyName("projectPath")]
    public string? ProjectPath { get; set; }

    [JsonPropertyName("totalBlocks")]
    public int TotalBlocks { get; set; }

    [JsonPropertyName("dirtyCount")]
    public int DirtyCount { get; set; }

    [JsonPropertyName("unchangedCount")]
    public int UnchangedCount { get; set; }

    [JsonPropertyName("elapsedMilliseconds")]
    public long ElapsedMilliseconds { get; set; }

    [JsonPropertyName("dirtyBlockNames")]
    public List<string> DirtyBlockNames { get; set; } = new();

    [JsonPropertyName("generatedNames")]
    public List<string> GeneratedNames { get; set; } = new();

    [JsonPropertyName("blocks")]
    public List<MerkleBlockSyncStatus> Blocks { get; set; } = new();

    [JsonPropertyName("compileResults")]
    public List<CompilePlcResult> CompileResults { get; set; } = new();

    [JsonPropertyName("errors")]
    public List<string> Errors { get; set; } = new();

    [JsonPropertyName("message")]
    public string? Message { get; set; }

    [JsonPropertyName("error")]
    public ToolError? Error { get; set; }
}

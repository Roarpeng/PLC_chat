using System;
using System.Collections.Generic;
using System.Diagnostics;
using System.Globalization;
using System.Linq;
using System.Net;
using System.Net.Sockets;
using System.Text.Json;
using System.Text.Json.Serialization;
using TiaOpenness.Models;

namespace TiaOpenness.Server;

/// <summary>
/// Live / simulated PLC cross-station DI &amp; diagnostic-word snapshot service
/// backing AF-Studio v5 minimal-cut-set root-cause tracing.
/// Fails closed with <c>errorCode = "plc_unreachable"</c> when a real <c>plcIp</c>
/// is requested in non-simulated mode and cannot be reached.
/// </summary>
public sealed class CutSetSnapshotService
{
    private readonly SimulatedPlcDiagnosticsProvider _simulatedProvider;
    private readonly IPlcLiveDiagnosticsProvider _opcUaProvider;
    private readonly IPlcLiveDiagnosticsProvider _s7CommPlusProvider;

    public SimulatedPlcDiagnosticsProvider SimulatedProvider => _simulatedProvider;

    public CutSetSnapshotService()
        : this(
            new SimulatedPlcDiagnosticsProvider(),
            new OpcUaDiagnosticsProvider(),
            new S7CommPlusDiagnosticsProvider())
    {
    }

    public CutSetSnapshotService(
        SimulatedPlcDiagnosticsProvider simulatedProvider,
        IPlcLiveDiagnosticsProvider? opcUaProvider = null,
        IPlcLiveDiagnosticsProvider? s7CommPlusProvider = null)
    {
        _simulatedProvider = simulatedProvider ?? throw new ArgumentNullException(nameof(simulatedProvider));
        _opcUaProvider = opcUaProvider ?? new OpcUaDiagnosticsProvider();
        _s7CommPlusProvider = s7CommPlusProvider ?? new S7CommPlusDiagnosticsProvider();
    }

    public CutSetSnapshotResult CaptureCutSetSnapshot(
        CutSetSnapshotRequest? request = null,
        IPlcLiveDiagnosticsProvider? overrideProvider = null)
    {
        request ??= new CutSetSnapshotRequest();
        var sw = Stopwatch.StartNew();

        try
        {
            IPlcLiveDiagnosticsProvider provider;
            if (overrideProvider is not null)
            {
                provider = overrideProvider;
            }
            else if (request.Simulate == true)
            {
                provider = _simulatedProvider;
            }
            else if (!string.IsNullOrWhiteSpace(request.PlcIp))
            {
                provider = string.Equals(request.Protocol, "s7commplus", StringComparison.OrdinalIgnoreCase)
                    ? _s7CommPlusProvider
                    : _opcUaProvider;
            }
            else if (string.Equals(request.Protocol, "opcua", StringComparison.OrdinalIgnoreCase) ||
                     string.Equals(request.Protocol, "s7commplus", StringComparison.OrdinalIgnoreCase))
            {
                return FailUnreachable(
                    request.PlcIp,
                    request.Protocol!,
                    "plcIp is required in non-simulated live diagnostics mode.",
                    sw.ElapsedMilliseconds);
            }
            else
            {
                provider = _simulatedProvider;
            }

            if (ReferenceEquals(provider, _simulatedProvider))
            {
                ApplySimulatedRequestMutations(request);
            }

            var read = provider.ReadSnapshot(request);
            if (!read.Ok)
            {
                var errCode = string.IsNullOrWhiteSpace(read.ErrorCode) ? "plc_unreachable" : read.ErrorCode!;
                return new CutSetSnapshotResult
                {
                    Ok = false,
                    ErrorCode = errCode,
                    Message = read.Message ?? "Failed to read PLC diagnostics snapshot.",
                    Source = string.IsNullOrWhiteSpace(read.Source) ? provider.ProviderKind : read.Source,
                    EvidenceLevel = string.IsNullOrWhiteSpace(read.EvidenceLevel) ? "offline" : read.EvidenceLevel,
                    PlcIp = request.PlcIp,
                    Protocol = string.IsNullOrWhiteSpace(request.Protocol) ? provider.ProviderKind : request.Protocol!,
                    CapturedAtUtc = DateTime.UtcNow.ToString("o", CultureInfo.InvariantCulture),
                    ElapsedMilliseconds = sw.ElapsedMilliseconds,
                    Error = new ToolError
                    {
                        Code = errCode,
                        Message = read.Message ?? "PLC unreachable.",
                    },
                };
            }

            var diStates = new Dictionary<string, bool>(StringComparer.OrdinalIgnoreCase);
            var crossStation = new Dictionary<string, Dictionary<string, bool>>(StringComparer.OrdinalIgnoreCase);
            var terminalMap = new Dictionary<string, TerminalPinMapping>(StringComparer.OrdinalIgnoreCase);
            var faultedTerminals = new List<TerminalPinMapping>();

            foreach (var pin in read.Terminals)
            {
                if (!string.IsNullOrWhiteSpace(request.StationFilter) &&
                    !string.Equals(pin.StationId, request.StationFilter, StringComparison.OrdinalIgnoreCase))
                {
                    continue;
                }

                diStates[pin.Address] = pin.Value;
                if (!crossStation.TryGetValue(pin.StationId, out var stationMap))
                {
                    stationMap = new Dictionary<string, bool>(StringComparer.OrdinalIgnoreCase);
                    crossStation[pin.StationId] = stationMap;
                }
                stationMap[pin.Address] = pin.Value;

                var clone = pin.Clone();
                terminalMap[pin.Address] = clone;
                if (clone.IsFaulted)
                {
                    faultedTerminals.Add(clone);
                }
            }

            var stationDiags = new Dictionary<string, StationDiagnosticWord>(StringComparer.OrdinalIgnoreCase);
            var blockingWords = new Dictionary<string, string>(StringComparer.OrdinalIgnoreCase);
            var anyBlocked = false;

            foreach (var diag in read.StationDiagnostics.Values)
            {
                if (!string.IsNullOrWhiteSpace(request.StationFilter) &&
                    !string.Equals(diag.StationId, request.StationFilter, StringComparison.OrdinalIgnoreCase))
                {
                    continue;
                }

                var clone = diag.Clone();
                stationDiags[clone.StationId] = clone;
                if (clone.IsBlocked)
                {
                    anyBlocked = true;
                    blockingWords[clone.StationId] = clone.DiagCodeHex;
                }
            }

            var isHealthy = !anyBlocked && faultedTerminals.Count == 0;
            return new CutSetSnapshotResult
            {
                Ok = true,
                ErrorCode = null,
                Message = isHealthy
                    ? "All cross-station interlocks and DI terminals healthy."
                    : $"Captured faulted cut-set snapshot ({faultedTerminals.Count} faulted terminal(s), {blockingWords.Count} blocked station(s)).",
                Source = string.IsNullOrWhiteSpace(read.Source) ? provider.ProviderKind : read.Source,
                EvidenceLevel = string.IsNullOrWhiteSpace(read.EvidenceLevel) ? "simulated" : read.EvidenceLevel,
                PlcIp = request.PlcIp,
                Protocol = string.IsNullOrWhiteSpace(request.Protocol) ? provider.ProviderKind : request.Protocol!,
                CapturedAtUtc = DateTime.UtcNow.ToString("o", CultureInfo.InvariantCulture),
                ElapsedMilliseconds = sw.ElapsedMilliseconds,
                IsHealthy = isHealthy,
                DiStates = diStates,
                CrossStationDiStates = crossStation,
                TerminalMap = terminalMap,
                StationDiagnostics = stationDiags,
                BlockingDiagWords = blockingWords,
                FaultedTerminals = faultedTerminals,
            };
        }
        catch (Exception ex)
        {
            return new CutSetSnapshotResult
            {
                Ok = false,
                ErrorCode = "snapshot_error",
                Message = OpennessMutate.Unwrap(ex).Message,
                Source = "error",
                EvidenceLevel = "offline",
                PlcIp = request.PlcIp,
                CapturedAtUtc = DateTime.UtcNow.ToString("o", CultureInfo.InvariantCulture),
                ElapsedMilliseconds = sw.ElapsedMilliseconds,
                Error = new ToolError
                {
                    Code = "snapshot_error",
                    Message = OpennessMutate.Unwrap(ex).Message,
                },
            };
        }
    }

    private void ApplySimulatedRequestMutations(CutSetSnapshotRequest request)
    {
        if (request.Healthy == true)
        {
            _simulatedProvider.SetHealthyScenario();
        }
        if (request.ResetFault == true)
        {
            _simulatedProvider.ResetToDefaultFaultScenario();
        }
        if (!string.IsNullOrWhiteSpace(request.RecoverAddress))
        {
            _simulatedProvider.RecoverFault(request.StationFilter ?? "ST10", request.RecoverAddress!, healthyValue: true);
        }
        if (request.InjectFault is not null && !string.IsNullOrWhiteSpace(request.InjectFault.Address))
        {
            _simulatedProvider.InjectFault(
                request.InjectFault.StationId,
                request.InjectFault.DiagCodeHex,
                request.InjectFault.Address,
                request.InjectFault.Value,
                request.InjectFault.CabinetWireTag,
                request.InjectFault.BlockedStepNo,
                request.InjectFault.Reason,
                request.InjectFault.SignalName);
        }
    }

    private static CutSetSnapshotResult FailUnreachable(
        string? plcIp, string protocol, string message, long elapsedMs) => new()
    {
        Ok = false,
        ErrorCode = "plc_unreachable",
        Message = message,
        Source = protocol,
        EvidenceLevel = "offline",
        PlcIp = plcIp,
        Protocol = protocol,
        CapturedAtUtc = DateTime.UtcNow.ToString("o", CultureInfo.InvariantCulture),
        ElapsedMilliseconds = elapsedMs,
        Error = new ToolError
        {
            Code = "plc_unreachable",
            Message = message,
        },
    };
}

/// <summary>Live PLC diagnostics provider abstraction (OPC UA / S7commPlus / Simulated).</summary>
public interface IPlcLiveDiagnosticsProvider
{
    string ProviderKind { get; }
    PlcDiagnosticsReadResult ReadSnapshot(CutSetSnapshotRequest request);
}

/// <summary>
/// Thread-safe simulated PLC diagnostics twin supporting fault injection and recovery.
/// Default state reproduces the cross-station cut-set scenario:
/// ST20 blocked with <c>16#0203</c> (<c>%I10.0 = true</c>), upstream ST10 <c>%I0.4 = false</c>
/// at cabinet terminal <c>X12:04</c>.
/// </summary>
public sealed class SimulatedPlcDiagnosticsProvider : IPlcLiveDiagnosticsProvider
{
    private readonly object _gate = new();
    private readonly Dictionary<string, TerminalPinMapping> _terminals =
        new(StringComparer.OrdinalIgnoreCase);
    private readonly Dictionary<string, StationDiagnosticWord> _stationDiagnostics =
        new(StringComparer.OrdinalIgnoreCase);

    public string ProviderKind => "simulated_plc_diagnostics";

    public SimulatedPlcDiagnosticsProvider(bool startFaulted = true)
    {
        if (startFaulted)
        {
            ResetToDefaultFaultScenario();
        }
        else
        {
            SetHealthyScenario();
        }
    }

    public void ResetToDefaultFaultScenario()
    {
        lock (_gate)
        {
            _terminals.Clear();
            _stationDiagnostics.Clear();

            _terminals["%I10.0"] = new TerminalPinMapping
            {
                Address = "%I10.0",
                StationId = "ST20",
                CabinetWireTag = "X20:01",
                SignalName = "ST20_ZAxis_AtHome",
                Value = true,
                ExpectedHealthyValue = true,
                IsFaulted = false,
            };

            _terminals["%I0.4"] = new TerminalPinMapping
            {
                Address = "%I0.4",
                StationId = "ST10",
                CabinetWireTag = "X12:04",
                SignalName = "ST10_TransferCyl_AtHome",
                Value = false,
                ExpectedHealthyValue = true,
                IsFaulted = true,
            };

            _stationDiagnostics["ST20"] = new StationDiagnosticWord
            {
                StationId = "ST20",
                DiagCodeHex = "16#0203",
                DiagCodeValue = 0x0203,
                IsBlocked = true,
                BlockedStepNo = 30,
                Reason = "ST20 Step 30 超时：跨站护栏阻断，上游 ST10 移载气缸原位信号 %I0.4 (端子 X12:04) 为 FALSE",
                FaultAddresses = new List<string> { "%I0.4" },
            };

            _stationDiagnostics["ST10"] = new StationDiagnosticWord
            {
                StationId = "ST10",
                DiagCodeHex = "16#0000",
                DiagCodeValue = 0,
                IsBlocked = false,
                Reason = "ST10 移载气缸原位磁性开关 %I0.4 (X12:04) 信号丢失",
                FaultAddresses = new List<string> { "%I0.4" },
            };
        }
    }

    public void SetHealthyScenario()
    {
        lock (_gate)
        {
            _terminals.Clear();
            _stationDiagnostics.Clear();

            _terminals["%I10.0"] = new TerminalPinMapping
            {
                Address = "%I10.0",
                StationId = "ST20",
                CabinetWireTag = "X20:01",
                SignalName = "ST20_ZAxis_AtHome",
                Value = true,
                ExpectedHealthyValue = true,
                IsFaulted = false,
            };

            _terminals["%I0.4"] = new TerminalPinMapping
            {
                Address = "%I0.4",
                StationId = "ST10",
                CabinetWireTag = "X12:04",
                SignalName = "ST10_TransferCyl_AtHome",
                Value = true,
                ExpectedHealthyValue = true,
                IsFaulted = false,
            };

            _stationDiagnostics["ST20"] = new StationDiagnosticWord
            {
                StationId = "ST20",
                DiagCodeHex = "16#0000",
                DiagCodeValue = 0,
                IsBlocked = false,
                Reason = "OK",
            };

            _stationDiagnostics["ST10"] = new StationDiagnosticWord
            {
                StationId = "ST10",
                DiagCodeHex = "16#0000",
                DiagCodeValue = 0,
                IsBlocked = false,
                Reason = "OK",
            };
        }
    }

    public void InjectFault(
        string stationId,
        string diagCodeHex,
        string address,
        bool value,
        string? cabinetWireTag = null,
        int? blockedStepNo = null,
        string? reason = null,
        string? signalName = null)
    {
        if (string.IsNullOrWhiteSpace(stationId)) throw new ArgumentNullException(nameof(stationId));
        if (string.IsNullOrWhiteSpace(address)) throw new ArgumentNullException(nameof(address));

        lock (_gate)
        {
            var addr = address.Trim();
            var station = stationId.Trim();
            _terminals.TryGetValue(addr, out var existingPin);

            _terminals[addr] = new TerminalPinMapping
            {
                Address = addr,
                StationId = existingPin?.StationId ?? station,
                CabinetWireTag = !string.IsNullOrWhiteSpace(cabinetWireTag)
                    ? cabinetWireTag!.Trim()
                    : (existingPin?.CabinetWireTag ?? ""),
                SignalName = !string.IsNullOrWhiteSpace(signalName)
                    ? signalName!.Trim()
                    : (existingPin?.SignalName ?? addr),
                Value = value,
                ExpectedHealthyValue = !value,
                IsFaulted = true,
            };

            var hex = string.IsNullOrWhiteSpace(diagCodeHex) ? "16#0203" : diagCodeHex.Trim();
            _stationDiagnostics[station] = new StationDiagnosticWord
            {
                StationId = station,
                DiagCodeHex = hex,
                DiagCodeValue = ParseDiagCode(hex),
                IsBlocked = true,
                BlockedStepNo = blockedStepNo,
                Reason = reason ?? $"{station} blocked by fault on {addr}",
                FaultAddresses = new List<string> { addr },
            };
        }
    }

    public void RecoverFault(string stationId, string address, bool healthyValue = true)
    {
        if (string.IsNullOrWhiteSpace(address)) throw new ArgumentNullException(nameof(address));

        lock (_gate)
        {
            var addr = address.Trim();
            if (_terminals.TryGetValue(addr, out var pin))
            {
                pin.Value = healthyValue;
                pin.ExpectedHealthyValue = healthyValue;
                pin.IsFaulted = false;
            }
            else if (!string.IsNullOrWhiteSpace(stationId))
            {
                _terminals[addr] = new TerminalPinMapping
                {
                    Address = addr,
                    StationId = stationId.Trim(),
                    SignalName = addr,
                    Value = healthyValue,
                    ExpectedHealthyValue = healthyValue,
                    IsFaulted = false,
                };
            }

            foreach (var diag in _stationDiagnostics.Values)
            {
                diag.FaultAddresses.RemoveAll(a => string.Equals(a, addr, StringComparison.OrdinalIgnoreCase));
                if (diag.FaultAddresses.Count == 0 &&
                    (string.Equals(diag.StationId, stationId, StringComparison.OrdinalIgnoreCase) || diag.IsBlocked))
                {
                    diag.DiagCodeHex = "16#0000";
                    diag.DiagCodeValue = 0;
                    diag.IsBlocked = false;
                    diag.BlockedStepNo = null;
                    diag.Reason = "OK";
                }
            }
        }
    }

    public void SetSignal(
        string address,
        bool value,
        string? stationId = null,
        string? cabinetWireTag = null,
        string? signalName = null)
    {
        if (string.IsNullOrWhiteSpace(address)) throw new ArgumentNullException(nameof(address));

        lock (_gate)
        {
            var addr = address.Trim();
            if (_terminals.TryGetValue(addr, out var existing))
            {
                existing.Value = value;
                if (!string.IsNullOrWhiteSpace(stationId)) existing.StationId = stationId!.Trim();
                if (!string.IsNullOrWhiteSpace(cabinetWireTag)) existing.CabinetWireTag = cabinetWireTag!.Trim();
                if (!string.IsNullOrWhiteSpace(signalName)) existing.SignalName = signalName!.Trim();
                existing.IsFaulted = value != existing.ExpectedHealthyValue;
            }
            else
            {
                _terminals[addr] = new TerminalPinMapping
                {
                    Address = addr,
                    StationId = string.IsNullOrWhiteSpace(stationId) ? "ST10" : stationId!.Trim(),
                    CabinetWireTag = cabinetWireTag ?? "",
                    SignalName = signalName ?? addr,
                    Value = value,
                    ExpectedHealthyValue = true,
                    IsFaulted = !value,
                };
            }
        }
    }

    public PlcDiagnosticsReadResult ReadSnapshot(CutSetSnapshotRequest request)
    {
        lock (_gate)
        {
            var result = new PlcDiagnosticsReadResult
            {
                Ok = true,
                Source = ProviderKind,
                EvidenceLevel = "simulated",
            };

            foreach (var pin in _terminals.Values)
            {
                result.Terminals.Add(pin.Clone());
            }

            foreach (var kv in _stationDiagnostics)
            {
                result.StationDiagnostics[kv.Key] = kv.Value.Clone();
            }

            return result;
        }
    }

    private static int ParseDiagCode(string hex)
    {
        var cleaned = (hex ?? "").Trim();
        if (cleaned.StartsWith("16#", StringComparison.OrdinalIgnoreCase))
        {
            cleaned = cleaned.Substring(3);
        }
        else if (cleaned.StartsWith("0x", StringComparison.OrdinalIgnoreCase))
        {
            cleaned = cleaned.Substring(2);
        }

        return int.TryParse(cleaned, NumberStyles.HexNumber, CultureInfo.InvariantCulture, out var val)
            ? val
            : 0;
    }
}

/// <summary>
/// OPC UA connector skeleton for live PLC cut-set snapshot acquisition.
/// Performs TCP endpoint probe and fails closed with <c>plc_unreachable</c>
/// when unreachable or when full OPC UA binary session protocol is not active.
/// </summary>
public sealed class OpcUaDiagnosticsProvider : IPlcLiveDiagnosticsProvider
{
    public const int DefaultPort = 4840;
    public string ProviderKind => "opcua_live";

    public PlcDiagnosticsReadResult ReadSnapshot(CutSetSnapshotRequest request)
    {
        var ip = (request.PlcIp ?? "").Trim();
        var port = request.Port is > 0 and <= 65535 ? request.Port.Value : DefaultPort;
        var timeoutMs = ClampTimeout(request.TimeoutMs);

        if (!PlcReachabilityProbe.TryValidateHost(ip, out var hostError))
        {
            return Unreachable($"Invalid OPC UA PLC host '{ip}': {hostError}");
        }

        var reachable = PlcReachabilityProbe.TryTcpConnect(ip, port, timeoutMs, out var connectDetail);
        if (!reachable)
        {
            return Unreachable($"OPC UA endpoint opc.tcp://{ip}:{port} unreachable ({connectDetail}).");
        }

        // Skeleton safety: TCP port responded, but no unverified synthetic tags are fabricated.
        return Unreachable(
            $"OPC UA TCP endpoint opc.tcp://{ip}:{port} reached, but OPC UA binary node read session is not configured (fail-closed).");
    }

    private PlcDiagnosticsReadResult Unreachable(string message) => new()
    {
        Ok = false,
        ErrorCode = "plc_unreachable",
        Message = message,
        Source = ProviderKind,
        EvidenceLevel = "offline",
    };

    private static int ClampTimeout(int? timeoutMs) =>
        timeoutMs is null ? 800 : Math.Max(100, Math.Min(timeoutMs.Value, 5000));
}

/// <summary>
/// Siemens S7commPlus (ISO-on-TCP port 102) connector skeleton.
/// Fails closed with <c>plc_unreachable</c> when the PLC cannot be reached.
/// </summary>
public sealed class S7CommPlusDiagnosticsProvider : IPlcLiveDiagnosticsProvider
{
    public const int DefaultPort = 102;
    public string ProviderKind => "s7commplus_live";

    public PlcDiagnosticsReadResult ReadSnapshot(CutSetSnapshotRequest request)
    {
        var ip = (request.PlcIp ?? "").Trim();
        var port = request.Port is > 0 and <= 65535 ? request.Port.Value : DefaultPort;
        var timeoutMs = ClampTimeout(request.TimeoutMs);

        if (!PlcReachabilityProbe.TryValidateHost(ip, out var hostError))
        {
            return Unreachable($"Invalid S7commPlus PLC host '{ip}': {hostError}");
        }

        var reachable = PlcReachabilityProbe.TryTcpConnect(ip, port, timeoutMs, out var connectDetail);
        if (!reachable)
        {
            return Unreachable($"S7commPlus endpoint {ip}:{port} unreachable ({connectDetail}).");
        }

        return Unreachable(
            $"S7commPlus TCP endpoint {ip}:{port} reached, but S7commPlus PDU diagnostics session is not configured (fail-closed).");
    }

    private PlcDiagnosticsReadResult Unreachable(string message) => new()
    {
        Ok = false,
        ErrorCode = "plc_unreachable",
        Message = message,
        Source = ProviderKind,
        EvidenceLevel = "offline",
    };

    private static int ClampTimeout(int? timeoutMs) =>
        timeoutMs is null ? 800 : Math.Max(100, Math.Min(timeoutMs.Value, 5000));
}

internal static class PlcReachabilityProbe
{
    public static bool TryValidateHost(string host, out string error)
    {
        if (string.IsNullOrWhiteSpace(host))
        {
            error = "empty host";
            return false;
        }
        if (IPAddress.TryParse(host, out _))
        {
            error = "";
            return true;
        }
        if (Uri.CheckHostName(host) != UriHostNameType.Unknown)
        {
            error = "";
            return true;
        }
        error = "malformed IP or hostname";
        return false;
    }

    public static bool TryTcpConnect(string host, int port, int timeoutMs, out string detail)
    {
        TcpClient? client = null;
        try
        {
            client = new TcpClient();
            var asyncResult = client.BeginConnect(host, port, null, null);
            var signaled = asyncResult.AsyncWaitHandle.WaitOne(timeoutMs);
            if (!signaled)
            {
                detail = $"connect timeout after {timeoutMs}ms";
                return false;
            }
            client.EndConnect(asyncResult);
            detail = "connected";
            return client.Connected;
        }
        catch (Exception ex)
        {
            detail = ex.Message;
            return false;
        }
        finally
        {
            try { client?.Close(); } catch { /* ignore */ }
        }
    }
}

public sealed class PlcDiagnosticsReadResult
{
    public bool Ok { get; set; }
    public string? ErrorCode { get; set; }
    public string? Message { get; set; }
    public string Source { get; set; } = "";
    public string EvidenceLevel { get; set; } = "offline";
    public List<TerminalPinMapping> Terminals { get; set; } = new();
    public Dictionary<string, StationDiagnosticWord> StationDiagnostics { get; set; } =
        new(StringComparer.OrdinalIgnoreCase);
}

public sealed class CutSetFaultInjection
{
    [JsonPropertyName("stationId")]
    public string StationId { get; set; } = "ST20";

    [JsonPropertyName("diagCodeHex")]
    public string DiagCodeHex { get; set; } = "16#0203";

    [JsonPropertyName("address")]
    public string Address { get; set; } = "";

    [JsonPropertyName("value")]
    public bool Value { get; set; }

    [JsonPropertyName("cabinetWireTag")]
    public string? CabinetWireTag { get; set; }

    [JsonPropertyName("blockedStepNo")]
    public int? BlockedStepNo { get; set; }

    [JsonPropertyName("reason")]
    public string? Reason { get; set; }

    [JsonPropertyName("signalName")]
    public string? SignalName { get; set; }
}

public sealed class CutSetSnapshotRequest
{
    [JsonPropertyName("plcIp")]
    public string? PlcIp { get; set; }

    [JsonPropertyName("port")]
    public int? Port { get; set; }

    [JsonPropertyName("protocol")]
    public string? Protocol { get; set; }

    [JsonPropertyName("simulate")]
    public bool? Simulate { get; set; }

    [JsonPropertyName("stationFilter")]
    public string? StationFilter { get; set; }

    [JsonPropertyName("timeoutMs")]
    public int? TimeoutMs { get; set; }

    [JsonPropertyName("healthy")]
    public bool? Healthy { get; set; }

    [JsonPropertyName("resetFault")]
    public bool? ResetFault { get; set; }

    [JsonPropertyName("recoverAddress")]
    public string? RecoverAddress { get; set; }

    [JsonPropertyName("injectFault")]
    public CutSetFaultInjection? InjectFault { get; set; }

    public static CutSetSnapshotRequest FromJson(JsonElement root)
    {
        var req = new CutSetSnapshotRequest
        {
            PlcIp = GetString(root, "plcIp") ?? GetString(root, "plc_ip") ?? GetString(root, "ip"),
            Port = GetInt(root, "port"),
            Protocol = GetString(root, "protocol"),
            Simulate = GetBool(root, "simulate"),
            StationFilter = GetString(root, "stationFilter") ?? GetString(root, "station_filter") ?? GetString(root, "station"),
            TimeoutMs = GetInt(root, "timeoutMs") ?? GetInt(root, "timeout_ms"),
            Healthy = GetBool(root, "healthy"),
            ResetFault = GetBool(root, "resetFault") ?? GetBool(root, "reset_fault"),
            RecoverAddress = GetString(root, "recoverAddress") ?? GetString(root, "recover_address") ?? GetString(root, "recover"),
        };

        if (root.TryGetProperty("injectFault", out var faultEl) && faultEl.ValueKind == JsonValueKind.Object)
        {
            req.InjectFault = new CutSetFaultInjection
            {
                StationId = GetString(faultEl, "stationId") ?? "ST20",
                DiagCodeHex = GetString(faultEl, "diagCodeHex") ?? "16#0203",
                Address = GetString(faultEl, "address") ?? "",
                Value = GetBool(faultEl, "value") ?? false,
                CabinetWireTag = GetString(faultEl, "cabinetWireTag") ?? GetString(faultEl, "wireTag"),
                BlockedStepNo = GetInt(faultEl, "blockedStepNo"),
                Reason = GetString(faultEl, "reason"),
                SignalName = GetString(faultEl, "signalName"),
            };
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
}

public sealed class TerminalPinMapping
{
    [JsonPropertyName("address")]
    public string Address { get; set; } = "";

    [JsonPropertyName("stationId")]
    public string StationId { get; set; } = "";

    [JsonPropertyName("cabinetWireTag")]
    public string CabinetWireTag { get; set; } = "";

    [JsonPropertyName("signalName")]
    public string SignalName { get; set; } = "";

    [JsonPropertyName("value")]
    public bool Value { get; set; }

    [JsonPropertyName("expectedHealthyValue")]
    public bool ExpectedHealthyValue { get; set; } = true;

    [JsonPropertyName("isFaulted")]
    public bool IsFaulted { get; set; }

    public TerminalPinMapping Clone() => new()
    {
        Address = Address,
        StationId = StationId,
        CabinetWireTag = CabinetWireTag,
        SignalName = SignalName,
        Value = Value,
        ExpectedHealthyValue = ExpectedHealthyValue,
        IsFaulted = IsFaulted,
    };
}

public sealed class StationDiagnosticWord
{
    [JsonPropertyName("stationId")]
    public string StationId { get; set; } = "";

    [JsonPropertyName("diagCodeHex")]
    public string DiagCodeHex { get; set; } = "16#0000";

    [JsonPropertyName("diagCodeValue")]
    public int DiagCodeValue { get; set; }

    [JsonPropertyName("isBlocked")]
    public bool IsBlocked { get; set; }

    [JsonPropertyName("blockedStepNo")]
    public int? BlockedStepNo { get; set; }

    [JsonPropertyName("reason")]
    public string Reason { get; set; } = "";

    [JsonPropertyName("faultAddresses")]
    public List<string> FaultAddresses { get; set; } = new();

    public StationDiagnosticWord Clone() => new()
    {
        StationId = StationId,
        DiagCodeHex = DiagCodeHex,
        DiagCodeValue = DiagCodeValue,
        IsBlocked = IsBlocked,
        BlockedStepNo = BlockedStepNo,
        Reason = Reason,
        FaultAddresses = new List<string>(FaultAddresses),
    };
}

public sealed class CutSetSnapshotResult
{
    [JsonPropertyName("ok")]
    public bool Ok { get; set; }

    [JsonPropertyName("errorCode")]
    public string? ErrorCode { get; set; }

    [JsonPropertyName("message")]
    public string? Message { get; set; }

    [JsonPropertyName("source")]
    public string Source { get; set; } = "";

    [JsonPropertyName("evidenceLevel")]
    public string EvidenceLevel { get; set; } = "simulated";

    [JsonPropertyName("plcIp")]
    public string? PlcIp { get; set; }

    [JsonPropertyName("protocol")]
    public string Protocol { get; set; } = "";

    [JsonPropertyName("capturedAtUtc")]
    public string CapturedAtUtc { get; set; } = "";

    [JsonPropertyName("elapsedMilliseconds")]
    public long ElapsedMilliseconds { get; set; }

    [JsonPropertyName("isHealthy")]
    public bool IsHealthy { get; set; }

    [JsonPropertyName("diStates")]
    public Dictionary<string, bool> DiStates { get; set; } = new(StringComparer.OrdinalIgnoreCase);

    [JsonPropertyName("crossStationDiStates")]
    public Dictionary<string, Dictionary<string, bool>> CrossStationDiStates { get; set; } =
        new(StringComparer.OrdinalIgnoreCase);

    [JsonPropertyName("terminalMap")]
    public Dictionary<string, TerminalPinMapping> TerminalMap { get; set; } =
        new(StringComparer.OrdinalIgnoreCase);

    [JsonPropertyName("stationDiagnostics")]
    public Dictionary<string, StationDiagnosticWord> StationDiagnostics { get; set; } =
        new(StringComparer.OrdinalIgnoreCase);

    [JsonPropertyName("blockingDiagWords")]
    public Dictionary<string, string> BlockingDiagWords { get; set; } =
        new(StringComparer.OrdinalIgnoreCase);

    [JsonPropertyName("faultedTerminals")]
    public List<TerminalPinMapping> FaultedTerminals { get; set; } = new();

    [JsonPropertyName("error")]
    public ToolError? Error { get; set; }
}

using System;
using System.Collections.Generic;
using System.IO;
using System.Linq;
using System.Net;
using System.Net.Sockets;
using System.Text;
using System.Text.Json;
using System.Threading;
using TiaOpenness.Models;
using TiaOpenness.Server;

namespace TiaOpenness.Tests;

public sealed class AfStudioV5DaemonTests
{
    private const string AutoSeqV1 = """
        FUNCTION_BLOCK "FB_ST20_AutoSeq"
        { S7_Optimized_Access := 'TRUE' }
        VERSION : 0.1
        VAR_INPUT
            i_bStart : Bool;
            i_bInterlockOK : Bool;
        END_VAR
        VAR_OUTPUT
            q_bDone : Bool;
        END_VAR
        VAR
            statStep : Int;
        END_VAR
        BEGIN
            IF #i_bStart AND #i_bInterlockOK THEN
                #statStep := 10;
            END_IF;
            #q_bDone := (#statStep = 10);
        END_FUNCTION_BLOCK
        """;

    private const string HomeSeqScl = """
        FUNCTION_BLOCK "FB_ST20_HomeSeq"
        VAR_INPUT
            i_bHomeReq : Bool;
        END_VAR
        VAR_OUTPUT
            q_bAtHome : Bool;
        END_VAR
        BEGIN
            #q_bAtHome := #i_bHomeReq;
        END_FUNCTION_BLOCK
        """;

    private const string GuardDiagFcScl = """
        FUNCTION "FC_ST20_GuardDiag" : Word
        VAR_INPUT
            i_bZAtHome : Bool;
        END_VAR
        BEGIN
            IF NOT #i_bZAtHome THEN
                #FC_ST20_GuardDiag := 16#0203;
            ELSE
                #FC_ST20_GuardDiag := 16#0000;
            END_IF;
        END_FUNCTION
        """;

    private const string InstancesDbScl = """
        DATA_BLOCK "DB_ST20_Instances"
        STRUCT
            bReady : Bool;
        END_STRUCT
        BEGIN
            bReady := TRUE;
        END_DATA_BLOCK
        """;

    private static List<MerkleBlockInput> BuildStation20Blocks(string autoSeqScl = AutoSeqV1, string? autoSeqIdb = "IDB_ST20_AutoSeq") =>
        new()
        {
            new()
            {
                BlockName = "FB_ST20_AutoSeq",
                BlockType = "FB",
                SclSource = autoSeqScl,
                InstanceDbName = autoSeqIdb,
            },
            new()
            {
                BlockName = "FB_ST20_HomeSeq",
                BlockType = "FB",
                SclSource = HomeSeqScl,
            },
            new()
            {
                BlockName = "FC_ST20_GuardDiag",
                BlockType = "FC",
                SclSource = GuardDiagFcScl,
            },
            new()
            {
                BlockName = "DB_ST20_Instances",
                BlockType = "DB",
                SclSource = InstancesDbScl,
            },
        };

    [Fact]
    public void MerkleSync_FirstSyncAllDirty_SecondSameSclAllUnchangedZeroExecution()
    {
        var service = new MerkleBlockSyncService();
        var executor = new RecordingMerkleExecutor();

        // 1st sync: all 4 blocks are new -> all DIRTY.
        var req1 = new MerkleSyncRequest
        {
            ProjectKey = "ST20_Line",
            Blocks = BuildStation20Blocks(),
        };
        var res1 = service.SyncDirtyBlocks(req1, executor);

        Assert.True(res1.Ok);
        Assert.True(res1.Executed);
        Assert.True(res1.CompileOk);
        Assert.True(res1.CacheUpdated);
        Assert.Equal(4, res1.TotalBlocks);
        Assert.Equal(4, res1.DirtyCount);
        Assert.Equal(0, res1.UnchangedCount);
        Assert.All(res1.Blocks, b => Assert.Equal("DIRTY", b.Status));
        Assert.Equal(1, executor.CallCount);
        Assert.Equal(4, executor.Batches[0].DirtyBlocks.Count);
        Assert.Equal(4, service.LastSyncedBlockHashes.Count);

        // 2nd sync: same semantics with decorative timestamp comment, CRLF, trailing spaces, extra consecutive blank lines -> 100% UNCHANGED, 0 execution.
        var normalizedAutoSeqForEdit = AutoSeqV1.Replace("\r\n", "\n");
        var decoratedAutoSeq =
            "// Timestamp: 2026-11-18T20:15:30Z\r\n\r\n\r\n" +
            normalizedAutoSeqForEdit.Replace("\n", "   \r\n") +
            "\r\n\r\n// Generated at 2026-11-18 20:15:30\r\n\r\n";
        var decoratedBlocks = BuildStation20Blocks(decoratedAutoSeq);

        var req2 = new MerkleSyncRequest
        {
            ProjectKey = "ST20_Line",
            Blocks = decoratedBlocks,
        };
        var res2 = service.SyncDirtyBlocks(req2, executor);

        Assert.True(res2.Ok);
        Assert.False(res2.Executed);
        Assert.Equal("unchanged_skip", res2.Mode);
        Assert.False(res2.CacheUpdated);
        Assert.Equal(4, res2.TotalBlocks);
        Assert.Equal(0, res2.DirtyCount);
        Assert.Equal(4, res2.UnchangedCount);
        Assert.All(res2.Blocks, b => Assert.Equal("UNCHANGED", b.Status));
        Assert.Equal(1, executor.CallCount);
    }

    [Fact]
    public void MerkleSync_ModifyOnlyAutoSeqBody_SyncsOnlyOneBlock()
    {
        var service = new MerkleBlockSyncService();
        var executor = new RecordingMerkleExecutor();

        var initial = service.SyncDirtyBlocks(new MerkleSyncRequest
        {
            ProjectKey = "ST20_Line",
            Blocks = BuildStation20Blocks(),
        }, executor);
        Assert.True(initial.Ok);
        Assert.Equal(1, executor.CallCount);

        // Modify only executable body of FB_ST20_AutoSeq (VAR_INPUT/VAR_OUTPUT/VAR unchanged).
        var bodyEditedAutoSeq = AutoSeqV1.Replace("#statStep := 10;", "#statStep := 20;");
        var res2 = service.SyncDirtyBlocks(new MerkleSyncRequest
        {
            ProjectKey = "ST20_Line",
            Blocks = BuildStation20Blocks(autoSeqScl: bodyEditedAutoSeq),
        }, executor);

        Assert.True(res2.Ok);
        Assert.True(res2.Executed);
        Assert.False(res2.InterfaceChanged);
        Assert.Equal(4, res2.TotalBlocks);
        Assert.Equal(1, res2.DirtyCount);
        Assert.Equal(3, res2.UnchangedCount);
        Assert.Equal(new[] { "FB_ST20_AutoSeq" }, res2.DirtyBlockNames);
        Assert.Equal(2, executor.CallCount);
        Assert.Single(executor.Batches[1].DirtyBlocks);
        Assert.Equal("FB_ST20_AutoSeq", executor.Batches[1].DirtyBlocks[0].BlockName);
    }

    [Fact]
    public void MerkleSync_ModifyFbVarInput_CascadesInstanceDbRefresh()
    {
        var service = new MerkleBlockSyncService();
        var executor = new RecordingMerkleExecutor();

        var first = service.SyncDirtyBlocks(new MerkleSyncRequest
        {
            ProjectKey = "ST20_Line",
            Blocks = BuildStation20Blocks(),
        }, executor);
        Assert.True(first.Ok);

        // Modify FB_ST20_AutoSeq VAR_INPUT -> InterfaceHash changes -> IDB_ST20_AutoSeq must cascade into DIRTY.
        var interfaceEdited = AutoSeqV1.Replace(
            "i_bInterlockOK : Bool;",
            "i_bInterlockOK : Bool;\n            i_bDoorClosed : Bool;");

        var second = service.SyncDirtyBlocks(new MerkleSyncRequest
        {
            ProjectKey = "ST20_Line",
            Blocks = BuildStation20Blocks(autoSeqScl: interfaceEdited),
        }, executor);

        Assert.True(second.Ok);
        Assert.True(second.Executed);
        Assert.True(second.InterfaceChanged);
        Assert.Equal(2, second.DirtyCount);
        Assert.Equal(3, second.UnchangedCount);
        Assert.Contains("FB_ST20_AutoSeq", second.DirtyBlockNames);
        Assert.Contains("IDB_ST20_AutoSeq", second.DirtyBlockNames);

        var idbBatchEntry = executor.Batches[1].DirtyBlocks.First(b => b.BlockName == "IDB_ST20_AutoSeq");
        Assert.True(idbBatchEntry.AutoGeneratedIdb);
        Assert.Equal("FB_ST20_AutoSeq", idbBatchEntry.SourceBlock);
        Assert.Equal(
            "DATA_BLOCK \"IDB_ST20_AutoSeq\" \"FB_ST20_AutoSeq\" BEGIN END_DATA_BLOCK",
            idbBatchEntry.SclSource);
        Assert.True(idbBatchEntry.Reason.IndexOf("接口时间戳刷新", StringComparison.Ordinal) >= 0);

        var idbStatus = second.Blocks.First(b => b.BlockName == "IDB_ST20_AutoSeq");
        Assert.Equal("DIRTY", idbStatus.Status);
        Assert.True(idbStatus.InterfaceChanged);
        Assert.True(idbStatus.Reason.IndexOf("接口时间戳刷新", StringComparison.Ordinal) >= 0);
    }

    [Fact]
    public void MerkleSync_ModifyFbVarInput_PromotesExistingUnchangedIdbInBatch()
    {
        var service = new MerkleBlockSyncService();
        var executor = new RecordingMerkleExecutor();
        const string idbScl = "DATA_BLOCK \"IDB_ST20_AutoSeq\" \"FB_ST20_AutoSeq\" BEGIN END_DATA_BLOCK";

        var blocks1 = BuildStation20Blocks();
        blocks1.Add(new MerkleBlockInput { BlockName = "IDB_ST20_AutoSeq", BlockType = "DB", SclSource = idbScl });
        Assert.True(service.SyncDirtyBlocks(new MerkleSyncRequest { ProjectKey = "P1", Blocks = blocks1 }, executor).Ok);

        var interfaceEdited = AutoSeqV1.Replace("i_bStart : Bool;", "i_bStart : Bool;\n            i_bSafetyGate : Bool;");
        var blocks2 = BuildStation20Blocks(autoSeqScl: interfaceEdited);
        blocks2.Add(new MerkleBlockInput { BlockName = "IDB_ST20_AutoSeq", BlockType = "DB", SclSource = idbScl });

        var res2 = service.SyncDirtyBlocks(new MerkleSyncRequest { ProjectKey = "P1", Blocks = blocks2 }, executor);

        Assert.True(res2.Ok);
        Assert.True(res2.InterfaceChanged);
        Assert.Equal(2, res2.DirtyCount);
        Assert.Contains("FB_ST20_AutoSeq", res2.DirtyBlockNames);
        Assert.Contains("IDB_ST20_AutoSeq", res2.DirtyBlockNames);
        var idbStatus = res2.Blocks.Single(b => b.BlockName == "IDB_ST20_AutoSeq");
        Assert.Equal("DIRTY", idbStatus.Status);
        Assert.True(idbStatus.Reason.IndexOf("接口时间戳刷新", StringComparison.Ordinal) >= 0);
    }

    [Fact]
    public void MerkleSync_CompileFailure_FailClosed_DoesNotUpdateCache()
    {
        var service = new MerkleBlockSyncService();
        var failingExecutor = new RecordingMerkleExecutor { ShouldCompileSucceed = false };

        var req = new MerkleSyncRequest
        {
            ProjectKey = "ST20_FailTest",
            Blocks = BuildStation20Blocks(),
        };
        var failed = service.SyncDirtyBlocks(req, failingExecutor);

        Assert.False(failed.Ok);
        Assert.False(failed.CompileOk);
        Assert.False(failed.CacheUpdated);
        Assert.True(failed.Executed);
        Assert.Empty(service.LastSyncedBlockHashes);
        Assert.All(failed.Blocks, b => Assert.Equal("failed", b.Action));

        // Next attempt with fixed compiler still sees all 4 blocks as DIRTY and caches them upon success.
        var passingExecutor = new RecordingMerkleExecutor { ShouldCompileSucceed = true };
        var retried = service.SyncDirtyBlocks(req, passingExecutor);

        Assert.True(retried.Ok);
        Assert.True(retried.CompileOk);
        Assert.True(retried.CacheUpdated);
        Assert.Equal(4, retried.DirtyCount);
        Assert.Equal(4, service.LastSyncedBlockHashes.Count);
    }

    [Fact]
    public void MerkleSync_DryRunAndNoOpenProject_ReturnsHonestOfflineDiff()
    {
        using var conn = new TiaConnection("V19");
        var projects = new ProjectService(conn);
        var blocks = new BlockService(projects);
        var service = new MerkleBlockSyncService(projects, blocks);
        var executor = new RecordingMerkleExecutor();

        // No open TIA project and no custom executor -> honest offline dry_run.
        var offline = service.SyncDirtyBlocks(new MerkleSyncRequest
        {
            ProjectKey = "OfflineProject",
            DryRun = false,
            Blocks = BuildStation20Blocks(),
        });

        Assert.True(offline.Ok);
        Assert.False(offline.Executed);
        Assert.False(offline.CacheUpdated);
        Assert.Equal("offline", offline.EvidenceLevel);
        Assert.Equal("dry_run", offline.Mode);
        Assert.Equal(4, offline.DirtyCount);
        Assert.Empty(service.LastSyncedBlockHashes);

        // Explicit dryRun: true even with custom executor -> never invokes executor or updates cache.
        var dryRun = service.SyncDirtyBlocks(new MerkleSyncRequest
        {
            ProjectKey = "OfflineProject",
            DryRun = true,
            Blocks = BuildStation20Blocks(),
        }, executor);

        Assert.True(dryRun.Ok);
        Assert.False(dryRun.Executed);
        Assert.False(dryRun.CacheUpdated);
        Assert.Equal("offline", dryRun.EvidenceLevel);
        Assert.Equal("dry_run", dryRun.Mode);
        Assert.Equal(0, executor.CallCount);
        Assert.Empty(service.LastSyncedBlockHashes);
    }

    [Fact]
    public void MerkleSync_OpennessStaExecutor_FailsClosedWhenProjectNotOpen()
    {
        using var conn = new TiaConnection("V19");
        var projects = new ProjectService(conn);
        var blocks = new BlockService(projects);
        var staExecutor = new OpennessStaMerkleExecutor(projects, blocks);

        var execResult = staExecutor.ExecuteSync(new MerkleExecutorBatch
        {
            ProjectKey = "Closed",
            DirtyBlocks = new List<MerkleDirtyBlock>
            {
                new() { BlockName = "FB_ST20_AutoSeq", BlockType = "FB", SclSource = AutoSeqV1 },
            },
        });

        Assert.False(execResult.Ok);
        Assert.False(execResult.CompileOk);
        Assert.Equal("no_project_open", execResult.Error?.Code);
    }

    [Fact]
    public void AfLibraryReflector_NoPortalNoDir_FallsBackToBuiltinAfStandard()
    {
        var reflector = new AfLibraryReflector();
        var payload = reflector.ReflectRegistry();

        Assert.True(payload.Ok);
        Assert.Equal("builtin_af_standard", payload.Source);
        Assert.Equal("offline", payload.EvidenceLevel);

        var names = payload.Classes.Select(c => c.DriverClass).ToList();
        Assert.Contains("FB_AF_AxisMotion", names);
        Assert.Contains("FB_AF_Actuator2Pos", names);
        Assert.Contains("FB_AF_Gripper", names);
        Assert.Contains("FB_AF_VisionSensor", names);

        foreach (var cls in payload.Classes)
        {
            Assert.NotEmpty(cls.DefaultStates);
            Assert.NotEmpty(cls.InPorts);
            Assert.NotEmpty(cls.OutPorts);
            Assert.NotEmpty(cls.RadialMethods);
        }

        var json = JsonSerializer.Serialize(payload, JsonDefaults.Options);
        using var doc = JsonDocument.Parse(json);
        Assert.Equal("builtin_af_standard", doc.RootElement.GetProperty("source").GetString());
        var first = doc.RootElement.GetProperty("classes")[0];
        Assert.True(first.TryGetProperty("driverClass", out _));
        Assert.True(first.TryGetProperty("defaultStates", out _));
        Assert.True(first.TryGetProperty("inPorts", out _));
        Assert.True(first.TryGetProperty("outPorts", out _));
        Assert.True(first.TryGetProperty("radialMethods", out _));
    }

    [Fact]
    public void AfLibraryReflector_OfflineSclAndXmlDirectory_ParsesInterfaces()
    {
        var tempDir = Path.Combine(Path.GetTempPath(), "af_lib_reflect_test_" + Guid.NewGuid().ToString("N"));
        Directory.CreateDirectory(tempDir);
        try
        {
            File.WriteAllText(Path.Combine(tempDir, "FB_AF_AxisMotion.scl"), """
                FUNCTION_BLOCK "FB_AF_AxisMotion"
                VAR_INPUT
                    i_bExecute : Bool;
                    i_bInterlockOK : Bool;
                    i_rTargetPos : Real;
                END_VAR
                VAR_OUTPUT
                    q_bDone : Bool;
                    q_bAtHome : Bool;
                END_VAR
                BEGIN
                    #q_bDone := #i_bExecute AND #i_bInterlockOK;
                END_FUNCTION_BLOCK
                """);

            File.WriteAllText(Path.Combine(tempDir, "FB_AF_Conveyor.xml"), """
                <?xml version="1.0" encoding="utf-8"?>
                <Document>
                  <SW.Blocks.FB ID="0">
                    <AttributeList>
                      <Name>FB_AF_Conveyor</Name>
                      <Interface>
                        <Sections xmlns="http://www.siemens.com/automation/Openness/SW/Interface/v5">
                          <Section Name="Input">
                            <Member Name="i_bRunFwd" Datatype="Bool" />
                            <Member Name="i_bGuardOk" Datatype="Bool" />
                          </Section>
                          <Section Name="Output">
                            <Member Name="q_bRunning" Datatype="Bool" />
                          </Section>
                        </Sections>
                      </Interface>
                    </AttributeList>
                  </SW.Blocks.FB>
                </Document>
                """);

            var reflector = new AfLibraryReflector();
            var payload = reflector.ReflectRegistry(new AfLibraryReflectRequest { LibraryDirectory = tempDir });

            Assert.True(payload.Ok);
            Assert.Equal("offline_scl_xml_directory", payload.Source);
            Assert.Equal("offline_library", payload.EvidenceLevel);
            Assert.Equal(2, payload.Classes.Count);

            var axis = payload.Classes.Single(c => c.DriverClass == "FB_AF_AxisMotion");
            Assert.Equal(3, axis.InPorts.Count);
            Assert.Contains(axis.InPorts, p => p.PinName == "i_bInterlockOK" && p.Type == "GUARD");
            Assert.Equal(2, axis.OutPorts.Count);
            Assert.Contains(axis.OutPorts, p => p.PinName == "q_bAtHome" && p.Type == "GUARD");

            var conv = payload.Classes.Single(c => c.DriverClass == "FB_AF_Conveyor");
            Assert.Contains(conv.InPorts, p => p.PinName == "i_bRunFwd");
            Assert.Contains(conv.InPorts, p => p.PinName == "i_bGuardOk" && p.Type == "GUARD");
            Assert.Contains(conv.OutPorts, p => p.PinName == "q_bRunning");

            // Missing explicit directory must fail closed.
            var missing = reflector.ReflectRegistry(new AfLibraryReflectRequest
            {
                LibraryDirectory = Path.Combine(tempDir, "does_not_exist"),
            });
            Assert.False(missing.Ok);
            Assert.Equal("not_found", missing.Error?.Code);
        }
        finally
        {
            if (Directory.Exists(tempDir)) Directory.Delete(tempDir, recursive: true);
        }
    }

    [Fact]
    public void AfLibraryReflector_MockTiaLibraries_ReflectsMasterCopiesAndTypes()
    {
        var mockPortal = new FakePortal
        {
            GlobalLibraries = new object[]
            {
                new FakeLibrary
                {
                    Name = "AF_Standard_Global",
                    MasterCopyFolder = new FakeLibraryFolder
                    {
                        MasterCopies = new object[]
                        {
                            new FakeLibraryItem
                            {
                                Name = "FB_AF_RotaryTable",
                                SclSource = """
                                    FUNCTION_BLOCK "FB_AF_RotaryTable"
                                    VAR_INPUT
                                        i_bIndexCmd : Bool;
                                        i_bInterlockOK : Bool;
                                    END_VAR
                                    VAR_OUTPUT
                                        q_bAtIndex : Bool;
                                    END_VAR
                                    BEGIN
                                    END_FUNCTION_BLOCK
                                    """,
                            },
                        },
                    },
                },
            },
        };

        var mockProject = new FakeProject
        {
            ProjectLibrary = new FakeLibrary
            {
                Name = "ProjectLibrary",
                TypeFolder = new FakeLibraryFolder
                {
                    Types = new object[]
                    {
                        new FakeLibraryType
                        {
                            Name = "FB_AF_Gripper",
                            Versions = new object[]
                            {
                                new FakeLibraryItem
                                {
                                    Name = "FB_AF_Gripper",
                                    Parameters = new[]
                                    {
                                        new FakePin { Name = "i_bClampCmd", Section = "VAR_INPUT", DataType = "Bool" },
                                        new FakePin { Name = "q_bClamped", Section = "VAR_OUTPUT", DataType = "Bool" },
                                    },
                                },
                            },
                        },
                    },
                },
            },
        };

        var reflector = new AfLibraryReflector();
        var payload = reflector.ReflectFromLiveObjects(mockPortal, mockProject, plcSoftware: null);

        Assert.True(payload.Ok);
        Assert.Equal("tia_openness_library", payload.Source);
        Assert.Equal("tia_live", payload.EvidenceLevel);
        Assert.Contains(payload.Classes, c => c.DriverClass == "FB_AF_RotaryTable");
        Assert.Contains(payload.Classes, c => c.DriverClass == "FB_AF_Gripper");
    }

    [Fact]
    public void CutSetSnapshot_SimulatedFaultAndRecovery_ReturnsExpectedCutSetDiagnostics()
    {
        var service = new CutSetSnapshotService();

        // 1) Default simulated fault snapshot: ST20 blocked 16#0203, %I10.0=true, ST10 %I0.4=false (X12:04).
        var faulted = service.CaptureCutSetSnapshot(new CutSetSnapshotRequest { Simulate = true });

        Assert.True(faulted.Ok);
        Assert.False(faulted.IsHealthy);
        Assert.Equal("simulated_plc_diagnostics", faulted.Source);
        Assert.True(faulted.DiStates["%I10.0"]);
        Assert.False(faulted.DiStates["%I0.4"]);
        Assert.True(faulted.CrossStationDiStates["ST20"]["%I10.0"]);
        Assert.False(faulted.CrossStationDiStates["ST10"]["%I0.4"]);
        Assert.Equal("X12:04", faulted.TerminalMap["%I0.4"].CabinetWireTag);
        Assert.Equal("16#0203", faulted.StationDiagnostics["ST20"].DiagCodeHex);
        Assert.Equal("16#0203", faulted.BlockingDiagWords["ST20"]);
        Assert.Contains(faulted.FaultedTerminals, t => t.Address == "%I0.4" && t.CabinetWireTag == "X12:04");

        // 2) Recover %I0.4 on ST10 -> healthy snapshot, ST20 diag cleared.
        service.SimulatedProvider.RecoverFault("ST10", "%I0.4", healthyValue: true);
        var recovered = service.CaptureCutSetSnapshot(new CutSetSnapshotRequest { Simulate = true });

        Assert.True(recovered.Ok);
        Assert.True(recovered.IsHealthy);
        Assert.True(recovered.DiStates["%I10.0"]);
        Assert.True(recovered.DiStates["%I0.4"]);
        Assert.Equal("16#0000", recovered.StationDiagnostics["ST20"].DiagCodeHex);
        Assert.False(recovered.StationDiagnostics["ST20"].IsBlocked);
        Assert.Empty(recovered.BlockingDiagWords);
        Assert.Empty(recovered.FaultedTerminals);
    }

    [Fact]
    public void CutSetSnapshot_UnreachableRealPlc_FailsClosedWithPlcUnreachable()
    {
        var closedPort = GetClosedLoopbackPort();
        var service = new CutSetSnapshotService();

        var opcuaResult = service.CaptureCutSetSnapshot(new CutSetSnapshotRequest
        {
            PlcIp = "127.0.0.1",
            Port = closedPort,
            Protocol = "opcua",
            Simulate = false,
            TimeoutMs = 250,
        });

        Assert.False(opcuaResult.Ok);
        Assert.Equal("plc_unreachable", opcuaResult.ErrorCode);
        Assert.Equal("plc_unreachable", opcuaResult.Error?.Code);

        // Even when Simulate is omitted (null), providing a real plcIp must attempt live connection and fail closed.
        var s7Result = service.CaptureCutSetSnapshot(new CutSetSnapshotRequest
        {
            PlcIp = "127.0.0.1",
            Port = closedPort,
            Protocol = "s7commplus",
            Simulate = null,
            TimeoutMs = 250,
        });

        Assert.False(s7Result.Ok);
        Assert.Equal("plc_unreachable", s7Result.ErrorCode);
    }

    [Fact]
    public void SessionServer_StaRoutes_MerkleSync_ReflectAfLibrary_CutSetSnapshot()
    {
        var freePort = GetClosedLoopbackPort();
        using var server = new SessionServer("127.0.0.1", freePort, token: null);
        server.StartStaLoopForTests();

        // /merkle-sync (offline dry_run via STA dispatcher) + verify consecutive blank line collapsing & (* Timestamp *) comment normalization
        var sclWithExtraBlanks = "(* Timestamp: 2026-11-18T12:00:00Z *)\nBEGIN\n\n\n    #a := 1;\nEND";
        var sclClean = "BEGIN\n\n    #a := 1;\nEND";
        var (h1, s1, _) = MerkleBlockSyncService.ComputeHashes(sclWithExtraBlanks);
        var (h2, s2, _) = MerkleBlockSyncService.ComputeHashes(sclClean);
        Assert.Equal(8, h1.Length);
        Assert.Equal(64, s1.Length);
        Assert.Equal(h2, h1);
        Assert.Equal(s2, s1);

        using (var doc = JsonDocument.Parse(JsonSerializer.Serialize(new
               {
                   projectKey = "SessionTest",
                   blocks = new[]
                   {
                       new { blockName = "FB_ST20_AutoSeq", blockType = "FB", sclSource = AutoSeqV1 },
                   },
               }, JsonDefaults.Options)))
        {
            var payload = server.DispatchStaRoute("/merkle-sync", doc.RootElement);
            var json = JsonSerializer.Serialize(payload, JsonDefaults.Options);
            using var parsed = JsonDocument.Parse(json);
            Assert.True(parsed.RootElement.GetProperty("ok").GetBoolean());
            Assert.Equal("dry_run", parsed.RootElement.GetProperty("mode").GetString());
            Assert.Equal("offline", parsed.RootElement.GetProperty("evidenceLevel").GetString());
            Assert.Equal(1, parsed.RootElement.GetProperty("dirtyCount").GetInt32());
        }

        // /reflect-af-library
        using (var emptyDoc = JsonDocument.Parse("{}"))
        {
            var payload = server.DispatchStaRoute("/reflect-af-library", emptyDoc.RootElement);
            var json = JsonSerializer.Serialize(payload, JsonDefaults.Options);
            using var parsed = JsonDocument.Parse(json);
            Assert.True(parsed.RootElement.GetProperty("ok").GetBoolean());
            Assert.Equal("builtin_af_standard", parsed.RootElement.GetProperty("source").GetString());
        }

        // /cutset-snapshot (unreachable real IP fail-closed + simulated)
        var closedPort = GetClosedLoopbackPort();
        using (var snapDoc = JsonDocument.Parse(JsonSerializer.Serialize(new
               {
                   plcIp = "127.0.0.1",
                   port = closedPort,
                   simulate = false,
                   timeoutMs = 200,
               }, JsonDefaults.Options)))
        {
            var payload = server.DispatchStaRoute("/cutset-snapshot", snapDoc.RootElement);
            var json = JsonSerializer.Serialize(payload, JsonDefaults.Options);
            using var parsed = JsonDocument.Parse(json);
            Assert.False(parsed.RootElement.GetProperty("ok").GetBoolean());
            Assert.Equal("plc_unreachable", parsed.RootElement.GetProperty("errorCode").GetString());
        }
    }

    [Fact]
    public void ProgramCli_AfStudioV5Commands_ReturnExpectedExitCodesAndJson()
    {
        var tempDir = Path.Combine(Path.GetTempPath(), "af_cli_test_" + Guid.NewGuid().ToString("N"));
        Directory.CreateDirectory(tempDir);
        try
        {
            var outReg = Path.Combine(tempDir, "motherClassRegistry.json");
            var rcLib = Program.RunCli(new[] { "reflect-af-library", "--out", outReg });
            Assert.Equal(0, rcLib);
            Assert.True(File.Exists(outReg));
            using (var regDoc = JsonDocument.Parse(File.ReadAllText(outReg)))
            {
                Assert.Equal("builtin_af_standard", regDoc.RootElement.GetProperty("source").GetString());
            }

            var sclPath = Path.Combine(tempDir, "FB_ST20_AutoSeq.scl");
            File.WriteAllText(sclPath, AutoSeqV1, new UTF8Encoding(encoderShouldEmitUTF8Identifier: true));
            var rcMerkle = Program.RunCli(new[] { "merkle-sync", "--scl", sclPath, "--dry-run" });
            Assert.Equal(0, rcMerkle);

            var rcSimSnap = Program.RunCli(new[] { "cutset-snapshot", "--simulate" });
            Assert.Equal(0, rcSimSnap);

            var closedPort = GetClosedLoopbackPort();
            var rcFailSnap = Program.RunCli(new[]
            {
                "cutset-snapshot",
                "--plc-ip", "127.0.0.1",
                "--port", closedPort.ToString(),
                "--no-simulate",
                "--timeout-ms", "200",
            });
            Assert.Equal(4, rcFailSnap);
        }
        finally
        {
            if (Directory.Exists(tempDir)) Directory.Delete(tempDir, recursive: true);
        }
    }

    private static int GetClosedLoopbackPort()
    {
        var listener = new TcpListener(IPAddress.Loopback, 0);
        listener.Start();
        var port = ((IPEndPoint)listener.LocalEndpoint).Port;
        listener.Stop();
        return port;
    }

    private sealed class RecordingMerkleExecutor : IMerkleBlockExecutor
    {
        public int CallCount { get; private set; }
        public bool ShouldCompileSucceed { get; set; } = true;
        public List<MerkleExecutorBatch> Batches { get; } = new();

        public MerkleExecutionResult ExecuteSync(MerkleExecutorBatch batch)
        {
            CallCount++;
            Batches.Add(batch);

            var result = new MerkleExecutionResult
            {
                Ok = ShouldCompileSucceed,
                CompileOk = ShouldCompileSucceed,
                Mode = "mock_sta_executor",
                EvidenceLevel = "mock_executor",
                GeneratedNames = batch.DirtyBlocks.Select(b => b.BlockName).ToList(),
            };

            foreach (var dirty in batch.DirtyBlocks)
            {
                result.BlockStatuses[dirty.BlockName] = new MerkleBlockExecutionOutcome
                {
                    Generated = true,
                    CompileOk = ShouldCompileSucceed,
                    State = ShouldCompileSucceed ? "Success" : "Error",
                    ErrorCount = ShouldCompileSucceed ? 0 : 1,
                    Error = ShouldCompileSucceed ? null : $"Simulated compile failure for {dirty.BlockName}",
                };
                if (!ShouldCompileSucceed)
                {
                    result.Errors.Add($"Simulated compile failure for {dirty.BlockName}");
                }
            }

            if (!ShouldCompileSucceed)
            {
                result.Error = new ToolError
                {
                    Code = "block_compile_failed",
                    Message = "Simulated compile failure.",
                };
            }

            return result;
        }
    }

    private sealed class FakePortal
    {
        public object[] GlobalLibraries { get; set; } = Array.Empty<object>();
    }

    private sealed class FakeProject
    {
        public FakeLibrary? ProjectLibrary { get; set; }
    }

    private sealed class FakeLibrary
    {
        public string Name { get; set; } = "";
        public FakeLibraryFolder? MasterCopyFolder { get; set; }
        public FakeLibraryFolder? TypeFolder { get; set; }
    }

    private sealed class FakeLibraryFolder
    {
        public string Name { get; set; } = "Folder";
        public object[] MasterCopies { get; set; } = Array.Empty<object>();
        public object[] Types { get; set; } = Array.Empty<object>();
        public object[] Folders { get; set; } = Array.Empty<object>();
    }

    private sealed class FakeLibraryItem
    {
        public string Name { get; set; } = "";
        public string? SclSource { get; set; }
        public FakePin[]? Parameters { get; set; }
    }

    private sealed class FakeLibraryType
    {
        public string Name { get; set; } = "";
        public object[] Versions { get; set; } = Array.Empty<object>();
    }

    private sealed class FakePin
    {
        public string Name { get; set; } = "";
        public string Section { get; set; } = "VAR_INPUT";
        public string DataType { get; set; } = "Bool";
    }
}

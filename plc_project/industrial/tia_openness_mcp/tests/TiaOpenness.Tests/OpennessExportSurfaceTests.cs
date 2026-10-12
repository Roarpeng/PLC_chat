using TiaOpenness.Server;

namespace TiaOpenness.Tests;

public class OpennessExportSurfaceTests
{
    [Theory]
    [InlineData("Siemens.Engineering.SW.Blocks.PlcBlock", "OB1", "blocks")]
    [InlineData("OrganizationBlock", "Main", "blocks")]
    [InlineData("FunctionBlock", "FB_Motor", "blocks")]
    [InlineData("GlobalDB", "DB_Data", "blocks")]
    [InlineData("InstanceDB", "FB_Motor_DB", "blocks")]
    [InlineData("ArrayDB", "DB_Array", "blocks")]
    [InlineData("Siemens.Engineering.SW.Types.PlcType", "UDT_Motor", "types")]
    [InlineData("PlcStruct", "TypeTable", "types")]
    [InlineData("TagTable", "Default tag table", "tags")]
    [InlineData("PlcTagTable", "Constants", "tags")]
    [InlineData("PlcWatchTable", "Watch_Main", "watch")]
    [InlineData("WatchTable", "W1", "watch")]
    [InlineData("PlcForceTable", "Force_Main", "force")]
    [InlineData("TechnologicalObject", "TO_Axis", "to")]
    [InlineData("TO_PositioningAxis", "Axis_1", "to")]
    [InlineData("PlcAlarmTextList", "Alarms", "alarms")]
    [InlineData("ProDiagSupervision", "Motor", "alarms")]
    [InlineData("CfcChart", "Chart1", "cfc")]
    [InlineData("SafetyUnit", "F-Runtime", "safety")]
    [InlineData("FailsafePlc", "F-CPU", "safety")]
    [InlineData("OpcUaServerInterface", "UA", "opcua")]
    [InlineData("HmiScreen", "Screen_1", "hmi")]
    [InlineData("HmiUnified", "HMI_1", "hmi")]
    public void MapExportCategory_Matches_Chapter6_Types(string clr, string name, string expected)
    {
        Assert.Equal(expected, OpennessExport.MapExportCategory(clr, name));
    }

    [Theory]
    [InlineData("Necessary license 'STEP 7 Basic' is missing", "no_license")]
    [InlineData("The object is inconsistent", "inconsistent")]
    [InlineData("IsConsistent=false", "inconsistent")]
    [InlineData("Know-how protection is active", "know_how")]
    [InlineData("KnowHowProtected block cannot export body", "know_how")]
    [InlineData("Chart is password protected", "password_protected")]
    [InlineData("Safety login required", "safety_login")]
    [InlineData("Import method not found", "no_import")]
    [InlineData("Export method not found", "no_export")]
    [InlineData("unexpected Siemens error", "openness_error")]
    public void ClassifySkipReason_Maps_Official_Vocabulary(string message, string expected)
    {
        Assert.Equal(expected, OpennessExport.ClassifySkipReason(message));
    }

    [Fact]
    public void ClassifySkipReason_NoExport_When_Item_Lacks_Export_Method()
    {
        Assert.Equal("no_export", OpennessExport.ClassifySkipReason("cannot export", new FakeWatchTable { Name = "W1" }));
    }

    [Fact]
    public void WalkGroups_Recurses_Nested_User_Groups()
    {
        var nested = new FakeGroup
        {
            Name = "Helpers",
            Blocks = { new FakeBlock { Name = "FC_Helper" } },
        };
        var root = new FakeGroup
        {
            Name = "Program blocks",
            Blocks = { new FakeBlock { Name = "OB1" }, new FakeBlock { Name = "FB_Motor" } },
            Groups = { nested },
        };

        var walked = OpennessExport.WalkGroups(root, new[] { "Blocks" }).ToList();
        var names = walked.Select(t => t.Relative).ToList();
        Assert.Contains("OB1", names);
        Assert.Contains("FB_Motor", names);
        Assert.Contains("Helpers/FC_Helper", names);
        Assert.Equal(3, names.Count);
    }

    [Fact]
    public void FolderForCategory_Matches_Export_Layout()
    {
        Assert.Equal("blocks", OpennessExport.FolderForCategory(OpennessExport.CatBlocks));
        Assert.Equal("types", OpennessExport.FolderForCategory(OpennessExport.CatTypes));
        Assert.Equal("watch", OpennessExport.FolderForCategory(OpennessExport.CatWatch));
        Assert.Equal("hardware", OpennessExport.FolderForCategory(OpennessExport.CatHardware));
        Assert.Equal("hmi", OpennessExport.FolderForCategory(OpennessExport.CatHmi));
    }

    [Fact]
    public void LooksFailsafe_Reads_TypeIdentifier_And_Flags()
    {
        Assert.True(OpennessExport.LooksFailsafe(new FakeHw { TypeIdentifier = "OrderNumber:6ES7 515-2AM02 F-CPU" }));
        Assert.True(OpennessExport.LooksFailsafe(new FakeHw { IsFailsafe = true, Name = "CPU" }));
        Assert.True(OpennessExport.LooksFailsafe(new FakeHw { Name = "F-Runtime" }));
        Assert.False(OpennessExport.LooksFailsafe(new FakeHw { Name = "PLC_1", TypeIdentifier = "CPU 1516" }));
    }

    [Fact]
    public void OfficialCategories_Cover_Chapter6_Surface()
    {
        var expected = new[]
        {
            "blocks", "types", "tags", "watch", "force", "to", "alarms",
            "cfc", "safety", "hardware", "hmi", "opcua", "project",
        };
        Assert.Equal(expected, OpennessExport.OfficialCategories);
    }

    private sealed class FakeBlock
    {
        public string Name { get; set; } = "";
    }

    private sealed class FakeGroup
    {
        public string Name { get; set; } = "";
        public List<FakeBlock> Blocks { get; } = new();
        public List<FakeGroup> Groups { get; } = new();
    }

    private sealed class FakeWatchTable
    {
        public string Name { get; set; } = "";
    }

    private sealed class FakeHw
    {
        public string Name { get; set; } = "";
        public string TypeIdentifier { get; set; } = "";
        public bool IsFailsafe { get; set; }
    }
}

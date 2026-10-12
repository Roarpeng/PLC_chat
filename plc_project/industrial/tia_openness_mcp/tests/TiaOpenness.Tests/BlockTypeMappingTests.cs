using TiaOpenness.Models;
using TiaOpenness.Server;

namespace TiaOpenness.Tests;

public class BlockTypeMappingTests
{
    [Theory]
    [InlineData("OB", "OB1", "OB")]
    [InlineData("OrganizationBlock", "Main", "OB")]
    [InlineData("FB", "FB_Motor", "FB")]
    [InlineData("FunctionBlock", "Motor", "FB")]
    [InlineData("FC", "FC10", "FC")]
    [InlineData("FC", "Helpers", "FC")]
    [InlineData("GlobalDB", "DB_Data", "DB")]
    [InlineData("InstanceDB", "FB_Motor_DB", "DB")]
    [InlineData("ArrayDB", "DB_Array", "DB")]
    [InlineData("UnknownThing", "X", "OTHER")]
    public void MapBlockType_Classifies_Openness_Types(string clr, string name, string expected)
    {
        Assert.Equal(expected, BlockService.MapBlockType(clr, name));
    }

    [Fact]
    public void MapBlockType_ObNameHeuristic()
    {
        Assert.Equal("OB", BlockService.MapBlockType("SomethingElse", "OB100"));
    }

    [Theory]
    [InlineData("OB", 0)]
    [InlineData("FB", 1)]
    [InlineData("FC", 1)]
    [InlineData("DB", 2)]
    [InlineData("OTHER", 3)]
    public void ExportRank_Orders_ObThenFbFcThenDb(string type, int rank)
    {
        Assert.Equal(rank, BlockService.ExportRank(type));
    }

    [Fact]
    public void IsKnowHowProtected_ReadsBoolProperty()
    {
        Assert.True(BlockService.IsKnowHowProtected(new FakeKnowHowBlock { IsKnowHowProtected = true }));
        Assert.False(BlockService.IsKnowHowProtected(new FakeKnowHowBlock { IsKnowHowProtected = false }));
        Assert.False(BlockService.IsKnowHowProtected(new object()));
    }

    private sealed class FakeKnowHowBlock
    {
        public bool IsKnowHowProtected { get; set; }
    }
}

public class TiaStatusTests
{
    [Fact]
    public void GetStatus_Reports_Openness_Dll_When_V19_Installed()
    {
        using var connection = new TiaConnection("V19");
        var status = connection.GetStatus();

        Assert.True(status.Ok);
        Assert.Equal("V19", status.TiaVersion);
        // This machine has Portal V19 PublicAPI; keep assertion soft if missing.
        if (status.OpennessAvailable)
        {
            Assert.False(string.IsNullOrWhiteSpace(status.EngineeringDll));
            Assert.True(File.Exists(status.EngineeringDll));
        }
    }

    [Fact]
    public void OpenProject_Rejects_Missing_File()
    {
        using var connection = new TiaConnection("V19");
        var projects = new ProjectService(connection);
        var result = projects.OpenProject(@"C:\does\not\exist\Line.ap19");

        Assert.False(result.Ok);
        Assert.Equal("not_found", result.Error?.Code);
    }

    [Fact]
    public void ListBlocks_Requires_Open_Project()
    {
        using var connection = new TiaConnection("V19");
        var projects = new ProjectService(connection);
        var blocks = new BlockService(projects);
        var result = blocks.ListBlocks();

        Assert.False(result.Ok);
        Assert.Equal("invalid_argument", result.Error?.Code);
    }

    [Fact]
    public void ImportBlock_Requires_Open_Project()
    {
        using var connection = new TiaConnection("V19");
        var projects = new ProjectService(connection);
        var blocks = new BlockService(projects);
        var result = blocks.ImportBlock(@"C:\temp\block.xml");

        Assert.False(result.Ok);
        Assert.Equal("invalid_argument", result.Error?.Code);
    }

    [Theory]
    [InlineData("F-FB_EStop", true)]
    [InlineData("F_FC_Door", true)]
    [InlineData("FOB_Safety", true)]
    [InlineData("FB_Motor", false)]
    [InlineData("FC_Hold", false)]
    public void LooksLikeSafetyName_Classifies_F_Blocks(string name, bool expected)
    {
        Assert.Equal(expected, BlockService.LooksLikeSafetyName(name));
    }

    [Fact]
    public void SclLooksLikeSafety_Detects_F_FunctionBlock()
    {
        Assert.True(BlockService.SclLooksLikeSafety("FUNCTION_BLOCK \"F-FB_EStop\"\nBEGIN\nEND_FUNCTION_BLOCK"));
        Assert.True(BlockService.SclLooksLikeSafety("F-FUNCTION \"F_FC_Door\" : Void"));
        Assert.False(BlockService.SclLooksLikeSafety("FUNCTION_BLOCK \"FB_Motor\"\nBEGIN\nEND_FUNCTION_BLOCK"));
    }

    [Fact]
    public void GenerateBlocksFromSource_Refuses_Safety_Scl_Without_Portal()
    {
        var tmp = Path.Combine(Path.GetTempPath(), "researchos-f-block-" + Guid.NewGuid().ToString("N") + ".scl");
        File.WriteAllText(tmp, "FUNCTION_BLOCK \"F-FB_EStop\"\nBEGIN\nEND_FUNCTION_BLOCK\n");
        try
        {
            using var connection = new TiaConnection("V19");
            var projects = new ProjectService(connection);
            var blocks = new BlockService(projects);
            var result = blocks.GenerateBlocksFromSource(tmp);
            Assert.False(result.Ok);
            Assert.Equal("safety_block", result.Error?.Code);
        }
        finally
        {
            if (File.Exists(tmp)) File.Delete(tmp);
        }
    }

    [Fact]
    public void GenerateBlocksFromSource_Requires_Open_Project()
    {
        var tmp = Path.Combine(Path.GetTempPath(), "researchos-std-" + Guid.NewGuid().ToString("N") + ".scl");
        File.WriteAllText(tmp, "FUNCTION_BLOCK \"FB_Motor\"\nBEGIN\nEND_FUNCTION_BLOCK\n");
        try
        {
            using var connection = new TiaConnection("V19");
            var projects = new ProjectService(connection);
            var blocks = new BlockService(projects);
            var result = blocks.GenerateBlocksFromSource(tmp);
            Assert.False(result.Ok);
            Assert.Equal("invalid_argument", result.Error?.Code);
        }
        finally
        {
            if (File.Exists(tmp)) File.Delete(tmp);
        }
    }

    [Fact]
    public void CompilePlcSoftwareStrict_Requires_Open_Project()
    {
        using var connection = new TiaConnection("V19");
        var projects = new ProjectService(connection);
        var blocks = new BlockService(projects);
        var result = blocks.CompilePlcSoftwareStrict();
        Assert.False(result.Ok);
        Assert.False(result.ApiAvailable);
        Assert.Equal("invalid_argument", result.Error?.Code);
    }

    [Fact]
    public void SaveProject_Requires_Open_Project()
    {
        using var connection = new TiaConnection("V19");
        var projects = new ProjectService(connection);
        var result = projects.SaveProject();

        Assert.False(result.Ok);
        Assert.Equal("invalid_argument", result.Error?.Code);
    }

    [Fact]
    public void Models_Serialize_CamelCase()
    {
        var payload = new TiaStatusResult
        {
            Ok = true,
            TiaRunning = false,
            OpennessAvailable = true,
            TiaVersion = "V19",
        };
        var json = System.Text.Json.JsonSerializer.Serialize(payload, JsonDefaults.Options);
        Assert.Contains("\"ok\":true", json);
        Assert.Contains("\"tiaRunning\":false", json);
        Assert.Contains("\"opennessAvailable\":true", json);
    }
}

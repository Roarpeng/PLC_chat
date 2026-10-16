using TiaOpenness.Server;

namespace TiaOpenness.Tests;

public class OpennessMutateTests
{
    [Theory]
    [InlineData("<SW.Types.PlcStruct Name=\"UDT_Motor\"/>", "UDT_Motor.xml", "type")]
    [InlineData("<SW.Tags.PlcTagTable Name=\"Default\"/>", "tags.xml", "tag")]
    [InlineData("<PlcWatchTable Name=\"W1\"/>", "Watch_Main.xml", "watch")]
    [InlineData("<PlcForceTable Name=\"F1\"/>", "Force_Main.xml", "force")]
    [InlineData("<Hmi.Screen Name=\"Main\"/>", "Screen_Main.xml", "hmi")]
    [InlineData("<CAEXFile/>", "project.aml", "hardware")]
    [InlineData("<HardwareTree/>", "devices.xml", "hardware")]
    [InlineData("<CfcChart Name=\"Chart1\"/>", "Chart1.xml", "cfc")]
    [InlineData("<TechnologicalObject Name=\"Axis\"/>", "TO_Axis.xml", "to")]
    [InlineData("<SW.Blocks.FB Name=\"FB_Motor\"/>", "FB_Motor.xml", "block")]
    public void ClassifyXmlKind_Matches_SimaticMl_Markers(string head, string file, string expected)
    {
        Assert.Equal(expected, OpennessMutate.ClassifyXmlKind(head, file));
    }

    [Fact]
    public void FindImportMethod_Null_When_Type_Has_No_Import()
    {
        Assert.Null(OpennessMutate.FindImportMethod(new FakeNoImport()));
        Assert.False(OpennessMutate.HasImport(new FakeNoImport()));
    }

    [Fact]
    public void FindImportMethod_Finds_FileInfo_ImportOptions()
    {
        var method = OpennessMutate.FindImportMethod(new FakeImportComposition());
        Assert.NotNull(method);
        Assert.Equal("Import", method!.Name);
        Assert.Equal(2, method.GetParameters().Length);
    }

    [Fact]
    public void TryGenerateSourceFromBlocks_NoExport_When_Method_Missing()
    {
        var (reason, api) = OpennessMutate.TryGenerateSourceFromBlocks(new FakeNoImport(), @"C:\tmp\x.scl");
        Assert.Equal("no_export", reason);
        Assert.Contains("GenerateSourceFromBlocks", api);
    }

    [Fact]
    public void TryCreate_NoImport_When_Create_Missing()
    {
        var (project, reason, api) = OpennessMutate.TryCreate(new FakeNoImport(), @"C:\tmp", "Line");
        Assert.Null(project);
        Assert.Equal("no_import", reason);
        Assert.Contains("Create", api);
    }

    [Fact]
    public void TryClose_NoImport_When_Close_Missing()
    {
        var (closed, reason, api) = OpennessMutate.TryClose(new FakeNoImport());
        Assert.False(closed);
        Assert.Equal("no_import", reason);
        Assert.Contains("Close", api);
    }

    [Fact]
    public void TryRetrieve_NoImport_When_Retrieve_Missing()
    {
        var (project, reason, api) = OpennessMutate.TryRetrieve(new FakeNoImport(), @"C:\a.zap19", @"C:\out");
        Assert.Null(project);
        Assert.Equal("no_import", reason);
        Assert.Contains("Retrieve", api);
    }

    private sealed class FakeNoImport
    {
        public string Name { get; set; } = "x";
    }

    private sealed class FakeImportComposition
    {
        public object Import(FileInfo file, FakeImportOptions options) => file.Name + options.ToString();
    }

    private enum FakeImportOptions
    {
        None = 0,
        Override = 1,
    }
}

public class OpennessWriteRefuseTests
{
    [Fact]
    public void ImportXml_Refuses_Safety_Without_Portal()
    {
        var tmp = Path.Combine(Path.GetTempPath(), "researchos-f-block-" + Guid.NewGuid().ToString("N") + ".xml");
        File.WriteAllText(tmp, "<Document><Name>F-FB_EStop</Name><ProgrammingLanguage>F-SCL</ProgrammingLanguage></Document>");
        try
        {
            using var connection = new TiaConnection("V19");
            var projects = new ProjectService(connection);
            var blocks = new BlockService(projects);
            var result = blocks.ImportXml(tmp, overwrite: true, kindHint: "block");
            Assert.False(result.Ok);
            Assert.Equal("safety_block", result.Error?.Code);
        }
        finally
        {
            if (File.Exists(tmp)) File.Delete(tmp);
        }
    }

    [Fact]
    public void ImportXml_Requires_Open_Project_For_Non_Safety()
    {
        var tmp = Path.Combine(Path.GetTempPath(), "researchos-udt-" + Guid.NewGuid().ToString("N") + ".xml");
        File.WriteAllText(tmp, "<Document><SW.Types.PlcStruct Name=\"UDT_Motor\"/></Document>");
        try
        {
            using var connection = new TiaConnection("V19");
            var projects = new ProjectService(connection);
            var blocks = new BlockService(projects);
            var result = blocks.ImportXml(tmp, overwrite: true, kindHint: "type");
            Assert.False(result.Ok);
            Assert.Equal("invalid_argument", result.Error?.Code);
        }
        finally
        {
            if (File.Exists(tmp)) File.Delete(tmp);
        }
    }

    [Fact]
    public void GenerateSourceFromBlock_Refuses_Safety_Name_Without_Portal()
    {
        using var connection = new TiaConnection("V19");
        var projects = new ProjectService(connection);
        var blocks = new BlockService(projects);
        var result = blocks.GenerateSourceFromBlock("F-FB_EStop");
        Assert.False(result.Ok);
        Assert.Equal("safety_block", result.Error?.Code);
        Assert.Contains("GenerateSourceFromBlocks", result.Api);
    }

    [Fact]
    public void GenerateSourceFromBlock_Requires_Open_Project()
    {
        using var connection = new TiaConnection("V19");
        var projects = new ProjectService(connection);
        var blocks = new BlockService(projects);
        var result = blocks.GenerateSourceFromBlock("FB_Motor");
        Assert.False(result.Ok);
        Assert.Equal("invalid_argument", result.Error?.Code);
    }

    [Fact]
    public void RetrieveProject_Rejects_Missing_Archive()
    {
        using var connection = new TiaConnection("V19");
        var projects = new ProjectService(connection);
        var result = projects.RetrieveProject(@"C:\does\not\exist\Line.zap19", Path.GetTempPath());
        Assert.False(result.Ok);
        Assert.Equal("not_found", result.Error?.Code);
        Assert.Contains("Retrieve", result.Api);
    }

    [Fact]
    public void CreateProject_Requires_Name_And_Directory()
    {
        using var connection = new TiaConnection("V19");
        var projects = new ProjectService(connection);
        var result = projects.CreateProject("", "");
        Assert.False(result.Ok);
        Assert.Equal("invalid_argument", result.Error?.Code);
    }

    [Fact]
    public void CloseProject_Requires_Open_Project()
    {
        using var connection = new TiaConnection("V19");
        var projects = new ProjectService(connection);
        var result = projects.CloseProject();
        Assert.False(result.Ok);
        Assert.Equal("invalid_argument", result.Error?.Code);
    }

    [Fact]
    public void XmlLooksLikeSafety_Detects_F_Language()
    {
        var tmp = Path.Combine(Path.GetTempPath(), "researchos-f-lang-" + Guid.NewGuid().ToString("N") + ".xml");
        File.WriteAllText(tmp, "<AttributeList><ProgrammingLanguage>F-LAD</ProgrammingLanguage></AttributeList>");
        try
        {
            Assert.True(BlockService.XmlLooksLikeSafety(tmp));
        }
        finally
        {
            if (File.Exists(tmp)) File.Delete(tmp);
        }
    }
}

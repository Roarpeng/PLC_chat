using System.Text.Json;
using TiaOpenness.Server;

namespace TiaOpenness.Tests;

/// <summary>
/// Colour channel handling of HmiUnifiedApplyOps: the ops payload carries
/// normalised #RRGGBB strings; the item property may be uint (RGB decimal,
/// same encoding the classic XML chain writes) or string.
/// </summary>
public class HmiUnifiedColorTests
{
    private static JsonElement Op(string json)
    {
        var doc = JsonDocument.Parse(json);
        return doc.RootElement;
    }

    private sealed class FullItem
    {
        public uint BackColor { get; set; }
        public string ForeColor { get; set; } = "";
        public string BorderColor { get; set; } = "";
    }

    private sealed class BoolColorItem
    {
        public bool BackColor { get; set; }
    }

    private sealed class NoColorItem
    {
        public string Text { get; set; } = "";
    }

    private sealed class ThrowingSetterItem
    {
        public uint BackColor
        {
            get => 0x0080FF;
            set => throw new InvalidOperationException("setter must not run for an unchanged colour");
        }
    }

    [Fact]
    public void ApplyColors_Writes_Uint_As_RgbDecimal_And_String_As_Hex()
    {
        var item = new FullItem();
        var notes = HmiUnifiedApplyOps.ApplyColors(
            item,
            Op(@"{""backColor"":""#0080FF"",""foreColor"":""#FF0000"",""borderColor"":""#FF8000""}"));

        Assert.Null(notes);
        Assert.Equal((0u << 16) | (128u << 8) | 255u, item.BackColor); // R<<16 | G<<8 | B
        Assert.Equal("#FF0000", item.ForeColor);
        Assert.Equal("#FF8000", item.BorderColor);
    }

    [Fact]
    public void ApplyColors_Unchanged_Value_Does_Not_Call_The_Setter()
    {
        var notes = HmiUnifiedApplyOps.ApplyColors(
            new ThrowingSetterItem(),
            Op(@"{""backColor"":""#0080FF""}"));

        Assert.Null(notes); // equal current value: no write, no dirty project
    }

    [Fact]
    public void ApplyColors_Missing_Property_Reported_Per_Channel()
    {
        var notes = HmiUnifiedApplyOps.ApplyColors(
            new NoColorItem(),
            Op(@"{""backColor"":""#000000"",""foreColor"":""#111111"",""borderColor"":""#222222""}"));

        Assert.NotNull(notes);
        Assert.Equal(
            new[] { "color_api_missing:backColor", "color_api_missing:foreColor", "color_api_missing:borderColor" },
            notes);
    }

    [Fact]
    public void ApplyColors_Unsupported_Property_Type_Is_Reported_Not_Guessed()
    {
        var notes = HmiUnifiedApplyOps.ApplyColors(new BoolColorItem(), Op(@"{""backColor"":""#000000""}"));

        Assert.NotNull(notes);
        Assert.Single(notes);
        Assert.Equal("color_property_unsupported:backColor:BackColor:Boolean", notes![0]);
    }

    [Theory]
    [InlineData(@"{""backColor"":""0080FF""}", "color_invalid_value:backColor:0080FF")]   // missing '#'
    [InlineData(@"{""backColor"":""#0080f""}", "color_invalid_value:backColor:#0080f")]   // 5 digits
    [InlineData(@"{""backColor"":""#0080ZZ""}", "color_invalid_value:backColor:#0080ZZ")] // not hex
    public void ApplyColors_Rejects_NonCanonical_Values(string json, string expected)
    {
        var item = new FullItem();
        var notes = HmiUnifiedApplyOps.ApplyColors(item, Op(json));

        Assert.NotNull(notes);
        Assert.Equal(expected, notes![0]);
        Assert.Equal(0u, item.BackColor); // nothing was invented on the item
    }

    [Fact]
    public void ApplyColors_Absent_Channels_Are_NoOps()
    {
        var notes = HmiUnifiedApplyOps.ApplyColors(
            new FullItem(),
            Op(@"{""left"":10,""top"":20,""width"":90,""height"":40,""text"":""运行""}"));

        Assert.Null(notes);
    }
}

using System;
using System.IO;
using System.Text.Json;
using TiaOpenness.Models;

namespace TiaOpenness.Tests;

/// <summary>
/// WP-01 / G5 contract tests. All are offline (no TIA Portal required):
/// exact archive path (D-2), create.projectPath CamelCase receipt (D-1),
/// explicit reopenOk (Q-06) and the archive_missing negative case.
/// TargetFramework stays net481 (Siemens.Engineering is .NET Framework Remoting).
/// </summary>
public sealed class ArchiveContractTests
{
    [Fact]
    public void ExactArchivePolicy_ResolveExactPath_IsPreciseAndHasNoWildcard()
    {
        var dir = Path.Combine(Path.GetTempPath(), "tia_exact_" + Guid.NewGuid().ToString("N"));
        var exact = ExactArchivePolicy.ResolveExactPath(dir, "unit.zap19");

        Assert.Equal(Path.Combine(Path.GetFullPath(dir), "unit.zap19"), exact);
        Assert.DoesNotContain("*", exact);
        Assert.EndsWith(".zap19", exact, StringComparison.Ordinal);
    }

    [Fact]
    public void ExactArchivePolicy_Verify_MissingExactFile_IsArchiveMissing()
    {
        var dir = Path.Combine(Path.GetTempPath(), "tia_missing_" + Guid.NewGuid().ToString("N"));
        Directory.CreateDirectory(dir);
        // A DIFFERENT archive in the same directory must NOT be picked as a fallback.
        File.WriteAllText(Path.Combine(dir, "other.zap19"), "not the requested archive");

        var result = ExactArchivePolicy.Verify(dir, "requested.zap19");

        Assert.False(result.Ok);
        Assert.Equal("archive_missing", result.ErrorCode);
        Assert.Equal(Path.Combine(Path.GetFullPath(dir), "requested.zap19"), result.ArchivePath);
        Assert.Null(result.ArchiveSha256);
        Assert.Equal(0L, result.SizeBytes);
    }

    [Fact]
    public void ExactArchivePolicy_Verify_ExactFile_ReturnsSha256AndSize()
    {
        var dir = Path.Combine(Path.GetTempPath(), "tia_exact_ok_" + Guid.NewGuid().ToString("N"));
        Directory.CreateDirectory(dir);
        var target = Path.Combine(dir, "exact.zap19");
        File.WriteAllText(target, "deterministic archive payload");

        var result = ExactArchivePolicy.Verify(dir, "exact.zap19");

        Assert.True(result.Ok);
        Assert.Equal(target, result.ArchivePath);
        Assert.StartsWith("sha256:", result.ArchiveSha256 ?? "", StringComparison.Ordinal);
        Assert.Equal(7 + 64, result.ArchiveSha256!.Length); // "sha256:" + 64 lowercase hex
        Assert.Equal(new FileInfo(target).Length, result.SizeBytes);
        Assert.Equal("", result.ErrorCode);
    }

    [Fact]
    public void CreateProjectReceipt_UsesCreateProjectPath_CamelCase()
    {
        var payload = new
        {
            ok = true,
            create = new CreateProjectResult
            {
                Ok = true,
                ProjectPath = @"C:\work\Demo.ap19",
                ProjectName = "Demo",
                Api = "Projects.Create",
            },
        };
        var json = JsonSerializer.Serialize(payload, JsonDefaults.Options);

        using (var document = JsonDocument.Parse(json))
        {
            var create = document.RootElement.GetProperty("create");
            Assert.Equal(@"C:\work\Demo.ap19", create.GetProperty("projectPath").GetString());
            Assert.False(create.TryGetProperty("ProjectPath", out _));
            Assert.False(document.RootElement.TryGetProperty("path", out _));
            Assert.True(create.TryGetProperty("ok", out var createdOk) && createdOk.GetBoolean());
        }
        Assert.Contains("\"create\":{\"ok\":true,\"projectPath\"", json);
        Assert.DoesNotContain("\"ProjectPath\"", json);
    }

    [Fact]
    public void ArchiveProjectResult_SerialisesExactPathHashAndSize()
    {
        var result = new ArchiveProjectResult
        {
            Ok = true,
            ProjectPath = @"C:\work\Demo.ap19",
            ArchivePath = @"C:\work\out\Demo.zap19",
            ArchiveSha256 = "sha256:abc123",
            SizeBytes = 42,
        };
        var json = JsonSerializer.Serialize(result, JsonDefaults.Options);

        Assert.Contains("\"archivePath\"", json);
        Assert.Contains("\"archiveSha256\":\"sha256:abc123\"", json);
        Assert.Contains("\"sizeBytes\":42", json);
        Assert.DoesNotContain("candidates", json);
    }

    [Fact]
    public void RetrieveProjectResult_SerialisesReopenOk()
    {
        var result = new RetrieveProjectResult
        {
            Ok = true,
            ReopenOk = true,
            ArchivePath = @"C:\work\out\Demo.zap19",
            ProjectPath = @"C:\work\reopen\Demo.ap19",
        };
        var json = JsonSerializer.Serialize(result, JsonDefaults.Options);
        Assert.Contains("\"reopenOk\":true", json);
    }

    [Fact]
    public void DeliveryChainReceipt_SerialisesExactBindingFields()
    {
        var receipt = new DeliveryChainReceipt
        {
            Ok = true,
            Stage = "RETRIEVE_REOPEN",
            State = "NATIVE_ARCHIVED",
            ProjectPath = @"C:\work\Demo.ap19",
            ArchivePath = @"C:\work\out\Demo.zap19",
            Sha256 = "sha256:abc123",
            ReopenOk = true,
            EvidenceLevel = "V19_real",
        };
        var json = JsonSerializer.Serialize(receipt, JsonDefaults.Options);
        Assert.Contains("\"archivePath\"", json);
        Assert.Contains("\"sha256\":\"sha256:abc123\"", json);
        Assert.Contains("\"reopenOk\":true", json);
        Assert.Contains("\"evidenceLevel\":\"V19_real\"", json);
    }

    [Fact]
    public void ProjectService_Source_HasNoDirectoryWildcardFallback()
    {
        var source = ReadProjectServiceSource();
        Assert.NotNull(source);
        Assert.DoesNotContain("candidates[0]", source!);
        Assert.DoesNotContain("Directory.GetFiles(dir", source!);
        Assert.Contains("ExactArchivePolicy.Verify", source!);
    }

    private static string? ReadProjectServiceSource()
    {
        var cursor = new DirectoryInfo(AppContext.BaseDirectory);
        for (var i = 0; i < 10 && cursor is not null; i++, cursor = cursor.Parent)
        {
            var candidate = Path.Combine(
                cursor.FullName,
                "industrial", "tia_openness_cli", "src", "TiaOpenness.Server", "ProjectService.cs");
            if (File.Exists(candidate))
            {
                return File.ReadAllText(candidate);
            }
        }
        return null;
    }
}

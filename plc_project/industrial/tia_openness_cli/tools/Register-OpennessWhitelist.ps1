#Requires -RunAsAdministrator
<#
.SYNOPSIS
    注册 TIA Openness 白名单（V3.0 Tab5 排故字典第 1 条）。
.DESCRIPTION
    按 TIA 版本把当前 Openness 宿主 .exe 写入
    HKLM\SOFTWARE\Siemens\Automation\Openness\<version>\Whitelist\<app>.exe\Entry (N)。

    真实格式（已在 TIA Portal V19 本机核实）：每一个 Entry 是一个**子键**，含三个值：
      Path         = exe 完整路径（REG_SZ）
      DateModified = exe 最后修改时间 UTC，格式 yyyy/MM/dd HH:mm:ss.fff（REG_SZ）
      FileHash     = SHA256 原始字节的 Base64（不是十六进制字符串）

    TIA 允许同一个 exe 有多个 Entry（每次重编译追加一个），因此本脚本自动查找
    现有最大编号并追加 Entry (N+1)，绝不覆盖历史条目。必须以管理员权限运行；
    任何失败都给出清晰中文提示，不静默吞错。
.PARAMETER AppPath
    待注册的可执行文件完整路径（Openness worker / 宿主 exe）。
.PARAMETER TiaVersion
    TIA 版本：V14 SP1 / V15 / V15.1 / V16 / V17 / V18 / V19（也接受 17 / 17.0 等别名）。
.PARAMETER PathValue
    可选。覆盖写入子键的 Path 值；默认使用 exe 完整路径。
.PARAMETER DryRun
    只计算并打印 SHA256 / 修改时间 / 目标子键，不写注册表。
.EXAMPLE
    .\Register-OpennessWhitelist.ps1 -AppPath "C:\App\TiaOpenness.Server.exe" -TiaVersion V19
#>
[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)]
    [ValidateNotNullOrEmpty()]
    [string] $AppPath,

    [Parameter(Mandatory = $true)]
    [ValidateNotNullOrEmpty()]
    [string] $TiaVersion,

    [string] $PathValue = "",

    [switch] $DryRun
)

$ErrorActionPreference = 'Stop'

# 与 C# 侧 OpennessGuardrails 的 VersionMap 保持同一映射（V17 -> 17.0）。
function Get-OpennessHiveVersion {
    param([string] $Version)
    $u = $Version.Trim().ToUpperInvariant()
    if ($u -match '15\.1') { return '15.1' }
    if ($u -match '(\d{2})') {
        $major = [int]$Matches[1]
        switch ($major) {
            14 { return '14.0' }
            15 { return '15.0' }
            16 { return '16.0' }
            17 { return '17.0' }
            18 { return '18.0' }
            19 { return '19.0' }
        }
    }
    throw "【失败】无法识别 TIA 版本 '$Version'；支持 V14 SP1 / V15 / V15.1 / V16 / V17 / V18 / V19。"
}

try {
    # 双重校验管理员权限（#Requires 已保证，这里给出更明确的中文提示）。
    $identity = [Security.Principal.WindowsIdentity]::GetCurrent()
    $principal = New-Object Security.Principal.WindowsPrincipal($identity)
    if (-not $principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) {
        throw "【失败】必须以管理员身份运行 PowerShell（右键『以管理员身份运行』）。"
    }

    if (-not (Test-Path -LiteralPath $AppPath -PathType Leaf)) {
        throw "【失败】找不到 AppPath 指定的文件：$AppPath"
    }
    $item = Get-Item -LiteralPath $AppPath
    $fullPath = $item.FullName
    $appName = $item.Name
    $dateModified = $item.LastWriteTimeUtc.ToString('yyyy/MM/dd HH:mm:ss.fff')

    # SHA256 原始字节 -> Base64。TIA 存的是 Base64，不是 Get-FileHash 的十六进制串。
    $shaHex = (Get-FileHash -LiteralPath $fullPath -Algorithm SHA256).Hash
    $shaBytes = [byte[]]::new($shaHex.Length / 2)
    for ($i = 0; $i -lt $shaBytes.Length; $i++) {
        $shaBytes[$i] = [Convert]::ToByte($shaHex.Substring($i * 2, 2), 16)
    }
    $shaBase64 = [Convert]::ToBase64String($shaBytes)

    $hive = Get-OpennessHiveVersion -Version $TiaVersion
    $key = "HKLM:\SOFTWARE\Siemens\Automation\Openness\$hive\Whitelist\$appName"
    $pathValue = if ([string]::IsNullOrWhiteSpace($PathValue)) { $fullPath } else { $PathValue }

    # 现有 Entry 子键编号：Entry / Entry (1) / Entry (2) ...
    $maxIndex = -1
    if (Test-Path -LiteralPath $key) {
        foreach ($child in Get-ChildItem -LiteralPath $key -ErrorAction SilentlyContinue) {
            $n = $child.PSChildName
            if ($n -eq 'Entry') {
                if ($maxIndex -lt 0) { $maxIndex = 0 }
            }
            elseif ($n -match '^Entry \((\d+)\)$') {
                $v = [int]$Matches[1]
                if ($v -gt $maxIndex) { $maxIndex = $v }
            }
        }
        # 幂等：同一路径 + 同一 hash 已登记时不重复追加。
        foreach ($child in Get-ChildItem -LiteralPath $key -ErrorAction SilentlyContinue) {
            $existingHash = (Get-ItemProperty -LiteralPath $child.PSPath -Name 'FileHash' -ErrorAction SilentlyContinue).FileHash
            $existingPath = (Get-ItemProperty -LiteralPath $child.PSPath -Name 'Path' -ErrorAction SilentlyContinue).Path
            if ($existingHash -eq $shaBase64 -and $existingPath -eq $pathValue) {
                Write-Host "【跳过】该 exe 已在 $($child.PSChildName) 登记，无需重复写入。" -ForegroundColor Yellow
                return
            }
        }
    }
    $entryName = if ($maxIndex -lt 0) { 'Entry' } else { "Entry ($($maxIndex + 1))" }
    $entryKey = Join-Path $key $entryName

    Write-Host "TIA 版本      : $TiaVersion -> Openness hive $hive"
    Write-Host "宿主 exe      : $fullPath"
    Write-Host "SHA256(hex)   : $($shaHex.ToLowerInvariant())"
    Write-Host "FileHash(b64) : $shaBase64"
    Write-Host "DateModified : $dateModified"
    Write-Host "目标子键      : $key\$entryName"

    if ($DryRun) {
        Write-Host "【DryRun】仅计算，未写入注册表。" -ForegroundColor Yellow
        return
    }

    # 写注册表；任一步失败由 catch 统一中文报错，不静默吞错。
    if (-not (Test-Path -LiteralPath $key)) {
        New-Item -Path $key -Force | Out-Null
    }
    New-Item -Path $entryKey -Force | Out-Null
    New-ItemProperty -LiteralPath $entryKey -Name 'Path' -Value $pathValue -PropertyType String -Force | Out-Null
    New-ItemProperty -LiteralPath $entryKey -Name 'DateModified' -Value $dateModified -PropertyType String -Force | Out-Null
    New-ItemProperty -LiteralPath $entryKey -Name 'FileHash' -Value $shaBase64 -PropertyType String -Force | Out-Null

    # 回读校验，避免"写成功但格式不对"。
    $verify = Get-ItemProperty -LiteralPath $entryKey
    if ($verify.FileHash -ne $shaBase64 -or $verify.Path -ne $pathValue) {
        throw "【失败】回读校验不一致，请检查注册表权限：$entryKey"
    }
    Write-Host "【成功】已写入 Openness 白名单子键 $entryName（Path / DateModified / FileHash）。" -ForegroundColor Green
}
catch {
    Write-Host ""
    Write-Host "【失败】注册 Openness 白名单时出错：$($_.Exception.Message)" -ForegroundColor Red
    Write-Host "  排查：1) 以管理员身份运行 PowerShell；2) 确认 -AppPath 指向真实 .exe；" -ForegroundColor Red
    Write-Host "        3) 确认 HKLM 注册表可写（组策略 / 安全软件 / UAC）；4) 确认 -TiaVersion 取值正确。" -ForegroundColor Red
    exit 1
}

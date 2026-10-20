<#
.SYNOPSIS
    为 WinUI3 前端准备 Windows App Runtime 运行库（非 MSIX / unpackaged 场景）。

.DESCRIPTION
    winio 的 WinUI 后端在启动时会做两件事：
      1) 尝试从 kernelbase.dll 取 Appx 动态依赖 API（TryCreatePackageDependency 等）；
      2) 取不到则加载 exe 同目录的 Microsoft.WindowsAppRuntime.dll，用它导出的
         MddTryCreatePackageDependency / MddAddPackageDependency 把
         Microsoft.WindowsAppRuntime.<版本> 框架包挂进当前进程，从而完成 WinRT 类注册。

    因此 exe 同目录必须存在 Microsoft.WindowsAppRuntime.dll（及其 .pri 资源），
    但**绝不能**同时放 Microsoft.ui.xaml.dll：winio 只要发现该 DLL 可加载就会
    跳过上面的注入流程，导致后续创建 XAML 对象时报
    0x80040154 REGDB_E_CLASSNOTREG（没有注册类）而崩溃退出。

    本脚本从已安装的 Windows App Runtime 框架包中拷贝所需的最小文件集合。

.PARAMETER TargetDir
    前端 exe 所在目录，默认 front-winui/target/x86_64-pc-windows-gnu/debug。

.PARAMETER Clean
    拷贝前先删除目标目录中已存在的 .dll/.pri（程序正在运行时无法覆盖，需先关闭）。
#>
[CmdletBinding()]
param(
    [string]$TargetDir,
    [switch]$Clean
)

$ErrorActionPreference = "Stop"

# ---------------- 定位目标目录 ----------------
if (-not $TargetDir) {
    $repoRoot = Split-Path -Parent $PSScriptRoot
    $TargetDir = Join-Path $repoRoot "target\x86_64-pc-windows-gnu\debug"
}
if (-not (Test-Path $TargetDir)) {
    throw "目标目录不存在：$TargetDir（请先执行 cargo build）"
}
Write-Host "目标目录：$TargetDir"

# ---------------- 定位 Windows App Runtime 框架包 ----------------
# 版本优先级：1.8 -> 2 -> 1.7（1.8 在 Win10 22H2 上实测可用）
$preferred = @("Microsoft.WindowsAppRuntime.1.8", "Microsoft.WindowsAppRuntime.2", "Microsoft.WindowsAppRuntime.1.7")
$pkg = $null
foreach ($name in $preferred) {
    $candidate = Get-AppxPackage -Name $name -ErrorAction SilentlyContinue |
        Where-Object { $_.Architecture -eq "X64" } |
        Select-Object -First 1
    if ($candidate -and (Test-Path $candidate.InstallLocation)) {
        $pkg = $candidate
        break
    }
}
if (-not $pkg) {
    throw "未找到已安装的 Windows App Runtime 框架包（Microsoft.WindowsAppRuntime.*）。`n请先安装 Windows App SDK 运行时：https://aka.ms/windowsappsdk/1.8/latest/windowsappruntimeinstall-x64.exe"
}
Write-Host "运行库包：$($pkg.Name) $($pkg.Version)"
Write-Host "包目录：$($pkg.InstallLocation)"

# ---------------- 清理旧文件 ----------------
if ($Clean) {
    Get-ChildItem $TargetDir -File | Where-Object { $_.Extension -in ".dll", ".pri" } | Remove-Item -Force
    Write-Host "已清理旧的 .dll/.pri"
}

# ---------------- 拷贝最小文件集合 ----------------
# 注意：不要拷贝 Microsoft.ui.xaml.dll / Microsoft.UI.Xaml.*.dll，
# 否则 winio 会误判运行库已就绪，跳过包注入 → 0x80040154。
$required = @(
    "Microsoft.WindowsAppRuntime.dll",
    "Microsoft.WindowsAppRuntime.Insights.Resource.dll",
    "Microsoft.WindowsAppRuntime.pri",
    "resources.pri"
)

foreach ($file in $required) {
    $src = Join-Path $pkg.InstallLocation $file
    if (Test-Path $src) {
        Copy-Item $src -Destination $TargetDir -Force
        Write-Host "  [拷贝] $file"
    } else {
        Write-Warning "  [跳过] 包内不存在：$file"
    }
}

# 如果目标目录残留了 XAML 主 DLL，会被 winio 误判，必须删掉
foreach ($name in @("Microsoft.ui.xaml.dll", "Microsoft.UI.Xaml.dll")) {
    $stale = Join-Path $TargetDir $name
    if (Test-Path $stale) {
        Remove-Item $stale -Force -ErrorAction SilentlyContinue
        Write-Host "  [移除] 残留的 $name（会导致 0x80040154）"
    }
}

Write-Host ""
Write-Host "完成。启动方式：" -ForegroundColor Green
Write-Host "  `$env:BACKEND_URL = 'http://localhost:5000'"
Write-Host "  & '$TargetDir\datavisual-winui.exe'"

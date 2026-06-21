param(
    [Parameter(Position = 0)]
    [string]$Command,

    [Parameter(Position = 1)]
    [string]$Change
)

$ErrorActionPreference = "Stop"
$RootDir = Resolve-Path $PSScriptRoot
Set-Location $RootDir

function Show-Usage {
    Write-Output @"
用法:
  .\init.ps1

说明:
  init.ps1 是 Windows 的环境探针入口。
  Unix/macOS/Linux 请使用 ./init.sh。
  验证与归档请使用 .\.harness\scripts\harness.ps1 verify|close <change>。

可选环境变量:
  UNITY_BIN=<path>          指定 Unity 可执行文件
  REQUIRE_UNITY_PROJECT=1   当前目录不是 Unity 项目时失败
  RUN_UNITY_IMPORT=1        执行 Unity 导入/编译
  RUN_EDITMODE=1            执行 EditMode 测试
  RUN_PLAYMODE=1            执行 PlayMode 测试
  RUN_START_COMMAND=1       打开 Unity 编辑器
"@
}

function Test-UnityProject {
    return (Test-Path "Assets" -PathType Container) `
        -and (Test-Path "Packages\manifest.json" -PathType Leaf) `
        -and (Test-Path "ProjectSettings" -PathType Container)
}

function Resolve-UnityBin {
    if (-not [string]::IsNullOrWhiteSpace($env:UNITY_BIN)) {
        return $env:UNITY_BIN
    }

    $CommandInfo = Get-Command "Unity" -ErrorAction SilentlyContinue
    if ($CommandInfo) {
        return $CommandInfo.Source
    }

    $HubEditors = Join-Path ${env:ProgramFiles} "Unity\Hub\Editor"
    if (Test-Path $HubEditors -PathType Container) {
        $UnityExe = Get-ChildItem $HubEditors -Directory |
            Sort-Object Name -Descending |
            ForEach-Object { Join-Path $_.FullName "Editor\Unity.exe" } |
            Where-Object { Test-Path $_ -PathType Leaf } |
            Select-Object -First 1

        if ($UnityExe) {
            return $UnityExe
        }
    }

    return $null
}

function Test-EnvFlag([string]$Name) {
    return [Environment]::GetEnvironmentVariable($Name) -eq "1"
}

function Invoke-Unity([string]$UnityBin, [string[]]$Arguments) {
    Write-Output "==> Unity: $UnityBin $($Arguments -join ' ')"
    & $UnityBin @Arguments
    if ($null -ne $LASTEXITCODE -and $LASTEXITCODE -ne 0) {
        throw "错误: Unity 命令失败，退出码 $LASTEXITCODE"
    }
}

if ($Command -in @("help", "--help", "-h")) {
    Show-Usage
    return
}

Write-Output "==> 当前目录: $PWD"

if (Get-Command "openspec" -ErrorAction SilentlyContinue) {
    Write-Output "==> OpenSpec 活跃变更"
    openspec list
}
else {
    Write-Output "==> 未找到 openspec；跳过 OpenSpec 探针"
}

if (-not (Test-UnityProject)) {
    $Message = "当前目录不是完整 Unity 项目；缺少 Assets、Packages\manifest.json 或 ProjectSettings。"
    if (Test-EnvFlag "REQUIRE_UNITY_PROJECT") {
        throw "错误: $Message"
    }

    Write-Output "==> $Message"
    Write-Output "==> 按模板/文档仓库处理，跳过 Unity 导入和测试。"
    return
}

$UnityBin = Resolve-UnityBin
if ([string]::IsNullOrWhiteSpace($UnityBin)) {
    $Message = "未找到 Unity 可执行文件；可通过 UNITY_BIN 指定。"
    if ((Test-EnvFlag "RUN_UNITY_IMPORT") -or (Test-EnvFlag "RUN_EDITMODE") -or (Test-EnvFlag "RUN_PLAYMODE") -or (Test-EnvFlag "RUN_START_COMMAND")) {
        throw "错误: $Message"
    }

    Write-Output "==> $Message"
    Write-Output "==> 未请求 Unity 动作，环境探针完成。"
    return
}

Write-Output "==> 使用编辑器: $UnityBin"

if (Test-EnvFlag "RUN_UNITY_IMPORT") {
    Invoke-Unity $UnityBin @("-batchmode", "-quit", "-nographics", "-projectPath", $RootDir, "-logFile", "-")
}

if (Test-EnvFlag "RUN_EDITMODE") {
    Invoke-Unity $UnityBin @("-batchmode", "-nographics", "-projectPath", $RootDir, "-runTests", "-testPlatform", "EditMode", "-testResults", (Join-Path $RootDir "test-results-editmode.xml"), "-logFile", "-")
}

if (Test-EnvFlag "RUN_PLAYMODE") {
    Invoke-Unity $UnityBin @("-batchmode", "-projectPath", $RootDir, "-runTests", "-testPlatform", "PlayMode", "-testResults", (Join-Path $RootDir "test-results-playmode.xml"), "-logFile", "-")
}

Write-Output "==> Unity 启动命令:"
Write-Output "    `"$UnityBin`" -projectPath `"$RootDir`""

if (Test-EnvFlag "RUN_START_COMMAND") {
    & $UnityBin -projectPath $RootDir
    if ($null -ne $LASTEXITCODE -and $LASTEXITCODE -ne 0) {
        throw "错误: Unity 启动失败，退出码 $LASTEXITCODE"
    }
    return
}

Write-Output "==> 环境探针完成。需要实际验证时，请按质量契约设置 RUN_UNITY_IMPORT/RUN_EDITMODE/RUN_PLAYMODE。"

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
    Write-Output "Usage:"
    Write-Output "  .\init.ps1"
    Write-Output ""
    Write-Output "Description:"
    Write-Output "  init.ps1 is the Windows environment probe entry."
    Write-Output "  Use ./init.sh on Unix/macOS/Linux."
    Write-Output "  Use .\.harness\scripts\harness.ps1 verify|close <change> for verification and archive."
    Write-Output ""
    Write-Output "Optional environment variables:"
    Write-Output "  UNITY_BIN=<path>          Override Unity executable"
    Write-Output "  REQUIRE_UNITY_PROJECT=1   Fail when current directory is not a Unity project"
    Write-Output "  RUN_UNITY_IMPORT=1        Run Unity import/compile"
    Write-Output "  RUN_EDITMODE=1            Run EditMode tests"
    Write-Output "  RUN_PLAYMODE=1            Run PlayMode tests"
    Write-Output "  RUN_START_COMMAND=1       Open Unity editor"
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
        throw "Error: Unity command failed with exit code $LASTEXITCODE"
    }
}

if ($Command -in @("help", "--help", "-h")) {
    Show-Usage
    return
}

Write-Output "==> Current directory: $PWD"

if (Get-Command "openspec" -ErrorAction SilentlyContinue) {
    Write-Output "==> OpenSpec active changes"
    openspec list
}
else {
    Write-Output "==> openspec not found; skipping OpenSpec probe"
}

if (-not (Test-UnityProject)) {
    $Message = "Current directory is not a complete Unity project; Assets, Packages\manifest.json, or ProjectSettings is missing."
    if (Test-EnvFlag "REQUIRE_UNITY_PROJECT") {
        throw "Error: $Message"
    }

    Write-Output "==> $Message"
    Write-Output "==> Treating this as a template/docs repository; skipping Unity import and tests."
    return
}

$UnityBin = Resolve-UnityBin
if ([string]::IsNullOrWhiteSpace($UnityBin)) {
    $Message = "Unity executable not found; set UNITY_BIN to override."
    if ((Test-EnvFlag "RUN_UNITY_IMPORT") -or (Test-EnvFlag "RUN_EDITMODE") -or (Test-EnvFlag "RUN_PLAYMODE") -or (Test-EnvFlag "RUN_START_COMMAND")) {
        throw "Error: $Message"
    }

    Write-Output "==> $Message"
    Write-Output "==> No Unity action requested; environment probe complete."
    return
}

Write-Output "==> Unity editor: $UnityBin"

if (Test-EnvFlag "RUN_UNITY_IMPORT") {
    Invoke-Unity $UnityBin @("-batchmode", "-quit", "-nographics", "-projectPath", $RootDir, "-logFile", "-")
}

if (Test-EnvFlag "RUN_EDITMODE") {
    Invoke-Unity $UnityBin @("-batchmode", "-nographics", "-projectPath", $RootDir, "-runTests", "-testPlatform", "EditMode", "-testResults", (Join-Path $RootDir "test-results-editmode.xml"), "-logFile", "-")
}

if (Test-EnvFlag "RUN_PLAYMODE") {
    Invoke-Unity $UnityBin @("-batchmode", "-projectPath", $RootDir, "-runTests", "-testPlatform", "PlayMode", "-testResults", (Join-Path $RootDir "test-results-playmode.xml"), "-logFile", "-")
}

Write-Output "==> Unity start command:"
Write-Output "    `"$UnityBin`" -projectPath `"$RootDir`""

if (Test-EnvFlag "RUN_START_COMMAND") {
    & $UnityBin -projectPath $RootDir
    if ($null -ne $LASTEXITCODE -and $LASTEXITCODE -ne 0) {
        throw "Error: Unity start failed with exit code $LASTEXITCODE"
    }
    return
}

Write-Output "==> Environment probe complete. Set RUN_UNITY_IMPORT/RUN_EDITMODE/RUN_PLAYMODE for real validation."

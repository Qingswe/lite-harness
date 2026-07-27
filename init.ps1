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
    Write-Output "  SKIP_OPENSPEC_LIST=1      Skip openspec list (caller already validated)"
    Write-Output "  UNITY_PROJECT_DIR=<path>  Unity subproject directory (default UnityProject/)"
    Write-Output "  UNITY_BIN=<path>          Override Unity executable"
    Write-Output "  REQUIRE_UNITY_PROJECT=1   Fail when no Unity project can be found"
    Write-Output "  RUN_UNITY_IMPORT=1        Run Unity import/compile"
    Write-Output "  RUN_EDITMODE=1            Run EditMode tests"
    Write-Output "  RUN_PLAYMODE=1            Run PlayMode tests"
    Write-Output "  RUN_START_COMMAND=1       Open Unity editor"
}

function Test-UnityProject([string]$CandidatePath) {
    return (Test-Path (Join-Path $CandidatePath "Assets") -PathType Container) `
        -and (Test-Path (Join-Path $CandidatePath "Packages\manifest.json") -PathType Leaf) `
        -and (Test-Path (Join-Path $CandidatePath "ProjectSettings") -PathType Container)
}

function Resolve-UnityProjectDir {
    if (-not [string]::IsNullOrWhiteSpace($env:UNITY_PROJECT_DIR)) {
        $Candidate = $env:UNITY_PROJECT_DIR
        if (-not [System.IO.Path]::IsPathRooted($Candidate)) {
            $Candidate = Join-Path $RootDir $Candidate
        }

        if (-not (Test-UnityProject $Candidate)) {
            throw "Error: UNITY_PROJECT_DIR is not a Unity project: $Candidate"
        }

        return (Resolve-Path $Candidate).Path
    }

    if (Test-UnityProject $RootDir) {
        return $RootDir.Path
    }

    $NestedProject = Join-Path $RootDir "UnityProject"
    if (Test-UnityProject $NestedProject) {
        return (Resolve-Path $NestedProject).Path
    }

    return $null
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

if ($env:SKIP_OPENSPEC_LIST -eq "1") {
    Write-Output "==> Skipping OpenSpec list (SKIP_OPENSPEC_LIST=1)"
}
elseif (Get-Command "openspec" -ErrorAction SilentlyContinue) {
    Write-Output "==> OpenSpec active changes"
    openspec list
}
else {
    Write-Output "==> openspec not found; skipping OpenSpec probe"
}

$UnityProjectDir = Resolve-UnityProjectDir

if ([string]::IsNullOrWhiteSpace($UnityProjectDir)) {
    $Message = "No Unity project found at repo root or UnityProject/."
    if (Test-EnvFlag "REQUIRE_UNITY_PROJECT") {
        throw "Error: $Message"
    }

    Write-Output "==> $Message"
    Write-Output "==> Treating this as a template/docs repository; skipping Unity import and tests."
    return
}

Write-Output "==> Unity project: $UnityProjectDir"

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
    Invoke-Unity $UnityBin @("-batchmode", "-quit", "-nographics", "-projectPath", $UnityProjectDir, "-logFile", "-")
}

if (Test-EnvFlag "RUN_EDITMODE") {
    Invoke-Unity $UnityBin @("-batchmode", "-nographics", "-projectPath", $UnityProjectDir, "-runTests", "-testPlatform", "EditMode", "-testResults", (Join-Path $RootDir "test-results-editmode.xml"), "-logFile", "-")
}

if (Test-EnvFlag "RUN_PLAYMODE") {
    Invoke-Unity $UnityBin @("-batchmode", "-projectPath", $UnityProjectDir, "-runTests", "-testPlatform", "PlayMode", "-testResults", (Join-Path $RootDir "test-results-playmode.xml"), "-logFile", "-")
}

Write-Output "==> Unity start command:"
Write-Output "    `"$UnityBin`" -projectPath `"$UnityProjectDir`""

if (Test-EnvFlag "RUN_START_COMMAND") {
    & $UnityBin -projectPath $UnityProjectDir
    if ($null -ne $LASTEXITCODE -and $LASTEXITCODE -ne 0) {
        throw "Error: Unity start failed with exit code $LASTEXITCODE"
    }
    return
}

Write-Output "==> Environment probe complete. Set RUN_UNITY_IMPORT/RUN_EDITMODE/RUN_PLAYMODE for real validation."

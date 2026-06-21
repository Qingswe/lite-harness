param(
    [Parameter(Position = 0)]
    [string]$Command,

    [Parameter(Position = 1)]
    [string]$Change
)

$ErrorActionPreference = "Stop"
$RootDir = Resolve-Path (Join-Path $PSScriptRoot "..\..")
Set-Location $RootDir

function Show-Usage {
    Write-Output "Usage:"
    Write-Output "  .\.harness\scripts\harness.ps1 verify <change>"
    Write-Output "  .\.harness\scripts\harness.ps1 close <change>"
    Write-Output ""
    Write-Output "Description:"
    Write-Output "  verify validates OpenSpec, required change files, and the baseline probe."
    Write-Output "  close checks tasks, human checks, quality docs decision, then runs openspec archive."
}

function Fail([string]$Message) {
    throw "Error: $Message"
}

function Require-Command([string]$Name) {
    if (-not (Get-Command $Name -ErrorAction SilentlyContinue)) {
        Fail "Missing command: $Name"
    }
}

function Get-ChangeDir([string]$ChangeId) {
    Join-Path "openspec\changes" $ChangeId
}

function Require-ChangeFiles([string]$ChangeId) {
    $Dir = Get-ChangeDir $ChangeId

    if (-not (Test-Path $Dir -PathType Container)) { Fail "Missing change directory: $Dir" }

    $RequiredFiles = @(
        "tasks.md",
        "quality-contract.md",
        "verification.md",
        "human-checks.md"
    )

    foreach ($File in $RequiredFiles) {
        $Path = Join-Path $Dir $File
        if (-not (Test-Path $Path -PathType Leaf)) {
            Fail "Missing $Path. Copy the matching template from .harness\templates\."
        }
    }
}

function Test-TasksComplete([string]$ChangeId) {
    $TasksFile = Join-Path (Get-ChangeDir $ChangeId) "tasks.md"
    $Content = Get-Content $TasksFile -Raw

    if ($Content -match '(?m)^\s*-\s*\[\s\]') {
        Fail "$TasksFile still has incomplete tasks."
    }
}

function Test-HumanChecksClear([string]$ChangeId) {
    $ChecksFile = Join-Path (Get-ChangeDir $ChangeId) "human-checks.md"
    $Content = Get-Content $ChecksFile -Raw

    if ($Content -match '(?im)^\s*\|\s*(pending|failed)\s*\|') {
        Fail "$ChecksFile still has pending or failed human check table rows."
    }
}

function Test-QualityDocsDecision([string]$ChangeId) {
    $VerificationFile = Join-Path (Get-ChangeDir $ChangeId) "verification.md"
    $Content = Get-Content $VerificationFile -Raw

    if ($Content -notmatch '(?m)^##\s+质量文档判断\s*$') {
        Fail "$VerificationFile is missing the quality docs decision section. Follow docs\quality\README.md."
    }
}

function Invoke-Verify([string]$ChangeId) {
    Require-Command "openspec"
    Require-ChangeFiles $ChangeId

    Write-Output "==> OpenSpec strict validation: $ChangeId"
    openspec validate $ChangeId --strict

    Write-Output "==> Baseline probe"
    if (Test-Path ".\init.ps1" -PathType Leaf) {
        & ".\init.ps1"
    }
    elseif (Get-Command bash -ErrorAction SilentlyContinue) {
        bash ./init.sh
    }
    else {
        Fail "Missing init.ps1 or bash; cannot run the baseline probe."
    }

    Write-Output "==> verify completed: $ChangeId"
}

function Invoke-Close([string]$ChangeId) {
    Invoke-Verify $ChangeId
    Test-TasksComplete $ChangeId
    Test-HumanChecksClear $ChangeId
    Test-QualityDocsDecision $ChangeId

    Write-Output "==> Archive change: $ChangeId"
    openspec archive $ChangeId

    Write-Output "==> close completed: $ChangeId"
}

if ([string]::IsNullOrWhiteSpace($Command) -or [string]::IsNullOrWhiteSpace($Change)) {
    Show-Usage
    exit 2
}

switch ($Command) {
    "verify" { Invoke-Verify $Change }
    "close" { Invoke-Close $Change }
    { $_ -in @("help", "--help", "-h") } { Show-Usage }
    default {
        Show-Usage
        Fail "Unknown command: $Command"
    }
}

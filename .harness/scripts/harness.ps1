param(
    [Parameter(Position = 0)]
    [string]$Command,

    [Parameter(Position = 1)]
    [string]$Change,

    [switch]$SkipSpecs,

    [switch]$Json,

    [switch]$NoProbe
)

$ErrorActionPreference = "Stop"
$RootDir = Resolve-Path (Join-Path $PSScriptRoot "..\..")
Set-Location $RootDir

function Show-Usage {
    Write-Output "Usage:"
    Write-Output "  .\.harness\scripts\harness.ps1 status [-Json]"
    Write-Output "  .\.harness\scripts\harness.ps1 sync-candidates"
    Write-Output "  .\.harness\scripts\harness.ps1 verify <change> [-NoProbe]"
    Write-Output "  .\.harness\scripts\harness.ps1 close <change> [-SkipSpecs] [-NoProbe]"
    Write-Output "  .\.harness\scripts\harness.ps1 reset-current"
    Write-Output ""
    Write-Output "Description:"
    Write-Output "  status prints the execution state needed to resume a session: active slot,"
    Write-Output "         candidates with lifecycle phase, blockers, next action, task progress,"
    Write-Output "         evidence counts, drift warnings, and recent commits."
    Write-Output "  sync-candidates rewrites candidate membership from openspec\changes\."
    Write-Output "  verify validates OpenSpec and required change files, runs repository structure"
    Write-Output "         checks (doc path references, skill consistency, feature-index sync), and"
    Write-Output "         runs the Unity probe only when quality-contract.md asks for it."
    Write-Output "  close checks tasks, human checks, quality docs decision, runs openspec archive,"
    Write-Output "        then finalizes .harness\current.json."
    Write-Output "  reset-current clears .harness\current.json back to an empty execution slot."
    Write-Output ""
    Write-Output "Options:"
    Write-Output "  -Json       Emit status as JSON for scripted consumers."
    Write-Output "  -NoProbe    Manual override: skip the Unity probe even if the contract wants it."
    Write-Output "  -SkipSpecs  Skip spec updates when archiving (infra, tooling, or doc-only changes)."
}

function Fail([string]$Message) {
    throw "Error: $Message"
}

function Require-Command([string]$Name) {
    if (-not (Get-Command $Name -ErrorAction SilentlyContinue)) {
        Fail "Missing command: $Name"
    }
}

function Require-ChangeArg([string]$CommandName, [string]$ChangeId) {
    if ([string]::IsNullOrWhiteSpace($ChangeId)) {
        Show-Usage
        Fail "$CommandName requires <change>."
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

function Invoke-CheckCommand([string[]]$CheckArgs) {
    # Gate logic lives in harness_checks.py so both platforms agree.
    $Python = Resolve-Python
    $CheckScript = Join-Path $PSScriptRoot "harness_checks.py"
    & $Python $CheckScript @CheckArgs
    return $LASTEXITCODE
}

function Test-HumanChecksClear([string]$ChangeId) {
    # Positive assertion: the table must exist, have at least one row, every row
    # must be passed or waived, and waived rows need a recorded exemption.
    if ((Invoke-CheckCommand @("human-checks", $ChangeId)) -ne 0) {
        Fail "Human check results are not conclusive for $ChangeId."
    }
}

function Test-QualityDocsDecision([string]$ChangeId) {
    $VerificationFile = Join-Path (Get-ChangeDir $ChangeId) "verification.md"
    $Content = Get-Content $VerificationFile -Raw

    if ($Content -notmatch '(?m)^##\s+质量文档判断\s*$') {
        Fail "$VerificationFile is missing the quality docs decision section. Follow docs\quality\README.md."
    }
}

function Resolve-Python {
    foreach ($Name in @("python3", "python", "py")) {
        if (Get-Command $Name -ErrorAction SilentlyContinue) { return $Name }
    }
    Fail "Missing command: python3"
}

function Invoke-Status([bool]$AsJson) {
    $Python = Resolve-Python
    $StateScript = Join-Path $PSScriptRoot "harness_state.py"

    # State projection is shared with the dashboard via harness_state.py;
    # this wrapper must not reimplement schema or lifecycle logic.
    if ($AsJson) {
        & $Python $StateScript status --json
    }
    else {
        & $Python $StateScript status
    }
    if ($LASTEXITCODE -ne 0) {
        exit $LASTEXITCODE
    }
}

function Invoke-Verify([string]$ChangeId, [bool]$SkipProbe) {
    Require-Command "openspec"
    Require-ChangeFiles $ChangeId

    Write-Output "==> OpenSpec strict validation: $ChangeId"
    openspec validate $ChangeId --strict

    Write-Output "==> Repository structure checks"
    if ((Invoke-CheckCommand @("doc-refs")) -ne 0) { Fail "Document path references are broken." }
    if ((Invoke-CheckCommand @("skills")) -ne 0) { Fail "Skill definitions diverge across client directories." }
    $Python = Resolve-Python
    & $Python (Join-Path $PSScriptRoot "sync-feature-index.py") --check
    if ($LASTEXITCODE -ne 0) { Fail "feature-index.json is out of sync with openspec." }

    if ($SkipProbe) {
        Write-Output "==> Baseline probe: skipped (-NoProbe)"
    }
    elseif ((Invoke-CheckCommand @("probe-needed", $ChangeId)) -eq 0) {
        Write-Output "==> Baseline probe"
        # verify already ran openspec validate; the probe need not list changes again.
        $env:SKIP_OPENSPEC_LIST = "1"
        try {
            if (Test-Path ".\init.ps1" -PathType Leaf) {
                & ".\init.ps1"
            }
            elseif (Get-Command bash -ErrorAction SilentlyContinue) {
                bash ./init.sh
            }
            else {
                Fail "Missing init.ps1 or bash; cannot run the baseline probe."
            }
        }
        finally {
            Remove-Item Env:\SKIP_OPENSPEC_LIST -ErrorAction SilentlyContinue
        }
    }

    Write-Output "==> verify completed: $ChangeId"
}

function Invoke-Close([string]$ChangeId, [bool]$SkipSpecUpdates, [bool]$SkipProbe) {
    Invoke-Verify $ChangeId $SkipProbe
    Test-TasksComplete $ChangeId
    Test-HumanChecksClear $ChangeId
    Test-QualityDocsDecision $ChangeId

    Write-Output "==> Archive change: $ChangeId"
    # --yes keeps the archive non-interactive inside agent sessions.
    if ($SkipSpecUpdates) {
        openspec archive $ChangeId --yes --skip-specs
    }
    else {
        openspec archive $ChangeId --yes
    }
    if ($LASTEXITCODE -ne 0) {
        Fail "OpenSpec archive failed for $ChangeId."
    }

    Write-Output "==> Finalize current.json"
    Invoke-StateCommand @("finalize-close", $ChangeId)

    Write-Output "==> close completed: $ChangeId"
}

function Invoke-StateCommand([string[]]$StateArgs) {
    # The schema lives only in harness_state.py; neither platform script keeps
    # its own literal JSON template.
    $Python = Resolve-Python
    $StateScript = Join-Path $PSScriptRoot "harness_state.py"
    & $Python $StateScript @StateArgs
    if ($LASTEXITCODE -ne 0) {
        Fail "harness_state.py $($StateArgs -join ' ') failed."
    }
}

function Reset-Current {
    Invoke-StateCommand @("reset-current")
}

function Sync-Candidates {
    Invoke-StateCommand @("sync-candidates")
}

if ([string]::IsNullOrWhiteSpace($Command)) {
    Show-Usage
    exit 2
}

if ($SkipSpecs -and $Command -ne "close") {
    Show-Usage
    Fail "-SkipSpecs can only be used with close."
}

if ($NoProbe -and $Command -notin @("verify", "close")) {
    Show-Usage
    Fail "-NoProbe can only be used with verify or close."
}

if ($Json -and $Command -ne "status") {
    Show-Usage
    Fail "-Json can only be used with status."
}

switch ($Command) {
    "status" {
        if (-not [string]::IsNullOrWhiteSpace($Change)) {
            Show-Usage
            Fail "status does not take a <change> argument."
        }
        Invoke-Status ([bool]$Json)
    }
    "verify" {
        Require-ChangeArg "verify" $Change
        Invoke-Verify $Change ([bool]$NoProbe)
    }
    "close" {
        Require-ChangeArg "close" $Change
        Invoke-Close $Change ([bool]$SkipSpecs) ([bool]$NoProbe)
    }
    "sync-candidates" {
        if (-not [string]::IsNullOrWhiteSpace($Change)) {
            Show-Usage
            Fail "sync-candidates does not take a <change> argument."
        }
        Sync-Candidates
    }
    "reset-current" { Reset-Current }
    { $_ -in @("help", "--help", "-h") } { Show-Usage }
    default {
        Show-Usage
        Fail "Unknown command: $Command"
    }
}

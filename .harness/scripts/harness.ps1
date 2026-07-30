param(
    [Parameter(Position = 0)]
    [string]$Command,

    [Parameter(Position = 1)]
    [string]$Change,

    [switch]$SkipSpecs,

    [switch]$Json,

    [switch]$NoProbe,

    [switch]$DryRun
)

$ErrorActionPreference = "Stop"
$RootDir = Resolve-Path (Join-Path $PSScriptRoot "..\..")
Set-Location $RootDir

function Show-Usage {
    Write-Output "Usage:"
    Write-Output "  .\.harness\scripts\harness.ps1 status [-Json]"
    Write-Output "  .\.harness\scripts\harness.ps1 ready [-Json]"
    Write-Output "  .\.harness\scripts\harness.ps1 next [-Json]"
    Write-Output "  .\.harness\scripts\harness.ps1 autoclose [-DryRun]"
    Write-Output "  .\.harness\scripts\harness.ps1 rollback <change>"
    Write-Output "  .\.harness\scripts\harness.ps1 lint <change>"
    Write-Output "  .\.harness\scripts\harness.ps1 render <change>"
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
    Write-Output "         runs the Unity probe based on program.md and the verification record."
    Write-Output "  close runs the shared gate, creates a rollback tag, runs openspec archive,"
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

function Require-ChangeDir([string]$ChangeId) {
    $Dir = Get-ChangeDir $ChangeId
    if (-not (Test-Path $Dir -PathType Container)) { Fail "Missing change directory: $Dir" }
}

function Invoke-CheckCommand([string[]]$CheckArgs) {
    # Gate logic lives in harness_checks.py so both platforms agree.
    $Python = Resolve-Python
    $CheckScript = Join-Path $PSScriptRoot "harness_checks.py"
    & $Python $CheckScript @CheckArgs
    return $LASTEXITCODE
}

function Invoke-CloseGate([string]$ChangeId) {
    # Required files, task completion, verification terminal states, risk floor,
    # role isolation, and quality-doc pre-screen all live in
    # harness_checks.py close_gate(). lint and close call the same function, and
    # both platforms call the same function - never reimplement it here.
    if ((Invoke-CheckCommand @("gate", $ChangeId)) -ne 0) {
        Fail "Close gate failed for $ChangeId."
    }
}

function New-RatchetTag([string]$ChangeId) {
    Require-Command "git"
    $Tag = "harness/pre-close/$ChangeId"
    & git rev-parse -q --verify "refs/tags/$Tag" > $null 2>&1
    if ($LASTEXITCODE -eq 0) { & git tag -d $Tag | Out-Null }
    & git tag -a $Tag -m "Rollback point before archiving $ChangeId"
    if ($LASTEXITCODE -ne 0) {
        Fail "Could not create rollback point $Tag; automatic archiving must abort without one."
    }
    Write-Output "==> Rollback point: $Tag (roll back with git reset --hard $Tag)"
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
    Require-ChangeDir $ChangeId

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
    Invoke-CloseGate $ChangeId

    # Create the rollback point before archiving: archiving moves directories and
    # rewrites openspec/specs/, so there is no way back without one.
    New-RatchetTag $ChangeId

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

    # Archiving lands delta specs in openspec/specs/, which makes the capability
    # index stale; without this the next verify fails on the sync check.
    Write-Output "==> Sync capability index"
    $Python = Resolve-Python
    & $Python (Join-Path $PSScriptRoot "sync-feature-index.py")
    if ($LASTEXITCODE -ne 0) { Fail "Failed to sync feature-index.json after archiving." }

    # The archive result must land in a commit, otherwise the ratchet is fake:
    # the archive directory and any new spec directory are UNTRACKED, and
    # `git reset --hard <tag>` does not touch them. That is a partial rollback,
    # which is worse than none because it looks like it worked.
    Invoke-CommitArchive $ChangeId

    Write-Output "==> close completed: $ChangeId"
}

function Invoke-CommitArchive([string]$ChangeId) {
    Require-Command "git"
    & git add -A openspec .harness | Out-Null
    & git diff --cached --quiet
    if ($LASTEXITCODE -eq 0) {
        Write-Output "==> Archive produced no changes; skipping commit."
        return
    }
    & git commit -q -m "Archive $ChangeId"
    if ($LASTEXITCODE -ne 0) {
        Fail "Could not commit the archive result; the ratchet does not hold."
    }
    Write-Output "==> Archive committed (roll back with harness.ps1 rollback $ChangeId)"
}

function Invoke-Rollback([string]$ChangeId) {
    Require-Command "git"
    $Tag = "harness/pre-close/$ChangeId"
    & git rev-parse -q --verify "refs/tags/$Tag" > $null 2>&1
    if ($LASTEXITCODE -ne 0) { Fail "No rollback point $Tag." }

    $Dirty = (& git status --porcelain | Out-String).Trim()
    if ($Dirty) { Fail "Working tree is not clean; rollback would discard:`n$Dirty" }

    Write-Output "==> Rolling back to $Tag"
    & git reset --hard $Tag
    $Residue = (& git status --porcelain | Out-String).Trim()
    if ($Residue) { Fail "Residue after rollback -- this is a partial rollback:`n$Residue" }
    Write-Output "==> Rollback complete; working tree clean"
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

function Invoke-AutoClose([bool]$DryRun) {
    # Readiness triggers archiving; it never replaces the gate. Every change still
    # runs the full close path (verify + shared gate + ratchet tag).
    $Python = Resolve-Python
    $CheckScript = Join-Path $PSScriptRoot "harness_checks.py"
    $Json = & $Python $CheckScript ready --json | Out-String
    if ($LASTEXITCODE -ne 0) { Fail "ready failed." }
    $Ready = ($Json | ConvertFrom-Json).ready
    if (-not $Ready -or $Ready.Count -eq 0) {
        Write-Output "==> No ready change; nothing to archive."
        return
    }
    foreach ($Item in $Ready) {
        if ($DryRun) {
            Write-Output "==> [dry-run] would archive: $($Item.change)"
            continue
        }
        Write-Output "==> Auto archiving: $($Item.change)"
        Invoke-Close $Item.change $false $false
    }
}

function Invoke-Lint([string]$ChangeId) {
    # Same gate assertions as close, without archiving. Runnable at any time.
    Require-ChangeDir $ChangeId
    Invoke-CloseGate $ChangeId
    Write-Output "==> lint passed: $ChangeId"
}

function Invoke-Ready([bool]$AsJson) {
    $CheckArgs = @("ready")
    if ($AsJson) { $CheckArgs += "--json" }
    if ((Invoke-CheckCommand $CheckArgs) -ne 0) { Fail "ready failed." }
}

function Invoke-Next([bool]$AsJson) {
    $CheckArgs = @("next")
    if ($AsJson) { $CheckArgs += "--json" }
    if ((Invoke-CheckCommand $CheckArgs) -ne 0) { Fail "next failed." }
}

function Invoke-Render([string]$ChangeId) {
    $Python = Resolve-Python
    & $Python (Join-Path $PSScriptRoot "harness_verification.py") render $ChangeId
    if ($LASTEXITCODE -ne 0) { Fail "render failed for $ChangeId." }
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

if ($DryRun -and $Command -ne "autoclose") {
    Show-Usage
    Fail "-DryRun can only be used with autoclose."
}

if ($NoProbe -and $Command -notin @("verify", "close")) {
    Show-Usage
    Fail "-NoProbe can only be used with verify or close."
}

if ($Json -and $Command -notin @("status", "ready", "next")) {
    Show-Usage
    Fail "-Json can only be used with status, ready, or next."
}

switch ($Command) {
    "status" {
        if (-not [string]::IsNullOrWhiteSpace($Change)) {
            Show-Usage
            Fail "status does not take a <change> argument."
        }
        Invoke-Status ([bool]$Json)
    }
    "ready" {
        if (-not [string]::IsNullOrWhiteSpace($Change)) {
            Show-Usage
            Fail "ready does not take a <change> argument."
        }
        Invoke-Ready ([bool]$Json)
    }
    "next" {
        if (-not [string]::IsNullOrWhiteSpace($Change)) {
            Show-Usage
            Fail "next does not take a <change> argument."
        }
        Invoke-Next ([bool]$Json)
    }
    "autoclose" {
        if (-not [string]::IsNullOrWhiteSpace($Change)) {
            Show-Usage
            Fail "autoclose does not take a <change> argument."
        }
        Invoke-AutoClose ([bool]$DryRun)
    }
    "lint" {
        Require-ChangeArg "lint" $Change
        Invoke-Lint $Change
    }
    "rollback" {
        Require-ChangeArg "rollback" $Change
        Invoke-Rollback $Change
    }
    "render" {
        Require-ChangeArg "render" $Change
        Invoke-Render $Change
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

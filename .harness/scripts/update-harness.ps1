param(
    [string]$Repo = "https://github.com/Qingswe/lite-harness.git",
    [string]$Ref = "main",
    [string]$Target,
    [string]$Manifest = ".harness/update-manifest.txt",
    [switch]$Apply,
    [switch]$NoBackup,
    [string]$BackupDir,
    [switch]$Help
)

$ErrorActionPreference = "Stop"

if ($Help) {
    Write-Output "Usage:"
    Write-Output "  .\.harness\scripts\update-harness.ps1 [-Apply] [options]"
    Write-Output ""
    Write-Output "Options:"
    Write-Output "  -Apply              Apply the update. Without this flag the command is a dry run."
    Write-Output "  -Repo <url>         Source Git repository. Default: https://github.com/Qingswe/lite-harness.git"
    Write-Output "  -Ref <name>         Source branch, tag, or commit. Default: main"
    Write-Output "  -Target <dir>       Target project root. Default: current harness root"
    Write-Output "  -Manifest <path>    Manifest path inside the source repo. Default: .harness/update-manifest.txt"
    Write-Output "  -BackupDir <dir>    Backup directory. Default: .harness\backups\harness-update-<timestamp>"
    Write-Output "  -NoBackup           Do not back up overwritten files."
    return
}

function Fail([string]$Message) {
    throw "Error: $Message"
}

function Require-Command([string]$Name) {
    if (-not (Get-Command $Name -ErrorAction SilentlyContinue)) {
        Fail "Missing command: $Name"
    }
}

function Resolve-RelativePath([string]$BasePath, [string]$Path) {
    $BaseFull = (Resolve-Path $BasePath).ProviderPath.TrimEnd([System.IO.Path]::DirectorySeparatorChar, [System.IO.Path]::AltDirectorySeparatorChar)
    $PathFull = (Resolve-Path $Path).ProviderPath

    $BaseUri = [Uri]($BaseFull + [System.IO.Path]::DirectorySeparatorChar)
    $PathUri = [Uri]$PathFull
    return [Uri]::UnescapeDataString($BaseUri.MakeRelativeUri($PathUri).ToString()).Replace("/", [System.IO.Path]::DirectorySeparatorChar)
}

function Test-SafeManifestEntry([string]$Entry) {
    if ([string]::IsNullOrWhiteSpace($Entry)) {
        return $false
    }

    if ([System.IO.Path]::IsPathRooted($Entry) -or $Entry.Contains("..")) {
        Fail "Manifest entries must be relative paths without '..': $Entry"
    }

    return $true
}

Require-Command "git"

if ([string]::IsNullOrWhiteSpace($Target)) {
    $Target = Resolve-Path (Join-Path $PSScriptRoot "..\..")
}
else {
    $Target = Resolve-Path $Target
}

$Target = $Target.ProviderPath
$Timestamp = Get-Date -Format "yyyyMMdd-HHmmss"

if ([string]::IsNullOrWhiteSpace($BackupDir)) {
    $BackupDir = Join-Path $Target ".harness\backups\harness-update-$Timestamp"
}
elseif (-not [System.IO.Path]::IsPathRooted($BackupDir)) {
    $BackupDir = Join-Path $Target $BackupDir
}

$TempDir = Join-Path ([System.IO.Path]::GetTempPath()) ("lite-harness-update-" + [Guid]::NewGuid().ToString("N"))
$SourceDir = Join-Path $TempDir "source"
New-Item -ItemType Directory -Path $TempDir | Out-Null

try {
    Write-Output "==> Source: $Repo ($Ref)"
    Write-Output "==> Target: $Target"
    if (-not $Apply) {
        Write-Output "==> Mode: dry run. Re-run with -Apply to copy files."
    }
    else {
        Write-Output "==> Mode: apply"
        if ($NoBackup) {
            Write-Output "==> Backup: disabled"
        }
        else {
            Write-Output "==> Backup: $BackupDir"
        }
    }

    & git clone --quiet --depth 1 --branch $Ref $Repo $SourceDir 2>$null
    if ($LASTEXITCODE -ne 0) {
        & git clone --quiet $Repo $SourceDir
        if ($LASTEXITCODE -ne 0) { Fail "git clone failed." }

        & git -C $SourceDir checkout --quiet $Ref
        if ($LASTEXITCODE -ne 0) { Fail "git checkout failed for ref: $Ref" }
    }

    $ManifestFile = Join-Path $SourceDir $Manifest
    if (-not (Test-Path $ManifestFile -PathType Leaf)) {
        Fail "Missing manifest in source repo: $Manifest"
    }

    function Backup-ExistingFile([string]$RelPath) {
        if ($NoBackup) { return }

        $Dest = Join-Path $Target $RelPath
        if (-not (Test-Path $Dest -PathType Leaf)) { return }

        $BackupPath = Join-Path $BackupDir $RelPath
        $BackupParent = Split-Path $BackupPath -Parent
        if (-not (Test-Path $BackupParent -PathType Container)) {
            New-Item -ItemType Directory -Path $BackupParent -Force | Out-Null
        }

        Copy-Item $Dest $BackupPath -Force
    }

    function Copy-OneFile([string]$RelPath) {
        $Source = Join-Path $SourceDir $RelPath
        $Dest = Join-Path $Target $RelPath

        if (-not (Test-Path $Source -PathType Leaf)) {
            Fail "Manifest entry is not a file in source repo: $RelPath"
        }

        if (Test-Path $Dest -PathType Leaf) {
            $Action = "update"
        }
        else {
            $Action = "create"
        }

        if (-not $Apply) {
            Write-Output "DRY-RUN $Action $RelPath"
            return
        }

        Backup-ExistingFile $RelPath
        $DestParent = Split-Path $Dest -Parent
        if (-not (Test-Path $DestParent -PathType Container)) {
            New-Item -ItemType Directory -Path $DestParent -Force | Out-Null
        }

        Copy-Item $Source $Dest -Force
        Write-Output "$Action $RelPath"
    }

    function Sync-Entry([string]$Entry) {
        $Source = Join-Path $SourceDir $Entry
        if (Test-Path $Source -PathType Container) {
            Get-ChildItem -Path $Source -Recurse -File | Sort-Object FullName | ForEach-Object {
                $Rel = Resolve-RelativePath $SourceDir $_.FullName
                Copy-OneFile $Rel
            }
        }
        else {
            Copy-OneFile $Entry
        }
    }

    Get-Content $ManifestFile | ForEach-Object {
        $Line = ($_ -replace '#.*$', '').Trim()
        if (Test-SafeManifestEntry $Line) {
            Sync-Entry $Line
        }
    }

    Write-Output "==> Harness update finished."
}
finally {
    if (Test-Path $TempDir -PathType Container) {
        Remove-Item $TempDir -Recurse -Force
    }
}

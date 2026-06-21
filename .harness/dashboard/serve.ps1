param(
    [int]$Port = 8777,
    [switch]$NoBrowser
)

# Harness board launcher (ASCII-only on purpose: Windows PowerShell 5.1
# reads BOM-less scripts in the ANSI codepage, so non-ASCII here breaks parsing).

$ErrorActionPreference = "Stop"
$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$Server = Join-Path $ScriptDir "server.py"

$python = (Get-Command python -ErrorAction SilentlyContinue)
if (-not $python) { $python = (Get-Command python3 -ErrorAction SilentlyContinue) }
if (-not $python) { throw "Python 3 not found. Please install Python 3 and retry." }

$url = "http://127.0.0.1:$Port"
if (-not $NoBrowser) {
    Start-Process $url | Out-Null
}

& $python.Source $Server --port $Port

<#
.SYNOPSIS
  Windows PowerShell wrapper for codex-keysmith.

.DESCRIPTION
  This wrapper only locates Python and forwards all arguments to codex-instruct.py.
  It intentionally does not add write-confirmation flags, does not copy files,
  does not overwrite Codex configuration, and does not modify Codex binaries,
  hooks, network, or running processes. The Python CLI keeps the dry-run /
  explicit confirmation behavior.
#>
[CmdletBinding()]
param(
  [Parameter(ValueFromRemainingArguments = $true)]
  [string[]] $KeysmithArgs
)

$ErrorActionPreference = 'Stop'
$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$RepoRoot = Split-Path -Parent $ScriptDir
$PythonCli = Join-Path $RepoRoot 'codex-instruct.py'

if (-not (Test-Path -LiteralPath $PythonCli -PathType Leaf)) {
  throw "Cannot find codex-instruct.py at $PythonCli"
}

function Test-PythonCandidate {
  param([string] $Path)
  if ([string]::IsNullOrWhiteSpace($Path)) { return $false }
  try {
    & $Path --version *> $null
    return ($LASTEXITCODE -eq 0)
  } catch {
    return $false
  }
}

function Invoke-PythonCli {
  param([string] $PythonCommand)
  & $PythonCommand $PythonCli @KeysmithArgs
  return $LASTEXITCODE
}

$candidates = @()
if ($env:CODEX_KEYSMITH_PYTHON) { $candidates += $env:CODEX_KEYSMITH_PYTHON }
$localVenvPython = Join-Path $RepoRoot '.venv\Scripts\python.exe'
if (Test-Path -LiteralPath $localVenvPython -PathType Leaf) { $candidates += $localVenvPython }
if ($env:VIRTUAL_ENV) {
  $activeVenvPython = Join-Path $env:VIRTUAL_ENV 'Scripts\python.exe'
  if (Test-Path -LiteralPath $activeVenvPython -PathType Leaf) { $candidates += $activeVenvPython }
}

foreach ($candidate in $candidates) {
  if (Test-PythonCandidate $candidate) {
    exit (Invoke-PythonCli $candidate)
  }
}

$python = Get-Command python -ErrorAction SilentlyContinue
if ($python -and (Test-PythonCandidate $python.Source)) {
  exit (Invoke-PythonCli $python.Source)
}

$python3 = Get-Command python3 -ErrorAction SilentlyContinue
if ($python3 -and (Test-PythonCandidate $python3.Source)) {
  exit (Invoke-PythonCli $python3.Source)
}

$py = Get-Command py -ErrorAction SilentlyContinue
if ($py) {
  & $py.Source -3 $PythonCli @KeysmithArgs
  exit $LASTEXITCODE
}

throw 'Python was not found. Install Python 3.8+ or run codex-instruct.py manually.'

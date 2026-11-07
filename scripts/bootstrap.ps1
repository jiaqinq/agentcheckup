# Recreate the dev environment for agentcheckup.
#
# The environment lives inside this folder so the whole tree can be copied to
# another machine or carried on an external drive. If the drive letter changes,
# run this script again - it rebuilds .venv in place.
#
#   powershell -ExecutionPolicy Bypass -File scripts\bootstrap.ps1
#   powershell -ExecutionPolicy Bypass -File scripts\bootstrap.ps1 -PythonExe "<path-to-python>\python.exe"
#
# Runtime note: agentcheckup itself has zero dependencies. You only need this
# environment for the test suite and the linter.

param(
    [string]$PythonExe = ""
)

$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
Set-Location $root

Write-Host "==> project root: $root"

$recreate = Test-Path ".venv"
if ($recreate) {
    Write-Host "==> .venv exists, recreating in place (this is what fixes a changed drive letter)"
}

# --------------------------------------------------------------------------
# Find a usable Python.
#
# Windows has two traps here: `python` on PATH is often the Microsoft Store
# stub that exits 9009, and `py` is missing entirely on conda-only installs.
# So: probe launchers, then well-known install paths, and let the caller
# override with -PythonExe.
# --------------------------------------------------------------------------

$candidates = @()
if ($PythonExe) {
    $candidates += , @($PythonExe, @())
}

if (Get-Command py -ErrorAction SilentlyContinue) {
    $candidates += , @("py", @("-3"))
}
foreach ($launcher in @("python", "python3")) {
    if (Get-Command $launcher -ErrorAction SilentlyContinue) {
        $candidates += , @($launcher, @())
    }
}

# Every location below is derived from an environment variable. No drive letters
# and no machine-specific paths: hardcoding those would leak the author's setup
# and fail on everyone else's, and a fallback list that only works on one machine
# is worse than no fallback list.
$versionDirs = @("Python313", "Python312", "Python311", "Python310")
$roots = @(
    (Join-Path $env:LOCALAPPDATA "Programs\Python"),
    (Join-Path $env:ProgramFiles "Python"),
    $env:ProgramData,
    $env:USERPROFILE,
    (Join-Path $env:USERPROFILE "anaconda3"),
    (Join-Path $env:USERPROFILE "miniconda3")
) | Where-Object { $_ }

$knownPaths = @()
foreach ($base in $roots) {
    foreach ($dir in $versionDirs) {
        $knownPaths += Join-Path $base "$dir\python.exe"
    }
    foreach ($conda in @("Anaconda3", "Miniconda3", "anaconda3", "miniconda3")) {
        $knownPaths += Join-Path $base "$conda\python.exe"
    }
    $knownPaths += Join-Path $base "python.exe"
}

# Conda is often installed at the root of some drive, and which drive differs per
# machine. Enumerating mounted drives finds it without naming one.
foreach ($drive in (Get-PSDrive -PSProvider FileSystem -ErrorAction SilentlyContinue).Root) {
    foreach ($name in @("Anaconda3", "Miniconda3", "Anaconda", "Miniconda", "Python313", "Python312")) {
        $knownPaths += Join-Path $drive "$name\python.exe"
    }
}
foreach ($path in $knownPaths) {
    if (Test-Path $path) {
        $candidates += , @($path, @())
    }
}

$pythonExe = $null
$pythonArgs = @()
$tried = @()

foreach ($c in $candidates) {
    $exe = $c[0]
    $argList = @($c[1])
    $probe = $argList + @("--version")
    try {
        $version = & $exe @probe 2>&1
        $code = $LASTEXITCODE
    } catch {
        $tried += "$exe (not runnable)"
        continue
    }
    $text = "$version".Trim()
    if ($code -eq 0 -and $text -match "Python 3\.(1[0-9]|[0-9])\.") {
        $pythonExe = $exe
        $pythonArgs = $argList
        Write-Host "==> using $exe $($argList -join ' ') -> $text"
        break
    }
    $tried += "$exe -> $text"
}

if (-not $pythonExe) {
    Write-Host ""
    Write-Host "error: no usable Python 3.10+ found. Tried:" -ForegroundColor Red
    foreach ($t in $tried) { Write-Host "  - $t" }
    Write-Host ""
    Write-Host "Fix one of these:"
    Write-Host "  1. Install Python 3.12 from https://www.python.org/downloads/"
    Write-Host "     (tick 'Add python.exe to PATH' in the installer)"
    Write-Host "  2. Or point this script at an existing interpreter:"
    Write-Host "     powershell -ExecutionPolicy Bypass -File scripts\bootstrap.ps1 -PythonExe `"<path-to-python>\python.exe`""
    exit 1
}

# `venv --clear` recreates the environment in place. It is safer than a recursive
# delete (which some environments block outright) and faster, because the
# interpreter is reused instead of recopied.
$venvArgs = @()
if ($recreate) { $venvArgs += "--clear" }
$venvArgs += ".venv"
& $pythonExe @pythonArgs -m venv @venvArgs
if ($LASTEXITCODE -ne 0) {
    Write-Error "venv creation failed (exit $LASTEXITCODE)"
}

$venvPython = Join-Path $root ".venv\Scripts\python.exe"
if (-not (Test-Path $venvPython)) {
    Write-Error "venv creation failed: $venvPython not found"
}

& $venvPython -m pip install --upgrade --quiet pip
& $venvPython -m pip install --quiet pytest ruff

Write-Host ""
Write-Host "==> environment ready" -ForegroundColor Green
Write-Host "    activate:  .venv\Scripts\Activate.ps1"
Write-Host "    test:      .venv\Scripts\python.exe -m pytest -q"
Write-Host "    lint:      .venv\Scripts\python.exe -m ruff check ."
Write-Host "    run:       `$env:PYTHONPATH='src'; .venv\Scripts\python.exe -m agentcheckup rules"

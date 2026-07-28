[CmdletBinding()]
param(
    [switch]$NoLaunch
)

$ErrorActionPreference = 'Stop'
$projectRoot = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
$venvRoot = Join-Path $projectRoot '.venv'
$venvPython = Join-Path $venvRoot 'Scripts\python.exe'
$codeslicer = Join-Path $venvRoot 'Scripts\codeslicer.exe'

if (-not (Test-Path -LiteralPath $venvPython)) {
    Write-Host 'Creating isolated CodeSlicer environment...' -ForegroundColor Cyan
    & py -3 -m venv $venvRoot
    if ($LASTEXITCODE -ne 0) { throw 'Unable to create .venv. Install Python 3.10+ with the Python launcher.' }
}

Write-Host 'Installing CodeSlicer...' -ForegroundColor Cyan
& $venvPython -m pip install --upgrade pip
if ($LASTEXITCODE -ne 0) { throw 'Unable to update pip.' }
& $venvPython -m pip install $projectRoot
if ($LASTEXITCODE -ne 0) { throw 'Unable to install CodeSlicer.' }

if ($NoLaunch) {
    Write-Host "Installed. Run: $codeslicer agent install" -ForegroundColor Green
    exit 0
}

Write-Host ''
Write-Host 'Choose IDEs with arrows and Space; press Enter to install.' -ForegroundColor Green
& $codeslicer agent install
exit $LASTEXITCODE

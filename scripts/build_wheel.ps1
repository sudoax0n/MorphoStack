# Build a MorphoStack wheel with bundled browser UI assets.
Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

$RepoRoot = Split-Path -Parent $PSScriptRoot
$WebDir = Join-Path $RepoRoot "apps\web"
$DistDir = Join-Path $WebDir "dist"

Push-Location $RepoRoot
try {
    if (-not (Test-Path (Join-Path $RepoRoot ".venv\Scripts\python.exe"))) {
        throw "MorphoStack venv not found. Run morphostack init first."
    }
    $Python = Join-Path $RepoRoot ".venv\Scripts\python.exe"

    Write-Host "Building browser UI..." -ForegroundColor Cyan
    Push-Location $WebDir
    npm run build
    Pop-Location

    if (-not (Test-Path $DistDir)) {
        throw "Web build did not produce apps/web/dist"
    }

    Write-Host "Building wheel..." -ForegroundColor Cyan
    & $Python -m pip install --upgrade build hatchling
    & $Python -m build --wheel

    Write-Host "Wheel build complete. Install with:" -ForegroundColor Green
    Write-Host "  pip install dist\morphostack-*.whl" -ForegroundColor Green
}
finally {
    Pop-Location
}
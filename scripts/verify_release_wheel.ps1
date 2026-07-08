# Build wheel and smoke-test pipx-style install in a temp venv.
param(
    [string]$WheelPath = ""
)

$ErrorActionPreference = "Stop"
$ProjectRoot = Split-Path -Parent $PSScriptRoot
Set-Location $ProjectRoot

if (-not $WheelPath) {
    & "$ProjectRoot\scripts\build_wheel.ps1"
    $WheelPath = Get-ChildItem -Path "$ProjectRoot\dist" -Filter "morphostack-*.whl" |
        Sort-Object LastWriteTime -Descending |
        Select-Object -First 1 -ExpandProperty FullName
}

if (-not (Test-Path $WheelPath)) {
    throw "Wheel not found: $WheelPath"
}

$venvDir = Join-Path $env:TEMP "morphostack-wheel-verify"
if (Test-Path $venvDir) {
    Remove-Item -Recurse -Force $venvDir
}
python -m venv $venvDir
$python = Join-Path $venvDir "Scripts\python.exe"
& $python -m pip install --upgrade pip
& $python -m pip install "$WheelPath[all]"
& $python -m morphostack doctor
& $python -c "from morphostack.cli.main import resolve_web_dist_dir; p = resolve_web_dist_dir(); assert p.exists(), p; print('web static:', p)"

Write-Host "Wheel verification passed: $WheelPath"
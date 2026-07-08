# Capture MorphoStack goal verification evidence to scratch dir.
$Scratch = "E:\Temp\grok-goal-e4ba54d35000\implementer"
$Repo = Split-Path -Parent $PSScriptRoot
New-Item -ItemType Directory -Force -Path $Scratch | Out-Null
Set-Location $Repo

git status --short | Out-File -FilePath (Join-Path $Scratch "git-status.txt") -Encoding utf8

& .\.venv\Scripts\python -m pytest -q 2>&1 | Tee-Object -FilePath (Join-Path $Scratch "pytest.log")

Push-Location apps\web
npm run build 2>&1 | Tee-Object -FilePath (Join-Path $Scratch "web-build.log")
Pop-Location

$cliLog = Join-Path $Scratch "cli-launch.log"
& .\.venv\Scripts\morphostack doctor 2>&1 | Out-File -FilePath $cliLog -Encoding utf8
& .\.venv\Scripts\morphostack inspect "D:\lab-data\paper-data\syst202400052-sup-0001-movie1-dopc.tif" 2>&1 | Out-File -FilePath $cliLog -Append -Encoding utf8
if (Test-Path "D:\rbc data pranay\Image 46.lsm") {
    & .\.venv\Scripts\morphostack inspect "D:\rbc data pranay\Image 46.lsm" 2>&1 | Out-File -FilePath $cliLog -Append -Encoding utf8
}

Get-ChildItem -Recurse validation\runs -Include manifest.json,report.md,metrics.csv,mesh.obj,README.md |
    Select-Object -ExpandProperty FullName |
    Out-File -FilePath (Join-Path $Scratch "validation-runs.txt") -Encoding utf8

& .\.venv\Scripts\python -m pytest tests/test_core_export.py tests/test_core_io.py -q 2>&1 |
    Out-File -FilePath (Join-Path $Scratch "calibration-tests.log") -Encoding utf8

& .\.venv\Scripts\python -m pytest tests/test_core_object_seed.py tests/test_core_tracking_diagnostics.py -q 2>&1 |
    Out-File -FilePath (Join-Path $Scratch "object-seed-tests.log") -Encoding utf8

$meshLog = Join-Path $Scratch "mesh-export.log"
& .\.venv\Scripts\python -m pytest tests/test_api.py::test_mesh_export_writes_obj_with_seed_and_z_range tests/test_cli.py::test_analyze_writes_mesh_export_with_z_range_and_seed -q 2>&1 |
    Out-File -FilePath $meshLog -Encoding utf8
$sampleObj = Get-ChildItem -Recurse validation\runs -Filter mesh.obj | Select-Object -First 1
if ($sampleObj) {
    "Sample mesh: $($sampleObj.FullName)" | Out-File -FilePath $meshLog -Append -Encoding utf8
    Get-Content $sampleObj.FullName -TotalCount 5 | Out-File -FilePath $meshLog -Append -Encoding utf8
}

$docsEvidence = Join-Path $Scratch "docs-ui-evidence.txt"
@(
    "=== main.ts calibration / tracking hooks ===",
    (Select-String -Path apps\web\src\main.ts -Pattern "voxelSourceMarkup|show-tracking-debug|globalPreviewFrameIndex|calibration-help" | ForEach-Object { $_.Line }),
    "",
    "=== docs mentions ===",
    (Select-String -Path README.md,docs\*.md -Pattern "object selection|calibration|validation|troubleshooting|Active Surfaces" | ForEach-Object { "$($_.Filename):$($_.LineNumber):$($_.Line)" })
) | Out-File -FilePath $docsEvidence -Encoding utf8

try {
    & .\.venv\Scripts\morphostack dev --check 2>&1 | Out-File -FilePath (Join-Path $Scratch "api-launch.log") -Encoding utf8
} catch {
    "dev --check failed: $_" | Out-File -FilePath (Join-Path $Scratch "api-launch.log") -Encoding utf8
}

Write-Host "Verification evidence written to $Scratch"
<#
.SYNOPSIS
    MorphoStack real-data validation for DOPC Movie 1.

.DESCRIPTION
    Runs the full MorphoStack analysis pipeline on the DOPC supplementary movie
    (syst202400052-sup-0001-movie1-dopc.tif) and writes outputs to:
        D:\MorphoStack\validation\runs\dopc-smoke-test\

    Outputs produced:
        metrics.csv       -- Per-frame 2D shape metrics
        metrics_mesh.csv  -- Per-frame metrics including 3D mesh columns
        manifest.json     -- Run provenance and checksums
        report.md         -- Markdown summary report
        sweep.csv         -- Threshold sweep (20..80 step 10)
        summary.json      -- Short JSON summary of key statistics
        threshold.txt     -- Auto-suggested threshold value

    CALIBRATION DISCLAIMER:
        Surface area and volume are computational outputs using the configured
        voxel size (default: 1.0 um/pixel). Biological interpretation requires
        verified microscope calibration from the original acquisition metadata
        or instrument log.

.NOTES
    Run from D:\MorphoStack:
        .\scripts\validate_dopc.ps1
#>

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------
$RepoRoot    = Split-Path -Parent $PSScriptRoot
$Morpho      = Join-Path $RepoRoot ".venv\Scripts\morphostack.exe"
$DataFile    = "D:\lab-data\paper-data\syst202400052-sup-0001-movie1-dopc.tif"
$OutDir      = Join-Path $RepoRoot "validation\runs\dopc-smoke-test"
# Note: --bundle-dir creates a per-source subdirectory (named after the input stem).
# e.g. dopc-smoke-test/syst202400052-sup-0001-movie1-dopc/metrics.csv
$BundleSubDir = Join-Path $OutDir "syst202400052-sup-0001-movie1-dopc"
$SummaryJson = Join-Path $OutDir "summary.json"
$ThreshTxt   = Join-Path $OutDir "threshold.txt"

# ---------------------------------------------------------------------------
# Preflight
# ---------------------------------------------------------------------------
Write-Host ""
Write-Host "============================================================" -ForegroundColor Cyan
Write-Host "  MorphoStack DOPC Real-Data Validation" -ForegroundColor Cyan
Write-Host "============================================================" -ForegroundColor Cyan
Write-Host ""

if (-not (Test-Path $Morpho)) {
    Write-Error "morphostack CLI not found at: $Morpho"
    Write-Host "Ensure the venv is active and morphostack is installed (pip install -e .[analysis])."
    exit 1
}

if (-not (Test-Path $DataFile)) {
    Write-Error "Test data file not found: $DataFile"
    exit 1
}

# Create output directory
New-Item -ItemType Directory -Force $OutDir | Out-Null
Write-Host "Output directory: $OutDir" -ForegroundColor Green
Write-Host ""

# ---------------------------------------------------------------------------
# Step 0: Stack inspection
# ---------------------------------------------------------------------------
Write-Host "[1/6] Inspecting stack..." -ForegroundColor Yellow
$InspectOut = & $Morpho inspect $DataFile 2>&1
Write-Host $InspectOut
Write-Host ""

# ---------------------------------------------------------------------------
# Step 1: Auto-threshold suggestion
# ---------------------------------------------------------------------------
Write-Host "[2/6] Suggesting threshold (Otsu)..." -ForegroundColor Yellow
$ThreshOut = & $Morpho threshold $DataFile --method otsu 2>&1
Write-Host $ThreshOut

# Parse threshold value from output
$ThreshLine = ($ThreshOut | Where-Object { $_ -match "Threshold:" }) | Select-Object -First 1
if ($ThreshLine -match "Threshold:\s*([0-9.]+)") {
    $AutoThreshold = [double]$Matches[1]
} else {
    # Fallback: use a reasonable default for GUV images
    $AutoThreshold = 30.0
    Write-Host "  Could not parse threshold from output; using fallback: $AutoThreshold" -ForegroundColor Yellow
}
Write-Host "  Using threshold: $AutoThreshold" -ForegroundColor Green
$AutoThreshold | Set-Content -Path $ThreshTxt -Encoding UTF8
Write-Host ""

# ---------------------------------------------------------------------------
# CALIBRATION DISCLAIMER
# ---------------------------------------------------------------------------
Write-Host "  CALIBRATION NOTICE:" -ForegroundColor Magenta
Write-Host "  Surface area and volume are computational outputs using voxel size" -ForegroundColor Magenta
Write-Host "  default=1.0 um. Biological interpretation requires verified" -ForegroundColor Magenta
Write-Host "  microscope calibration from the original acquisition metadata." -ForegroundColor Magenta
Write-Host ""

# ---------------------------------------------------------------------------
# Step 2: Analysis without mesh (fast)
# ---------------------------------------------------------------------------
Write-Host "[3/6] Running analysis (no mesh, fast)..." -ForegroundColor Yellow
# --bundle-dir creates: <OutDir>/<stem>/metrics.csv, manifest.json, report.md
$CsvNoMesh = Join-Path $BundleSubDir "metrics.csv"
& $Morpho analyze $DataFile `
    --threshold $AutoThreshold `
    --profile vesicle `
    --bundle-dir $OutDir `
    --report `
    --no-mesh 2>&1 | Write-Host

if (-not (Test-Path $CsvNoMesh)) {
    Write-Warning "metrics.csv was not produced at expected path: $CsvNoMesh"
    Write-Warning "Check: $BundleSubDir"
}
Write-Host ""

# ---------------------------------------------------------------------------
# Step 3: Analysis WITH 3D mesh
# ---------------------------------------------------------------------------
Write-Host "[4/6] Running analysis WITH 3D mesh (slower)..." -ForegroundColor Yellow
$CsvMesh = Join-Path $OutDir "metrics_mesh.csv"
$ManifestMesh = Join-Path $OutDir "manifest_mesh.json"
& $Morpho analyze $DataFile `
    --threshold $AutoThreshold `
    --profile vesicle `
    --out $CsvMesh `
    --manifest $ManifestMesh `
    --mesh 2>&1 | Write-Host

if (-not (Test-Path $CsvMesh)) {
    Write-Warning "metrics_mesh.csv was not produced. Check the output above."
}
Write-Host ""

# ---------------------------------------------------------------------------
# Step 4: Threshold sweep
# ---------------------------------------------------------------------------
Write-Host "[5/6] Running threshold sweep (20..80 step 10)..." -ForegroundColor Yellow
$SweepCsv = Join-Path $OutDir "sweep.csv"
& $Morpho sweep $DataFile `
    --start 20 --stop 80 --step 10 `
    --profile vesicle `
    --out $SweepCsv 2>&1 | Write-Host

if (-not (Test-Path $SweepCsv)) {
    Write-Warning "sweep.csv was not produced. Check the output above."
}
Write-Host ""

# ---------------------------------------------------------------------------
# Step 5: Build summary JSON
# ---------------------------------------------------------------------------
Write-Host "[6/6] Writing summary JSON..." -ForegroundColor Yellow

# The no-mesh bundle manifest is in the sub-directory
$ManifestJson = Join-Path $BundleSubDir "manifest.json"
$FrameCount   = 0
$ValidFrames  = 0
$MeshSA       = $null
$MeshVol      = $null
$MeshSph      = $null
$VoxelSource  = "unknown"

if (Test-Path $ManifestJson) {
    $manifest    = Get-Content $ManifestJson -Raw | ConvertFrom-Json
    $FrameCount  = $manifest.frame_count
    $ValidFrames = $manifest.valid_frame_count
    $VoxelSource = $manifest.voxel_source
    if ($manifest.PSObject.Properties["mesh_surface_area_um2"]) {
        $MeshSA  = $manifest.mesh_surface_area_um2
        $MeshVol = $manifest.mesh_volume_um3
        $MeshSph = $manifest.mesh_sphericity
    }
}

$Summary = [ordered]@{
    "generated_at"       = (Get-Date -Format "o")
    "input_file"         = $DataFile
    "threshold_used"     = $AutoThreshold
    "voxel_size_um"      = "1.0 x 1.0 x 1.0 (default)"
    "voxel_source"       = $VoxelSource
    "calibration_note"   = "Surface area and volume are computational outputs using the configured voxel size; biological interpretation requires verified microscope calibration."
    "frame_count"        = $FrameCount
    "valid_frame_count"  = $ValidFrames
    "mesh_surface_area_um2"  = $MeshSA
    "mesh_volume_um3"        = $MeshVol
    "mesh_sphericity"        = $MeshSph
    "outputs" = [ordered]@{
        "metrics_csv"       = $CsvNoMesh
        "metrics_mesh_csv"  = $CsvMesh
        "manifest_json"     = $ManifestJson
        "report_md"         = (Join-Path $BundleSubDir "report.md")
        "sweep_csv"         = $SweepCsv
        "threshold_txt"     = $ThreshTxt
        "summary_json"      = $SummaryJson
    }
}

$Summary | ConvertTo-Json -Depth 4 | Set-Content -Path $SummaryJson -Encoding UTF8
Write-Host "  Summary written to: $SummaryJson" -ForegroundColor Green

# ---------------------------------------------------------------------------
# Final report
# ---------------------------------------------------------------------------
Write-Host ""
Write-Host "============================================================" -ForegroundColor Cyan
Write-Host "  Validation Complete" -ForegroundColor Cyan
Write-Host "============================================================" -ForegroundColor Cyan
Write-Host ""
Write-Host "  Input  : $DataFile"
Write-Host "  Output : $OutDir"
Write-Host "  Threshold used : $AutoThreshold"
Write-Host ""
Write-Host "  Files produced:" -ForegroundColor Green
Get-ChildItem $OutDir -File | Sort-Object Name | ForEach-Object {
    $size = [math]::Round($_.Length / 1KB, 1)
    Write-Host ("    {0,-35} {1,7} KB" -f $_.Name, $size)
}
Write-Host ""
Write-Host "  CALIBRATION REMINDER:" -ForegroundColor Magenta
Write-Host "  All area/volume/surface-area values use voxel size 1.0 um/pixel." -ForegroundColor Magenta
Write-Host "  Update --voxel-x/y/z once real calibration is confirmed." -ForegroundColor Magenta
Write-Host ""
Write-Host "  Next steps:" -ForegroundColor Cyan
Write-Host "    1. Open validation\runs\dopc-smoke-test\metrics.csv" -ForegroundColor Cyan
Write-Host "    2. Check valid_frame_count in manifest.json" -ForegroundColor Cyan
Write-Host "    3. Inspect area/circularity trends per frame" -ForegroundColor Cyan
Write-Host "    4. Compare against D:\Shape-Analysis reference manually" -ForegroundColor Cyan
Write-Host "    5. Update validation\reports\dopc-vs-reference.md with results" -ForegroundColor Cyan
Write-Host ""

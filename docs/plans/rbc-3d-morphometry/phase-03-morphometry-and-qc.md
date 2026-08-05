# Phase 3: RBC Morphometry and QC Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use `superpowers:subagent-driven-development` or `superpowers:executing-plans` to implement this packet task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Produce rotation-safe RBC morphology, fail-closed capability assignment, and measured 3D metrics from accepted occupancy and scientific meshes.

**Architecture:** Keep metric calculation pure and separate from capability policy. A central QC evaluator consumes calibration, slice association, topology, stack coverage, and mesh diagnostics; only its accepted result can promote occupancy to measured authority.

**Tech Stack:** NumPy linear algebra, scikit-image marching cubes, existing MorphoStack authority types, pytest, deterministic physical-coordinate phantoms.

## Global Constraints

- This packet implements master requirements R7-R11 and depends on Phases 1-2.
- Never release volume or surface area when calibration or completeness fails.
- Keep `deformation_index` only for explicit legacy compatibility outside normal RBC output.
- Do not report dimple thickness, rim thickness, or biconcavity score until a validated surface representation supports them.
- Record all metric definitions and methods in manifests and reports.
- Do not smooth the scientific mesh to improve appearance; display processing remains derivative-only.

---

## File Structure

- Create `src/morphostack/core/rbc_metrics.py` for physical-coordinate 2D and permitted 3D metric functions.
- Create `src/morphostack/core/rbc_qc.py` for capability evaluation and withholding reasons.
- Extend `src/morphostack/core/rbc_models.py` with metric and QC result dataclasses.
- Modify `src/morphostack/core/mesh.py` to expose occupancy volume and mesh validity checks without weakening existing authority rules.
- Modify `src/morphostack/core/pipeline.py` to attach RBC metrics, capability, authority, and reasons.
- Create `tests/test_rbc_morphometry.py`; extend mesh, pipeline, and authority tests.

---

### Task 1: Implement moment-equivalent RBC 2D metrics

**Files:**

- Create: `src/morphostack/core/rbc_metrics.py`
- Modify: `src/morphostack/core/rbc_models.py`
- Create: `tests/test_rbc_morphometry.py`

**Interfaces:**

- Produces: `RbcProjectedMetrics` and `measure_rbc_projected_mask(mask, voxel) -> RbcProjectedMetrics`.
- Fields: projected area, calibrated perimeter, major axis L, minor axis W, `aspect_ratio_L_over_W`, `static_elongation_index`, circularity, solidity, and equivalent diameter.

- [ ] **Step 1: Write failing rotation and anisotropy tests**

```python
@pytest.mark.parametrize("angle", [0, 17, 43, 79])
def test_moment_axes_are_rotation_invariant(angle):
    mask = rotated_ellipse_mask(major_um=8.0, minor_um=5.0, angle_deg=angle, voxel=VOXEL)
    result = measure_rbc_projected_mask(mask, VOXEL)
    assert result.major_axis_um == pytest.approx(8.0, rel=0.02)
    assert result.minor_axis_um == pytest.approx(5.0, rel=0.02)
    assert result.aspect_ratio_L_over_W == pytest.approx(1.6, rel=0.03)


def test_static_elongation_uses_named_formula():
    result = measure_rbc_projected_mask(ellipse_mask(8.0, 4.0), VOXEL)
    assert result.static_elongation_index == pytest.approx((8.0 - 4.0) / (8.0 + 4.0), rel=0.03)
```

- [ ] **Step 2: Run tests and verify the RBC metric module is missing**

Run: `.\.venv\Scripts\pytest tests\test_rbc_morphometry.py -k "moment or elongation" -q`

Expected: collection fails because the RBC metrics API does not exist.

- [ ] **Step 3: Implement second moments in physical coordinates**

```python
def measure_rbc_projected_mask(mask: np.ndarray, voxel: VoxelSize) -> RbcProjectedMetrics:
    yy, xx = np.nonzero(mask)
    points_um = np.column_stack((xx * voxel.x_um, yy * voxel.y_um))
    centered = points_um - points_um.mean(axis=0)
    covariance = centered.T @ centered / len(centered)
    eigenvalues = np.linalg.eigvalsh(covariance)[::-1]
    major_axis_um, minor_axis_um = 4.0 * np.sqrt(eigenvalues)
    aspect = major_axis_um / minor_axis_um
    static_elongation = (major_axis_um - minor_axis_um) / (major_axis_um + minor_axis_um)
```

Use calibrated Crofton or ordered subpixel contour perimeter through the existing installed stack. Document the exact perimeter method in the returned dataclass.

- [ ] **Step 4: Run metric tests**

Run: `.\.venv\Scripts\pytest tests\test_rbc_morphometry.py tests\test_core_metrics.py -q`

Expected: PASS; existing generic contour metrics remain unchanged for compatibility.

- [ ] **Step 5: Commit RBC projected metrics**

```powershell
git add src/morphostack/core/rbc_metrics.py src/morphostack/core/rbc_models.py tests/test_rbc_morphometry.py tests/test_core_metrics.py
git commit -m "feat: add rotation-safe RBC projected metrics"
```

---

### Task 2: Implement central RBC reconstruction QC

**Files:**

- Create: `src/morphostack/core/rbc_qc.py`
- Modify: `src/morphostack/core/rbc_models.py`
- Test: `tests/test_rbc_morphometry.py`

**Interfaces:**

- Consumes: `CalibrationAssessment`, `RbcStackCandidate`, source-stack shape, selected Z range, clipping/merge diagnostics, and mesh diagnostics.
- Produces: `evaluate_rbc_reconstruction(...) -> RbcQcResult` containing highest permitted capability and ordered withholding reasons.

- [ ] **Step 1: Write a failing QC decision table**

```python
@pytest.mark.parametrize(
    ("case", "expected_capability", "reason"),
    [
        ("complete", RbcCapability.VALIDATED_3D_OCCUPANCY, None),
        ("missing_z_axis", RbcCapability.PIXEL_PREVIEW, RbcQcIssue.CALIBRATION_UNVERIFIED),
        ("touches_first_slice", RbcCapability.CALIBRATED_2D, RbcQcIssue.INCOMPLETE_CAP),
        ("internal_gap", RbcCapability.CALIBRATED_2D, RbcQcIssue.INTERNAL_GAP),
        ("lateral_clip", RbcCapability.CALIBRATED_2D, RbcQcIssue.LATERAL_CLIPPING),
        ("merge", RbcCapability.CALIBRATED_2D, RbcQcIssue.UNRESOLVED_MERGE),
    ],
)
def test_qc_capability_table(case, expected_capability, reason):
    result = evaluate_rbc_reconstruction(make_qc_case(case))
    assert result.capability is expected_capability
    assert reason is None or reason in result.issues
```

- [ ] **Step 2: Run QC tests and verify failure**

Run: `.\.venv\Scripts\pytest tests\test_rbc_morphometry.py -k "qc or capability" -q`

Expected: FAIL because no central RBC reconstruction evaluator exists.

- [ ] **Step 3: Implement deterministic fail-closed QC**

Check per-axis calibration, explicit seed, first/last valid slice relative to selected and source Z bounds, internal gaps, lateral clipping, unresolved merge, loop-rasterization agreement, and bidirectional Z-linking agreement. Return the highest defensible capability; do not return a boolean that forces consumers to infer permissions.

- [ ] **Step 4: Run QC tests**

Run: `.\.venv\Scripts\pytest tests\test_rbc_morphometry.py -k "qc or capability" -q`

Expected: PASS with stable reason ordering for deterministic reports.

- [ ] **Step 5: Commit central QC**

```powershell
git add src/morphostack/core/rbc_qc.py src/morphostack/core/rbc_models.py tests/test_rbc_morphometry.py
git commit -m "feat: gate RBC capability with reconstruction QC"
```

---

### Task 3: Measure accepted occupancy and validate scientific mesh

**Files:**

- Modify: `src/morphostack/core/mesh.py`
- Modify: `src/morphostack/core/rbc_metrics.py`
- Test: `tests/test_core_mesh.py`
- Test: `tests/test_rbc_morphometry.py`
- Test: `tests/test_result_authority.py`

**Interfaces:**

- Produces: `measure_rbc_occupancy(mask, voxel) -> RbcVolumeCrossCheck` and `validate_rbc_scientific_mesh(mesh, occupancy) -> RbcMeshQc`.
- The scientific mesh is derived only from an accepted full-resolution `AuthoritativeMask`.

- [ ] **Step 1: Write failing volume, surface, and authority tests**

```python
def test_biconcave_phantom_volume_matches_voxel_truth():
    mask, expected_volume = analytic_biconcave_phantom(voxel=VoxelSize(0.08, 0.08, 0.16))
    result = measure_rbc_occupancy(mask, VoxelSize(0.08, 0.08, 0.16))
    assert result.voxel_volume_um3 == pytest.approx(expected_volume, rel=0.03)
    assert result.mesh_volume_um3 == pytest.approx(expected_volume, rel=0.06)


def test_display_mesh_cannot_supply_rbc_measurement():
    with pytest.raises(ResultAuthorityError):
        measure_rbc_mesh(display_mesh_fixture())
```

- [ ] **Step 2: Run mesh tests and verify failure**

Run: `.\.venv\Scripts\pytest tests\test_core_mesh.py tests\test_result_authority.py tests\test_rbc_morphometry.py -k "biconcave or authority or volume" -q`

Expected: FAIL because occupancy cross-check and RBC mesh QC do not exist.

- [ ] **Step 3: Implement occupancy and mesh checks**

Compute voxel volume as `count_nonzero(mask) * x_um * y_um * z_um`. Derive the complete un-smoothed scientific mesh through the existing authority path. Record watertight boundary-edge count, finite coordinates, face orientation/volume sign, connected components, and relative voxel-versus-mesh volume disagreement. Withhold 3D capability when required checks fail.

- [ ] **Step 4: Run mesh and authority tests**

Run: `.\.venv\Scripts\pytest tests\test_core_mesh.py tests\test_result_authority.py tests\test_rbc_morphometry.py -q`

Expected: PASS; display simplification never changes reported measurements.

- [ ] **Step 5: Commit measured 3D morphometry**

```powershell
git add src/morphostack/core/mesh.py src/morphostack/core/rbc_metrics.py tests/test_core_mesh.py tests/test_result_authority.py tests/test_rbc_morphometry.py
git commit -m "feat: measure validated RBC occupancy"
```

---

### Task 4: Attach capability-scoped metrics to stack analysis

**Files:**

- Modify: `src/morphostack/core/rbc_models.py`
- Modify: `src/morphostack/core/pipeline.py`
- Test: `tests/test_core_pipeline.py`
- Test: `tests/test_rbc_morphometry.py`

**Interfaces:**

- Produces: `RbcAnalysisResult` with calibration, capability, authority, projected metrics, optional occupancy metrics, optional surface metrics, QC issues, and method versions.
- Fields unsupported by the assigned capability remain `None`.

- [ ] **Step 1: Write failing capability-scoped serialization tests**

```python
def test_calibrated_2d_result_has_no_3d_metrics():
    result = analyze_rbc(incomplete_cap_stack())
    assert result.capability is RbcCapability.CALIBRATED_2D
    assert result.projected_metrics is not None
    assert result.volume_um3 is None
    assert result.surface_area_um2 is None


def test_validated_occupancy_result_reports_measured_volume():
    result = analyze_rbc(complete_biconcave_stack())
    assert result.authority is RbcAuthority.MEASURED
    assert result.capability is RbcCapability.VALIDATED_3D_OCCUPANCY
    assert result.volume_um3 is not None
    assert result.dimple_thickness_um is None
```

- [ ] **Step 2: Run pipeline tests and verify failure**

Run: `.\.venv\Scripts\pytest tests\test_core_pipeline.py tests\test_rbc_morphometry.py -k "capability or metrics" -q`

Expected: FAIL because current `StackAnalysis` exposes generic mesh values without RBC capability scoping.

- [ ] **Step 3: Add the typed RBC analysis result**

Create the result only for `profile="rbc"`. Retain existing generic `StackAnalysis` fields for non-RBC compatibility, but prevent RBC consumers from treating legacy mesh fields as authoritative.

- [ ] **Step 4: Run Phase 3 verification**

```powershell
.\.venv\Scripts\pytest tests\test_rbc_morphometry.py tests\test_rbc_topology.py tests\test_core_metrics.py tests\test_core_mesh.py tests\test_result_authority.py tests\test_core_pipeline.py -q
```

Expected: PASS with no populated metric above the assigned capability.

- [ ] **Step 5: Commit capability-scoped results**

```powershell
git add src/morphostack/core/rbc_models.py src/morphostack/core/pipeline.py tests/test_core_pipeline.py tests/test_rbc_morphometry.py
git commit -m "feat: expose capability-scoped RBC morphometry"
```

---

## Phase 3 Exit Gate

- RBC aspect and elongation metrics are rotation-safe and scientifically named.
- Every measured value is permitted by one explicit capability.
- Calibration, caps, gaps, clipping, merges, topology, and mesh problems withhold unsupported 3D fields.
- Voxel and mesh volumes are cross-checked and recorded.
- Dimple and rim thickness remain absent until validated surface reconstruction exists.
- Existing generic metrics and vesicle results retain compatibility.

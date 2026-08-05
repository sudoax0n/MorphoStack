# Phase 1: RBC Capability and Calibration Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use `superpowers:subagent-driven-development` or `superpowers:executing-plans` to implement this packet task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Establish typed RBC result authority, independent calibration-axis provenance, mandatory single-object selection, and one shared fail-closed input gate.

**Architecture:** Add RBC-specific contracts without changing existing vesicle result semantics. Preserve current inspection support, but stop RBC analysis before segmentation when selection or calibration requirements fail.

**Tech Stack:** Python dataclasses/enums, NumPy, tifffile, CZI metadata helpers, FastAPI validation, pytest.

## Global Constraints

- This packet implements master requirements R1-R4 and provides contracts consumed by Phases 2-4.
- A direct `.lsm` remains inspectable but cannot start RBC analysis without manual X/Y/Z calibration.
- A TIFF/OME-TIFF conversion is not trusted by extension; all axes and provenance must pass.
- Missing or withheld physical values are `None`, never `0.0` or placeholder micrometres.
- Preserve existing `ImageStack.voxel_size` and `voxel_source` compatibility while adding richer provenance.
- Do not change normal vesicle or active-surfaces gating.

---

## File Structure

- Create `src/morphostack/core/rbc_models.py` for RBC capability, authority, calibration, QC, and refusal reason types.
- Create `src/morphostack/core/rbc_capabilities.py` for pure calibration and input capability evaluation.
- Modify `src/morphostack/core/models.py` to attach optional per-axis calibration provenance to `ImageStack` without removing current fields.
- Modify `src/morphostack/core/io.py` to preserve detected, overridden, defaulted, and missing status for each axis.
- Modify `src/morphostack/core/pipeline.py` to require an RBC seed and invoke the shared input gate before segmentation.
- Modify `src/morphostack/api/app.py` and the CLI analyze entry point only enough to serialize the structured refusal.
- Create `tests/test_rbc_capabilities.py`; extend `tests/test_core_io.py`, `tests/test_core_pipeline.py`, `tests/test_api.py`, and `tests/test_cli.py`.

---

### Task 1: Define stable RBC authority and calibration contracts

**Files:**

- Create: `src/morphostack/core/rbc_models.py`
- Test: `tests/test_rbc_capabilities.py`

**Interfaces:**

- Produces: `CalibrationAxis`, `CalibrationAssessment`, `RbcCapability`, `RbcAuthority`, `RbcRefusalCode`, and `RbcInputDecision`.
- Later phases must import these types rather than recreate strings.

- [ ] **Step 1: Write failing enum and invariants tests**

```python
def test_calibration_requires_all_three_verified_axes():
    assessment = CalibrationAssessment(
        x=CalibrationAxis(0.11, "metadata", True),
        y=CalibrationAxis(0.11, "metadata", True),
        z=CalibrationAxis(1.0, "placeholder", False),
        source_format="ome-tiff",
    )
    assert not assessment.all_axes_verified


def test_estimated_authority_is_not_measured():
    assert not RbcAuthority.ESTIMATED.is_measured
    assert RbcAuthority.MEASURED.is_measured
```

- [ ] **Step 2: Run the tests and verify contract types are missing**

Run: `.\.venv\Scripts\pytest tests\test_rbc_capabilities.py -q`

Expected: collection fails because `morphostack.core.rbc_models` does not exist.

- [ ] **Step 3: Implement the contracts**

```python
class RbcCapability(str, Enum):
    PIXEL_PREVIEW = "PIXEL_PREVIEW"
    CALIBRATED_2D = "2D_OUTER_CONTOUR"
    VALIDATED_3D_OCCUPANCY = "3D_OCCUPANCY_VALIDATED"
    VALIDATED_3D_SURFACE = "3D_SURFACE_VALIDATED"


class RbcAuthority(str, Enum):
    MEASURED = "MEASURED"
    ESTIMATED = "ESTIMATED"
    WITHHELD = "WITHHELD"

    @property
    def is_measured(self) -> bool:
        return self is RbcAuthority.MEASURED


@dataclass(frozen=True)
class CalibrationAxis:
    value_um: float | None
    source: str
    verified: bool


@dataclass(frozen=True)
class CalibrationAssessment:
    x: CalibrationAxis
    y: CalibrationAxis
    z: CalibrationAxis
    source_format: str

    @property
    def all_axes_verified(self) -> bool:
        return all(axis.verified and axis.value_um is not None for axis in (self.x, self.y, self.z))
```

Add structured refusal codes for missing seed, direct-LSM calibration, incomplete axis calibration, and unverified converted metadata. `RbcInputDecision` must carry `allowed`, `capability`, and an ordered tuple of refusal codes.

- [ ] **Step 4: Run contract tests**

Run: `.\.venv\Scripts\pytest tests\test_rbc_capabilities.py -q`

Expected: PASS.

- [ ] **Step 5: Commit the stable contract**

```powershell
git add src/morphostack/core/rbc_models.py tests/test_rbc_capabilities.py
git commit -m "feat: define RBC capability contracts"
```

---

### Task 2: Preserve per-axis voxel provenance

**Files:**

- Modify: `src/morphostack/core/models.py`
- Modify: `src/morphostack/core/io.py`
- Test: `tests/test_core_io.py`
- Test: `tests/test_rbc_capabilities.py`

**Interfaces:**

- Consumes: `CalibrationAssessment` and `CalibrationAxis` from Task 1.
- Produces: `ImageStack.calibration` and inspection payload calibration details while retaining `voxel_size` and `voxel_source`.

- [ ] **Step 1: Add failing tests for partial TIFF metadata and overrides**

```python
def test_partial_tiff_metadata_does_not_verify_missing_z(monkeypatch, tmp_path):
    stack = load_image_stack(tmp_path / "partial.tif")
    assert stack.calibration.x.verified
    assert stack.calibration.y.verified
    assert not stack.calibration.z.verified
    assert stack.calibration.z.source == "placeholder"


def test_manual_override_verifies_all_axes(monkeypatch, tmp_path):
    stack = load_image_stack(tmp_path / "cell.lsm", voxel_override=VoxelSize(0.1, 0.1, 0.3))
    assert stack.calibration.all_axes_verified
    assert {stack.calibration.x.source, stack.calibration.y.source, stack.calibration.z.source} == {"override"}
```

- [ ] **Step 2: Run the focused I/O tests and verify failure**

Run: `.\.venv\Scripts\pytest tests\test_core_io.py tests\test_rbc_capabilities.py -q`

Expected: FAIL because `ImageStack` has no calibration assessment and partial metadata is currently completed with `1.0`.

- [ ] **Step 3: Add a compatibility-preserving calibration field**

```python
@dataclass(frozen=True)
class ImageStack:
    source_path: Path
    grayscale: np.ndarray
    color: np.ndarray
    voxel_size: VoxelSize
    voxel_source: str
    calibration: CalibrationAssessment
```

Refactor TIFF/CZI metadata parsing so every axis returns both its numeric value and provenance. Keep the effective `VoxelSize` for legacy display, but mark placeholder-filled axes unverified. Manual overrides mark all three axes verified.

- [ ] **Step 4: Run I/O and project serialization tests**

Run: `.\.venv\Scripts\pytest tests\test_core_io.py tests\test_core_project.py tests\test_rbc_capabilities.py -q`

Expected: PASS with legacy voxel fields unchanged and the new axis provenance present.

- [ ] **Step 5: Commit provenance support**

```powershell
git add src/morphostack/core/models.py src/morphostack/core/io.py tests/test_core_io.py tests/test_core_project.py tests/test_rbc_capabilities.py
git commit -m "feat: track voxel calibration by axis"
```

---

### Task 3: Implement the shared RBC input gate

**Files:**

- Create: `src/morphostack/core/rbc_capabilities.py`
- Modify: `src/morphostack/core/pipeline.py`
- Test: `tests/test_rbc_capabilities.py`
- Test: `tests/test_core_pipeline.py`

**Interfaces:**

- Consumes: `ImageStack.calibration`, source suffix, profile, and `ObjectSeed`.
- Produces: `evaluate_rbc_input(...) -> RbcInputDecision` and a structured `RbcInputRefused` exception for thin surfaces.

- [ ] **Step 1: Write failing decision-table tests**

```python
@pytest.mark.parametrize(
    ("suffix", "manual", "seeded", "allowed", "reason"),
    [
        (".lsm", False, True, False, RbcRefusalCode.LSM_REQUIRES_CONVERSION_OR_MANUAL),
        (".lsm", True, True, True, None),
        (".ome.tif", False, False, False, RbcRefusalCode.SEED_REQUIRED),
        (".ome.tif", False, True, True, None),
    ],
)
def test_rbc_input_gate(suffix, manual, seeded, allowed, reason):
    decision = evaluate_rbc_input(make_input(suffix, manual, seeded))
    assert decision.allowed is allowed
    assert reason is None or reason in decision.reasons
```

- [ ] **Step 2: Run gate tests and verify failure**

Run: `.\.venv\Scripts\pytest tests\test_rbc_capabilities.py tests\test_core_pipeline.py -q`

Expected: FAIL because the central evaluator and seed enforcement do not exist.

- [ ] **Step 3: Implement one pure evaluator and invoke it before RBC segmentation**

```python
def evaluate_rbc_input(
    *,
    source_path: Path,
    calibration: CalibrationAssessment,
    object_seed: ObjectSeed | None,
) -> RbcInputDecision:
    reasons: list[RbcRefusalCode] = []
    if object_seed is None:
        reasons.append(RbcRefusalCode.SEED_REQUIRED)
    if source_path.suffix.lower() == ".lsm" and not calibration.all_axes_from_override:
        reasons.append(RbcRefusalCode.LSM_REQUIRES_CONVERSION_OR_MANUAL)
    elif not calibration.all_axes_verified:
        reasons.append(RbcRefusalCode.INCOMPLETE_AXIS_CALIBRATION)
    return RbcInputDecision(allowed=not reasons, reasons=tuple(reasons))
```

Keep the evaluator pure. Pass the source/calibration context into the RBC orchestration layer rather than reading global session state.

- [ ] **Step 4: Run gate and pipeline tests**

Run: `.\.venv\Scripts\pytest tests\test_rbc_capabilities.py tests\test_core_pipeline.py -q`

Expected: PASS; vesicle cases remain unaffected.

- [ ] **Step 5: Commit the core input gate**

```powershell
git add src/morphostack/core/rbc_capabilities.py src/morphostack/core/pipeline.py tests/test_rbc_capabilities.py tests/test_core_pipeline.py
git commit -m "feat: gate RBC analysis on selection and calibration"
```

---

### Task 4: Expose structured refusal through API and CLI

**Files:**

- Modify: `src/morphostack/api/app.py`
- Modify: `src/morphostack/cli/main.py`
- Test: `tests/test_api.py`
- Test: `tests/test_cli.py`

**Interfaces:**

- Consumes: `RbcInputRefused` and `RbcInputDecision` from Task 3.
- Produces: stable refusal `code`, human guidance, and no physical result payload.

- [ ] **Step 1: Add failing API and CLI refusal tests**

```python
def test_api_refuses_uncalibrated_lsm_rbc_analysis(client, lsm_stack):
    response = client.post("/api/analyze", data={"profile": "rbc"}, files={"file": lsm_stack})
    assert response.status_code == 422
    assert response.json()["detail"]["code"] == "lsm_requires_conversion_or_manual_calibration"
    assert "mesh" not in response.json()
```

Add an equivalent CLI test that asserts nonzero exit and guidance for conversion or all three manual voxel values.

- [ ] **Step 2: Run the interface tests and verify failure**

Run: `.\.venv\Scripts\pytest tests\test_api.py tests\test_cli.py -k "rbc and (lsm or calibration or seed)" -q`

Expected: FAIL because current surfaces warn or continue.

- [ ] **Step 3: Map the shared refusal without duplicating policy**

Catch `RbcInputRefused` at each thin boundary and serialize its existing codes and guidance. Do not re-evaluate suffixes, voxel values, or seeds in API/CLI code.

- [ ] **Step 4: Run Phase 1 verification**

```powershell
.\.venv\Scripts\pytest tests\test_rbc_capabilities.py tests\test_core_io.py tests\test_core_pipeline.py tests\test_api.py tests\test_cli.py -q
```

Expected: PASS, including legacy non-RBC cases.

- [ ] **Step 5: Commit thin-surface wiring**

```powershell
git add src/morphostack/api/app.py src/morphostack/cli/main.py tests/test_api.py tests/test_cli.py
git commit -m "feat: surface RBC calibration refusals"
```

---

## Phase 1 Exit Gate

- Direct uncalibrated `.lsm` RBC analysis is refused before segmentation on API and CLI paths.
- Manual X/Y/Z overrides permit `.lsm` analysis.
- Missing or placeholder-filled axes remain visibly unverified.
- RBC analysis requires an explicit seed.
- No physical result is serialized on refusal.
- Focused I/O, pipeline, API, CLI, and vesicle compatibility tests pass.

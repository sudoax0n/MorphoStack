# Phase 2: Topology-Preserving RBC Reconstruction Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use `superpowers:subagent-driven-development` or `superpowers:executing-plans` to implement this packet task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Route the RBC profile through loop-aware slice segmentation and full-resolution 3D occupancy without changing the vesicle path.

**Architecture:** Reuse the current seed crop, intensity preprocessing, candidate selection, and Z association where scientifically compatible. Fork before unconditional hole filling, retain contour hierarchy plus occupancy, and adapt the accepted stack into the existing scientific authority chain.

**Tech Stack:** NumPy, OpenCV contour hierarchy, scikit-image morphology where already installed, frozen dataclasses, pytest.

## Global Constraints

- This packet implements master requirements R5-R6 and provides the reconstruction consumed by Phase 3.
- Never route RBC measured geometry through `FrameAnalysis.contour -> contours_to_mask_stack()`.
- Preserve full-resolution anisotropic occupancy; display downsampling remains derivative-only.
- Reject ambiguous hierarchy, lateral clipping, and unresolved merges instead of guessing.
- Keep the GUV call to `_fill_holes()` unchanged and covered by regression tests.

---

## File Structure

- Extend `src/morphostack/core/rbc_models.py` with immutable loop-aware slice and stack candidate types.
- Create `src/morphostack/core/rbc_topology.py` for hierarchy extraction, parity rasterization, and topology checks.
- Create `src/morphostack/core/rbc_segmentation.py` for RBC slice segmentation and bidirectional Z association.
- Modify `src/morphostack/core/seeded_vesicle.py` only to extract a shared pre-hole-fill candidate helper while preserving its current public behavior.
- Modify `src/morphostack/core/pipeline.py` to route `profile="rbc"` to the new result type.
- Modify `src/morphostack/core/mesh.py` only where an accepted RBC occupancy enters the existing authority chain.
- Create `tests/test_rbc_topology.py`; extend pipeline, mesh, and result-authority tests.

---

### Task 1: Represent and rasterize loop hierarchy

**Files:**

- Modify: `src/morphostack/core/rbc_models.py`
- Create: `src/morphostack/core/rbc_topology.py`
- Create: `tests/test_rbc_topology.py`

**Interfaces:**

- Produces: `RbcBoundaryLoop`, `RbcSliceTopology`, `extract_rbc_slice_topology(mask, *, frame_index)`, and `rasterize_rbc_topology(topology, shape)`.
- `RbcSliceTopology` carries one outer loop, zero or more inner loops, the full-frame occupancy mask, hierarchy depth, and explicit QC reasons.

- [ ] **Step 1: Write failing parity and ambiguity tests**

```python
def test_annular_slice_preserves_inner_hole():
    mask = annulus_mask(shape=(96, 96), outer_radius=30, inner_radius=12)
    result = extract_rbc_slice_topology(mask, frame_index=4)
    rebuilt = rasterize_rbc_topology(result, mask.shape)
    assert result.ok
    assert len(result.inner_loops_xy) == 1
    assert not rebuilt[48, 48]
    assert np.array_equal(rebuilt, mask)


def test_two_disconnected_outer_loops_are_ambiguous():
    result = extract_rbc_slice_topology(two_component_mask(), frame_index=2)
    assert not result.ok
    assert RbcTopologyIssue.MULTIPLE_OUTER_COMPONENTS in result.issues
```

- [ ] **Step 2: Run tests and verify the topology module is missing**

Run: `.\.venv\Scripts\pytest tests\test_rbc_topology.py -q`

Expected: collection fails because the loop-aware API does not exist.

- [ ] **Step 3: Implement hierarchy extraction and even-odd rasterization**

```python
@dataclass(frozen=True)
class RbcSliceTopology:
    frame_index: int
    outer_loop_xy: np.ndarray | None
    inner_loops_xy: tuple[np.ndarray, ...]
    occupancy_mask: np.ndarray | None
    issues: tuple[RbcTopologyIssue, ...]
    ok: bool


def extract_rbc_slice_topology(mask: np.ndarray, *, frame_index: int) -> RbcSliceTopology:
    contours, hierarchy = cv2.findContours(
        np.asarray(mask, dtype=np.uint8), cv2.RETR_TREE, cv2.CHAIN_APPROX_NONE
    )
    # Select one root contour, retain odd-depth descendants as holes, and
    # reject multiple roots or unsupported nesting instead of flattening them.
```

Use contour hierarchy depth and even-odd parity. Verify rasterization by comparing the rebuilt mask with the accepted input mask; mismatch is a topology issue.

- [ ] **Step 4: Run topology tests**

Run: `.\.venv\Scripts\pytest tests\test_rbc_topology.py -q`

Expected: PASS for solid, annular, nested, empty, clipped, and ambiguous fixtures.

- [ ] **Step 5: Commit loop-aware topology**

```powershell
git add src/morphostack/core/rbc_models.py src/morphostack/core/rbc_topology.py tests/test_rbc_topology.py
git commit -m "feat: preserve RBC slice topology"
```

---

### Task 2: Split RBC segmentation before hole filling

**Files:**

- Modify: `src/morphostack/core/seeded_vesicle.py`
- Create: `src/morphostack/core/rbc_segmentation.py`
- Test: `tests/test_rbc_topology.py`
- Test: existing seeded-vesicle regression tests discovered by `rg -n "segment_slice_seeded" tests`

**Interfaces:**

- Consumes: seed crop and accepted pre-fill candidate mask from the shared helper.
- Produces: `segment_rbc_slice_seeded(...) -> RbcSliceTopology`.
- Vesicle continues to produce `SeededSliceResult` with its current hole-filled `solid_mask`.

- [ ] **Step 1: Add failing RBC-versus-vesicle behavior tests**

```python
def test_rbc_keeps_center_hole_while_vesicle_preserves_legacy_fill():
    frame = synthetic_membrane_annulus()
    rbc = segment_rbc_slice_seeded(frame, seed_x=48, seed_y=48, seed_radius=32)
    guv = segment_slice_seeded(frame, seed_x=48, seed_y=48, seed_radius=32, profile="vesicle")
    assert rbc.ok and not rbc.occupancy_mask[48, 48]
    assert guv.ok and guv.solid_mask[48, 48]
```

- [ ] **Step 2: Run targeted tests and verify RBC follows the old fill**

Run: `.\.venv\Scripts\pytest tests\test_rbc_topology.py -q`

Expected: FAIL because RBC currently calls the vesicle implementation and `_fill_holes()`.

- [ ] **Step 3: Extract the shared pre-fill candidate and add the RBC adapter**

```python
def _segment_seed_candidate_mask(
    frame: np.ndarray,
    *,
    seed_x: float,
    seed_y: float,
    seed_radius: float,
    profile: str,
    refine: bool,
    multiscale_consensus: bool,
) -> SeedCandidateMask:
    """Return the selected pre-hole-fill mask plus existing diagnostics."""


def segment_rbc_slice_seeded(...) -> RbcSliceTopology:
    candidate = _segment_seed_candidate_mask(..., profile="rbc")
    return extract_rbc_slice_topology(candidate.mask, frame_index=frame_index)
```

Make the existing `segment_slice_seeded()` call the same helper and then apply `_fill_holes()` exactly as before. Compare representative vesicle masks byte-for-byte in tests.

- [ ] **Step 4: Run RBC and vesicle regression tests**

Run: `.\.venv\Scripts\pytest tests\test_rbc_topology.py tests\test_core_object_seed.py tests\test_core_pipeline.py -q`

Expected: PASS; RBC retains holes and legacy vesicle masks remain unchanged.

- [ ] **Step 5: Commit the profile split**

```powershell
git add src/morphostack/core/seeded_vesicle.py src/morphostack/core/rbc_segmentation.py tests/test_rbc_topology.py tests/test_core_object_seed.py tests/test_core_pipeline.py
git commit -m "feat: split RBC segmentation before hole filling"
```

---

### Task 3: Associate loop-aware slices through Z

**Files:**

- Modify: `src/morphostack/core/rbc_models.py`
- Modify: `src/morphostack/core/rbc_segmentation.py`
- Test: `tests/test_rbc_topology.py`

**Interfaces:**

- Produces: `RbcStackCandidate` and `track_rbc_stack(...) -> RbcStackCandidate`.
- Association diagnostics must preserve lost slices, internal gaps, centroid movement, area changes, merge suspicion, and bidirectional agreement.

- [ ] **Step 1: Write failing bidirectional association tests**

```python
def test_rbc_stack_tracks_one_seeded_cell_in_both_z_directions():
    stack = moving_biconcave_stack()
    result = track_rbc_stack(stack, seed=ObjectSeed.circle(48, 48, frame_index=8, radius=30))
    assert result.seed_frame_index == 8
    assert result.valid_slice_indices == tuple(range(3, 14))
    assert not result.internal_gap_indices


def test_rbc_stack_does_not_force_ambiguous_neighbor_merge():
    result = track_rbc_stack(touching_pair_stack(), seed=target_seed())
    assert result.withheld
    assert RbcTopologyIssue.UNRESOLVED_MERGE in result.issues
```

- [ ] **Step 2: Run association tests and verify failure**

Run: `.\.venv\Scripts\pytest tests\test_rbc_topology.py -k "stack or merge" -q`

Expected: FAIL because the stack candidate and RBC association function do not exist.

- [ ] **Step 3: Implement RBC association using existing diagnostics**

Reuse physical centroid distance, overlap, reference area, and request-scoped consensus helpers. Rename new RBC-facing diagnostics to `slice_association` or `z_linking`; do not call Z-slice association biological tracking in new reports.

- [ ] **Step 4: Run association and legacy tracking tests**

Run: `.\.venv\Scripts\pytest tests\test_rbc_topology.py tests\test_core_pipeline.py tests\test_core_object_seed.py -q`

Expected: PASS with ambiguous links withheld and legacy tracking unaffected.

- [ ] **Step 5: Commit Z association**

```powershell
git add src/morphostack/core/rbc_models.py src/morphostack/core/rbc_segmentation.py tests/test_rbc_topology.py tests/test_core_pipeline.py
git commit -m "feat: associate topology-aware RBC slices"
```

---

### Task 4: Route RBC occupancy into the authority chain

**Files:**

- Modify: `src/morphostack/core/pipeline.py`
- Modify: `src/morphostack/core/mesh.py`
- Modify: `src/morphostack/core/models.py` only if the existing candidate adapter requires a typed extension
- Test: `tests/test_core_pipeline.py`
- Test: `tests/test_result_authority.py`
- Test: `tests/test_core_mesh.py`

**Interfaces:**

- Consumes: `RbcStackCandidate.occupancy_mask` and Phase 1 calibration assessment.
- Produces: a full-resolution `SegmentationCandidate` whose method identifies the RBC topology path; it is not authoritative until Phase 3 QC accepts it.

- [ ] **Step 1: Write failing pipeline authority tests**

```python
def test_rbc_pipeline_candidate_uses_loop_aware_occupancy():
    analysis = analyze_stack(biconcave_stack(), profile="rbc", object_seed=rbc_seed(), include_mesh=False)
    candidate = rbc_candidate_from_analysis(analysis)
    assert candidate.mask[cap_slice, center_y, center_x] == 0
    assert candidate.profile == "rbc"
    assert candidate.provisional


def test_rbc_pipeline_does_not_call_legacy_contour_rasterizer(monkeypatch):
    monkeypatch.setattr(mesh, "contours_to_mask_stack", fail_if_called)
    analyze_stack(biconcave_stack(), profile="rbc", object_seed=rbc_seed(), include_mesh=True)
```

- [ ] **Step 2: Run pipeline and authority tests and verify failure**

Run: `.\.venv\Scripts\pytest tests\test_core_pipeline.py tests\test_result_authority.py tests\test_core_mesh.py -k "rbc or authority" -q`

Expected: FAIL because RBC still stores one contour and uses the legacy rasterizer.

- [ ] **Step 3: Add the RBC analysis branch and candidate adapter**

Route `profile="vesicle"` and `profile="rbc"` separately inside `analyze_stack()`. Keep preview contours for drawing, but make the loop-aware occupancy the only RBC 3D measurement candidate. Pass it into the existing `AuthoritativeMask` acceptance path without constructing a filled contour stack.

- [ ] **Step 4: Run Phase 2 verification**

```powershell
.\.venv\Scripts\pytest tests\test_rbc_topology.py tests\test_core_pipeline.py tests\test_core_mesh.py tests\test_result_authority.py tests\test_core_object_seed.py -q
```

Expected: PASS; annular topology survives pipeline-to-candidate conversion.

- [ ] **Step 5: Commit the RBC pipeline route**

```powershell
git add src/morphostack/core/pipeline.py src/morphostack/core/mesh.py src/morphostack/core/models.py tests/test_core_pipeline.py tests/test_core_mesh.py tests/test_result_authority.py
git commit -m "feat: route RBC occupancy through result authority"
```

---

## Phase 2 Exit Gate

- RBC and vesicle no longer share the same measurement representation.
- Inner loops survive slice segmentation, Z association, pipeline storage, and occupancy reconstruction.
- Ambiguous hierarchy, clipping, and unresolved merges fail closed.
- RBC scientific measurement no longer depends on `contours_to_mask_stack()`.
- Existing vesicle segmentation and tracking regression tests pass unchanged.

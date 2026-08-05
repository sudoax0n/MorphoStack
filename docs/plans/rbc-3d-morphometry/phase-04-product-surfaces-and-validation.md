# Phase 4: RBC Product Surfaces and Engineering Validation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use `superpowers:subagent-driven-development` or `superpowers:executing-plans` to implement this packet task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Carry RBC capability and authority through every user-facing surface, provide safe estimated-model plumbing, and establish the engineering regression suite.

**Architecture:** Serialize the typed core result instead of inferring status in API/UI/export code. Estimated geometry enters through a separate provider interface and remains unavailable in production until Phase 5 approves a scientific model; tests use a deterministic fake provider to prove separation and UX.

**Tech Stack:** FastAPI/Pydantic, Python export/report code, TypeScript/Vite, existing mesh viewer, pytest, deterministic synthetic validation scripts.

## Global Constraints

- This packet implements master requirements R12-R16 and depends on Phases 1-3.
- No thin surface may infer capability from the presence of a number or mesh.
- Show the limitation before the explicit estimated-model action.
- Use distinct labels and styling for `MEASURED`, `ESTIMATED`, and `WITHHELD`.
- The production estimated model remains unavailable until Phase 5 selects and validates its formula and priors.
- A test-only fake estimator must never be registered in production startup.
- Keep reports and exports honest when values are absent; do not write zeroes or empty measured meshes.

---

## File Structure

- Extend `src/morphostack/core/rbc_models.py` with estimated geometry and serialized result contracts.
- Create `src/morphostack/core/rbc_estimation.py` for the provider protocol and authority checks, without a production estimator implementation.
- Modify `src/morphostack/api/app.py` for capability-aware analyze, preview, estimate, and export payloads.
- Modify `src/morphostack/core/export.py` and relevant CLI output wiring for status-aware CSV, manifest, report, mask, and mesh output.
- Modify `apps/web/src/main.ts`, `apps/web/src/volumeViewer.ts`, and focused styles/types for refusal, QC, disclaimer, badges, and geometry layers.
- Create `scripts/validate_rbc_phantoms.py` and committed reference output under `validation/`.
- Add focused API/export tests and `apps/web/tests/rbcResultStates.test.mjs`; add that test to `apps/web/package.json`.
- Update `docs/limitations.md`, `docs/metrics.md`, `docs/usage.md`, and `improvements.md` after behavior is verified.

---

### Task 1: Define one serialized RBC result envelope

**Files:**

- Modify: `src/morphostack/core/rbc_models.py`
- Modify: `src/morphostack/api/app.py`
- Modify: `src/morphostack/core/export.py`
- Test: `tests/test_api.py`
- Test: `tests/test_core_export.py`

**Interfaces:**

- Produces: `RbcResultEnvelope` with `authority`, `capability`, `qc_issues`, `calibration`, `measured`, `estimated`, and method/provenance fields.
- `measured` and `estimated` are distinct optional objects and cannot both claim the same metric authority.

- [ ] **Step 1: Write failing API and export envelope tests**

```python
def test_withheld_api_result_has_reasons_and_no_measured_3d_values(client, clipped_rbc):
    payload = analyze_rbc(client, clipped_rbc)
    assert payload["authority"] == "WITHHELD"
    assert "lateral_clipping" in payload["qc_issues"]
    assert payload["measured"]["volume_um3"] is None
    assert payload["estimated"] is None


def test_export_keeps_authority_and_metric_definition_version(tmp_path, measured_rbc_result):
    export_analysis(measured_rbc_result, tmp_path)
    manifest = json.loads((tmp_path / "manifest.json").read_text())
    assert manifest["rbc"]["authority"] == "MEASURED"
    assert manifest["rbc"]["metric_definition_version"] == RBC_METRIC_DEFINITION_VERSION
```

- [ ] **Step 2: Run API/export tests and verify failure**

Run: `.\.venv\Scripts\pytest tests\test_api.py tests\test_core_export.py -k "rbc and (authority or capability or withheld)" -q`

Expected: FAIL because current surfaces expose generic metrics and warnings.

- [ ] **Step 3: Serialize the core envelope directly**

```python
@dataclass(frozen=True)
class RbcResultEnvelope:
    authority: RbcAuthority
    capability: RbcCapability
    qc_issues: tuple[RbcQcIssue, ...]
    calibration: CalibrationAssessment
    measured: RbcMeasuredOutput | None
    estimated: RbcEstimatedOutput | None
    metric_definition_version: str
```

API and export adapters may rename fields for JSON conventions but must not recalculate permission, capability, or authority.

- [ ] **Step 4: Run envelope tests**

Run: `.\.venv\Scripts\pytest tests\test_api.py tests\test_core_export.py -k "rbc or voxel or mesh" -q`

Expected: PASS with `None` for unsupported values and stable QC reason codes.

- [ ] **Step 5: Commit the result envelope**

```powershell
git add src/morphostack/core/rbc_models.py src/morphostack/api/app.py src/morphostack/core/export.py tests/test_api.py tests/test_core_export.py
git commit -m "feat: serialize RBC capability and authority"
```

---

### Task 2: Build estimated-model plumbing without inventing a model

**Files:**

- Create: `src/morphostack/core/rbc_estimation.py`
- Modify: `src/morphostack/core/rbc_models.py`
- Modify: `src/morphostack/api/app.py`
- Test: `tests/test_rbc_estimation.py`
- Test: `tests/test_api.py`

**Interfaces:**

- Produces: `RbcEstimator` protocol, `RbcEstimateRequest`, `RbcEstimatedOutput`, and `request_rbc_estimate(...)`.
- Production registry initially contains no estimator; the endpoint returns an unavailable capability response until Phase 5 installs an approved provider.

- [ ] **Step 1: Write failing authority and provider-availability tests**

```python
def test_estimated_output_cannot_be_promoted_to_authoritative_mask(fake_estimator):
    estimate = request_rbc_estimate(valid_request(), provider=fake_estimator)
    assert estimate.authority is RbcAuthority.ESTIMATED
    with pytest.raises(ResultAuthorityError):
        scientific_mesh_from_authoritative_mask(estimate.geometry)


def test_production_estimator_is_unavailable_until_registered(client):
    response = client.post("/api/rbc/estimate", json=valid_estimate_payload())
    assert response.status_code == 409
    assert response.json()["detail"]["code"] == "rbc_estimator_not_validated"
```

- [ ] **Step 2: Run estimation tests and verify failure**

Run: `.\.venv\Scripts\pytest tests\test_rbc_estimation.py tests\test_api.py -k "estimate or estimated" -q`

Expected: FAIL because no provider or separated estimated type exists.

- [ ] **Step 3: Implement the provider boundary**

```python
class RbcEstimator(Protocol):
    model_id: str
    model_version: str

    def estimate(self, request: RbcEstimateRequest) -> RbcEstimatedOutput: ...


def request_rbc_estimate(
    request: RbcEstimateRequest,
    *,
    provider: RbcEstimator | None,
) -> RbcEstimatedOutput:
    if provider is None:
        raise RbcEstimatorUnavailable("rbc_estimator_not_validated")
    output = provider.estimate(request)
    if output.authority is not RbcAuthority.ESTIMATED:
        raise ResultAuthorityError("RBC estimator returned non-estimated authority")
    return output
```

The request carries measured outer footprint, permitted calibration, and model assumptions. The output records provider ID, version, assumptions, and confidence language. Do not define a biological formula in this phase.

- [ ] **Step 4: Run estimation and authority tests**

Run: `.\.venv\Scripts\pytest tests\test_rbc_estimation.py tests\test_result_authority.py tests\test_api.py -k "estimate or authority" -q`

Expected: PASS with a test-only provider and no production provider.

- [ ] **Step 5: Commit estimator plumbing**

```powershell
git add src/morphostack/core/rbc_estimation.py src/morphostack/core/rbc_models.py src/morphostack/api/app.py tests/test_rbc_estimation.py tests/test_api.py
git commit -m "feat: separate estimated RBC model authority"
```

---

### Task 3: Implement the RBC refusal, QC, and estimate UX

**Files:**

- Modify: `apps/web/src/main.ts`
- Modify: `apps/web/src/volumeViewer.ts`
- Modify: `apps/web/src/styles.css`
- Modify: `apps/web/package.json`
- Create: `apps/web/tests/rbcResultStates.test.mjs`

**Interfaces:**

- Consumes: `RbcResultEnvelope` and structured refusal responses.
- Produces: visible calibration stop, capability badge, QC reasons, measured layer, disclaimer, explicit estimate action, and visually distinct estimated layer.

- [ ] **Step 1: Add failing UI state tests**

```typescript
it("shows the disclaimer before enabling estimated geometry", async () => {
  renderRbcResult(withheldResult("biconcavity_unidentifiable"));
  expect(screen.getByText(/cannot be measured from this stack/i)).toBeVisible();
  expect(screen.queryByText(/ESTIMATED model visible/i)).toBeNull();
  await user.click(screen.getByRole("button", { name: /show estimated model/i }));
  expect(screen.getByText(/ESTIMATED model/i)).toBeVisible();
});

it("does not render physical metrics for an uncalibrated refusal", () => {
  renderRbcRefusal(uncalibratedLsmRefusal());
  expect(screen.getByText(/convert.*TIFF|enter X.*Y.*Z/i)).toBeVisible();
  expect(screen.queryByText(/µm3|µm²/i)).toBeNull();
});
```

- [ ] **Step 2: Run web tests and verify failure**

Run: `cd apps\web; node tests\rbcResultStates.test.mjs`

Expected: FAIL because the current UI describes RBC as the same pipeline and has no authority states.

- [ ] **Step 3: Render the typed states**

Replace the “same pipeline” help text. Use fixed semantic styles: measured uses the normal scientific-result treatment, estimated uses a distinct dashed/amber treatment with a persistent `ESTIMATED` badge, and withheld shows no measurement table. Keep measured and estimated layers independently toggleable and never merge their summaries.

- [ ] **Step 4: Run web tests and production build**

```powershell
cd apps\web
npm run build
```

Expected: all RBC UI tests pass and the TypeScript production build succeeds.

- [ ] **Step 5: Commit the user-facing states**

```powershell
git add apps/web/src/main.ts apps/web/src/volumeViewer.ts apps/web/src/styles.css apps/web/package.json apps/web/tests/rbcResultStates.test.mjs
git commit -m "feat: show measured and estimated RBC states"
```

---

### Task 4: Make all exports authority-safe

**Files:**

- Modify: `src/morphostack/core/export.py`
- Modify: CLI export/report wiring under `src/morphostack/cli/`
- Modify: API download routes in `src/morphostack/api/app.py`
- Test: `tests/test_core_export.py`
- Test: `tests/test_cli.py`
- Test: `tests/test_api.py`

**Interfaces:**

- Consumes: `RbcResultEnvelope` only.
- Produces: filenames, CSV columns, manifest entries, reports, and geometry metadata with an explicit authority role and withholding reason.

- [ ] **Step 1: Write failing cross-format export tests**

```python
@pytest.mark.parametrize("format_name", ["csv", "manifest", "report", "obj", "stl", "ply", "glb"])
def test_estimated_export_is_labeled_in_content_and_filename(format_name, tmp_path, estimated_result):
    artifact = export_rbc_result(estimated_result, tmp_path, format_name)
    assert "estimated" in artifact.name.lower()
    assert artifact_authority(artifact) == "ESTIMATED"


def test_withheld_result_does_not_write_scientific_mesh(tmp_path, withheld_result):
    outputs = export_rbc_result(withheld_result, tmp_path, "all")
    assert not any(path.suffix in {".obj", ".stl", ".ply", ".glb"} for path in outputs)
```

- [ ] **Step 2: Run export tests and verify failure**

Run: `.\.venv\Scripts\pytest tests\test_core_export.py tests\test_cli.py tests\test_api.py -k "rbc and (estimated or withheld or export)" -q`

Expected: FAIL because current exports repeat generic mesh values and do not encode authority.

- [ ] **Step 3: Route every export through the envelope**

Add explicit authority and capability fields, method versions, axis provenance, QC issues, and model assumptions. Keep measured and estimated tables separate. Remove the normal RBC `deformation_index` field; if compatibility output retains it, label it `legacy_deformation_index_bbox` and exclude it from the primary report.

- [ ] **Step 4: Run export, API, and CLI tests**

Run: `.\.venv\Scripts\pytest tests\test_core_export.py tests\test_cli.py tests\test_api.py -k "rbc or export or calibration" -q`

Expected: PASS with no unlabeled estimated artifact and no measured artifact on withheld results.

- [ ] **Step 5: Commit authority-safe exports**

```powershell
git add src/morphostack/core/export.py src/morphostack/cli src/morphostack/api/app.py tests/test_core_export.py tests/test_cli.py tests/test_api.py
git commit -m "feat: preserve RBC authority in exports"
```

---

### Task 5: Add deterministic RBC engineering validation and documentation

**Files:**

- Create: `scripts/validate_rbc_phantoms.py`
- Create: `validation/references/rbc-phantom-metrics.json`
- Create: `validation/reports/rbc-engineering-validation.md`
- Modify: `docs/limitations.md`
- Modify: `docs/metrics.md`
- Modify: `docs/usage.md`
- Modify: `improvements.md`
- Test: `tests/test_rbc_morphometry.py`
- Test: `tests/test_rbc_topology.py`

**Interfaces:**

- Produces: deterministic JSON/report evidence for solid, annular, tilted, anisotropic, incomplete-cap, clipped, touching, and noisy phantoms.
- The report states engineering tolerances and explicitly excludes biological-accuracy claims.

- [ ] **Step 1: Write failing validator contract tests**

```python
def test_validator_reports_every_required_phantom(tmp_path):
    report = run_rbc_phantom_validation(output_dir=tmp_path)
    assert set(report.cases) == {
        "solid_oblate", "biconcave", "annular_caps", "tilted", "anisotropic",
        "incomplete_caps", "lateral_clip", "touching_pair", "noisy_low_sbr",
    }
    assert report.biological_validation is False
```

- [ ] **Step 2: Run validation tests and verify failure**

Run: `.\.venv\Scripts\pytest tests\test_rbc_morphometry.py tests\test_rbc_topology.py -k "validator or phantom" -q`

Expected: FAIL because the validator and committed references do not exist.

- [ ] **Step 3: Implement deterministic fixtures and thresholds**

Generate shapes in physical coordinates, sample them on anisotropic grids, and compare topology plus metric bias against exact voxel or analytic truth. Use fixed seeds for noise. Set engineering gates to preserve holes exactly, reject every negative case, keep high-resolution phantom volume error at or below 5%, and keep rotation-derived axis error at or below 3%. Report surface-area sensitivity separately rather than hiding it in one aggregate score.

- [ ] **Step 4: Run the complete engineering gate**

```powershell
.\.venv\Scripts\python scripts\validate_rbc_phantoms.py
.\.venv\Scripts\pytest
cd apps\web
npm run build
```

Expected: phantom report passes, the Python suite passes, and the web build succeeds. A Windows pytest temp-directory ACL error is reported as infrastructure-blocked rather than success.

- [ ] **Step 5: Update documentation from verified behavior and commit**

Replace the vague RBC checklist line in `improvements.md` with links/status for the engineering and evidence-dependent packets. Update limitations, metrics, and usage only with behavior proven by the completed tests and validator.

```powershell
git add scripts/validate_rbc_phantoms.py validation/references/rbc-phantom-metrics.json validation/reports/rbc-engineering-validation.md docs/limitations.md docs/metrics.md docs/usage.md improvements.md tests/test_rbc_morphometry.py tests/test_rbc_topology.py
git commit -m "validation: add RBC engineering regression gate"
```

---

## Phase 4 Exit Gate

- API, CLI, UI, reports, and exports display the same capability, authority, calibration, and QC state.
- The disclaimer precedes the explicit estimated-model action.
- Estimated geometry cannot enter measured authority or overwrite measured fields.
- Production estimation remains unavailable until Phase 5 approves a provider.
- Every required synthetic case is deterministic and has a committed engineering tolerance.
- Full Python regression and web build pass or are reported honestly as infrastructure-blocked.
- Documentation distinguishes engineering completion from biological validation.

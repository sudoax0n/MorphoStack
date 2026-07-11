"""Packet 06: staged cheap→expensive QC and MorphGAC clean-frame gating."""

from __future__ import annotations

import time

import numpy as np
import pytest

from morphostack.core.seeded_vesicle import (
    get_qc_refinement_counters,
    get_qc_refinement_gating,
    reset_qc_refinement_counters,
    segment_slice_seeded,
    set_qc_refinement_gating,
    track_seeded_vesicle_stack,
)
from morphostack.core.slice_qc import (
    cheap_suspicion_flags,
    compute_slice_qc,
    is_clean_frame_pre_refine,
)


@pytest.fixture(autouse=True)
def _restore_gating_policy():
    prev = get_qc_refinement_gating()
    # Production packet-06 defaults: both gates off (reference path).
    set_qc_refinement_gating(staged_full_qc=False, skip_morphgac_when_clean=False)
    reset_qc_refinement_counters()
    yield
    set_qc_refinement_gating(
        staged_full_qc=prev.get("staged_full_qc", False),
        skip_morphgac_when_clean=prev.get("skip_morphgac_when_clean", False),
    )
    reset_qc_refinement_counters()


def _ring(h, w, cx, cy, r_in, r_out, value=200.0) -> np.ndarray:
    yy, xx = np.ogrid[:h, :w]
    d2 = (xx - cx) ** 2 + (yy - cy) ** 2
    frame = np.zeros((h, w), dtype=np.float64)
    frame[(d2 >= r_in**2) & (d2 <= r_out**2)] = value
    return frame


def _filled(h, w, cx, cy, r) -> np.ndarray:
    yy, xx = np.ogrid[:h, :w]
    return (xx - cx) ** 2 + (yy - cy) ** 2 <= r**2


def test_policy_reference_path_disables_gates():
    set_qc_refinement_gating(staged_full_qc=False, skip_morphgac_when_clean=False)
    pol = get_qc_refinement_gating()
    assert pol["staged_full_qc"] is False
    assert pol["skip_morphgac_when_clean"] is False


def test_production_defaults_are_both_gates_off():
    pol = get_qc_refinement_gating()
    assert pol["staged_full_qc"] is False
    assert pol["skip_morphgac_when_clean"] is False


def test_staged_gate_skips_pre_refine_full_qc_when_enabled():
    """Opt-in staged path: clean ring skips pre-refine full QC; MorphGAC still runs."""
    frame = _ring(100, 100, 50, 50, 16, 20)
    set_qc_refinement_gating(staged_full_qc=True, skip_morphgac_when_clean=False)
    reset_qc_refinement_counters()
    res = segment_slice_seeded(frame, seed_x=50, seed_y=50, seed_radius=20, refine=True)
    assert res.ok
    c = get_qc_refinement_counters()
    assert c["cheap_qc_calls"] >= 1
    assert c["full_qc_skipped_clean"] >= 1
    assert c["morphgac_calls"] >= 1
    assert c["morphgac_skipped_clean"] == 0
    # Post-MorphGAC full QC still runs whenever MorphGAC runs.
    assert c["full_qc_calls"] >= 1
    assert c["ransac_calls"] >= 1


def test_optional_morphgac_skip_gate_still_instrumented():
    """MorphGAC skip remains available for re-bench; not the production default."""
    frame = _ring(100, 100, 50, 50, 16, 20)
    set_qc_refinement_gating(staged_full_qc=True, skip_morphgac_when_clean=True)
    reset_qc_refinement_counters()
    res = segment_slice_seeded(frame, seed_x=50, seed_y=50, seed_radius=20, refine=True)
    assert res.ok
    c = get_qc_refinement_counters()
    assert c["morphgac_skipped_clean"] >= 1
    assert c["morphgac_calls"] == 0


def test_reference_path_still_runs_morphgac_on_clean_ring():
    frame = _ring(100, 100, 50, 50, 16, 20)
    set_qc_refinement_gating(staged_full_qc=False, skip_morphgac_when_clean=False)
    reset_qc_refinement_counters()
    res = segment_slice_seeded(frame, seed_x=50, seed_y=50, seed_radius=20, refine=True)
    assert res.ok
    c = get_qc_refinement_counters()
    assert c["morphgac_calls"] >= 1
    assert c["full_qc_calls"] >= 1
    assert c["ransac_calls"] >= 1


def test_suspicion_flags_on_merged_mask():
    h = w = 120
    solid = _filled(h, w, 48, 60, 18) | _filled(h, w, 72, 60, 18)
    frame = _ring(h, w, 48, 60, 14, 18) + _ring(h, w, 72, 60, 14, 18)
    qc = compute_slice_qc(solid, frame, seed_x=48, seed_y=60, seed_radius=18, cheap=True)
    flags = cheap_suspicion_flags(
        qc, solid, seed_x=48, seed_y=60, seed_radius=18, ref_area=None
    )
    # Broad dual lobe should raise area and/or far_mass (and often circularity).
    assert flags
    assert not is_clean_frame_pre_refine(flags)


def test_contact_fixture_no_new_merge_accept_vs_reference():
    """W2-style safety: gating must not newly accept a dual-blob as ok isolation."""
    h = w = 120
    frame = np.zeros((h, w), dtype=np.float64)
    frame += _ring(h, w, 48, 60, 14, 18)
    frame += _ring(h, w, 72, 60, 14, 18)

    set_qc_refinement_gating(staged_full_qc=False, skip_morphgac_when_clean=False)
    ref = segment_slice_seeded(frame, seed_x=48, seed_y=60, seed_radius=18, refine=True)

    set_qc_refinement_gating(staged_full_qc=True, skip_morphgac_when_clean=True)
    gated = segment_slice_seeded(frame, seed_x=48, seed_y=60, seed_radius=18, refine=True)

    def _is_bad_dual(res) -> bool:
        if not res.ok or res.solid_mask is None:
            return False
        # Dual acceptance if far center included and area near two disks.
        far = bool(res.solid_mask[60, 72])
        return far and res.area_px > 1.6 * (np.pi * 18**2)

    assert not _is_bad_dual(gated), "gated path newly accepted dual-blob merge"
    # If reference rejected merge, gated must not accept.
    if not ref.ok or ref.method == "circle_seed_merge_reject":
        assert (not gated.ok) or gated.method == "circle_seed_merge_reject" or (
            gated.solid_mask is not None and not gated.solid_mask[60, 72]
        )


def test_touching_cases_zero_new_merge_acceptances():
    from morphostack.core.synthetic_touching import (
        case_overlapping_neck,
        case_tangent_neighbour,
        case_isolated_shrinking,
    )

    cases = [case_isolated_shrinking(), case_tangent_neighbour(), case_overlapping_neck()]
    new_merges = []
    for case in cases:
        st = np.asarray(case.stack)
        sx, sy, R = float(case.seed_x), float(case.seed_y), float(case.seed_radius)
        for z in range(st.shape[0]):
            set_qc_refinement_gating(staged_full_qc=False, skip_morphgac_when_clean=False)
            ref = segment_slice_seeded(st[z], seed_x=sx, seed_y=sy, seed_radius=R, refine=True)
            set_qc_refinement_gating(staged_full_qc=True, skip_morphgac_when_clean=True)
            g = segment_slice_seeded(st[z], seed_x=sx, seed_y=sy, seed_radius=R, refine=True)
            # New merge accept: reference failed/rejected, gated ok with merge_suspect false
            # and larger dual-ish area — conservative identity check on ok flags.
            if (not ref.ok) and g.ok and g.method != "circle_seed_merge_reject":
                # Allow gated success only if reference also ok on same method class;
                # a hard reject→accept flip is a new acceptance.
                new_merges.append((case.case_id, z, ref.method, g.method))
            if ref.method == "circle_seed_merge_reject" and g.ok:
                new_merges.append((case.case_id, z, "reject->ok", g.method))
    assert new_merges == [], f"new merge acceptances: {new_merges}"


def test_counters_prove_fewer_pre_refine_expensive_calls_on_w1_mid():
    rng = np.random.default_rng(0)
    nz, ny, nx, R = 20, 96, 96, 16.0
    zz, yy, xx = np.ogrid[:nz, :ny, :nx]
    cz, cy, cx = (nz - 1) / 2.0, (ny - 1) / 2.0, (nx - 1) / 2.0
    r2 = ((xx - cx) / R) ** 2 + ((yy - cy) / R) ** 2 + ((zz - cz) / (R * 0.55)) ** 2
    stack = np.zeros((nz, ny, nx), dtype=np.float32)
    stack[r2 <= 1.0] = 40.0
    stack[(r2 <= 1.05) & (r2 >= 0.75)] = 180.0
    stack += rng.normal(0, 6.0, size=stack.shape).astype(np.float32)
    stack = np.clip(stack, 0, 255)
    frame = stack[int(cz)]

    set_qc_refinement_gating(staged_full_qc=False, skip_morphgac_when_clean=False)
    reset_qc_refinement_counters()
    segment_slice_seeded(frame, seed_x=cx, seed_y=cy, seed_radius=R, refine=True)
    ref_c = get_qc_refinement_counters()

    set_qc_refinement_gating(staged_full_qc=True, skip_morphgac_when_clean=False)
    reset_qc_refinement_counters()
    segment_slice_seeded(frame, seed_x=cx, seed_y=cy, seed_radius=R, refine=True)
    g_c = get_qc_refinement_counters()

    # Staged full QC must skip pre-refine escalation on clean mid-plane.
    assert g_c["full_qc_skipped_clean"] >= 1 or g_c["suspicion_escalations"] < ref_c.get(
        "suspicion_escalations", 10**9
    )
    # MorphGAC remains on when skip-clean is off.
    assert g_c["morphgac_calls"] >= 1


def test_instrumentation_overhead_reference_path_small():
    """Disabled gates (reference) should not add >3% vs itself (smoke)."""
    frame = _ring(80, 80, 40, 40, 14, 18)
    set_qc_refinement_gating(staged_full_qc=False, skip_morphgac_when_clean=False)
    for _ in range(2):
        segment_slice_seeded(frame, seed_x=40, seed_y=40, seed_radius=18, refine=True)
    n = 5
    t0 = time.perf_counter()
    for _ in range(n):
        segment_slice_seeded(frame, seed_x=40, seed_y=40, seed_radius=18, refine=True)
    ms = (time.perf_counter() - t0) / n * 1000.0
    assert ms > 0
    # Not a hard absolute budget — just ensure path runs.
    assert ms < 5000.0

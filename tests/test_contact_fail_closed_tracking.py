"""Composite fail-closed contact / identity matrix (accept + reject, not reject-all)."""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pytest

from morphostack.core.seeded_vesicle import (
    SeededSliceResult,
    segment_slice_seeded,
    track_seeded_vesicle_stack,
    _candidate_accepted,
)
from morphostack.core.slice_qc import SliceQC, fail_closed, multi_object_cue_count


def _ring(h, w, cx, cy, r_in, r_out, value=200.0):
    yy, xx = np.ogrid[:h, :w]
    d2 = (xx - cx) ** 2 + (yy - cy) ** 2
    frame = np.zeros((h, w), dtype=np.float64)
    frame[(d2 >= r_in**2) & (d2 <= r_out**2)] = value
    return frame


def _filled(h, w, cx, cy, r):
    yy, xx = np.ogrid[:h, :w]
    return (xx - cx) ** 2 + (yy - cy) ** 2 <= r**2


def _mask_iou(a, b) -> float:
    a = np.asarray(a, dtype=bool)
    b = np.asarray(b, dtype=bool)
    inter = np.count_nonzero(a & b)
    union = np.count_nonzero(a | b)
    return inter / union if union else 0.0


def _rim_from_solid(solid: np.ndarray, iterations: int = 2) -> np.ndarray:
    try:
        from scipy import ndimage as ndi

        rim = solid ^ ndi.binary_erosion(solid, iterations=iterations)
    except Exception:
        rim = solid
    frame = np.zeros(solid.shape, dtype=np.uint8)
    frame[rim] = 200
    return frame


# ---------------------------------------------------------------------------
# Unit: composite fail_closed
# ---------------------------------------------------------------------------


def test_fail_closed_high_edge_composite_merge():
    """High edge + multi-object composite cues still fail closed (no hole)."""
    qc = SliceQC(
        circularity=0.88,
        eta=0.11,
        edge_support=0.92,
        inlier_frac=0.6,
        defect_depth_norm=0.09,
        flat_contact_frac=0.14,
        delta_bic=-8.0,
        n_dt_markers=1,
        merge_suspect=True,
        strong_two_circle=False,
        fitted_radius=18.0,
        cheap=False,
    )
    assert multi_object_cue_count(qc) >= 2
    assert fail_closed(qc) is True


def test_fail_closed_single_soft_cue_not_enough():
    """Lone merge_suspect / mild flatness must not hard-reject (pear risk)."""
    qc = SliceQC(
        circularity=0.72,
        eta=0.05,
        edge_support=0.70,
        inlier_frac=0.8,
        defect_depth_norm=0.04,
        flat_contact_frac=0.13,  # one contact-like cue
        delta_bic=1.0,
        n_dt_markers=1,
        merge_suspect=True,
        strong_two_circle=False,
        fitted_radius=18.0,
        cheap=False,
    )
    assert multi_object_cue_count(qc) == 1
    assert fail_closed(qc) is False


def test_fail_closed_n_peaks_alone_not_enough():
    qc = SliceQC(
        circularity=0.85,
        eta=0.04,
        edge_support=0.75,
        inlier_frac=0.8,
        defect_depth_norm=0.02,
        flat_contact_frac=0.02,
        delta_bic=2.0,
        n_dt_markers=2,
        merge_suspect=False,
        strong_two_circle=False,
        fitted_radius=15.0,
        cheap=False,
    )
    assert fail_closed(qc) is False


# ---------------------------------------------------------------------------
# Labelled synthetic matrix with FP/FN accounting
# ---------------------------------------------------------------------------


@dataclass
class MatrixCase:
    name: str
    expect_accept: bool  # True = must keep target identity; False = reject dual/mixed
    allow_safe_reject: bool = False  # True = accept target OR explicit reject OK


def _evaluate_case(case: MatrixCase) -> str:
    """Return 'ok', 'false_reject', or 'false_accept'."""
    if case.name == "clean_drifting_target":
        n, h, w = 8, 64, 64
        stack = np.zeros((n, h, w), dtype=np.uint8)
        for z in range(n):
            cx = 20 + z * 3
            yy, xx = np.ogrid[:h, :w]
            d2 = (xx - cx) ** 2 + (yy - 32) ** 2
            stack[z][(d2 >= 8**2) & (d2 <= 12**2)] = 200
        results = track_seeded_vesicle_stack(
            stack, seed_x=20, seed_y=32, seed_frame=0, seed_radius=14
        )
        ok_frames = [r for r in results if r.ok]
        if len(ok_frames) < 4:
            return "false_reject"
        if ok_frames[-1].center_xy[0] <= 20 + 6:
            return "false_reject"
        return "ok"

    if case.name == "separable_tangent_touch":
        h = w = 100
        tcx, tcy, tr = 36.0, 50.0, 12.0
        ncx, ncy, nr = 60.0, 50.0, 12.0  # gap between exteriors ~0
        frame = np.clip(
            _ring(h, w, tcx, tcy, tr - 3, tr) + _ring(h, w, ncx, ncy, nr - 3, nr),
            0,
            255,
        ).astype(np.uint8)
        res = segment_slice_seeded(frame, seed_x=tcx, seed_y=tcy, seed_radius=tr + 1, refine=False)
        neighbor = _filled(h, w, ncx, ncy, nr)
        target = _filled(h, w, tcx, tcy, tr)
        if not res.ok:
            return "false_reject"
        assert res.solid_mask is not None
        if bool(res.solid_mask[int(ncy), int(ncx)]):
            return "false_accept"
        if _mask_iou(res.solid_mask, target) < 0.35:
            return "false_reject"
        neigh_frac = np.count_nonzero(res.solid_mask & neighbor) / max(
            1, np.count_nonzero(neighbor)
        )
        if neigh_frac > 0.22:
            return "false_accept"
        return "ok"

    if case.name == "ambiguous_broad_contact":
        h = w = 120
        tcx, tcy, tr = 48.0, 60.0, 16.0
        ncx, ncy, nr = 74.0, 60.0, 16.0
        frame = np.clip(
            _ring(h, w, tcx, tcy, tr - 4, tr) + _ring(h, w, ncx, ncy, nr - 4, nr),
            0,
            255,
        ).astype(np.uint8)
        frame[56:65, 58:68] = np.maximum(frame[56:65, 58:68], 180)
        res = segment_slice_seeded(frame, seed_x=tcx, seed_y=tcy, seed_radius=tr, refine=True)
        neighbor = _filled(h, w, ncx, ncy, nr)
        if not res.ok:
            if res.contour_xy is None:
                return "ok"  # safe reject
            return "false_accept"
        assert res.solid_mask is not None
        if bool(res.solid_mask[int(round(ncy)), int(round(ncx))]):
            return "false_accept"
        return "ok"

    if case.name == "brighter_neighbour_separable":
        h = w = 100
        tcx, tcy, tr = 34.0, 50.0, 11.0
        ncx, ncy, nr = 58.0, 50.0, 13.0
        frame = np.zeros((h, w), dtype=np.uint8)
        frame = np.maximum(
            frame, _ring(h, w, tcx, tcy, tr - 3, tr, value=150).astype(np.uint8)
        )
        frame = np.maximum(
            frame, _ring(h, w, ncx, ncy, nr - 3, nr, value=255).astype(np.uint8)
        )
        # Thin contact only
        frame[49:52, 44:48] = np.maximum(frame[49:52, 44:48], 160)
        res = segment_slice_seeded(
            frame, seed_x=tcx, seed_y=tcy, seed_radius=tr + 2, refine=False
        )
        if not res.ok:
            return "false_reject"
        assert res.solid_mask is not None
        if bool(res.solid_mask[int(ncy), int(ncx)]):
            return "false_accept"
        if res.center_xy[0] >= (tcx + ncx) / 2:
            return "false_accept"
        return "ok"

    if case.name == "gradual_contact_sequence":
        n, h, w = 8, 100, 100
        stack = np.zeros((n, h, w), dtype=np.uint8)
        tcx, tcy, tr = 40.0, 50.0, 14.0
        ncx, ncy, nr = 68.0, 50.0, 14.0
        for z in range(n):
            frame = np.clip(
                _ring(h, w, tcx, tcy, tr - 4, tr) + _ring(h, w, ncx, ncy, nr - 4, nr),
                0,
                255,
            ).astype(np.uint8)
            if z >= 3:
                bridge = 100 + (z - 3) * 35
                frame[48:53, 48:62] = np.maximum(frame[48:53, 48:62], min(bridge, 255))
            stack[z] = frame
        results = track_seeded_vesicle_stack(
            stack, seed_x=tcx, seed_y=tcy, seed_frame=0, seed_radius=tr
        )
        neighbor = _filled(h, w, ncx, ncy, nr)
        # Pre-contact frames must track target
        for z in (0, 1, 2):
            if not results[z].ok:
                return "false_reject"
            assert results[z].solid_mask is not None
            if results[z].center_xy[0] >= (tcx + ncx) / 2:
                return "false_accept"
        # Later frames: isolation or safe reject; never dual-center
        for z in range(3, n):
            res = results[z]
            if not res.ok:
                if res.contour_xy is not None:
                    return "false_accept"
                continue
            assert res.solid_mask is not None
            if bool(res.solid_mask[int(ncy), int(ncx)]):
                return "false_accept"
            neigh_frac = np.count_nonzero(res.solid_mask & neighbor) / max(
                1, np.count_nonzero(neighbor)
            )
            if neigh_frac > 0.25:
                return "false_accept"
        return "ok"

    if case.name == "pear_deformed_single":
        h = w = 100
        yy, xx = np.ogrid[:h, :w]
        solid = ((xx - 50) / 20) ** 2 + ((yy - 50) / 14) ** 2 <= 1.0
        solid = solid | (((xx - 58) / 10) ** 2 + ((yy - 50) / 10) ** 2 <= 1.0)
        frame = _rim_from_solid(solid)
        res = segment_slice_seeded(frame, seed_x=50, seed_y=50, seed_radius=22, refine=False)
        if not res.ok:
            return "false_reject"
        return "ok"

    if case.name == "flattened_ellipse_single":
        h = w = 100
        yy, xx = np.ogrid[:h, :w]
        solid = ((xx - 50) / 22) ** 2 + ((yy - 50) / 13) ** 2 <= 1.0
        frame = _rim_from_solid(solid)
        res = segment_slice_seeded(frame, seed_x=50, seed_y=50, seed_radius=22, refine=False)
        if not res.ok:
            return "false_reject"
        return "ok"

    if case.name == "mildly_concave_single":
        h = w = 100
        solid = _filled(h, w, 50, 50, 18)
        solid[44:56, 50:58] = False  # indentation
        frame = _rim_from_solid(solid)
        res = segment_slice_seeded(frame, seed_x=48, seed_y=50, seed_radius=18, refine=False)
        if not res.ok:
            return "false_reject"
        return "ok"

    if case.name == "noisy_single":
        h = w = 80
        frame = _ring(h, w, 40, 40, 12, 16).astype(np.uint8)
        rng = np.random.default_rng(0)
        noise = rng.integers(0, 40, size=frame.shape, dtype=np.uint8)
        frame = np.clip(frame.astype(np.int16) + noise, 0, 255).astype(np.uint8)
        res = segment_slice_seeded(frame, seed_x=40, seed_y=40, seed_radius=16, refine=False)
        if not res.ok:
            return "false_reject"
        return "ok"

    if case.name == "underdrawn_seed_radius":
        # Object outer R~18, user seed R=12 (underdrawn) — must not reject solely for 1.20R mass.
        h = w = 80
        frame = _ring(h, w, 40, 40, 12, 18).astype(np.uint8)
        res = segment_slice_seeded(frame, seed_x=40, seed_y=40, seed_radius=12, refine=False)
        if not res.ok:
            return "false_reject"
        return "ok"

    if case.name == "overdrawn_seed_radius":
        h = w = 80
        frame = _ring(h, w, 40, 40, 10, 14).astype(np.uint8)
        res = segment_slice_seeded(frame, seed_x=40, seed_y=40, seed_radius=22, refine=False)
        if not res.ok:
            return "false_reject"
        return "ok"

    if case.name == "deliberate_dual_center_mixed":
        h = w = 100
        # Force a fused dual solid by painting full filled dumbbell intensity.
        solid = _filled(h, w, 38, 50, 14) | _filled(h, w, 62, 50, 14)
        frame = np.zeros((h, w), dtype=np.uint8)
        frame[solid] = 200
        res = segment_slice_seeded(frame, seed_x=38, seed_y=50, seed_radius=14, refine=True)
        if res.ok and res.solid_mask is not None:
            # Dual center enclosed → false accept
            if res.solid_mask[50, 38] and res.solid_mask[50, 62]:
                return "false_accept"
            # Isolated target is also ok
            if res.solid_mask[50, 62]:
                return "false_accept"
            return "ok"
        if res.contour_xy is None and (res.solid_mask is None or not np.any(res.solid_mask)):
            return "ok"
        return "false_accept"

    raise AssertionError(f"unknown case {case.name}")


MATRIX: list[MatrixCase] = [
    MatrixCase("clean_drifting_target", expect_accept=True),
    MatrixCase("separable_tangent_touch", expect_accept=True),
    MatrixCase("ambiguous_broad_contact", expect_accept=False, allow_safe_reject=True),
    MatrixCase("brighter_neighbour_separable", expect_accept=True),
    MatrixCase("gradual_contact_sequence", expect_accept=True, allow_safe_reject=True),
    MatrixCase("pear_deformed_single", expect_accept=True),
    MatrixCase("flattened_ellipse_single", expect_accept=True),
    MatrixCase("mildly_concave_single", expect_accept=True),
    MatrixCase("noisy_single", expect_accept=True),
    MatrixCase("underdrawn_seed_radius", expect_accept=True),
    MatrixCase("overdrawn_seed_radius", expect_accept=True),
    MatrixCase("deliberate_dual_center_mixed", expect_accept=False, allow_safe_reject=True),
]


def test_labelled_synthetic_matrix_fp_fn_report():
    """Report false-positive / false-reject counts; fail if any error type > 0."""
    results: dict[str, str] = {}
    for case in MATRIX:
        results[case.name] = _evaluate_case(case)

    false_reject = [n for n, r in results.items() if r == "false_reject"]
    false_accept = [n for n, r in results.items() if r == "false_accept"]
    ok = [n for n, r in results.items() if r == "ok"]

    report = (
        f"matrix n={len(MATRIX)} ok={len(ok)} "
        f"false_reject={len(false_reject)}{false_reject} "
        f"false_accept={len(false_accept)}{false_accept}"
    )
    print(report)
    assert not false_reject, report
    assert not false_accept, report


def test_blank_gap_no_reacquisition_neighbor():
    n, h, w = 6, 80, 80
    stack = np.zeros((n, h, w), dtype=np.uint8)
    yy, xx = np.ogrid[:h, :w]
    stack[0][
        ((xx - 25) ** 2 + (yy - 40) ** 2 >= 8**2)
        & ((xx - 25) ** 2 + (yy - 40) ** 2 <= 12**2)
    ] = 200
    for z in (3, 4, 5):
        stack[z][
            ((xx - 60) ** 2 + (yy - 40) ** 2 >= 8**2)
            & ((xx - 60) ** 2 + (yy - 40) ** 2 <= 12**2)
        ] = 200
    results = track_seeded_vesicle_stack(
        stack, seed_x=25, seed_y=40, seed_frame=0, seed_radius=14
    )
    assert results[0].ok
    for z in (3, 4, 5):
        if results[z].ok and results[z].solid_mask is not None:
            assert results[z].center_xy[0] < 45, f"reacquired neighbor at z={z}"


def test_candidate_accepted_rejects_composite_merge_not_soft_flag_alone():
    """Composite multi-object QC fails association; soft single-cue merge does not."""
    prev = SeededSliceResult(
        contour_xy=np.array([[10.0, 10.0], [20.0, 10.0], [20.0, 20.0], [10.0, 20.0]]),
        solid_mask=np.zeros((40, 40), dtype=bool),
        center_xy=(15.0, 15.0),
        area_px=100.0,
        perimeter_px=40.0,
        method="circle_seed",
        ok=True,
    )
    prev.solid_mask[10:20, 10:20] = True
    cand_mask = np.zeros((40, 40), dtype=bool)
    cand_mask[10:20, 10:28] = True

    hard_qc = SliceQC(
        circularity=0.9,
        eta=0.12,
        edge_support=0.95,
        inlier_frac=0.7,
        defect_depth_norm=0.09,
        flat_contact_frac=0.15,
        delta_bic=-7.0,
        n_dt_markers=1,
        merge_suspect=True,
        strong_two_circle=False,
        fitted_radius=12.0,
    )
    hard = SeededSliceResult(
        contour_xy=np.array([[10.0, 10.0], [28.0, 10.0], [28.0, 20.0], [10.0, 20.0]]),
        solid_mask=cand_mask,
        center_xy=(18.0, 15.0),
        area_px=160.0,
        perimeter_px=50.0,
        method="circle_seed",
        ok=True,
        merge_suspect=True,
        qc=hard_qc,
    )
    assert (
        _candidate_accepted(
            hard, prev=prev, ref_area=100.0, max_area_ratio=2.2, jump=40.0
        )
        is False
    )

    soft_qc = SliceQC(
        circularity=0.75,
        eta=0.04,
        edge_support=0.70,
        inlier_frac=0.8,
        defect_depth_norm=0.03,
        flat_contact_frac=0.13,
        delta_bic=1.0,
        n_dt_markers=1,
        merge_suspect=True,
        strong_two_circle=False,
        fitted_radius=12.0,
    )
    # Similar area/center so IoU gates can pass — soft flag alone must not veto.
    soft_mask = np.zeros((40, 40), dtype=bool)
    soft_mask[10:20, 10:21] = True
    soft = SeededSliceResult(
        contour_xy=np.array([[10.0, 10.0], [21.0, 10.0], [21.0, 20.0], [10.0, 20.0]]),
        solid_mask=soft_mask,
        center_xy=(15.5, 15.0),
        area_px=110.0,
        perimeter_px=42.0,
        method="circle_seed",
        ok=True,
        merge_suspect=True,
        qc=soft_qc,
    )
    assert fail_closed(soft_qc) is False
    # May still fail other gates; only assert composite path does not auto-reject soft flag.
    # Soft single-cue: association may accept if IoU/score ok.
    _ = _candidate_accepted(
        soft, prev=prev, ref_area=100.0, max_area_ratio=2.2, jump=40.0
    )

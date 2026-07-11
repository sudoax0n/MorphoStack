"""Labelled synthetic membrane fixtures for seeded identity validation.

These are **computational** fixtures (hollow rings + polar shrink), not biological
ground truth. They support deterministic identity scoring for CI: target vs
neighbour masks, ambiguity policy, and safe-reject outcomes.

Real crowded CZI sign-off is separate (see docs/validation-real-czi-signoff.md).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

import numpy as np

FramePolicy = Literal["require_target", "allow_reject", "expect_blank"]


@dataclass(frozen=True)
class FrameExpectation:
    """Per-frame labels for scoring."""

    target_cx: float
    target_cy: float
    target_r: float
    neighbor_cx: float | None
    neighbor_cy: float | None
    neighbor_r: float | None
    policy: FramePolicy
    # When True, a correct isolated target OR explicit safe rejection both pass.
    ambiguous_contact: bool = False


@dataclass(frozen=True)
class SyntheticTouchingCase:
    """One deterministic validation scenario with full labels."""

    case_id: str
    description: str
    stack: np.ndarray  # (z, y, x) uint8 grayscale
    target_masks: np.ndarray  # (z, y, x) bool solid GT for target body
    neighbor_masks: np.ndarray  # (z, y, x) bool solid GT for neighbour body
    frames: tuple[FrameExpectation, ...]
    seed_x: float
    seed_y: float
    seed_frame: int
    seed_radius: float

    @property
    def shape(self) -> tuple[int, int, int]:
        return tuple(int(v) for v in self.stack.shape)  # type: ignore[return-value]


def _polar_scale(z: int, nz: int, *, pole_scale: float = 0.40) -> float:
    z_eq = (nz - 1) / 2.0
    t = abs(float(z) - z_eq) / max(z_eq, 1e-6)
    return float(pole_scale) + (1.0 - float(pole_scale)) * (1.0 - min(t, 1.0) ** 1.2)


def _paint_membrane_ring(
    frame: np.ndarray,
    *,
    cx: float,
    cy: float,
    r_out: float,
    thickness: float,
    intensity: int = 220,
    broken: bool = False,
    rng: np.random.Generator | None = None,
) -> None:
    if r_out < 2.0:
        return
    r_in = max(1.0, float(r_out) - float(thickness))
    h, w = frame.shape
    yy, xx = np.ogrid[:h, :w]
    d2 = (xx - cx) ** 2 + (yy - cy) ** 2
    ring = (d2 >= r_in**2) & (d2 <= r_out**2)
    if broken and rng is not None:
        # Deterministic sparse gaps along angles (weak/broken membrane control).
        ang = np.arctan2(yy - cy, xx - cx)
        keep = (np.floor((ang + np.pi) * 6 / (2 * np.pi)).astype(int) % 2) == 0
        ring = ring & keep
    frame[ring] = np.maximum(frame[ring], np.uint8(intensity))


def _filled_disk_mask(
    shape_yx: tuple[int, int],
    *,
    cx: float,
    cy: float,
    r: float,
) -> np.ndarray:
    h, w = shape_yx
    yy, xx = np.ogrid[:h, :w]
    return (xx - cx) ** 2 + (yy - cy) ** 2 <= max(float(r), 0.5) ** 2


def _empty_stack(nz: int, h: int, w: int) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    stack = np.zeros((nz, h, w), dtype=np.uint8)
    target = np.zeros((nz, h, w), dtype=bool)
    neighbor = np.zeros((nz, h, w), dtype=bool)
    return stack, target, neighbor


def case_isolated_shrinking(
    *,
    nz: int = 7,
    h: int = 64,
    w: int = 64,
    cx: float = 32.0,
    cy: float = 32.0,
    r_eq: float = 14.0,
) -> SyntheticTouchingCase:
    """No neighbour: polar-shrinking hollow ring (control)."""
    stack, tmask, nmask = _empty_stack(nz, h, w)
    frames: list[FrameExpectation] = []
    for z in range(nz):
        scale = _polar_scale(z, nz)
        r = max(3.0, r_eq * scale)
        _paint_membrane_ring(stack[z], cx=cx, cy=cy, r_out=r, thickness=3.0 * scale)
        tmask[z] = _filled_disk_mask((h, w), cx=cx, cy=cy, r=r)
        frames.append(
            FrameExpectation(
                target_cx=cx,
                target_cy=cy,
                target_r=r,
                neighbor_cx=None,
                neighbor_cy=None,
                neighbor_r=None,
                policy="require_target",
            )
        )
    return SyntheticTouchingCase(
        case_id="isolated_shrinking",
        description="Single hollow ring with polar shrink; no neighbour.",
        stack=stack,
        target_masks=tmask,
        neighbor_masks=nmask,
        frames=tuple(frames),
        seed_x=cx,
        seed_y=cy,
        seed_frame=nz // 2,
        seed_radius=r_eq,
    )


def case_tangent_neighbour(
    *,
    nz: int = 7,
    h: int = 72,
    w: int = 96,
    t_cx: float = 34.0,
    t_cy: float = 36.0,
    t_r: float = 14.0,
    n_r: float = 12.0,
) -> SyntheticTouchingCase:
    """Two rings kiss at equator (tangent / near-tangent outer membranes)."""
    # Centers: distance ≈ t_r + n_r (slight gap 0.2 to stay distinct membranes)
    n_cx = t_cx + t_r + n_r - 0.5
    n_cy = t_cy
    return _two_ring_case(
        case_id="tangent_neighbour",
        description="Near-tangent equatorial membranes with polar shrink.",
        nz=nz,
        h=h,
        w=w,
        t_cx=t_cx,
        t_cy=t_cy,
        t_r_eq=t_r,
        n_cx=n_cx,
        n_cy=n_cy,
        n_r_eq=n_r,
        contact_ambiguous=False,
    )


def case_overlapping_neck(
    *,
    nz: int = 7,
    h: int = 72,
    w: int = 96,
    t_cx: float = 34.0,
    t_cy: float = 36.0,
    t_r: float = 14.0,
    n_r: float = 12.0,
    overlap: float = 3.0,
) -> SyntheticTouchingCase:
    """Circle–circle overlap creates a natural neck (no painted bar)."""
    n_cx = t_cx + t_r + n_r - overlap
    n_cy = t_cy
    return _two_ring_case(
        case_id="overlapping_neck",
        description="Overlapping outer membranes forming a thin geometric neck.",
        nz=nz,
        h=h,
        w=w,
        t_cx=t_cx,
        t_cy=t_cy,
        t_r_eq=t_r,
        n_cx=n_cx,
        n_cy=n_cy,
        n_r_eq=n_r,
        contact_ambiguous=True,
    )


def case_broad_flat_contact(
    *,
    nz: int = 7,
    h: int = 72,
    w: int = 100,
    t_cx: float = 36.0,
    t_cy: float = 36.0,
    t_r: float = 15.0,
    n_r: float = 15.0,
    overlap: float = 7.0,
) -> SyntheticTouchingCase:
    """Similar radii + larger overlap → broader contact zone."""
    n_cx = t_cx + t_r + n_r - overlap
    n_cy = t_cy
    return _two_ring_case(
        case_id="broad_flat_contact",
        description="Broad contact (equal radii, deep outer-circle overlap).",
        nz=nz,
        h=h,
        w=w,
        t_cx=t_cx,
        t_cy=t_cy,
        t_r_eq=t_r,
        n_cx=n_cx,
        n_cy=n_cy,
        n_r_eq=n_r,
        contact_ambiguous=True,
    )


def case_lateral_target_drift(
    *,
    nz: int = 7,
    h: int = 64,
    w: int = 96,
    cy: float = 32.0,
    r_eq: float = 12.0,
    x0: float = 28.0,
    dx_per_z: float = 2.5,
) -> SyntheticTouchingCase:
    """Isolated target drifts laterally across Z (no neighbour)."""
    stack, tmask, nmask = _empty_stack(nz, h, w)
    frames: list[FrameExpectation] = []
    for z in range(nz):
        scale = _polar_scale(z, nz)
        r = max(3.0, r_eq * scale)
        cx = x0 + dx_per_z * z
        _paint_membrane_ring(stack[z], cx=cx, cy=cy, r_out=r, thickness=2.8 * scale)
        tmask[z] = _filled_disk_mask((h, w), cx=cx, cy=cy, r=r)
        frames.append(
            FrameExpectation(
                target_cx=cx,
                target_cy=cy,
                target_r=r,
                neighbor_cx=None,
                neighbor_cy=None,
                neighbor_r=None,
                policy="require_target",
            )
        )
    return SyntheticTouchingCase(
        case_id="lateral_target_drift",
        description="Isolated ring drifts in X across Z.",
        stack=stack,
        target_masks=tmask,
        neighbor_masks=nmask,
        frames=tuple(frames),
        seed_x=x0,
        seed_y=cy,
        seed_frame=0,
        seed_radius=r_eq,
    )


def case_blank_gap_then_neighbour(
    *,
    nz: int = 8,
    h: int = 64,
    w: int = 80,
    t_cx: float = 28.0,
    t_cy: float = 32.0,
    t_r: float = 12.0,
    blank_start: int = 3,
    blank_count: int = 2,
    n_cx: float | None = None,
    n_cy: float | None = None,
    n_r: float = 11.0,
) -> SyntheticTouchingCase:
    """Target present, then blank slices, then a neighbour near the old seed.

    After the gap the target is gone; accepting the neighbour as the target fails.
    Safe rejection / lost frames pass.
    """
    if n_cx is None:
        n_cx = t_cx + 1.0  # near original seed
    if n_cy is None:
        n_cy = t_cy
    stack, tmask, nmask = _empty_stack(nz, h, w)
    frames: list[FrameExpectation] = []
    blank_end = blank_start + blank_count
    for z in range(nz):
        scale = _polar_scale(z, nz)
        if z < blank_start:
            r = max(3.0, t_r * scale)
            _paint_membrane_ring(stack[z], cx=t_cx, cy=t_cy, r_out=r, thickness=2.8 * scale)
            tmask[z] = _filled_disk_mask((h, w), cx=t_cx, cy=t_cy, r=r)
            frames.append(
                FrameExpectation(
                    target_cx=t_cx,
                    target_cy=t_cy,
                    target_r=r,
                    neighbor_cx=None,
                    neighbor_cy=None,
                    neighbor_r=None,
                    policy="require_target",
                )
            )
        elif z < blank_end:
            frames.append(
                FrameExpectation(
                    target_cx=t_cx,
                    target_cy=t_cy,
                    target_r=max(3.0, t_r * scale),
                    neighbor_cx=None,
                    neighbor_cy=None,
                    neighbor_r=None,
                    policy="expect_blank",
                )
            )
        else:
            r_n = max(3.0, n_r * scale)
            _paint_membrane_ring(stack[z], cx=float(n_cx), cy=float(n_cy), r_out=r_n, thickness=2.8 * scale)
            nmask[z] = _filled_disk_mask((h, w), cx=float(n_cx), cy=float(n_cy), r=r_n)
            # Target absent; accepting neighbour as target must fail.
            frames.append(
                FrameExpectation(
                    target_cx=t_cx,
                    target_cy=t_cy,
                    target_r=max(3.0, t_r * scale),
                    neighbor_cx=float(n_cx),
                    neighbor_cy=float(n_cy),
                    neighbor_r=r_n,
                    policy="expect_blank",  # no valid target contour allowed
                    ambiguous_contact=False,
                )
            )
    return SyntheticTouchingCase(
        case_id="blank_gap_then_neighbour",
        description="Target then blank gap then neighbour near old seed (no re-entry).",
        stack=stack,
        target_masks=tmask,
        neighbor_masks=nmask,
        frames=tuple(frames),
        seed_x=t_cx,
        seed_y=t_cy,
        seed_frame=0,
        seed_radius=t_r,
    )


def case_weak_broken_membrane(
    *,
    nz: int = 5,
    h: int = 64,
    w: int = 64,
    cx: float = 32.0,
    cy: float = 32.0,
    r_eq: float = 13.0,
) -> SyntheticTouchingCase:
    """Isolated ring with angular gaps (weak/broken membrane control)."""
    stack, tmask, nmask = _empty_stack(nz, h, w)
    frames: list[FrameExpectation] = []
    rng = np.random.default_rng(0)
    for z in range(nz):
        scale = _polar_scale(z, nz)
        r = max(3.0, r_eq * scale)
        _paint_membrane_ring(
            stack[z],
            cx=cx,
            cy=cy,
            r_out=r,
            thickness=3.0 * scale,
            broken=True,
            rng=rng,
        )
        tmask[z] = _filled_disk_mask((h, w), cx=cx, cy=cy, r=r)
        frames.append(
            FrameExpectation(
                target_cx=cx,
                target_cy=cy,
                target_r=r,
                neighbor_cx=None,
                neighbor_cy=None,
                neighbor_r=None,
                # Isolation preferred; safe miss also acceptable if membrane too weak.
                policy="allow_reject",
                ambiguous_contact=True,
            )
        )
    return SyntheticTouchingCase(
        case_id="weak_broken_membrane",
        description="Isolated ring with broken membrane arcs.",
        stack=stack,
        target_masks=tmask,
        neighbor_masks=nmask,
        frames=tuple(frames),
        seed_x=cx,
        seed_y=cy,
        seed_frame=nz // 2,
        seed_radius=r_eq,
    )


def _two_ring_case(
    *,
    case_id: str,
    description: str,
    nz: int,
    h: int,
    w: int,
    t_cx: float,
    t_cy: float,
    t_r_eq: float,
    n_cx: float,
    n_cy: float,
    n_r_eq: float,
    contact_ambiguous: bool,
) -> SyntheticTouchingCase:
    stack, tmask, nmask = _empty_stack(nz, h, w)
    frames: list[FrameExpectation] = []
    z_eq = nz // 2
    for z in range(nz):
        scale = _polar_scale(z, nz)
        tr = max(3.0, t_r_eq * scale)
        nr = max(3.0, n_r_eq * scale)
        _paint_membrane_ring(stack[z], cx=t_cx, cy=t_cy, r_out=tr, thickness=3.0 * scale)
        _paint_membrane_ring(stack[z], cx=n_cx, cy=n_cy, r_out=nr, thickness=3.0 * scale)
        tmask[z] = _filled_disk_mask((h, w), cx=t_cx, cy=t_cy, r=tr)
        nmask[z] = _filled_disk_mask((h, w), cx=n_cx, cy=n_cy, r=nr)
        # Contact strongest near equator; poles less ambiguous.
        near_eq = abs(z - z_eq) <= 1
        ambiguous = bool(contact_ambiguous and near_eq)
        policy: FramePolicy = "allow_reject" if ambiguous else "require_target"
        frames.append(
            FrameExpectation(
                target_cx=t_cx,
                target_cy=t_cy,
                target_r=tr,
                neighbor_cx=n_cx,
                neighbor_cy=n_cy,
                neighbor_r=nr,
                policy=policy,
                ambiguous_contact=ambiguous,
            )
        )
    return SyntheticTouchingCase(
        case_id=case_id,
        description=description,
        stack=stack,
        target_masks=tmask,
        neighbor_masks=nmask,
        frames=tuple(frames),
        seed_x=t_cx,
        seed_y=t_cy,
        seed_frame=z_eq,
        seed_radius=t_r_eq,
    )


def all_mandatory_cases() -> list[SyntheticTouchingCase]:
    """Mandatory seeded-identity suite (order stable for reports)."""
    return [
        case_isolated_shrinking(),
        case_tangent_neighbour(),
        case_overlapping_neck(),
        case_broad_flat_contact(),
        case_lateral_target_drift(),
        case_blank_gap_then_neighbour(),
        case_weak_broken_membrane(),
    ]


# ---------------------------------------------------------------------------
# Scoring (identity metrics — not biological claims)
# ---------------------------------------------------------------------------


def contour_to_mask(contour_xy: np.ndarray | None, shape_yx: tuple[int, int]) -> np.ndarray:
    """Rasterize contour to a filled boolean mask (empty if no contour)."""
    h, w = shape_yx
    out = np.zeros((h, w), dtype=bool)
    if contour_xy is None or len(contour_xy) < 3:
        return out
    try:
        import cv2

        pts = np.round(np.asarray(contour_xy, dtype=np.float64)).astype(np.int32)
        pts[:, 0] = np.clip(pts[:, 0], 0, w - 1)
        pts[:, 1] = np.clip(pts[:, 1], 0, h - 1)
        canvas = np.zeros((h, w), dtype=np.uint8)
        cv2.fillPoly(canvas, [pts.reshape(-1, 1, 2)], 1)
        return canvas.astype(bool)
    except Exception:
        # Fallback: bbox of points (coarse; used only if OpenCV missing).
        xs = contour_xy[:, 0]
        ys = contour_xy[:, 1]
        x0, x1 = int(max(0, xs.min())), int(min(w, xs.max() + 1))
        y0, y1 = int(max(0, ys.min())), int(min(h, ys.max() + 1))
        out[y0:y1, x0:x1] = True
        return out


def mask_iou(a: np.ndarray, b: np.ndarray) -> float:
    aa = np.asarray(a, dtype=bool)
    bb = np.asarray(b, dtype=bool)
    inter = int(np.count_nonzero(aa & bb))
    union = int(np.count_nonzero(aa | bb))
    if union == 0:
        return 0.0
    return inter / union


def neighbor_contamination(pred: np.ndarray, neighbor: np.ndarray) -> float:
    """Fraction of predicted mask overlapping neighbour GT (0 if pred empty)."""
    p = np.asarray(pred, dtype=bool)
    n = np.asarray(neighbor, dtype=bool)
    area = int(np.count_nonzero(p))
    if area == 0:
        return 0.0
    return int(np.count_nonzero(p & n)) / area


def centroid_of_mask(mask: np.ndarray) -> tuple[float, float] | None:
    m = np.asarray(mask, dtype=bool)
    ys, xs = np.nonzero(m)
    if ys.size == 0:
        return None
    return float(xs.mean()), float(ys.mean())


@dataclass(frozen=True)
class FrameScore:
    frame_index: int
    policy: FramePolicy
    tracked: bool
    target_iou: float
    neighbor_contamination: float
    centroid_error_px: float | None
    merge_rejected: bool
    frame_pass: bool
    detail: str


@dataclass(frozen=True)
class CaseScore:
    case_id: str
    passed: bool
    valid_coverage: float
    mean_target_iou: float
    max_neighbor_contamination: float
    mean_centroid_error_px: float | None
    frames: tuple[FrameScore, ...]
    identity_after_gap_ok: bool
    summary: str


# Thresholds are computational acceptance gates for synthetic CI, not biology.
_MIN_TARGET_IOU = 0.35
_MAX_NEIGHBOR_CONTAM = 0.12
_MAX_CENTROID_ERR_FRAC = 0.55  # × target radius


def score_frame(
    *,
    frame_index: int,
    expect: FrameExpectation,
    pred_mask: np.ndarray,
    tracked: bool,
    merge_rejected: bool,
    target_mask: np.ndarray,
    neighbor_mask: np.ndarray,
) -> FrameScore:
    t_iou = mask_iou(pred_mask, target_mask) if tracked else 0.0
    n_cont = neighbor_contamination(pred_mask, neighbor_mask) if tracked else 0.0
    c_err: float | None = None
    if tracked:
        c = centroid_of_mask(pred_mask)
        if c is not None:
            c_err = float(np.hypot(c[0] - expect.target_cx, c[1] - expect.target_cy))

    max_err = max(float(expect.target_r) * _MAX_CENTROID_ERR_FRAC, 3.0)
    good_isolation = (
        tracked
        and t_iou >= _MIN_TARGET_IOU
        and n_cont <= _MAX_NEIGHBOR_CONTAM
        and (c_err is None or c_err <= max_err)
    )
    wrong_accept = tracked and (
        n_cont > _MAX_NEIGHBOR_CONTAM
        or t_iou < _MIN_TARGET_IOU * 0.5
        or (c_err is not None and c_err > max_err * 1.5)
    )
    safe_reject = (not tracked) and (merge_rejected or expect.policy in ("allow_reject", "expect_blank"))

    if expect.policy == "require_target":
        ok = good_isolation
        detail = "isolated_target" if ok else ("wrong_accept" if tracked else "missing_target")
    elif expect.policy == "expect_blank":
        # No valid target on this frame: must not accept a contour as the target.
        ok = (not tracked) or (not wrong_accept and t_iou >= _MIN_TARGET_IOU and n_cont <= _MAX_NEIGHBOR_CONTAM)
        # Stronger: any tracked contour with neighbour contamination fails.
        if tracked and n_cont > _MAX_NEIGHBOR_CONTAM:
            ok = False
            detail = "identity_theft"
        elif tracked and t_iou < _MIN_TARGET_IOU:
            ok = False
            detail = "wrong_identity"
        elif not tracked:
            ok = True
            detail = "safe_blank"
        else:
            ok = good_isolation
            detail = "kept_target"
    else:  # allow_reject
        ok = good_isolation or (not tracked)  # safe miss ok
        if wrong_accept:
            ok = False
        detail = (
            "isolated_target"
            if good_isolation
            else ("safe_reject" if not tracked else "wrong_accept")
        )

    return FrameScore(
        frame_index=frame_index,
        policy=expect.policy,
        tracked=tracked,
        target_iou=float(t_iou),
        neighbor_contamination=float(n_cont),
        centroid_error_px=c_err,
        merge_rejected=bool(merge_rejected),
        frame_pass=bool(ok),
        detail=detail,
    )


def score_case_from_predictions(
    case: SyntheticTouchingCase,
    *,
    contours: list[np.ndarray | None],
    tracked: list[bool],
    merge_rejected: list[bool],
) -> CaseScore:
    """Score a case given per-frame predicted contours and flags."""
    nz = case.stack.shape[0]
    assert len(contours) == nz and len(tracked) == nz and len(merge_rejected) == nz
    frame_scores: list[FrameScore] = []
    for z in range(nz):
        pred = contour_to_mask(contours[z], case.stack.shape[1:])
        frame_scores.append(
            score_frame(
                frame_index=z,
                expect=case.frames[z],
                pred_mask=pred,
                tracked=bool(tracked[z]),
                merge_rejected=bool(merge_rejected[z]),
                target_mask=case.target_masks[z],
                neighbor_mask=case.neighbor_masks[z],
            )
        )

    # Identity after gap: for blank_gap case, post-blank frames must not steal neighbour.
    identity_after_gap_ok = True
    saw_blank = False
    for fs, exp in zip(frame_scores, case.frames):
        if exp.policy == "expect_blank":
            saw_blank = True
            if fs.detail in ("identity_theft", "wrong_identity"):
                identity_after_gap_ok = False
        elif saw_blank and exp.policy == "require_target" and not fs.frame_pass:
            identity_after_gap_ok = False

    valid_frames = [fs for fs in frame_scores if case.frames[fs.frame_index].policy == "require_target"]
    if valid_frames:
        coverage = sum(1 for fs in valid_frames if fs.frame_pass) / len(valid_frames)
    else:
        coverage = 1.0 if all(fs.frame_pass for fs in frame_scores) else 0.0

    ious = [fs.target_iou for fs in frame_scores if fs.tracked]
    contams = [fs.neighbor_contamination for fs in frame_scores if fs.tracked]
    cerrs = [fs.centroid_error_px for fs in frame_scores if fs.centroid_error_px is not None]

    all_pass = all(fs.frame_pass for fs in frame_scores) and identity_after_gap_ok
    summary = "PASS" if all_pass else "FAIL"
    return CaseScore(
        case_id=case.case_id,
        passed=all_pass,
        valid_coverage=float(coverage),
        mean_target_iou=float(np.mean(ious)) if ious else 0.0,
        max_neighbor_contamination=float(max(contams) if contams else 0.0),
        mean_centroid_error_px=float(np.mean(cerrs)) if cerrs else None,
        frames=tuple(frame_scores),
        identity_after_gap_ok=identity_after_gap_ok,
        summary=summary,
    )


def assert_case_geometry_consistent(case: SyntheticTouchingCase) -> None:
    """Internal consistency checks for generators (unit tests)."""
    nz, h, w = case.stack.shape
    assert case.target_masks.shape == (nz, h, w)
    assert case.neighbor_masks.shape == (nz, h, w)
    assert len(case.frames) == nz
    assert case.stack.dtype == np.uint8
    assert 0 <= case.seed_frame < nz
    for z, exp in enumerate(case.frames):
        # Target mask empty only on blank policies when target absent.
        t_area = int(np.count_nonzero(case.target_masks[z]))
        n_area = int(np.count_nonzero(case.neighbor_masks[z]))
        if exp.policy == "require_target":
            assert t_area > 0, f"{case.case_id} z={z}: empty target mask"
            assert case.stack[z].max() > 0, f"{case.case_id} z={z}: dark frame"
        if exp.neighbor_cx is not None:
            assert n_area > 0 or exp.policy == "expect_blank"
        # Masks should not be identical when both present and centers differ.
        if t_area > 0 and n_area > 0:
            if abs(exp.target_cx - float(exp.neighbor_cx or -1)) > 1.0:
                assert mask_iou(case.target_masks[z], case.neighbor_masks[z]) < 0.95

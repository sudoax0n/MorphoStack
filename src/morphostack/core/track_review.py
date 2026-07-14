"""Manual review states and correction invalidation for seeded tracking.

Frame authority (Packet 04 / quality plan):

- ``provisional`` — display-only pending / fast path
- ``exact_accepted`` — auto exact accept, measure-authoritative
- ``uncertain`` — published but not measure-authoritative (merge-suspect, fail, cap…)
- ``gap`` — honest gap terminal
- ``manually_anchored`` — operator correction anchor, measure-authoritative
- ``unreached`` — not yet walked / invalidated placeholder

Only ``exact_accepted`` and ``manually_anchored`` contribute to authoritative
measurement. ``merge_suspect`` is never displayed or counted as tracked.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal

from morphostack.core.seeded_vesicle import SeededSliceResult

FrameAuthorityState = Literal[
    "provisional",
    "exact_accepted",
    "uncertain",
    "gap",
    "manually_anchored",
    "unreached",
]

CorrectionAction = Literal[
    "reject_frame",
    "accept_manual_anchor",
    "reseed",
]

MEASURE_AUTHORITATIVE_STATES: frozenset[str] = frozenset(
    {"exact_accepted", "manually_anchored"}
)

MANUAL_METHOD = "manual_anchor"
MANUAL_REJECT_METHOD = "manual_reject"


def is_unreached_result(result: SeededSliceResult | None) -> bool:
    if result is None:
        return True
    if result.ok:
        return False
    return str(result.method) == "circle_seed_unreached"


def has_complete_measure_geometry(result: SeededSliceResult | None) -> bool:
    """Measure authority requires a non-empty contour and a solid mask with area."""
    if result is None or not result.ok:
        return False
    contour = getattr(result, "contour_xy", None)
    if contour is None:
        return False
    try:
        import numpy as np

        arr = np.asarray(contour)
        if arr.size < 6 or arr.reshape(-1, 2).shape[0] < 3:
            return False
    except Exception:
        return False
    mask = getattr(result, "solid_mask", None)
    if mask is None:
        return False
    try:
        import numpy as np

        m = np.asarray(mask)
        if m.size == 0 or not bool(m.any()):
            return False
    except Exception:
        return False
    if float(getattr(result, "area_px", 0.0) or 0.0) <= 0.0:
        return False
    return True


def require_complete_manual_geometry(result: SeededSliceResult | None) -> None:
    """Raise if result cannot be a measure-authoritative manual anchor."""
    if result is None or not result.ok:
        raise ValueError("accept_manual_anchor requires an accepted anchor_result")
    if not has_complete_measure_geometry(result):
        raise ValueError(
            "accept_manual_anchor requires a complete contour and solid_mask "
            "(incomplete rasterization or missing mask cannot be measure-authoritative)"
        )


def is_manual_anchor_result(result: SeededSliceResult | None) -> bool:
    """True for operator anchors that carry complete geometry (never incomplete masks)."""
    if result is None:
        return False
    if not str(result.method).startswith(MANUAL_METHOD):
        return False
    if not bool(result.ok):
        return False
    if bool(getattr(result, "merge_suspect", False)):
        return False
    return has_complete_measure_geometry(result)


def is_gap_result(result: SeededSliceResult | None) -> bool:
    if result is None:
        return False
    m = str(result.method)
    return m in ("circle_seed_gap", "manual_invalidate_gap") or m.endswith("_gap")


def is_measure_authoritative(result: SeededSliceResult | None) -> bool:
    """True only for exact-accepted or complete manual anchors (never merge-suspect)."""
    if result is None or not result.ok:
        return False
    if bool(getattr(result, "merge_suspect", False)):
        return False
    if not has_complete_measure_geometry(result):
        return False
    if is_manual_anchor_result(result):
        return True
    m = str(result.method)
    if m in (MANUAL_REJECT_METHOD, "exact_pending", "circle_seed_unreached"):
        return False
    if m in ("circle_seed_gap", "cap_detected") or "fail" in m or "reject" in m:
        return False
    # Incomplete geometry cannot be exact_accepted for measurement either.
    if str(result.method).startswith(MANUAL_METHOD):
        return False
    return True


def classify_frame_authority(
    result: SeededSliceResult | None,
    *,
    preview_quality: str | None = None,
    exact_pending: bool = False,
) -> tuple[FrameAuthorityState, str | None]:
    """Return (state, reason) for one published or pending frame."""
    if exact_pending or (preview_quality == "provisional" and result is None):
        return "provisional", "exact_pending"
    if result is None:
        if preview_quality == "provisional":
            return "provisional", "provisional_overlay"
        return "unreached", "missing"
    method = str(result.method or "")
    if method == "exact_pending":
        return "provisional", "exact_pending"
    if is_unreached_result(result):
        return "unreached", "unreached"
    if is_gap_result(result):
        return "gap", method or "gap"
    if method == MANUAL_REJECT_METHOD:
        return "uncertain", "manual_reject"
    if not result.ok:
        if "cap" in method:
            return "uncertain", method
        if "reject" in method or "fail" in method:
            return "uncertain", method
        return "uncertain", method or "not_ok"
    # ok=True paths — unsafe provenance and incomplete geometry never look "tracked".
    if bool(getattr(result, "merge_suspect", False)):
        return "uncertain", "merge_suspect"
    if method.startswith(MANUAL_METHOD):
        if not has_complete_measure_geometry(result):
            return "uncertain", "incomplete_manual_geometry"
        return "manually_anchored", "operator_anchor"
    if not has_complete_measure_geometry(result):
        return "uncertain", "incomplete_geometry"
    return "exact_accepted", None


def display_as_tracked(state: FrameAuthorityState) -> bool:
    """UI may only label measure-authoritative states as tracked."""
    return state in MEASURE_AUTHORITATIVE_STATES


@dataclass
class CorrectionEvent:
    """Audit row for one operator correction (old frame kept for rollback)."""

    action: CorrectionAction
    frame_index: int
    correction_revision: int
    invalidated_low: int | None
    invalidated_high: int | None  # inclusive range cleared to unreached
    previous_result: SeededSliceResult | None
    reason: str | None = None


@dataclass
class TrackingReviewMeta:
    """Per-cache-key correction bookkeeping (not part of scientific mask)."""

    correction_revision: int = 0
    events: list[CorrectionEvent] = field(default_factory=list)

    def to_json_dict(self) -> dict[str, Any]:
        return {
            "correction_revision": int(self.correction_revision),
            "event_count": len(self.events),
            "events": [
                {
                    "action": e.action,
                    "frame_index": e.frame_index,
                    "correction_revision": e.correction_revision,
                    "invalidated_low": e.invalidated_low,
                    "invalidated_high": e.invalidated_high,
                    "reason": e.reason,
                    "had_previous": e.previous_result is not None,
                    "previous_ok": bool(e.previous_result.ok) if e.previous_result else None,
                    "previous_method": (
                        str(e.previous_result.method) if e.previous_result else None
                    ),
                }
                for e in self.events[-32:]
            ],
        }


def _unreached_placeholder(seed_x: float, seed_y: float) -> SeededSliceResult:
    return SeededSliceResult(
        None, None, (float(seed_x), float(seed_y)), 0.0, 0.0, "circle_seed_unreached", False
    )


def next_manual_or_seed_anchor(
    results: list[SeededSliceResult],
    *,
    start_frame: int,
    direction: int,
    seed_frame: int,
) -> int | None:
    """First manual anchor or seed frame strictly past ``start_frame`` along direction."""
    n = len(results)
    z = int(start_frame) + int(direction)
    while 0 <= z < n:
        if z == int(seed_frame):
            return z
        if is_manual_anchor_result(results[z]):
            return z
        z += int(direction)
    return None


def invalidate_downstream_interval(
    results: list[SeededSliceResult],
    *,
    anchor_frame: int,
    direction: int,
    seed_frame: int,
    seed_x: float,
    seed_y: float,
) -> tuple[list[SeededSliceResult], int | None, int | None]:
    """Clear frames strictly beyond the anchor until the next manual/seed anchor.

    Returns (new_results, invalidated_low, invalidated_high) inclusive bounds
    of cleared frames, or (results, None, None) if nothing cleared.
    Does not clear the seed frame or other manual anchors.
    """
    n = len(results)
    out = list(results)
    while len(out) < n:
        out.append(_unreached_placeholder(seed_x, seed_y))
    stop = next_manual_or_seed_anchor(
        out, start_frame=anchor_frame, direction=direction, seed_frame=seed_frame
    )
    cleared: list[int] = []
    z = int(anchor_frame) + int(direction)
    while 0 <= z < n:
        if stop is not None and (
            (direction > 0 and z >= stop) or (direction < 0 and z <= stop)
        ):
            break
        if z == int(seed_frame) or is_manual_anchor_result(out[z]):
            break
        out[z] = _unreached_placeholder(seed_x, seed_y)
        cleared.append(z)
        z += int(direction)
    if not cleared:
        return out, None, None
    return out, min(cleared), max(cleared)


def apply_manual_correction(
    results: list[SeededSliceResult] | None,
    *,
    n_frames: int,
    seed_frame: int,
    seed_x: float,
    seed_y: float,
    frame_index: int,
    action: CorrectionAction,
    anchor_result: SeededSliceResult | None = None,
    meta: TrackingReviewMeta | None = None,
    operator_drawn: bool = False,
) -> tuple[list[SeededSliceResult], TrackingReviewMeta, CorrectionEvent]:
    """Apply reject or accept_manual_anchor; invalidate only downstream intervals.

    ``accept_manual_anchor`` requires complete contour + solid_mask. Unsafe
    automatic provenance (``merge_suspect``) may be cleared only when
    ``operator_drawn=True`` (genuine user-drawn geometry). Auto re-segment
    accept must not launder merge-suspect into measure authority.

    ``reseed`` is identity-level (new seed key) — callers should not use this
    for reseeds; it is accepted here only to record an audit event without
    mutating frames when ``action=='reseed'``.
    """
    meta = meta if meta is not None else TrackingReviewMeta()
    if results is None:
        base = [_unreached_placeholder(seed_x, seed_y) for _ in range(n_frames)]
    else:
        base = list(results)
        while len(base) < n_frames:
            base.append(_unreached_placeholder(seed_x, seed_y))
        base = base[:n_frames]

    if frame_index < 0 or frame_index >= n_frames:
        raise ValueError("frame_index out of range")

    previous = base[frame_index]
    meta.correction_revision = int(meta.correction_revision) + 1
    rev = meta.correction_revision
    inv_low: int | None = None
    inv_high: int | None = None

    if action == "reseed":
        # Seed change creates a new TrackingCacheKey; no in-place mutation.
        event = CorrectionEvent(
            action=action,
            frame_index=int(frame_index),
            correction_revision=rev,
            invalidated_low=None,
            invalidated_high=None,
            previous_result=previous,
            reason="reseed_new_identity",
        )
        meta.events.append(event)
        return base, meta, event

    if action == "reject_frame":
        base[frame_index] = SeededSliceResult(
            None,
            None,
            (float(seed_x), float(seed_y)),
            0.0,
            0.0,
            MANUAL_REJECT_METHOD,
            False,
            merge_suspect=False,
        )
    elif action == "accept_manual_anchor":
        require_complete_manual_geometry(anchor_result)
        assert anchor_result is not None  # for type checkers
        suspect = bool(getattr(anchor_result, "merge_suspect", False))
        if suspect and not operator_drawn:
            raise ValueError(
                "accept_manual_anchor refuses merge_suspect automatic geometry; "
                "draw a confirmed polygon mask or fix isolation before anchoring"
            )
        # Provenance is operator-confirmed only after geometry validation above.
        # merge_suspect is never carried into a measure-authoritative manual anchor:
        # auto path already refused suspect; drawn path clears it by confirmation.
        base[frame_index] = SeededSliceResult(
            anchor_result.contour_xy,
            anchor_result.solid_mask,
            anchor_result.center_xy,
            float(anchor_result.area_px),
            float(anchor_result.perimeter_px),
            MANUAL_METHOD,
            True,
            merge_suspect=False,
            qc=anchor_result.qc,
            effective_threshold=anchor_result.effective_threshold,
        )
    else:
        raise ValueError(f"unknown correction action: {action!r}")

    # Invalidate only the open intervals away from the correction until the
    # next manual or seed anchor (never the opposite side beyond those anchors).
    lows: list[int] = []
    highs: list[int] = []
    for d in (-1, 1):
        base, lo, hi = invalidate_downstream_interval(
            base,
            anchor_frame=frame_index,
            direction=d,
            seed_frame=seed_frame,
            seed_x=seed_x,
            seed_y=seed_y,
        )
        if lo is not None and hi is not None:
            lows.append(lo)
            highs.append(hi)
    if lows:
        inv_low = min(lows)
        inv_high = max(highs)

    event = CorrectionEvent(
        action=action,
        frame_index=int(frame_index),
        correction_revision=rev,
        invalidated_low=inv_low,
        invalidated_high=inv_high,
        previous_result=previous,
        reason=action,
    )
    meta.events.append(event)
    return base, meta, event


def frame_authority_payload(
    result: SeededSliceResult | None,
    *,
    preview_quality: str | None = None,
    exact_pending: bool = False,
    correction_revision: int = 0,
) -> dict[str, Any]:
    state, reason = classify_frame_authority(
        result,
        preview_quality=preview_quality,
        exact_pending=exact_pending,
    )
    return {
        "frame_authority": state,
        "authority_reason": reason,
        "measure_authoritative": state in MEASURE_AUTHORITATIVE_STATES,
        "display_as_tracked": display_as_tracked(state),
        "merge_suspect": bool(getattr(result, "merge_suspect", False)) if result else False,
        "correction_revision": int(correction_revision),
    }

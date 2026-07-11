from __future__ import annotations

import numpy as np

import morphostack.core.seeded_vesicle as sv


def _ring_frame(h: int, w: int, cx: float, cy: float, r_in: float, r_out: float) -> np.ndarray:
    yy, xx = np.ogrid[:h, :w]
    d = (xx - cx) ** 2 + (yy - cy) ** 2
    frame = np.zeros((h, w), dtype=np.float64)
    frame[(d >= r_in**2) & (d <= r_out**2)] = 1.0
    return frame


def test_fast_preview_bypasses_expensive_seed_refinement(monkeypatch):
    frame = _ring_frame(80, 80, 40, 40, 14, 18)

    def should_not_run(*args, **kwargs):
        raise AssertionError("fast preview must bypass expensive refinement")

    monkeypatch.setattr(sv, "_bilateral", should_not_run)
    monkeypatch.setattr(sv, "_refine_contour_morphgac", should_not_run)

    result = sv.segment_slice_seeded(
        frame,
        seed_x=40,
        seed_y=40,
        seed_radius=18,
        fast_preview=True,
    )

    assert result.ok
    assert result.contour_xy is not None
    assert result.solid_mask is not None
    assert result.solid_mask.shape == frame.shape
    assert result.solid_mask[40, 40]
    assert abs(result.center_xy[0] - 40) < 3

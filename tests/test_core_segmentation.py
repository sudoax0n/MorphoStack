from __future__ import annotations

import numpy as np
import pytest

from morphostack.core.segmentation import (
    THRESHOLD_CONTRACT_VERSION,
    _sample_intensity_values,
    apply_rect_roi,
    suggest_threshold,
    suggest_threshold_report,
    threshold_mask,
)


def test_threshold_mask_is_inclusive():
    image = np.array([[0, 5], [10, 15]])
    mask = threshold_mask(image, 10)
    np.testing.assert_array_equal(mask, [[False, False], [True, True]])


def test_suggest_threshold_handles_constant_stack():
    threshold, method = suggest_threshold(np.full((2, 4, 4), 7, dtype=np.uint8))

    assert threshold == 7.0
    assert method == "constant"


def test_suggest_threshold_report_matches_numeric_and_adds_contract():
    rng = np.random.default_rng(1)
    stack = rng.integers(0, 200, size=(4, 32, 32), dtype=np.uint8)
    stack[:, 10:20, 10:20] = 180
    thr_a, method_a = suggest_threshold(stack, method="auto", max_samples=50_000, seed=0)
    thr_b, method_b, meta = suggest_threshold_report(
        stack,
        method="auto",
        max_samples=50_000,
        seed=0,
        source_path="fixture.tif",
        source_revision="path:/abs/fixture.tif|m1|s2",
        source_identity_kind="path",
    )
    assert thr_a == thr_b
    assert method_a == method_b
    assert meta["threshold"] == thr_b
    assert meta["method"] == method_b
    assert meta["threshold_semantics"] == "ui_starting_guess"
    assert meta["suggestion_scope"] == "stack_sample"
    assert meta["threshold_contract_version"] == THRESHOLD_CONTRACT_VERSION
    assert meta["source_revision"] == "path:/abs/fixture.tif|m1|s2"
    assert meta["source_identity_kind"] == "path"
    assert meta["authoritative_for"] == []
    assert "seeded_exact_contour" in meta["not_authoritative_for"]
    assert meta["histogram_domain"]["dtype"] == "uint8"
    assert meta["histogram_domain"]["n_samples"] > 0
    assert any("local per-slice" in w or "local" in w for w in meta["warnings"])

    # Ephemeral upload: revision stays null (never falls back to filename).
    _t, _m, ephemeral = suggest_threshold_report(
        stack,
        method="percentile",
        source_path="pretty.tif",
        source_revision=None,
        source_identity_kind="upload_ephemeral",
    )
    assert ephemeral["source_revision"] is None
    assert ephemeral["source_identity_kind"] == "upload_ephemeral"
    assert ephemeral["source_path"] == "pretty.tif"


def test_suggest_threshold_percentile_fallback():
    stack = np.array([0, 0, 10, 20], dtype=np.uint8)

    threshold, method = suggest_threshold(stack, method="percentile")

    assert threshold == 12.5
    assert method == "percentile"


def test_suggest_threshold_rejects_unknown_method():
    with pytest.raises(ValueError, match="threshold method"):
        suggest_threshold(np.zeros((1, 2, 2)), method="entropy")


def test_suggest_threshold_small_stack_returns_finite():
    rng = np.random.default_rng(1)
    stack = rng.integers(0, 200, size=(4, 32, 32), dtype=np.uint8)
    stack[:, 10:20, 10:20] = 180

    threshold, method = suggest_threshold(stack)

    assert np.isfinite(threshold)
    assert method in {"robust_otsu", "otsu", "percentile", "constant"}


def test_sample_intensity_values_caps_at_max_samples():
    arr = np.arange(10_000, dtype=np.uint16).reshape(10, 100, 10)
    sample = _sample_intensity_values(arr, max_samples=100, seed=0)

    assert sample.dtype == np.float64
    assert sample.size <= 100
    assert sample.size > 0


def test_sample_intensity_values_reproducible_with_seed():
    arr = np.arange(5_000, dtype=np.float32)
    a = _sample_intensity_values(arr, max_samples=200, seed=42)
    b = _sample_intensity_values(arr, max_samples=200, seed=42)
    c = _sample_intensity_values(arr, max_samples=200, seed=7)

    np.testing.assert_array_equal(a, b)
    assert not np.array_equal(a, c)


def test_sample_intensity_values_prefers_nonzero_when_sparse():
    # Large volume of zeros with a small bright patch — sampling must still
    # surface some positive intensities for membrane-like data.
    stack = np.zeros((30, 200, 200), dtype=np.uint8)
    stack[:, 50:70, 50:70] = 120
    sample = _sample_intensity_values(stack, max_samples=5_000, seed=0)

    assert sample.size <= 5_000
    assert np.count_nonzero(sample) >= 16


def test_suggest_threshold_large_stack_uses_sampling_without_oom():
    # 20×500×500 = 5e6 voxels; full float64 ravel would be ~40MB and full-size
    # bool masks worse. Cap samples tightly and assert a finite suggestion.
    stack = np.zeros((20, 500, 500), dtype=np.uint8)
    stack[:, 100:200, 100:200] = 160
    stack[:, 300:320, 300:320] = 40

    threshold, method = suggest_threshold(stack, max_samples=50_000, seed=0)

    assert np.isfinite(threshold)
    assert 0 < threshold < 255
    assert method in {"robust_otsu", "otsu", "percentile"}


def test_suggest_threshold_sampling_path_invoked_for_large_input(monkeypatch):
    calls: list[tuple[int, int]] = []
    real = _sample_intensity_values

    def spy(stack, *, max_samples=2_000_000, seed=0):
        calls.append((int(np.asarray(stack).size), max_samples))
        return real(stack, max_samples=max_samples, seed=seed)

    monkeypatch.setattr(
        "morphostack.core.segmentation._sample_intensity_values",
        spy,
    )
    # Import path used by suggest_threshold is the module-local name; patch there.
    import morphostack.core.segmentation as seg

    monkeypatch.setattr(seg, "_sample_intensity_values", spy)

    stack = np.zeros((8, 256, 256), dtype=np.uint8)
    stack[2:6, 20:80, 20:80] = 200
    threshold, _method = seg.suggest_threshold(stack, max_samples=1_000, seed=1)

    assert calls
    assert calls[0][0] == stack.size
    assert calls[0][1] == 1_000
    assert np.isfinite(threshold)


def test_apply_rect_roi_masks_all_frames():
    stack = np.ones((2, 4, 4), dtype=np.uint8)
    cropped = apply_rect_roi(stack, xmin=1, xmax=3, ymin=1, ymax=3)
    assert cropped.sum() == 8
    assert cropped[:, 1:3, 1:3].sum() == 8


def test_apply_rect_roi_rejects_empty_bounds():
    stack = np.ones((1, 4, 4), dtype=np.uint8)
    with pytest.raises(ValueError):
        apply_rect_roi(stack, xmin=2, xmax=2, ymin=0, ymax=3)

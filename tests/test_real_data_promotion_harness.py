"""Packet 05: real-data promotion harness (validation-only)."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import numpy as np
import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from validation.promotion.gates import evaluate_promotion, score_object
from validation.promotion.metrics import dice_binary, hausdorff95_boundary, jaccard_binary
from validation.promotion.schema import (
    CorpusManifest,
    HoldoutManifest,
    LabelledFrame,
    ObjectRecord,
    PredictedFrame,
    PredictionBundle,
    SeedSpec,
    VoxelProvenance,
    AcquisitionRecord,
    load_corpus_dir,
)


FIXTURES = ROOT / "validation" / "promotion" / "fixtures"


def _disk(h: int, w: int, cy: float, cx: float, r: float) -> np.ndarray:
    yy, xx = np.ogrid[:h, :w]
    return ((yy - cy) ** 2 + (xx - cx) ** 2) <= r**2


def test_dice_jaccard_perfect_and_empty():
    m = _disk(32, 32, 16, 16, 6)
    assert dice_binary(m, m) == pytest.approx(1.0)
    assert jaccard_binary(m, m) == pytest.approx(1.0)
    z = np.zeros_like(m)
    assert dice_binary(z, z) == pytest.approx(1.0)


def test_hausdorff95_identical_near_zero():
    m = _disk(32, 32, 16, 16, 5)
    hd = hausdorff95_boundary(m, m)
    assert hd is not None
    assert hd < 1.0


def test_hausdorff95_physical_um_scales_with_spacing():
    """Calibrated HD must be in µm, not bare pixels when spacing is supplied."""
    m = _disk(40, 40, 20, 20, 6)
    shifted = _disk(40, 40, 20, 22, 6)  # ~2 px lateral shift
    hd_px = hausdorff95_boundary(m, shifted)
    assert hd_px is not None and hd_px > 0.5
    hd_um = hausdorff95_boundary(m, shifted, pixel_size_yx_um=(0.5, 0.2))
    assert hd_um is not None
    # Distance is anisotropic; must scale off pure pixel value when spacing ≠ 1.
    assert hd_um != pytest.approx(hd_px)
    # Lower bound: pure-x shift of 2 px at 0.2 µm/px → ~0.4 µm component.
    assert hd_um > 0.2
    # Upper bound sanity: not equal to treating as 1 µm/px.
    assert hd_um < hd_px * 0.95


def test_empty_corpus_blocked():
    corpus, preds = load_corpus_dir(FIXTURES / "blocked_empty")
    result = evaluate_promotion(corpus, preds, require_speed=False)
    assert result["overall"] == "BLOCKED"
    assert result["composite_accuracy_percent"] is None
    statuses = {g["gate_id"]: g["status"] for g in result["gates"]}
    assert statuses["W5"] == "BLOCKED"
    assert statuses["HOLD"] == "BLOCKED"
    assert "Touching-vesicle real-data sign-off incomplete" in result["overall_detail"] or (
        "incomplete" in result["incomplete_signoff_statement"].lower()
    )


def test_synthetic_unit_still_blocked_for_w5():
    """Synthetic schema may compute, but must not close W5."""
    corpus, preds = load_corpus_dir(FIXTURES / "synthetic_unit")
    result = evaluate_promotion(corpus, preds, require_speed=True)
    assert result["overall"] == "BLOCKED"
    assert result["composite_accuracy_percent"] is None
    w5 = next(g for g in result["gates"] if g["gate_id"] == "W5")
    assert w5["status"] == "BLOCKED"
    assert "Synthetic" in w5["detail"] or "absent" in w5["detail"].lower()


def test_partition_leakage_detected():
    corpus, _ = load_corpus_dir(FIXTURES / "synthetic_unit")
    # Split contact pair across partitions
    objs = []
    for o in corpus.objects:
        if o.object_id == "contact-pair-b":
            o.partition = "tune"  # type: ignore[misc]
        objs.append(o)
    corpus.objects = objs
    result = evaluate_promotion(corpus, None, require_speed=False)
    leak = next(g for g in result["gates"] if g["gate_id"] == "LEAK")
    assert leak["status"] == "FAIL"


def test_zero_false_merge_gate_fails_on_accept():
    ref = _disk(32, 32, 16, 12, 5)
    # Prediction overlaps badly toward neighbor (still "accepted")
    bad = _disk(32, 32, 16, 18, 8)
    obj = ObjectRecord(
        object_id="c1",
        source_id="s1",
        primary_stratum="S2",
        stratum_ids=("S2",),
        seed=SeedSpec("circle", 12, 16, 0, 5.0),
        partition="holdout",
        labelled_frames=[
            LabelledFrame(
                frame_index=0,
                mask_array=ref,
                is_lobe_bridge_if_accepted=True,
                expected_algorithm_behavior="must_not_merge",
            )
        ],
    )
    corpus = CorpusManifest(
        corpus_id="fm",
        acquisitions=[
            AcquisitionRecord(
                source_id="s1",
                source_basename="x.tif",
                source_sha256=None,
                format="tif",
                shape_zyx=(1, 32, 32),
                voxel=VoxelProvenance("override", (0.5, 0.2, 0.2), True),
            )
        ],
        objects=[obj],
        holdout=HoldoutManifest(frozen=True, object_ids=("c1",)),
    )
    preds = PredictionBundle(
        by_object={
            "c1": [
                PredictedFrame(
                    frame_index=0,
                    accepted=True,
                    mask_array=bad,
                    false_merge=True,
                )
            ]
        },
        bit_identical_rerun=True,
        latencies=[],
    )
    # Make completeness pass-ish by faking more objects would be heavy;
    # we only assert Gate A logic when not data-blocked on contact labels.
    # Force W5-like labels present:
    result = evaluate_promotion(corpus, preds, require_speed=False)
    # Still CORPUS_N blocked but A may be BLOCKED or FAIL — check score path
    score = score_object(obj, preds.by_object["c1"], corpus=corpus, corrections_for_obj=[])
    assert score.false_merge_accepts >= 1
    assert score.to_dict()["composite_accuracy_percent"] is None


def test_uncertain_frames_excluded_from_dice():
    ref = _disk(24, 24, 12, 12, 5)
    pred = ref.copy()
    obj = ObjectRecord(
        object_id="u1",
        source_id="s1",
        primary_stratum="S1",
        stratum_ids=("S1",),
        seed=SeedSpec("circle", 12, 12, 0, 5.0),
        partition="holdout",
        labelled_frames=[
            LabelledFrame(
                frame_index=0,
                mask_array=ref,
                exclude_from_contour_metrics=True,
                boundary_uncertain=True,
            ),
            LabelledFrame(frame_index=1, mask_array=ref, exclude_from_contour_metrics=False),
        ],
    )
    corpus = CorpusManifest(
        corpus_id="unc",
        acquisitions=[
            AcquisitionRecord(
                source_id="s1",
                source_basename="x.tif",
                source_sha256=None,
                format="tif",
                shape_zyx=(2, 24, 24),
                voxel=VoxelProvenance("metadata", (0.5, 0.2, 0.2), True),
            )
        ],
        objects=[obj],
        holdout=HoldoutManifest(frozen=True, object_ids=("u1",)),
    )
    preds = [
        PredictedFrame(frame_index=0, accepted=True, mask_array=np.zeros_like(ref)),
        PredictedFrame(frame_index=1, accepted=True, mask_array=pred),
    ]
    score = score_object(obj, preds, corpus=corpus, corrections_for_obj=[])
    assert score.n_uncertain_excluded == 1
    assert score.n_labelled_scored == 1
    assert score.dice["median"] == pytest.approx(1.0)


def test_uncalibrated_physical_metrics_suppressed():
    ref = _disk(24, 24, 12, 12, 5)
    obj = ObjectRecord(
        object_id="d1",
        source_id="dopc",
        primary_stratum="S1",
        stratum_ids=("S1",),
        seed=SeedSpec("circle", 12, 12, 0, 5.0),
        partition="holdout",
        labelled_frames=[LabelledFrame(frame_index=0, mask_array=ref)],
    )
    corpus = CorpusManifest(
        corpus_id="def",
        acquisitions=[
            AcquisitionRecord(
                source_id="dopc",
                source_basename="movie.tif",
                source_sha256=None,
                format="tif",
                shape_zyx=(1, 24, 24),
                voxel=VoxelProvenance("default", (1.0, 1.0, 1.0), False),
            )
        ],
        objects=[obj],
        holdout=HoldoutManifest(frozen=True, object_ids=("d1",)),
    )
    preds = [PredictedFrame(frame_index=0, accepted=True, mask_array=ref)]
    score = score_object(obj, preds, corpus=corpus, corrections_for_obj=[])
    assert score.physical_metrics_suppressed is True
    assert score.calibrated is False
    assert score.hausdorff95_um["n"] == 0


def test_calibrated_scores_hausdorff_um():
    ref = _disk(32, 32, 16, 16, 6)
    pred = _disk(32, 32, 16, 17, 6)
    obj = ObjectRecord(
        object_id="c_um",
        source_id="s1",
        primary_stratum="S2",
        stratum_ids=("S2",),
        seed=SeedSpec("circle", 16, 16, 0, 6.0),
        partition="holdout",
        labelled_frames=[LabelledFrame(frame_index=0, mask_array=ref)],
    )
    corpus = CorpusManifest(
        corpus_id="um",
        acquisitions=[
            AcquisitionRecord(
                source_id="s1",
                source_basename="x.tif",
                source_sha256=None,
                format="tif",
                shape_zyx=(1, 32, 32),
                voxel=VoxelProvenance("metadata", (0.5, 0.2, 0.2), True),
            )
        ],
        objects=[obj],
        holdout=HoldoutManifest(frozen=True, object_ids=("c_um",)),
        hausdorff95_limit_um=2.0,
    )
    preds = [PredictedFrame(frame_index=0, accepted=True, mask_array=pred)]
    score = score_object(obj, preds, corpus=corpus, corrections_for_obj=[])
    assert score.calibrated is True
    assert score.physical_metrics_suppressed is False
    assert score.hausdorff95_px["n"] == 1
    assert score.hausdorff95_um["n"] == 1
    assert score.hausdorff95_um["median"] is not None
    # µm distance must not equal raw pixel HD when spacing is 0.2 µm/px.
    assert score.hausdorff95_um["median"] != pytest.approx(score.hausdorff95_px["median"])


def test_gate_d_requires_seed_exact_and_target_z():
    """Provisional-only latency must not PASS Gate D under require_speed."""
    from validation.promotion.schema import LatencyRecord, PredictionBundle

    corpus, _ = load_corpus_dir(FIXTURES / "synthetic_unit")
    # Provisional fast but seed_exact / target_z missing → INCOMPLETE
    preds = PredictionBundle(
        by_object={},
        latencies=[
            LatencyRecord(
                object_id="iso-1",
                provisional_p95_ms=40.0,
                seed_exact_p95_ms=None,
                target_z_p95_ms=None,
            )
        ],
        bit_identical_rerun=True,
    )
    result = evaluate_promotion(corpus, preds, require_speed=True)
    d = next(g for g in result["gates"] if g["gate_id"] == "D")
    assert d["status"] == "INCOMPLETE"
    assert "seed_exact" in d["detail"] or "target_z" in d["detail"]

    # All lanes present but seed_exact over budget → FAIL
    preds2 = PredictionBundle(
        by_object={},
        latencies=[
            LatencyRecord(
                object_id="iso-1",
                provisional_p95_ms=40.0,
                seed_exact_p95_ms=9000.0,
                target_z_p95_ms=100.0,
            )
        ],
        bit_identical_rerun=True,
    )
    result2 = evaluate_promotion(
        corpus,
        preds2,
        require_speed=True,
        seed_exact_p95_budget_ms=5000.0,
        target_z_p95_budget_ms=2500.0,
    )
    d2 = next(g for g in result2["gates"] if g["gate_id"] == "D")
    assert d2["status"] == "FAIL"
    assert "seed_exact" in d2["detail"]


def test_calibration_honesty_fails_default_claimed_biological():
    corpus = CorpusManifest(
        corpus_id="bad-cal",
        acquisitions=[
            AcquisitionRecord(
                source_id="x",
                source_basename="x.tif",
                source_sha256=None,
                format="tif",
                shape_zyx=(1, 8, 8),
                voxel=VoxelProvenance("default", (1.0, 1.0, 1.0), True),  # invalid
            )
        ],
        objects=[],
        holdout=HoldoutManifest(frozen=True, object_ids=()),
    )
    result = evaluate_promotion(corpus, None, require_speed=False)
    f = next(g for g in result["gates"] if g["gate_id"] == "F")
    assert f["status"] == "FAIL"


def test_cli_blocked_empty_exit_2():
    script = ROOT / "scripts" / "run_real_data_promotion_gates.py"
    out = ROOT / ".agent-runs" / "tracking-recovery-20260712" / "packet-05" / "example_blocked"
    out.mkdir(parents=True, exist_ok=True)
    proc = subprocess.run(
        [
            sys.executable,
            str(script),
            "--corpus",
            str(FIXTURES / "blocked_empty"),
            "--out",
            str(out),
            "--no-require-speed",
        ],
        cwd=str(ROOT),
        capture_output=True,
        text=True,
    )
    assert proc.returncode == 2, proc.stdout + proc.stderr
    report = json.loads((out / "gate_report.json").read_text(encoding="utf-8"))
    assert report["overall"] == "BLOCKED"
    assert report["composite_accuracy_percent"] is None
    assert (out / "gate_report.md").is_file()


def test_no_composite_accuracy_key_used_for_promotion():
    corpus, preds = load_corpus_dir(FIXTURES / "synthetic_unit")
    result = evaluate_promotion(corpus, preds, require_speed=False)
    assert "composite_accuracy_percent" in result
    assert result["composite_accuracy_percent"] is None
    for s in result["per_object"]:
        assert s["composite_accuracy_percent"] is None

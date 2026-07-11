from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import numpy as np
import pytest

from morphostack.core.synthetic_touching import (
    all_mandatory_cases,
    assert_case_geometry_consistent,
    case_blank_gap_then_neighbour,
    case_broad_flat_contact,
    case_isolated_shrinking,
    case_lateral_target_drift,
    case_overlapping_neck,
    case_tangent_neighbour,
    case_weak_broken_membrane,
    contour_to_mask,
    neighbor_contamination,
    score_case_from_predictions,
    score_frame,
)


PROJECT_ROOT = Path(__file__).resolve().parents[1]


@pytest.mark.parametrize(
    "factory",
    [
        case_isolated_shrinking,
        case_tangent_neighbour,
        case_overlapping_neck,
        case_broad_flat_contact,
        case_lateral_target_drift,
        case_blank_gap_then_neighbour,
        case_weak_broken_membrane,
    ],
)
def test_generator_geometry_internally_consistent(factory):
    case = factory()
    assert_case_geometry_consistent(case)
    # Hollow membrane: lumen at target center darker than membrane peak (when present).
    z = case.seed_frame
    if case.frames[z].policy == "require_target":
        cy, cx = int(round(case.seed_y)), int(round(case.seed_x))
        # Sample lumen vs a ring pixel if stack is non-empty.
        assert case.stack[z].max() >= 100
        if 0 <= cy < case.stack.shape[1] and 0 <= cx < case.stack.shape[2]:
            assert int(case.stack[z, cy, cx]) < int(case.stack[z].max())


def test_deliberately_injected_neighbour_bleed_fails():
    """A contour that covers the neighbour must fail scoring."""
    case = case_overlapping_neck()
    z = case.seed_frame
    # Fake prediction = neighbour solid mask (identity theft).
    pred = case.neighbor_masks[z]
    # Build a dummy contour ring around neighbour center for raster path.
    n_cx = case.frames[z].neighbor_cx
    n_cy = case.frames[z].neighbor_cy
    assert n_cx is not None and n_cy is not None
    theta = np.linspace(0, 2 * np.pi, 48, endpoint=False)
    r = float(case.frames[z].neighbor_r or 10.0)
    contour = np.column_stack([n_cx + r * np.cos(theta), n_cy + r * np.sin(theta)])

    nz = case.stack.shape[0]
    contours = [None] * nz
    tracked = [False] * nz
    merge_rejected = [False] * nz
    # Perfect target on non-eq frames to isolate the bleed failure at equator.
    for zi in range(nz):
        if zi == z:
            contours[zi] = contour
            tracked[zi] = True
        elif case.frames[zi].policy == "require_target":
            # Use true target boundary approximate circle.
            t = case.frames[zi]
            th = np.linspace(0, 2 * np.pi, 48, endpoint=False)
            contours[zi] = np.column_stack(
                [t.target_cx + t.target_r * np.cos(th), t.target_cy + t.target_r * np.sin(th)]
            )
            tracked[zi] = True
        else:
            # allow_reject / blank: leave empty (safe)
            pass

    # Contaminated equator alone should fail the case.
    score = score_case_from_predictions(
        case, contours=contours, tracked=tracked, merge_rejected=merge_rejected
    )
    assert score.frames[z].frame_pass is False
    assert score.frames[z].neighbor_contamination > 0.12
    assert score.passed is False

    # Direct metric check
    cont = neighbor_contamination(contour_to_mask(contour, case.stack.shape[1:]), case.neighbor_masks[z])
    assert cont > 0.5


def test_safe_merge_rejection_counted_correctly():
    """allow_reject / ambiguous frames pass when untracked (safe reject)."""
    case = case_broad_flat_contact()
    nz = case.stack.shape[0]
    contours = [None] * nz
    tracked = [False] * nz
    merge_rejected = [False] * nz
    for z, exp in enumerate(case.frames):
        if exp.policy == "require_target":
            th = np.linspace(0, 2 * np.pi, 40, endpoint=False)
            contours[z] = np.column_stack(
                [
                    exp.target_cx + exp.target_r * 0.9 * np.cos(th),
                    exp.target_cy + exp.target_r * 0.9 * np.sin(th),
                ]
            )
            tracked[z] = True
        elif exp.policy == "allow_reject":
            # Safe reject on ambiguous equator band.
            tracked[z] = False
            merge_rejected[z] = True
        else:
            tracked[z] = False

    score = score_case_from_predictions(
        case, contours=contours, tracked=tracked, merge_rejected=merge_rejected
    )
    amb = [fs for fs in score.frames if case.frames[fs.frame_index].ambiguous_contact]
    assert amb, "expected ambiguous frames in broad contact case"
    assert all(fs.frame_pass for fs in amb)
    assert all(fs.merge_rejected or not fs.tracked for fs in amb)


def test_blank_gap_neighbour_reentry_cannot_pass_as_target():
    """After blanks, accepting the neighbour near the old seed must fail."""
    case = case_blank_gap_then_neighbour()
    nz = case.stack.shape[0]
    contours = [None] * nz
    tracked = [False] * nz
    merge_rejected = [False] * nz

    for z, exp in enumerate(case.frames):
        if exp.policy == "require_target":
            th = np.linspace(0, 2 * np.pi, 40, endpoint=False)
            contours[z] = np.column_stack(
                [
                    exp.target_cx + exp.target_r * 0.9 * np.cos(th),
                    exp.target_cy + exp.target_r * 0.9 * np.sin(th),
                ]
            )
            tracked[z] = True
        elif exp.policy == "expect_blank" and exp.neighbor_cx is not None:
            # Steal identity: contour on neighbour after gap.
            th = np.linspace(0, 2 * np.pi, 40, endpoint=False)
            r = float(exp.neighbor_r or 10.0)
            contours[z] = np.column_stack(
                [
                    exp.neighbor_cx + r * 0.9 * np.cos(th),
                    exp.neighbor_cy + r * 0.9 * np.sin(th),
                ]
            )
            tracked[z] = True

    score = score_case_from_predictions(
        case, contours=contours, tracked=tracked, merge_rejected=merge_rejected
    )
    assert score.identity_after_gap_ok is False
    assert score.passed is False
    post = [fs for fs in score.frames if case.frames[fs.frame_index].neighbor_cx is not None]
    assert any(fs.detail in ("identity_theft", "wrong_identity") for fs in post)


def test_score_frame_safe_reject_vs_wrong_accept():
    case = case_overlapping_neck()
    z = case.seed_frame
    exp = case.frames[z]
    empty = np.zeros(case.stack.shape[1:], dtype=bool)
    # Safe reject
    fs_ok = score_frame(
        frame_index=z,
        expect=exp,
        pred_mask=empty,
        tracked=False,
        merge_rejected=True,
        target_mask=case.target_masks[z],
        neighbor_mask=case.neighbor_masks[z],
    )
    assert exp.policy in ("allow_reject", "require_target")
    # On allow_reject equator, safe reject passes.
    if exp.policy == "allow_reject":
        assert fs_ok.frame_pass is True

    # Wrong accept = neighbour mask
    fs_bad = score_frame(
        frame_index=z,
        expect=exp,
        pred_mask=case.neighbor_masks[z],
        tracked=True,
        merge_rejected=False,
        target_mask=case.target_masks[z],
        neighbor_mask=case.neighbor_masks[z],
    )
    assert fs_bad.frame_pass is False
    assert fs_bad.neighbor_contamination > 0.12


def test_script_aggregate_exit_status(tmp_path: Path):
    """Script exit code follows mandatory aggregate pass/fail."""
    out_dir = tmp_path / "synthetic-touching-membranes"
    result = subprocess.run(
        [
            sys.executable,
            str(PROJECT_ROOT / "scripts" / "validate_synthetic_touching.py"),
            "--out-dir",
            str(out_dir),
        ],
        cwd=PROJECT_ROOT,
        check=False,
        capture_output=True,
        text=True,
    )
    summary = json.loads((out_dir / "summary.json").read_text(encoding="utf-8"))
    assert summary["mandatory_case_count"] == len(all_mandatory_cases())
    assert summary["residual_seeded_merge_is_failure"] is True
    assert summary["unseeded_merge_not_required"] is True
    assert "synthetic_limits" in summary
    # Exit matches aggregate.
    if summary["all_passed"]:
        assert result.returncode == 0, result.stdout + result.stderr
    else:
        assert result.returncode != 0, "aggregate FAIL must be non-zero exit"
    # One JSON per case.
    for case in all_mandatory_cases():
        assert (out_dir / f"{case.case_id}.json").exists()
    assert (out_dir / "README.md").exists()

"""Phase 5 evidence-bundle validator (fail-closed)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from morphostack.core.rbc_evidence import validate_rbc_evidence_bundle


def _axis(v: float = 0.1) -> dict:
    return {"value_um": v, "source": "override", "verified": True}


def _full_stack(stack_id: str, split: str) -> dict:
    return {
        "stack_id": stack_id,
        "source_path": f"{stack_id}.ome.tif",
        "source_sha256": "a" * 64,
        "calibration": {"x": _axis(), "y": _axis(), "z": _axis(0.2)},
        "acquisition": {
            "objective": "63x",
            "numerical_aperture": 1.4,
            "immersion": "oil",
            "excitation_nm": 488,
            "emission_nm": 520,
            "pinhole": "1 AU",
            "z_step_um": 0.2,
        },
        "split": split,
    }


def _annotation(role: str, stack_id: str = "s1") -> dict:
    return {
        "role": role,
        "source_stack_id": stack_id,
        "source_sha256": "a" * 64,
        "frame_index": 0,
    }


def test_bundle_rejects_missing_axis_calibration(tmp_path: Path):
    stacks = [_full_stack(f"s{i}", "evaluate" if i else "tune") for i in range(3)]
    stacks[0]["calibration"]["z"] = {"value_um": None, "source": "default", "verified": False}
    manifest = {
        "stacks": stacks,
        "annotations": [_annotation(r) for r in ("center", "rim", "cap")] * 4,
        "preparation_note": "discocytes in PBS",
        "psf_or_bead_evidence": {"present": False, "lab_decision": "surface withheld"},
        "estimator_addendum": {"path": "researches/example.md"},
        "lab_acceptance_thresholds": {"dice_min": 0.9},
    }
    result = validate_rbc_evidence_bundle(manifest)
    assert not result.accepted
    assert "missing_verified_z_calibration" in result.reasons


def test_bundle_requires_center_rim_and_cap_annotations():
    stacks = [_full_stack(f"s{i}", "evaluate" if i else "tune") for i in range(3)]
    manifest = {
        "stacks": stacks,
        "annotations": [_annotation("center")] * 12,
        "preparation_note": "discocytes",
        "psf_or_bead_evidence": {"present": True, "path": "beads.json"},
        "estimator_addendum": {"path": "researches/example.md"},
        "lab_acceptance_thresholds": {"dice_min": 0.9},
    }
    result = validate_rbc_evidence_bundle(manifest)
    assert not result.accepted
    assert "annotation_coverage_incomplete" in result.reasons


def test_bundle_rejects_tune_evaluate_overlap():
    stacks = [
        _full_stack("cellA", "tune"),
        _full_stack("cellA", "evaluate"),
        _full_stack("cellB", "evaluate"),
    ]
    anns = []
    for role in ("center", "rim", "cap"):
        for _ in range(4):
            anns.append(_annotation(role, "cellA"))
    manifest = {
        "stacks": stacks,
        "annotations": anns,
        "preparation_note": "note",
        "psf_or_bead_evidence": {"lab_decision": "withhold surface"},
        "estimator_addendum": {"path": "x.md"},
        "lab_acceptance_thresholds": {"dice_min": 0.9},
    }
    result = validate_rbc_evidence_bundle(manifest)
    assert not result.accepted
    assert "tune_evaluate_cell_overlap" in result.reasons


def test_placeholder_manifest_is_refused():
    root = Path(__file__).resolve().parents[1]
    path = root / "validation" / "references" / "rbc-annotations-v1" / "manifest.json"
    result = validate_rbc_evidence_bundle(path)
    assert not result.accepted
    assert "insufficient_stacks" in result.reasons


def test_complete_schema_accepts_structure_only():
    stacks = [
        _full_stack("t1", "tune"),
        _full_stack("e1", "evaluate"),
        _full_stack("e2", "evaluate"),
    ]
    anns = []
    for role in ("center", "rim", "cap"):
        for i in range(4):
            anns.append(_annotation(role, "e1" if i % 2 else "e2"))
    # ensure 12 annotations (>=10)
    manifest = {
        "stacks": stacks,
        "annotations": anns,
        "preparation_note": "fresh discocytes",
        "psf_or_bead_evidence": {"present": False, "lab_decision": "surface unavailable"},
        "estimator_addendum": {"path": "researches/rbc-estimated-model-addendum.md"},
        "lab_acceptance_thresholds": {"dice_min": 0.85, "hd95_um_max": 0.5},
    }
    result = validate_rbc_evidence_bundle(manifest)
    assert result.accepted
    assert result.stack_count == 3
    assert result.annotation_count >= 10

"""Fail-closed RBC lab evidence-bundle validation (Phase 5).

Does not load or invent biological stacks. Pure schema/completeness checks so
missing lab inputs cannot silently promote capabilities.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


REQUIRED_ANNOTATION_ROLES = frozenset({"center", "rim", "cap"})
REQUIRED_ACQUISITION_FIELDS = (
    "objective",
    "numerical_aperture",
    "immersion",
    "excitation_nm",
    "emission_nm",
    "pinhole",
    "z_step_um",
)
REQUIRED_STACK_FIELDS = (
    "stack_id",
    "source_path",
    "source_sha256",
    "calibration",
    "acquisition",
    "split",
)


@dataclass(frozen=True)
class RbcEvidenceBundleResult:
    accepted: bool
    reasons: tuple[str, ...]
    stack_count: int = 0
    annotation_count: int = 0
    notes: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, object]:
        return {
            "accepted": self.accepted,
            "reasons": list(self.reasons),
            "stack_count": self.stack_count,
            "annotation_count": self.annotation_count,
            "notes": list(self.notes),
        }


def _axis_verified(axis: object) -> bool:
    if not isinstance(axis, dict):
        return False
    value = axis.get("value_um")
    verified = axis.get("verified")
    return verified is True and value is not None and float(value) > 0.0


def validate_rbc_evidence_bundle(manifest: dict[str, Any] | Path | str) -> RbcEvidenceBundleResult:
    """Validate an evidence manifest dict or JSON path.

    Never invents missing calibration, acquisition, or annotation coverage.
    """

    notes: list[str] = []
    if isinstance(manifest, (str, Path)):
        path = Path(manifest)
        if not path.is_file():
            return RbcEvidenceBundleResult(
                accepted=False,
                reasons=("manifest_missing",),
                notes=(f"path not found: {path}",),
            )
        try:
            manifest = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            return RbcEvidenceBundleResult(
                accepted=False,
                reasons=("manifest_unreadable",),
                notes=(str(exc),),
            )

    if not isinstance(manifest, dict):
        return RbcEvidenceBundleResult(accepted=False, reasons=("manifest_not_object",))

    reasons: list[str] = []
    stacks = manifest.get("stacks")
    if not isinstance(stacks, list) or len(stacks) < 3:
        reasons.append("insufficient_stacks")

    annotations = manifest.get("annotations")
    if not isinstance(annotations, list):
        annotations = []
        reasons.append("annotations_missing")

    prep = manifest.get("preparation_note")
    if not isinstance(prep, str) or not prep.strip():
        reasons.append("preparation_note_missing")

    psf = manifest.get("psf_or_bead_evidence")
    if psf is None or (isinstance(psf, dict) and not psf.get("present") and not psf.get("lab_decision")):
        reasons.append("psf_or_bead_evidence_missing")

    estimator = manifest.get("estimator_addendum")
    if not isinstance(estimator, dict) or not estimator.get("path"):
        reasons.append("estimator_addendum_missing")

    lab_thresholds = manifest.get("lab_acceptance_thresholds")
    if not isinstance(lab_thresholds, dict) or not lab_thresholds:
        reasons.append("lab_acceptance_thresholds_missing")

    tune_ids: set[str] = set()
    eval_ids: set[str] = set()
    stack_count = 0
    if isinstance(stacks, list):
        for item in stacks:
            if not isinstance(item, dict):
                reasons.append("stack_entry_invalid")
                continue
            stack_count += 1
            for key in REQUIRED_STACK_FIELDS:
                if key not in item:
                    reasons.append(f"stack_missing_{key}")
            cal = item.get("calibration")
            if not isinstance(cal, dict):
                reasons.append("missing_verified_z_calibration")
            else:
                for axis_name in ("x", "y", "z"):
                    if not _axis_verified(cal.get(axis_name)):
                        reasons.append(f"missing_verified_{axis_name}_calibration")
            acq = item.get("acquisition")
            if not isinstance(acq, dict):
                reasons.append("acquisition_record_missing")
            else:
                for field_name in REQUIRED_ACQUISITION_FIELDS:
                    if acq.get(field_name) in (None, ""):
                        reasons.append(f"acquisition_missing_{field_name}")
            split = str(item.get("split") or "").lower()
            sid = str(item.get("stack_id") or "")
            if split == "tune":
                tune_ids.add(sid)
            elif split == "evaluate":
                eval_ids.add(sid)
            elif split:
                notes.append(f"unrecognized split for {sid}: {split}")
            else:
                reasons.append("stack_split_missing")

    overlap = tune_ids & eval_ids
    if overlap:
        reasons.append("tune_evaluate_cell_overlap")
        notes.append(f"overlap ids: {sorted(overlap)}")

    roles: set[str] = set()
    annotation_count = 0
    for ann in annotations:
        if not isinstance(ann, dict):
            continue
        annotation_count += 1
        role = str(ann.get("role") or "").lower()
        if role:
            roles.add(role)
        if not ann.get("source_stack_id"):
            reasons.append("annotation_missing_source_stack")
        if not ann.get("source_sha256"):
            reasons.append("annotation_missing_source_hash")
    if not REQUIRED_ANNOTATION_ROLES.issubset(roles):
        reasons.append("annotation_coverage_incomplete")
        missing = sorted(REQUIRED_ANNOTATION_ROLES - roles)
        notes.append(f"missing annotation roles: {missing}")
    if annotation_count < 10:
        reasons.append("annotation_count_below_minimum")

    # Deduplicate reasons preserving order
    ordered = tuple(dict.fromkeys(reasons))
    accepted = len(ordered) == 0
    if accepted:
        notes.append("schema complete; lab still must approve thresholds before promotion")
    return RbcEvidenceBundleResult(
        accepted=accepted,
        reasons=ordered,
        stack_count=stack_count,
        annotation_count=annotation_count,
        notes=tuple(notes),
    )


def load_rbc_evidence_manifest(path: Path | str) -> dict[str, Any]:
    """Load JSON manifest or raise FileNotFoundError / ValueError."""

    p = Path(path)
    data = json.loads(p.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError("evidence manifest must be a JSON object")
    return data

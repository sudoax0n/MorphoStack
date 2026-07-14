"""Corpus / holdout / object / prediction schemas for promotion evaluation."""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Literal

Partition = Literal["train", "tune", "holdout"]
StratumId = Literal[
    "S1",
    "S2",
    "S3",
    "S4",
    "S5",
    "S6",
    "S7",
    "S8",
    "S9",
]

CONTACT_STRATA = frozenset({"S2", "S3"})
TARGET_STRATA = frozenset({"S1", "S2", "S3", "S4", "S5", "S6", "S7", "S8"})


@dataclass(frozen=True)
class VoxelProvenance:
    voxel_source: Literal["metadata", "override", "default"]
    spacing_um: tuple[float, float, float]  # z, y, x
    calibrated_biological_units: bool

    def to_dict(self) -> dict[str, Any]:
        return {
            "voxel_source": self.voxel_source,
            "spacing_um": {
                "z": self.spacing_um[0],
                "y": self.spacing_um[1],
                "x": self.spacing_um[2],
            },
            "calibrated_biological_units": bool(self.calibrated_biological_units),
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> VoxelProvenance:
        sp = data.get("spacing_um") or {}
        if isinstance(sp, dict):
            spacing = (float(sp["z"]), float(sp["y"]), float(sp["x"]))
        else:
            spacing = (float(sp[0]), float(sp[1]), float(sp[2]))
        return cls(
            voxel_source=str(data.get("voxel_source", "default")),  # type: ignore[arg-type]
            spacing_um=spacing,
            calibrated_biological_units=bool(
                data.get("calibrated_biological_units", False)
            ),
        )


@dataclass(frozen=True)
class AcquisitionRecord:
    source_id: str
    source_basename: str
    source_sha256: str | None
    format: str
    shape_zyx: tuple[int, int, int] | None
    voxel: VoxelProvenance
    acquisition_notes: str = ""
    lab_path_ref: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "source_id": self.source_id,
            "source_basename": self.source_basename,
            "source_sha256": self.source_sha256,
            "format": self.format,
            "shape_zyx": list(self.shape_zyx) if self.shape_zyx else None,
            "voxel": self.voxel.to_dict(),
            "acquisition_notes": self.acquisition_notes,
            "lab_path_ref": self.lab_path_ref,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> AcquisitionRecord:
        shape = data.get("shape_zyx")
        shape_t = tuple(int(v) for v in shape) if shape else None
        return cls(
            source_id=str(data["source_id"]),
            source_basename=str(data.get("source_basename", "")),
            source_sha256=data.get("source_sha256"),
            format=str(data.get("format", "unknown")),
            shape_zyx=shape_t,  # type: ignore[arg-type]
            voxel=VoxelProvenance.from_dict(data.get("voxel") or {}),
            acquisition_notes=str(data.get("acquisition_notes", "")),
            lab_path_ref=data.get("lab_path_ref"),
        )


@dataclass(frozen=True)
class SeedSpec:
    type: Literal["circle", "polygon"]
    x: float
    y: float
    seed_frame: int
    radius_px: float | None = None
    points: tuple[tuple[float, float], ...] | None = None

    def to_dict(self) -> dict[str, Any]:
        d: dict[str, Any] = {
            "type": self.type,
            "x": self.x,
            "y": self.y,
            "seed_frame": self.seed_frame,
            "radius_px": self.radius_px,
        }
        if self.points is not None:
            d["points"] = [list(p) for p in self.points]
        return d

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> SeedSpec:
        pts = data.get("points")
        points = None
        if pts is not None:
            points = tuple((float(a), float(b)) for a, b in pts)
        return cls(
            type=str(data.get("type", "circle")),  # type: ignore[arg-type]
            x=float(data["x"]),
            y=float(data["y"]),
            seed_frame=int(data["seed_frame"]),
            radius_px=float(data["radius_px"]) if data.get("radius_px") is not None else None,
            points=points,
        )


@dataclass(frozen=True)
class LabelledFrame:
    """One reference annotation on a plane."""

    frame_index: int
    # Optional path relative to corpus root; harness may load masks from disk.
    mask_relpath: str | None = None
    # Inline binary mask only for synthetic unit fixtures (not real labels).
    mask_array: Any | None = field(default=None, repr=False, compare=False)
    exclude_from_contour_metrics: bool = False
    boundary_uncertain: bool = False
    contact_class: str = "none"  # none|tangent|broad|overlap_projection|unresolved
    expected_algorithm_behavior: str = "accept_or_reject_ok"
    neighbor_contamination: str = "none"  # none|mild|severe
    # Adjudicated events on this frame (reference-side)
    is_identity_switch_if_accepted: bool = False
    is_lobe_bridge_if_accepted: bool = False
    is_cap_hallucination_if_accepted: bool = False
    is_visible: bool = True

    def to_dict(self) -> dict[str, Any]:
        return {
            "frame_index": self.frame_index,
            "mask_relpath": self.mask_relpath,
            "exclude_from_contour_metrics": self.exclude_from_contour_metrics,
            "boundary_uncertain": self.boundary_uncertain,
            "contact_class": self.contact_class,
            "expected_algorithm_behavior": self.expected_algorithm_behavior,
            "neighbor_contamination": self.neighbor_contamination,
            "is_identity_switch_if_accepted": self.is_identity_switch_if_accepted,
            "is_lobe_bridge_if_accepted": self.is_lobe_bridge_if_accepted,
            "is_cap_hallucination_if_accepted": self.is_cap_hallucination_if_accepted,
            "is_visible": self.is_visible,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any], *, mask_array: Any | None = None) -> LabelledFrame:
        return cls(
            frame_index=int(data["frame_index"]),
            mask_relpath=data.get("mask_relpath"),
            mask_array=mask_array,
            exclude_from_contour_metrics=bool(
                data.get("exclude_from_contour_metrics", False)
            ),
            boundary_uncertain=bool(data.get("boundary_uncertain", False)),
            contact_class=str(data.get("contact_class", "none")),
            expected_algorithm_behavior=str(
                data.get("expected_algorithm_behavior", "accept_or_reject_ok")
            ),
            neighbor_contamination=str(data.get("neighbor_contamination", "none")),
            is_identity_switch_if_accepted=bool(
                data.get("is_identity_switch_if_accepted", False)
            ),
            is_lobe_bridge_if_accepted=bool(data.get("is_lobe_bridge_if_accepted", False)),
            is_cap_hallucination_if_accepted=bool(
                data.get("is_cap_hallucination_if_accepted", False)
            ),
            is_visible=bool(data.get("is_visible", True)),
        )


@dataclass
class ObjectRecord:
    object_id: str
    source_id: str
    primary_stratum: str
    stratum_ids: tuple[str, ...]
    seed: SeedSpec
    partition: Partition
    labelled_frames: list[LabelledFrame] = field(default_factory=list)
    contact_group_id: str | None = None  # touching pairs share this; same partition
    profile: str = "vesicle"
    notes: str = ""
    is_negative_seed: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "object_id": self.object_id,
            "source_id": self.source_id,
            "primary_stratum": self.primary_stratum,
            "stratum_ids": list(self.stratum_ids),
            "seed": self.seed.to_dict(),
            "partition": self.partition,
            "labelled_frames": [f.to_dict() for f in self.labelled_frames],
            "contact_group_id": self.contact_group_id,
            "profile": self.profile,
            "notes": self.notes,
            "is_negative_seed": self.is_negative_seed,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> ObjectRecord:
        strata = data.get("stratum_ids") or [data.get("primary_stratum", "S1")]
        frames = [LabelledFrame.from_dict(f) for f in (data.get("labelled_frames") or [])]
        return cls(
            object_id=str(data["object_id"]),
            source_id=str(data["source_id"]),
            primary_stratum=str(data.get("primary_stratum", strata[0])),
            stratum_ids=tuple(str(s) for s in strata),
            seed=SeedSpec.from_dict(data["seed"]),
            partition=str(data.get("partition", "holdout")),  # type: ignore[arg-type]
            labelled_frames=frames,
            contact_group_id=data.get("contact_group_id"),
            profile=str(data.get("profile", "vesicle")),
            notes=str(data.get("notes", "")),
            is_negative_seed=bool(data.get("is_negative_seed", False))
            or str(data.get("primary_stratum")) == "S9",
        )


@dataclass
class HoldoutManifest:
    """Frozen holdout IDs — must exist before scoring a promotion candidate."""

    frozen: bool
    object_ids: tuple[str, ...]
    frozen_at: str | None = None
    notes: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "frozen": bool(self.frozen),
            "object_ids": list(self.object_ids),
            "frozen_at": self.frozen_at,
            "notes": self.notes,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> HoldoutManifest:
        return cls(
            frozen=bool(data.get("frozen", False)),
            object_ids=tuple(str(x) for x in (data.get("object_ids") or [])),
            frozen_at=data.get("frozen_at"),
            notes=str(data.get("notes", "")),
        )


@dataclass
class CorpusManifest:
    corpus_id: str
    acquisitions: list[AcquisitionRecord]
    objects: list[ObjectRecord]
    holdout: HoldoutManifest
    # Declared before scoring (contact Hausdorff threshold policy).
    hausdorff95_limit_px: float = 4.0
    # Physical boundary limit for calibrated contact (µm). Required for honest Gate B.
    hausdorff95_limit_um: float | None = None
    membrane_thickness_px: float | None = None
    incomplete_signoff_statement: str = (
        "Touching-vesicle real-data sign-off incomplete. "
        "Synthetic and isolated-stack results do not establish accuracy on "
        "crowded or contacting vesicles."
    )

    def to_dict(self) -> dict[str, Any]:
        return {
            "corpus_id": self.corpus_id,
            "acquisitions": [a.to_dict() for a in self.acquisitions],
            "objects": [o.to_dict() for o in self.objects],
            "holdout": self.holdout.to_dict(),
            "hausdorff95_limit_px": self.hausdorff95_limit_px,
            "hausdorff95_limit_um": self.hausdorff95_limit_um,
            "membrane_thickness_px": self.membrane_thickness_px,
            "incomplete_signoff_statement": self.incomplete_signoff_statement,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> CorpusManifest:
        return cls(
            corpus_id=str(data.get("corpus_id", "unnamed")),
            acquisitions=[
                AcquisitionRecord.from_dict(a) for a in (data.get("acquisitions") or [])
            ],
            objects=[ObjectRecord.from_dict(o) for o in (data.get("objects") or [])],
            holdout=HoldoutManifest.from_dict(data.get("holdout") or {}),
            hausdorff95_limit_px=float(data.get("hausdorff95_limit_px", 4.0)),
            hausdorff95_limit_um=(
                float(data["hausdorff95_limit_um"])
                if data.get("hausdorff95_limit_um") is not None
                else None
            ),
            membrane_thickness_px=(
                float(data["membrane_thickness_px"])
                if data.get("membrane_thickness_px") is not None
                else None
            ),
            incomplete_signoff_statement=str(
                data.get(
                    "incomplete_signoff_statement",
                    CorpusManifest.__dataclass_fields__[
                        "incomplete_signoff_statement"
                    ].default,
                )
            ),
        )


@dataclass
class PredictedFrame:
    frame_index: int
    accepted: bool  # measure-authoritative accept (exact_accepted / manual)
    method: str = ""
    merge_suspect: bool = False
    center_xy: tuple[float, float] | None = None
    area_px: float | None = None
    mask_array: Any | None = field(default=None, repr=False, compare=False)
    identity_switch: bool = False  # adjudicated or auto flag
    false_merge: bool = False
    cap_hallucination: bool = False
    neighbor_steal: bool = False
    attempts: int = 1


@dataclass
class CorrectionRecord:
    correction_id: str
    object_id: str
    frame_index: int
    action: str
    time_s: float | None = None
    operator: str | None = None


@dataclass
class LatencyRecord:
    object_id: str
    provisional_p95_ms: float | None = None
    seed_exact_p95_ms: float | None = None
    target_z_p95_ms: float | None = None
    full_track_wall_s: float | None = None
    cold: bool | None = None
    machine_id: str | None = None
    attempts_mean: float | None = None


@dataclass
class PredictionBundle:
    """Algorithm outputs for one object (or multi-object map by id)."""

    by_object: dict[str, list[PredictedFrame]]
    corrections: list[CorrectionRecord] = field(default_factory=list)
    latencies: list[LatencyRecord] = field(default_factory=list)
    algorithm_version: str = "unknown"
    bit_identical_rerun: bool | None = None

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> PredictionBundle:
        by_obj: dict[str, list[PredictedFrame]] = {}
        for oid, frames in (data.get("by_object") or {}).items():
            out: list[PredictedFrame] = []
            for f in frames:
                c = f.get("center_xy")
                out.append(
                    PredictedFrame(
                        frame_index=int(f["frame_index"]),
                        accepted=bool(f.get("accepted", False)),
                        method=str(f.get("method", "")),
                        merge_suspect=bool(f.get("merge_suspect", False)),
                        center_xy=(float(c[0]), float(c[1])) if c else None,
                        area_px=float(f["area_px"]) if f.get("area_px") is not None else None,
                        identity_switch=bool(f.get("identity_switch", False)),
                        false_merge=bool(f.get("false_merge", False)),
                        cap_hallucination=bool(f.get("cap_hallucination", False)),
                        neighbor_steal=bool(f.get("neighbor_steal", False)),
                        attempts=int(f.get("attempts", 1)),
                    )
                )
            by_obj[str(oid)] = out
        corrs = [
            CorrectionRecord(
                correction_id=str(c["correction_id"]),
                object_id=str(c["object_id"]),
                frame_index=int(c["frame_index"]),
                action=str(c["action"]),
                time_s=float(c["time_s"]) if c.get("time_s") is not None else None,
                operator=c.get("operator"),
            )
            for c in (data.get("corrections") or [])
        ]
        lats = [
            LatencyRecord(
                object_id=str(L["object_id"]),
                provisional_p95_ms=_opt_float(L.get("provisional_p95_ms")),
                seed_exact_p95_ms=_opt_float(L.get("seed_exact_p95_ms")),
                target_z_p95_ms=_opt_float(L.get("target_z_p95_ms")),
                full_track_wall_s=_opt_float(L.get("full_track_wall_s")),
                cold=L.get("cold"),
                machine_id=L.get("machine_id"),
                attempts_mean=_opt_float(L.get("attempts_mean")),
            )
            for L in (data.get("latencies") or [])
        ]
        return cls(
            by_object=by_obj,
            corrections=corrs,
            latencies=lats,
            algorithm_version=str(data.get("algorithm_version", "unknown")),
            bit_identical_rerun=data.get("bit_identical_rerun"),
        )


def _opt_float(v: Any) -> float | None:
    if v is None:
        return None
    return float(v)


def load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def load_corpus_dir(root: Path) -> tuple[CorpusManifest, PredictionBundle | None]:
    """Load corpus_manifest.json (+ optional holdout override + predictions)."""
    root = Path(root)
    corpus_path = root / "corpus_manifest.json"
    if not corpus_path.is_file():
        raise FileNotFoundError(f"missing {corpus_path}")
    data = load_json(corpus_path)
    # Optional split files
    holdout_path = root / "holdout_manifest.json"
    if holdout_path.is_file():
        data["holdout"] = load_json(holdout_path)
    objects_path = root / "objects.json"
    if objects_path.is_file() and "objects" not in data:
        data["objects"] = load_json(objects_path)
    acq_path = root / "acquisitions.json"
    if acq_path.is_file() and "acquisitions" not in data:
        data["acquisitions"] = load_json(acq_path)
    corpus = CorpusManifest.from_dict(data)
    pred: PredictionBundle | None = None
    pred_path = root / "predictions.json"
    if pred_path.is_file():
        pred = PredictionBundle.from_dict(load_json(pred_path))
    return corpus, pred


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=False) + "\n", encoding="utf-8")

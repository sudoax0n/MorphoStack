"""RBC slice segmentation and Z association without hole filling."""

from __future__ import annotations

from typing import Any

import numpy as np

from morphostack.core.pipeline import ObjectSeed
from morphostack.core.rbc_models import RbcStackCandidate, RbcSliceTopology, RbcTopologyIssue
from morphostack.core.rbc_topology import extract_rbc_slice_topology
from morphostack.core.seeded_vesicle import (
    SeededSliceResult,
    effective_seed_radius,
    segment_slice_seeded,
    track_seeded_vesicle_stack,
)


def segment_rbc_slice_seeded(
    frame: np.ndarray,
    *,
    seed_x: float,
    seed_y: float,
    seed_radius: float | None = None,
    frame_index: int = 0,
    refine: bool = True,
    ref_area: float | None = None,
    multiscale_consensus: bool = False,
    competitive_isolation: bool | None = False,
) -> RbcSliceTopology:
    """Segment one RBC slice preserving inner holes (no ``_fill_holes``)."""

    res = segment_slice_seeded(
        frame,
        seed_x=seed_x,
        seed_y=seed_y,
        seed_radius=seed_radius,
        refine=refine,
        ref_area=ref_area,
        multiscale_consensus=multiscale_consensus,
        competitive_isolation=competitive_isolation,
        profile="rbc",
        fill_holes=False,
    )
    if not res.ok or res.solid_mask is None:
        return RbcSliceTopology(
            frame_index=int(frame_index),
            outer_loop_xy=None,
            inner_loops_xy=(),
            occupancy_mask=None,
            issues=(RbcTopologyIssue.EMPTY, RbcTopologyIssue.SEED_SLICE_FAILED),
            ok=False,
            method=str(res.method or "circle_seed_fail"),
            center_xy=res.center_xy,
            merge_suspect=bool(res.merge_suspect),
        )
    return extract_rbc_slice_topology(
        res.solid_mask,
        frame_index=int(frame_index),
        method=str(res.method or "rbc"),
        center_xy=res.center_xy,
        merge_suspect=bool(res.merge_suspect),
    )


def _internal_gaps(valid: list[int]) -> tuple[int, ...]:
    if len(valid) < 2:
        return ()
    lo, hi = valid[0], valid[-1]
    present = set(valid)
    return tuple(i for i in range(lo, hi + 1) if i not in present)


def track_rbc_stack(
    stack: np.ndarray,
    *,
    seed: ObjectSeed,
    max_centroid_jump_px: float | None = None,
    max_centroid_jump_um: float | None = None,
    voxel_x_um: float = 1.0,
    voxel_y_um: float = 1.0,
    competitive_isolation: bool | None = False,
    multiscale_consensus: bool = False,
) -> RbcStackCandidate:
    """Bidirectional Z association of topology-preserving RBC slices."""

    arr = np.asarray(stack)
    if arr.ndim != 3:
        raise ValueError("track_rbc_stack expects (z, y, x)")
    n = int(arr.shape[0])
    seed_frame = int(seed.frame_index)
    if seed_frame < 0 or seed_frame >= n:
        raise ValueError("seed frame out of range")

    R = effective_seed_radius(float(seed.radius) if seed.radius else None)
    seeded: list[SeededSliceResult] = track_seeded_vesicle_stack(
        arr,
        seed_x=float(seed.x),
        seed_y=float(seed.y),
        seed_frame=seed_frame,
        seed_radius=R,
        max_centroid_jump_px=max_centroid_jump_px,
        max_centroid_jump_um=max_centroid_jump_um,
        voxel_x_um=voxel_x_um,
        voxel_y_um=voxel_y_um,
        competitive_isolation=competitive_isolation,
        multiscale_consensus=multiscale_consensus,
        profile="rbc",
        fill_holes=False,
    )

    slices: list[RbcSliceTopology] = []
    valid: list[int] = []
    issues: list[RbcTopologyIssue] = []
    occupancy = np.zeros(arr.shape, dtype=bool)

    for z, sres in enumerate(seeded):
        if sres is None or not sres.ok or sres.solid_mask is None:
            slices.append(
                RbcSliceTopology(
                    frame_index=z,
                    outer_loop_xy=None,
                    inner_loops_xy=(),
                    occupancy_mask=None,
                    issues=(RbcTopologyIssue.EMPTY,),
                    ok=False,
                    method=str(getattr(sres, "method", None) or "seeded_lost"),
                    merge_suspect=bool(getattr(sres, "merge_suspect", False)),
                )
            )
            continue
        topo = extract_rbc_slice_topology(
            sres.solid_mask,
            frame_index=z,
            method=str(sres.method or "rbc"),
            center_xy=sres.center_xy,
            merge_suspect=bool(sres.merge_suspect),
        )
        if sres.merge_suspect:
            issues.append(RbcTopologyIssue.UNRESOLVED_MERGE)
            topo = RbcSliceTopology(
                frame_index=topo.frame_index,
                outer_loop_xy=topo.outer_loop_xy,
                inner_loops_xy=topo.inner_loops_xy,
                occupancy_mask=topo.occupancy_mask,
                issues=tuple(dict.fromkeys((*topo.issues, RbcTopologyIssue.UNRESOLVED_MERGE))),
                ok=False,
                method=topo.method,
                center_xy=topo.center_xy,
                area_px=topo.area_px,
                merge_suspect=True,
            )
        slices.append(topo)
        if topo.ok and topo.occupancy_mask is not None:
            occupancy[z] = topo.occupancy_mask
            valid.append(z)
            for iss in topo.issues:
                if iss not in issues:
                    issues.append(iss)

    if seed_frame >= len(seeded) or not seeded[seed_frame].ok:
        if RbcTopologyIssue.SEED_SLICE_FAILED not in issues:
            issues.append(RbcTopologyIssue.SEED_SLICE_FAILED)

    gaps = _internal_gaps(valid)
    if gaps:
        issues.append(RbcTopologyIssue.INTERNAL_GAP)

    if not valid:
        issues.append(RbcTopologyIssue.NO_VALID_SLICES)

    # Fail closed on unresolved merge anywhere in the track or empty result.
    withheld = (
        RbcTopologyIssue.UNRESOLVED_MERGE in issues
        or RbcTopologyIssue.NO_VALID_SLICES in issues
        or RbcTopologyIssue.SEED_SLICE_FAILED in issues
        or not valid
    )
    ok = bool(valid) and not withheld

    return RbcStackCandidate(
        seed_frame_index=seed_frame,
        slices=tuple(slices),
        occupancy_mask=occupancy if valid else None,
        valid_slice_indices=tuple(valid),
        internal_gap_indices=gaps,
        issues=tuple(dict.fromkeys(issues)),
        withheld=withheld,
        ok=ok,
        provenance={
            "n_frames": n,
            "seed_xy": (float(seed.x), float(seed.y)),
            "seed_radius": R,
        },
    )


def seeded_results_from_rbc_candidate(
    candidate: RbcStackCandidate,
    *,
    fallback_center: tuple[float, float],
) -> list[SeededSliceResult]:
    """Adapter so pipeline frame builders can reuse SeededSliceResult fields."""

    out: list[SeededSliceResult] = []
    for topo in candidate.slices:
        if not topo.ok or topo.outer_loop_xy is None or topo.occupancy_mask is None:
            out.append(
                SeededSliceResult(
                    None,
                    None,
                    fallback_center,
                    0.0,
                    0.0,
                    topo.method or "rbc_lost",
                    False,
                    merge_suspect=topo.merge_suspect,
                )
            )
            continue
        contour = np.asarray(topo.outer_loop_xy, dtype=np.float64)
        cx, cy = topo.center_xy if topo.center_xy is not None else fallback_center
        out.append(
            SeededSliceResult(
                contour,
                np.asarray(topo.occupancy_mask, dtype=bool),
                (float(cx), float(cy)),
                float(topo.area_px),
                0.0,
                topo.method or "rbc_topology",
                True,
                merge_suspect=topo.merge_suspect,
            )
        )
    return out

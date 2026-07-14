"""Independent promotion gates A–F + corpus completeness (BLOCKED when data missing)."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal

import numpy as np

from .metrics import (
    dice_binary,
    hausdorff95_boundary,
    jaccard_binary,
    summarize_frame_scores,
)
from .schema import (
    CONTACT_STRATA,
    TARGET_STRATA,
    CorpusManifest,
    ObjectRecord,
    PredictedFrame,
    PredictionBundle,
)

GateStatus = Literal["PASS", "FAIL", "BLOCKED", "NOT_APPLICABLE", "INCOMPLETE"]


@dataclass
class GateResult:
    gate_id: str
    name: str
    status: GateStatus
    detail: str
    evidence: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "gate_id": self.gate_id,
            "name": self.name,
            "status": self.status,
            "detail": self.detail,
            "evidence": self.evidence,
        }


@dataclass
class ObjectScore:
    object_id: str
    partition: str
    primary_stratum: str
    dice: dict[str, Any]
    jaccard: dict[str, Any]
    hausdorff95_px: dict[str, Any]
    hausdorff95_um: dict[str, Any]
    n_labelled_scored: int
    n_uncertain_excluded: int
    false_merge_accepts: int
    identity_switches: int
    cap_hallucinations: int
    neighbor_steals: int
    false_fail_closed: int
    visible_frames: int
    accepted_frames: int
    gap_like_frames: int
    calibrated: bool
    physical_metrics_suppressed: bool
    corrections: int
    correction_time_s: float | None

    def to_dict(self) -> dict[str, Any]:
        return {
            "object_id": self.object_id,
            "partition": self.partition,
            "primary_stratum": self.primary_stratum,
            "dice": self.dice,
            "jaccard": self.jaccard,
            "hausdorff95_px": self.hausdorff95_px,
            "hausdorff95_um": self.hausdorff95_um,
            "n_labelled_scored": self.n_labelled_scored,
            "n_uncertain_excluded": self.n_uncertain_excluded,
            "false_merge_accepts": self.false_merge_accepts,
            "identity_switches": self.identity_switches,
            "cap_hallucinations": self.cap_hallucinations,
            "neighbor_steals": self.neighbor_steals,
            "false_fail_closed": self.false_fail_closed,
            "visible_frames": self.visible_frames,
            "accepted_frames": self.accepted_frames,
            "gap_like_frames": self.gap_like_frames,
            "calibrated": self.calibrated,
            "physical_metrics_suppressed": self.physical_metrics_suppressed,
            "corrections": self.corrections,
            "correction_time_s": self.correction_time_s,
            # Explicitly never a single accuracy %.
            "composite_accuracy_percent": None,
        }


def _acq_calibrated(corpus: CorpusManifest, source_id: str) -> bool:
    for a in corpus.acquisitions:
        if a.source_id == source_id:
            return bool(a.voxel.calibrated_biological_units) and a.voxel.voxel_source != "default"
    return False


def _acq_spacing_yx_um(
    corpus: CorpusManifest, source_id: str
) -> tuple[float, float] | None:
    """Return (y_um, x_um) when acquisition claims calibrated biological units."""
    for a in corpus.acquisitions:
        if a.source_id == source_id:
            if not (
                bool(a.voxel.calibrated_biological_units)
                and a.voxel.voxel_source != "default"
            ):
                return None
            # spacing_um is (z, y, x)
            _z, y_um, x_um = a.voxel.spacing_um
            if y_um > 0 and x_um > 0:
                return (float(y_um), float(x_um))
            return None
    return None


def _pred_map(frames: list[PredictedFrame]) -> dict[int, PredictedFrame]:
    return {int(f.frame_index): f for f in frames}


def score_object(
    obj: ObjectRecord,
    preds: list[PredictedFrame] | None,
    *,
    corpus: CorpusManifest,
    corrections_for_obj: list[Any],
) -> ObjectScore:
    calibrated = _acq_calibrated(corpus, obj.source_id)
    physical_suppressed = not calibrated
    spacing_yx = _acq_spacing_yx_um(corpus, obj.source_id) if calibrated else None

    dice_scores: list[float] = []
    jac_scores: list[float] = []
    hd_px_scores: list[float] = []
    hd_um_scores: list[float] = []
    n_unc = 0
    false_merge = 0
    id_sw = 0
    cap_h = 0
    steal = 0
    false_fc = 0
    visible = 0
    accepted = 0
    gap_like = 0

    pmap = _pred_map(preds or [])

    for lab in obj.labelled_frames:
        if lab.is_visible:
            visible += 1
        pf = pmap.get(int(lab.frame_index))
        accepted_here = bool(pf and pf.accepted and not pf.merge_suspect)
        if accepted_here:
            accepted += 1
        if pf is not None and not pf.accepted:
            gap_like += 1

        # Safety events on accepted frames
        if accepted_here:
            if pf.false_merge or lab.is_lobe_bridge_if_accepted or lab.neighbor_contamination == "severe":
                false_merge += 1
            if pf.identity_switch or lab.is_identity_switch_if_accepted:
                id_sw += 1
            if pf.cap_hallucination or lab.is_cap_hallucination_if_accepted:
                cap_h += 1
            if pf.neighbor_steal:
                steal += 1

        # False fail-closed: clear isolated expected accept, algorithm not accepted
        if (
            lab.expected_algorithm_behavior == "accept_isolated"
            and lab.is_visible
            and not lab.exclude_from_contour_metrics
            and not accepted_here
        ):
            false_fc += 1

        # Contour metrics
        if lab.exclude_from_contour_metrics or lab.boundary_uncertain:
            n_unc += 1
            continue
        if lab.mask_array is None or pf is None or pf.mask_array is None:
            continue
        if not accepted_here:
            # Unaccepted frames do not enter Dice promotion population
            continue
        d = dice_binary(pf.mask_array, lab.mask_array)
        j = jaccard_binary(pf.mask_array, lab.mask_array)
        dice_scores.append(d)
        jac_scores.append(j)
        hd_px = hausdorff95_boundary(pf.mask_array, lab.mask_array)
        if hd_px is not None:
            hd_px_scores.append(hd_px)
        # Physical boundary distance only when calibrated spacing is known.
        if spacing_yx is not None:
            hd_um = hausdorff95_boundary(
                pf.mask_array, lab.mask_array, pixel_size_yx_um=spacing_yx
            )
            if hd_um is not None:
                hd_um_scores.append(hd_um)

    # Also count events on unlabelled predicted frames if flags set
    for pf in preds or []:
        if pf.accepted and pf.false_merge:
            # may double-count labelled; use max via set of frames for labelled path only
            pass

    c_time = sum(
        float(c.time_s) for c in corrections_for_obj if c.time_s is not None
    ) or None

    return ObjectScore(
        object_id=obj.object_id,
        partition=obj.partition,
        primary_stratum=obj.primary_stratum,
        dice=summarize_frame_scores(dice_scores),
        jaccard=summarize_frame_scores(jac_scores),
        hausdorff95_px=summarize_frame_scores(hd_px_scores),
        hausdorff95_um=summarize_frame_scores(hd_um_scores),
        n_labelled_scored=len(dice_scores),
        n_uncertain_excluded=n_unc,
        false_merge_accepts=false_merge,
        identity_switches=id_sw,
        cap_hallucinations=cap_h,
        neighbor_steals=steal,
        false_fail_closed=false_fc,
        visible_frames=visible,
        accepted_frames=accepted,
        gap_like_frames=gap_like,
        calibrated=calibrated,
        physical_metrics_suppressed=physical_suppressed,
        corrections=len(corrections_for_obj),
        correction_time_s=c_time,
    )


def check_partition_leakage(corpus: CorpusManifest) -> GateResult:
    """Contact pairs (shared contact_group_id) must share one partition."""
    groups: dict[str, set[str]] = {}
    for obj in corpus.objects:
        if not obj.contact_group_id:
            continue
        groups.setdefault(obj.contact_group_id, set()).add(obj.partition)
    leaks = {g: sorted(parts) for g, parts in groups.items() if len(parts) > 1}
    if leaks:
        return GateResult(
            gate_id="LEAK",
            name="partition_leakage",
            status="FAIL",
            detail="Contact group(s) split across partitions — holdout leakage risk",
            evidence={"leaking_groups": leaks},
        )
    return GateResult(
        gate_id="LEAK",
        name="partition_leakage",
        status="PASS",
        detail="No contact-group partition splits",
        evidence={"groups_checked": len(groups)},
    )


def check_corpus_completeness(corpus: CorpusManifest) -> list[GateResult]:
    """W5 / PoC minimum: ≥12 targets, ≥3 acq, ≥4 contact, ≥3 negatives; holdout frozen."""
    results: list[GateResult] = []
    acq_ids = {a.source_id for a in corpus.acquisitions}
    targets = [
        o
        for o in corpus.objects
        if not o.is_negative_seed and o.primary_stratum in TARGET_STRATA
    ]
    negatives = [o for o in corpus.objects if o.is_negative_seed or o.primary_stratum == "S9"]
    contact = [
        o
        for o in targets
        if o.primary_stratum in CONTACT_STRATA
        or any(s in CONTACT_STRATA for s in o.stratum_ids)
    ]
    target_sources = {o.source_id for o in targets}
    calibrated_contact = [
        o
        for o in contact
        if _acq_calibrated(corpus, o.source_id)
        and any(f.mask_array is not None or f.mask_relpath for f in o.labelled_frames)
    ]
    holdout_objs = [o for o in corpus.objects if o.object_id in set(corpus.holdout.object_ids)]
    holdout_contact = [
        o
        for o in holdout_objs
        if o.primary_stratum in CONTACT_STRATA
        or any(s in CONTACT_STRATA for s in o.stratum_ids)
    ]

    # Holdout freeze
    if not corpus.holdout.frozen or not corpus.holdout.object_ids:
        results.append(
            GateResult(
                gate_id="HOLD",
                name="holdout_frozen",
                status="BLOCKED",
                detail="Holdout IDs not frozen before scoring",
                evidence={"holdout": corpus.holdout.to_dict()},
            )
        )
    else:
        results.append(
            GateResult(
                gate_id="HOLD",
                name="holdout_frozen",
                status="PASS",
                detail="Holdout manifest frozen",
                evidence={"n_holdout": len(corpus.holdout.object_ids)},
            )
        )

    # Minimum N
    n_ok = len(targets) >= 12 and len(acq_ids) >= 3 and len(contact) >= 4 and len(negatives) >= 3
    results.append(
        GateResult(
            gate_id="CORPUS_N",
            name="corpus_minimum_n",
            status="PASS" if n_ok else "BLOCKED",
            detail=(
                "PoC N met"
                if n_ok
                else "PoC minimum not met (≥12 targets, ≥3 acquisitions, ≥4 contact, ≥3 negatives)"
            ),
            evidence={
                "n_targets": len(targets),
                "n_acquisitions": len(acq_ids),
                "n_contact": len(contact),
                "n_negatives": len(negatives),
                "target_sources": sorted(target_sources),
            },
        )
    )

    # Labelled calibrated contact (W5) — never pass by synthetic alone
    w5_ok = len(calibrated_contact) >= 1 and len(holdout_contact) >= 1
    # Require actual labels on holdout contact
    holdout_contact_labelled = [
        o
        for o in holdout_contact
        if any(f.mask_array is not None or f.mask_relpath for f in o.labelled_frames)
        and _acq_calibrated(corpus, o.source_id)
    ]
    if not holdout_contact_labelled:
        results.append(
            GateResult(
                gate_id="W5",
                name="labelled_calibrated_contact",
                status="BLOCKED",
                detail=(
                    "Labelled calibrated real contact (holdout S2/S3) absent. "
                    "Synthetic fixtures cannot close W5. "
                    + corpus.incomplete_signoff_statement
                ),
                evidence={
                    "n_calibrated_contact_objects": len(calibrated_contact),
                    "n_holdout_contact": len(holdout_contact),
                    "n_holdout_contact_labelled_calibrated": len(holdout_contact_labelled),
                },
            )
        )
    else:
        results.append(
            GateResult(
                gate_id="W5",
                name="labelled_calibrated_contact",
                status="PASS",
                detail="Holdout labelled calibrated contact objects present",
                evidence={
                    "object_ids": [o.object_id for o in holdout_contact_labelled],
                },
            )
        )

    return results


def evaluate_promotion(
    corpus: CorpusManifest,
    predictions: PredictionBundle | None,
    *,
    provisional_p95_budget_ms: float = 250.0,
    seed_exact_p95_budget_ms: float = 5000.0,
    target_z_p95_budget_ms: float = 2500.0,
    require_speed: bool = True,
) -> dict[str, Any]:
    """Run completeness + leakage + per-object scores + gates A–F.

    Never returns a composite accuracy percentage.
    Gate D requires provisional, seed-exact, and target-Z p95 when require_speed.
    """
    gates: list[GateResult] = []
    gates.extend(check_corpus_completeness(corpus))
    gates.append(check_partition_leakage(corpus))

    # Score objects
    obj_scores: list[ObjectScore] = []
    holdout_ids = set(corpus.holdout.object_ids)
    for obj in corpus.objects:
        preds = None
        if predictions is not None:
            preds = predictions.by_object.get(obj.object_id)
        corrs = [
            c
            for c in (predictions.corrections if predictions else [])
            if c.object_id == obj.object_id
        ]
        obj_scores.append(
            score_object(obj, preds, corpus=corpus, corrections_for_obj=corrs)
        )

    holdout_scores = [s for s in obj_scores if s.object_id in holdout_ids]
    holdout_contact_scores = [
        s
        for s in holdout_scores
        if s.primary_stratum in CONTACT_STRATA
        or any(
            st in CONTACT_STRATA
            for st in next(
                (o.stratum_ids for o in corpus.objects if o.object_id == s.object_id),
                (),
            )
        )
    ]
    holdout_s1 = [s for s in holdout_scores if s.primary_stratum == "S1"]
    holdout_neg = [
        s
        for s in holdout_scores
        if next(
            (o.is_negative_seed for o in corpus.objects if o.object_id == s.object_id),
            False,
        )
        or s.primary_stratum == "S9"
    ]

    data_blocked = any(g.status == "BLOCKED" for g in gates if g.gate_id in ("W5", "HOLD", "CORPUS_N"))

    # --- Gate A safety ---
    if data_blocked and not holdout_contact_scores:
        gates.append(
            GateResult(
                gate_id="A",
                name="safe_failure",
                status="BLOCKED",
                detail="Safety gate not scorable without holdout contact labelled data",
                evidence={},
            )
        )
    else:
        fm = sum(s.false_merge_accepts for s in holdout_scores)
        ids = sum(s.identity_switches for s in holdout_scores)
        caps = sum(s.cap_hallucinations for s in holdout_scores)
        steals = sum(s.neighbor_steals for s in holdout_scores)
        # Negative seeds: no full credible track (accepted_frames high)
        neg_fail = [
            s
            for s in holdout_neg
            if s.accepted_frames >= max(3, s.visible_frames // 2) and s.visible_frames > 0
        ]
        a_fail = fm > 0 or ids > 0 or caps > 0 or steals > 0 or bool(neg_fail)
        gates.append(
            GateResult(
                gate_id="A",
                name="safe_failure",
                status="FAIL" if a_fail else ("PASS" if holdout_scores else "BLOCKED"),
                detail=(
                    "Safety failure on holdout"
                    if a_fail
                    else (
                        "Zero false-merge / identity / cap / steal on holdout"
                        if holdout_scores
                        else "No holdout scores"
                    )
                ),
                evidence={
                    "false_merge_accepts": fm,
                    "identity_switches": ids,
                    "cap_hallucinations": caps,
                    "neighbor_steals": steals,
                    "negative_seed_full_track_object_ids": [s.object_id for s in neg_fail],
                },
            )
        )

    # --- Gate B contour quality ---
    if data_blocked:
        gates.append(
            GateResult(
                gate_id="B",
                name="contour_quality",
                status="BLOCKED",
                detail="Contour quality blocked until labelled calibrated holdout exists",
                evidence={},
            )
        )
    else:
        b_fail = False
        b_ev: dict[str, Any] = {"s1": [], "contact": []}
        for s in holdout_s1:
            med = s.dice.get("median")
            worst = s.dice.get("worst")
            ok = (
                med is not None
                and worst is not None
                and med >= 0.85
                and worst >= 0.70
            )
            b_ev["s1"].append({"object_id": s.object_id, "dice": s.dice, "ok": ok})
            if not ok and s.n_labelled_scored > 0:
                b_fail = True
        hd_limit_px = corpus.hausdorff95_limit_px
        if corpus.membrane_thickness_px is not None:
            hd_limit_px = min(hd_limit_px, 3.0 * float(corpus.membrane_thickness_px))
        for s in holdout_contact_scores:
            med = s.dice.get("median")
            ok = med is not None and med >= 0.75
            if s.physical_metrics_suppressed:
                # Uncalibrated: px HD only; never claim µm.
                hd_px = s.hausdorff95_px.get("median")
                if hd_px is not None and hd_px > corpus.hausdorff95_limit_px:
                    ok = False
            else:
                # Calibrated: Gate B boundary criterion uses physical µm HD.
                hd_um = s.hausdorff95_um.get("median")
                if hd_um is None and s.n_labelled_scored > 0:
                    ok = False  # must compute physical HD when calibrated
                limit_um = corpus.hausdorff95_limit_um
                if limit_um is None:
                    # Fallback: convert px policy by mean of calibrated XY spacings.
                    spacings = [
                        _acq_spacing_yx_um(corpus, o.source_id)
                        for o in corpus.objects
                        if o.object_id == s.object_id
                    ]
                    sp = next((x for x in spacings if x is not None), None)
                    if sp is not None:
                        limit_um = float(hd_limit_px) * float(min(sp[0], sp[1]))
                    else:
                        limit_um = float(hd_limit_px)
                if hd_um is not None and hd_um > float(limit_um):
                    ok = False
            b_ev["contact"].append(
                {
                    "object_id": s.object_id,
                    "dice": s.dice,
                    "hausdorff95_px": s.hausdorff95_px,
                    "hausdorff95_um": s.hausdorff95_um,
                    "physical_metrics_suppressed": s.physical_metrics_suppressed,
                    "ok": ok,
                }
            )
            if s.n_labelled_scored > 0 and not ok:
                b_fail = True
        if not holdout_s1 and not holdout_contact_scores:
            gates.append(
                GateResult(
                    gate_id="B",
                    name="contour_quality",
                    status="BLOCKED",
                    detail="No holdout objects with scorable labels",
                    evidence=b_ev,
                )
            )
        else:
            gates.append(
                GateResult(
                    gate_id="B",
                    name="contour_quality",
                    status="FAIL" if b_fail else "PASS",
                    detail="Isolated/contact Dice(/HD) criteria",
                    evidence=b_ev,
                )
            )

    # --- Gate C continuity ---
    if not holdout_scores:
        gates.append(
            GateResult(
                gate_id="C",
                name="continuity",
                status="BLOCKED",
                detail="No holdout objects to score continuity",
                evidence={},
            )
        )
    else:
        # false fail-closed rate on S1
        rates = []
        for s in holdout_s1:
            if s.visible_frames > 0:
                rates.append(s.false_fail_closed / s.visible_frames)
        max_rate = max(rates) if rates else 0.0
        c_fail = max_rate > 0.10 or any(s.identity_switches > 0 for s in holdout_scores)
        gates.append(
            GateResult(
                gate_id="C",
                name="continuity",
                status="FAIL" if c_fail else "PASS",
                detail="Identity continuity + S1 false fail-closed ≤10%",
                evidence={
                    "max_s1_false_fail_closed_rate": max_rate,
                    "identity_switches_holdout": sum(
                        s.identity_switches for s in holdout_scores
                    ),
                },
            )
        )

    # --- Gate D speed ---
    # Interaction is fixed only when provisional *and* seed-exact *and* target-Z
    # p95 meet predeclared budgets (not provisional alone).
    lats = predictions.latencies if predictions else []
    if require_speed and not lats:
        gates.append(
            GateResult(
                gate_id="D",
                name="speed_interaction",
                status="INCOMPLETE",
                detail="Timing protocol incomplete — cannot claim interaction fixed",
                evidence={},
            )
        )
    elif not lats:
        gates.append(
            GateResult(
                gate_id="D",
                name="speed_interaction",
                status="NOT_APPLICABLE",
                detail="No latency records supplied",
                evidence={},
            )
        )
    else:
        prov = [L.provisional_p95_ms for L in lats if L.provisional_p95_ms is not None]
        seed_ex = [L.seed_exact_p95_ms for L in lats if L.seed_exact_p95_ms is not None]
        target_z = [L.target_z_p95_ms for L in lats if L.target_z_p95_ms is not None]
        missing_lanes = []
        if not prov:
            missing_lanes.append("provisional_p95_ms")
        if not seed_ex:
            missing_lanes.append("seed_exact_p95_ms")
        if not target_z:
            missing_lanes.append("target_z_p95_ms")
        over: list[str] = []
        if any(p > provisional_p95_budget_ms for p in prov):
            over.append(f"provisional>{provisional_p95_budget_ms}")
        if any(p > seed_exact_p95_budget_ms for p in seed_ex):
            over.append(f"seed_exact>{seed_exact_p95_budget_ms}")
        if any(p > target_z_p95_budget_ms for p in target_z):
            over.append(f"target_z>{target_z_p95_budget_ms}")
        if require_speed and missing_lanes:
            d_status: GateStatus = "INCOMPLETE"
            d_detail = (
                "Timing protocol incomplete — provisional, seed_exact, and "
                f"target_z p95 all required ({', '.join(missing_lanes)} missing)"
            )
        elif over:
            d_status = "FAIL"
            d_detail = (
                f"Speed budgets exceeded: {', '.join(over)} "
                f"(prov≤{provisional_p95_budget_ms}, "
                f"seed_exact≤{seed_exact_p95_budget_ms}, "
                f"target_z≤{target_z_p95_budget_ms} ms)"
            )
        else:
            d_status = "PASS"
            d_detail = (
                f"Provisional/seed_exact/target_z p95 within budgets "
                f"({provisional_p95_budget_ms}/{seed_exact_p95_budget_ms}/"
                f"{target_z_p95_budget_ms} ms)"
            )
        gates.append(
            GateResult(
                gate_id="D",
                name="speed_interaction",
                status=d_status,
                detail=d_detail,
                evidence={
                    "provisional_p95_ms": prov,
                    "seed_exact_p95_ms": seed_ex,
                    "target_z_p95_ms": target_z,
                    "budgets_ms": {
                        "provisional": provisional_p95_budget_ms,
                        "seed_exact": seed_exact_p95_budget_ms,
                        "target_z": target_z_p95_budget_ms,
                    },
                    "missing_lanes": missing_lanes,
                    "over_budget": over,
                    "attempts_mean": [
                        L.attempts_mean for L in lats if L.attempts_mean is not None
                    ],
                },
            )
        )

    # --- Gate E reproducibility ---
    if predictions is None or predictions.bit_identical_rerun is None:
        gates.append(
            GateResult(
                gate_id="E",
                name="reproducibility",
                status="INCOMPLETE",
                detail="bit_identical_rerun not declared",
                evidence={"algorithm_version": getattr(predictions, "algorithm_version", None)},
            )
        )
    else:
        gates.append(
            GateResult(
                gate_id="E",
                name="reproducibility",
                status="PASS" if predictions.bit_identical_rerun else "FAIL",
                detail="Declared bit-identical re-run flag",
                evidence={"bit_identical_rerun": predictions.bit_identical_rerun},
            )
        )

    # --- Gate F calibration honesty ---
    # Fail if any object scored physical claims while uncalibrated (harness suppresses;
    # check predictions don't claim µm in evidence). We enforce: physical_metrics_suppressed
    # when default voxels; fail if corpus marks calibrated_biological_units with default source.
    f_fail = False
    f_ev: list[dict[str, Any]] = []
    for a in corpus.acquisitions:
        bad = a.voxel.calibrated_biological_units and a.voxel.voxel_source == "default"
        f_ev.append(
            {
                "source_id": a.source_id,
                "voxel_source": a.voxel.voxel_source,
                "calibrated_biological_units": a.voxel.calibrated_biological_units,
                "invalid_claim": bad,
            }
        )
        if bad:
            f_fail = True
    gates.append(
        GateResult(
            gate_id="F",
            name="calibration_honesty",
            status="FAIL" if f_fail else "PASS",
            detail="No biological units from default 1×1×1 voxels",
            evidence={"acquisitions": f_ev},
        )
    )

    # Overall decision
    statuses = {g.gate_id: g.status for g in gates}
    if any(g.status == "BLOCKED" for g in gates if g.gate_id in ("W5", "HOLD", "CORPUS_N", "A", "B")):
        overall = "BLOCKED"
        overall_detail = corpus.incomplete_signoff_statement
    elif any(g.status == "FAIL" for g in gates if g.gate_id == "A"):
        overall = "REJECT_SCIENTIFICALLY"
        overall_detail = "Safety gate failed on holdout"
    elif any(g.status == "FAIL" for g in gates if g.gate_id in ("B", "C", "E", "F", "LEAK")):
        overall = "REJECT"
        overall_detail = "One or more science/process gates failed"
    elif any(g.status == "FAIL" for g in gates if g.gate_id == "D"):
        overall = "REJECT_SPEED"
        overall_detail = "Science may pass but speed/interaction budgets failed"
    elif any(g.status == "INCOMPLETE" for g in gates if g.gate_id in ("D", "E")):
        overall = "INCOMPLETE"
        overall_detail = "Required timing or reproducibility evidence incomplete"
    elif all(
        g.status in ("PASS", "NOT_APPLICABLE")
        for g in gates
        if g.gate_id in ("A", "B", "C", "D", "E", "F", "W5", "HOLD", "LEAK")
    ):
        overall = "PROMOTE_ENGINEERING"
        overall_detail = (
            "All applicable gates PASS (engineering PoC only; not publication readiness)"
        )
    else:
        overall = "INCOMPLETE"
        overall_detail = "Unresolved gate mix"

    return {
        "corpus_id": corpus.corpus_id,
        "overall": overall,
        "overall_detail": overall_detail,
        "incomplete_signoff_statement": corpus.incomplete_signoff_statement,
        "gates": [g.to_dict() for g in gates],
        "per_object": [s.to_dict() for s in obj_scores],
        "per_stack_summary": _per_stack_summary(corpus, obj_scores),
        "corrections": [
            {
                "correction_id": c.correction_id,
                "object_id": c.object_id,
                "frame_index": c.frame_index,
                "action": c.action,
                "time_s": c.time_s,
            }
            for c in (predictions.corrections if predictions else [])
        ],
        "composite_accuracy_percent": None,
        "notes": [
            "Never interpret this report as a single accuracy percentage.",
            "No >95% or publication-ready claim is authorized by this harness.",
            corpus.incomplete_signoff_statement,
        ],
    }


def _per_stack_summary(
    corpus: CorpusManifest, scores: list[ObjectScore]
) -> list[dict[str, Any]]:
    by_src: dict[str, list[ObjectScore]] = {}
    for s in scores:
        obj = next(o for o in corpus.objects if o.object_id == s.object_id)
        by_src.setdefault(obj.source_id, []).append(s)
    out = []
    for sid, slist in sorted(by_src.items()):
        medians = [s.dice["median"] for s in slist if s.dice.get("median") is not None]
        out.append(
            {
                "source_id": sid,
                "n_objects": len(slist),
                "median_of_object_median_dice": (
                    float(np.median(medians)) if medians else None
                ),
                "false_merge_accepts": sum(s.false_merge_accepts for s in slist),
                "identity_switches": sum(s.identity_switches for s in slist),
                "composite_accuracy_percent": None,
            }
        )
    return out

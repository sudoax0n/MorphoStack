#!/usr/bin/env python3
"""Real-stack RBC validation runner (Phase 5).

Runs only when an evidence bundle is accepted. Without lab data the runner
records a withheld capability decision and exits non-zero for missing evidence
(not as a false engineering pass).
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from morphostack.core.rbc_evidence import validate_rbc_evidence_bundle  # noqa: E402

REQUIRED_METRIC_FAMILIES = (
    "segmentation",
    "surface_distance",
    "topology",
    "z_linking",
    "morphometry",
    "repeatability",
    "capability_decision",
)


class RealValidationReport:
    def __init__(
        self,
        biological_validation: bool,
        evidence_accepted: bool,
        metric_families: tuple[str, ...],
        capability_decisions: dict[str, str],
        reasons: list[str] | None = None,
        generated_at_utc: str = "",
    ) -> None:
        self.biological_validation = biological_validation
        self.evidence_accepted = evidence_accepted
        self.metric_families = metric_families
        self.capability_decisions = capability_decisions
        self.reasons = list(reasons or [])
        self.generated_at_utc = generated_at_utc

    def to_dict(self) -> dict:
        return {
            "biological_validation": self.biological_validation,
            "evidence_accepted": self.evidence_accepted,
            "metric_families": list(self.metric_families),
            "capability_decisions": dict(self.capability_decisions),
            "reasons": list(self.reasons),
            "generated_at_utc": self.generated_at_utc,
        }


def run_rbc_real_validation(
    bundle_manifest: Path | str | dict,
    *,
    output_dir: Path | None = None,
) -> RealValidationReport:
    """Evaluate real stacks when evidence is accepted; otherwise withhold all."""

    evidence = validate_rbc_evidence_bundle(bundle_manifest)
    now = datetime.now(timezone.utc).isoformat()
    withheld = {
        "calibrated_2d": "WITHHELD",
        "validated_3d_occupancy": "WITHHELD",
        "validated_3d_surface": "WITHHELD",
        "estimated_model": "WITHHELD",
    }
    if not evidence.accepted:
        report = RealValidationReport(
            biological_validation=False,
            evidence_accepted=False,
            metric_families=REQUIRED_METRIC_FAMILIES,
            capability_decisions=withheld,
            reasons=list(evidence.reasons),
            generated_at_utc=now,
        )
        if output_dir is not None:
            _write_outputs(Path(output_dir), report, evidence.to_dict())
        return report

    # Evidence schema accepted — still no auto-promotion without lab thresholds
    # and actual stack evaluation. Phase 5 keeps decisions WITHHELD until runs
    # and lab approval are recorded.
    report = RealValidationReport(
        biological_validation=False,
        evidence_accepted=True,
        metric_families=REQUIRED_METRIC_FAMILIES,
        capability_decisions=withheld,
        reasons=[
            "evidence_schema_ok_but_stack_evaluation_not_executed",
            "lab_acceptance_thresholds_not_applied",
        ],
        generated_at_utc=now,
    )
    if output_dir is not None:
        _write_outputs(Path(output_dir), report, evidence.to_dict())
    return report


def _write_outputs(output_dir: Path, report: RealValidationReport, evidence: dict) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    (output_dir / "manifest.json").write_text(
        json.dumps(
            {
                "report": report.to_dict(),
                "evidence": evidence,
            },
            indent=2,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )
    # Empty metrics placeholder — real metrics require annotated stacks.
    (output_dir / "metrics.csv").write_text(
        "stack_id,metric_family,metric,value,status\n",
        encoding="utf-8",
    )
    md_lines = [
        "# RBC real-stack validation",
        "",
        f"Generated: `{report.generated_at_utc}`",
        "",
        f"**Biological validation:** `{report.biological_validation}`",
        f"**Evidence accepted:** `{report.evidence_accepted}`",
        "",
        "## Capability decisions",
        "",
    ]
    for k, v in report.capability_decisions.items():
        md_lines.append(f"- `{k}`: **{v}**")
    md_lines.append("")
    md_lines.append("## Reasons")
    md_lines.append("")
    for r in report.reasons:
        md_lines.append(f"- `{r}`")
    md_lines.append("")
    (output_dir / "summary.md").write_text("\n".join(md_lines) + "\n", encoding="utf-8")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--manifest",
        default=str(
            ROOT / "validation" / "references" / "rbc-annotations-v1" / "manifest.json"
        ),
    )
    parser.add_argument(
        "--output",
        default=str(ROOT / "validation" / "runs" / "rbc-real-v1"),
    )
    parser.add_argument(
        "--protocol",
        default=str(
            ROOT / "validation" / "protocols" / "rbc-real-stack-validation-v1.md"
        ),
        help="Protocol path (recorded for provenance; not parsed as code)",
    )
    args = parser.parse_args(argv)
    report = run_rbc_real_validation(args.manifest, output_dir=Path(args.output))
    # Also publish a top-level report copy when evidence is missing.
    reports = ROOT / "validation" / "reports"
    reports.mkdir(parents=True, exist_ok=True)
    summary_src = Path(args.output) / "summary.md"
    if summary_src.is_file():
        (reports / "rbc-real-stack-validation-v1.md").write_text(
            summary_src.read_text(encoding="utf-8")
            + f"\nProtocol: `{args.protocol}`\n",
            encoding="utf-8",
        )
    print(json.dumps(report.to_dict(), indent=2, sort_keys=True))
    return 0 if report.evidence_accepted and report.biological_validation else 1


if __name__ == "__main__":
    raise SystemExit(main())

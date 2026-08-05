"""Phase 5 real-stack validation runner contracts."""

from __future__ import annotations

import importlib.util
from pathlib import Path


def _load_runner():
    script = Path(__file__).resolve().parents[1] / "scripts" / "validate_rbc_real_stacks.py"
    spec = importlib.util.spec_from_file_location("validate_rbc_real_stacks", script)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_real_validation_report_contains_required_metric_families(tmp_path):
    mod = _load_runner()
    # Placeholder / empty bundle
    report = mod.run_rbc_real_validation(
        Path(__file__).resolve().parents[1]
        / "validation"
        / "references"
        / "rbc-annotations-v1"
        / "manifest.json",
        output_dir=tmp_path,
    )
    assert set(report.metric_families) == set(mod.REQUIRED_METRIC_FAMILIES)
    assert report.biological_validation is False
    assert report.evidence_accepted is False
    assert all(v == "WITHHELD" for v in report.capability_decisions.values())
    assert (tmp_path / "manifest.json").is_file()
    assert (tmp_path / "metrics.csv").is_file()


def test_production_estimator_still_unregistered():
    from morphostack.core.rbc_estimation import get_production_estimator

    assert get_production_estimator() is None

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

SCRIPT_PATH = Path(__file__).resolve().parents[1] / "scripts" / "compare_active_surfaces_threshold.py"


def load_compare_module():
    spec = importlib.util.spec_from_file_location("compare_active_surfaces_threshold", SCRIPT_PATH)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules["compare_active_surfaces_threshold"] = module
    spec.loader.exec_module(module)
    return module


def test_run_synthetic_writes_report(tmp_path: Path):
    module = load_compare_module()
    report_path = module.run_synthetic(tmp_path)
    assert report_path.exists()
    assert "Active Surfaces vs Threshold" in report_path.read_text(encoding="utf-8")
    assert (tmp_path / "active-surfaces-vs-threshold-synthetic-sphere.json").exists()


@pytest.mark.slow
def test_run_dopc_writes_report_when_source_exists(tmp_path: Path):
    module = load_compare_module()
    dopc_path = Path(r"D:\lab-data\paper-data\syst202400052-sup-0001-movie1-dopc.tif")
    if not dopc_path.exists():
        pytest.skip(f"DOPC source missing: {dopc_path}")
    report_path = module.run_dopc(tmp_path, dopc_path)
    assert report_path is not None
    assert report_path.exists()
    assert (tmp_path / "active-surfaces-vs-threshold-dopc-movie1.json").exists()
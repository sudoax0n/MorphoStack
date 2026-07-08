import importlib.util
import sys
from pathlib import Path

import numpy as np

SCRIPT_PATH = Path(__file__).resolve().parents[1] / "scripts" / "compare_limeseg_threshold.py"


def load_compare_module():
    spec = importlib.util.spec_from_file_location("compare_limeseg_threshold", SCRIPT_PATH)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    sys.modules["compare_limeseg_threshold"] = module
    spec.loader.exec_module(module)
    return module


def test_pct_delta_handles_missing_and_zero():
    mod = load_compare_module()
    assert mod.pct_delta(None, 10.0) == "n/a"
    assert mod.pct_delta(10.0, None) == "n/a"
    assert mod.pct_delta(0.0, 5.0) == "n/a"
    assert mod.pct_delta(100.0, 110.0) == "+10.0%"


def test_run_synthetic_writes_report(tmp_path):
    mod = load_compare_module()
    report_path = mod.run_synthetic(tmp_path)
    assert report_path.exists()
    assert "LimeSeg vs Threshold" in report_path.read_text(encoding="utf-8")
    assert (tmp_path / "limeseg-vs-threshold-synthetic-sphere.json").exists()


def test_build_sphere_stack_has_expected_shape():
    mod = load_compare_module()
    stack = mod.build_sphere_stack()
    assert stack.shape == (10, 40, 40)
    assert int(np.max(stack)) == 255


import pytest


@pytest.mark.slow
def test_run_dopc_writes_report_when_source_exists(tmp_path):
    mod = load_compare_module()
    dopc_path = Path(r"D:\lab-data\paper-data\syst202400052-sup-0001-movie1-dopc.tif")
    if not dopc_path.exists():
        return
    report_path = mod.run_dopc(tmp_path, dopc_path)
    assert report_path is not None
    assert report_path.exists()
    assert (tmp_path / "limeseg-vs-threshold-dopc-movie1.json").exists()
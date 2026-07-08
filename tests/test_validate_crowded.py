import importlib.util
import sys
from pathlib import Path

SCRIPT_PATH = Path(__file__).resolve().parents[1] / "scripts" / "validate_crowded.py"


def load_module():
    spec = importlib.util.spec_from_file_location("validate_crowded", SCRIPT_PATH)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    sys.modules["validate_crowded"] = module
    spec.loader.exec_module(module)
    return module


def test_validation_cases_include_new_datasets():
    mod = load_module()
    slugs = {case.slug for case in mod.VALIDATION_CASES}
    assert "czi-1644-crowded-two-objects" in slugs
    assert "rbc-image32-crowded-two-objects" in slugs
    assert len(mod.VALIDATION_CASES) >= 4


def test_crowded_case_out_dir_under_validation_runs():
    mod = load_module()
    case = next(item for item in mod.VALIDATION_CASES if item.slug == "czi-1644-crowded-two-objects")
    assert case.out_dir.name == "czi-1644-crowded-two-objects"
    assert case.out_dir.parent.name == "runs"
import importlib.util
import json
import sys
from pathlib import Path

import numpy as np

SCRIPT_PATH = Path(__file__).resolve().parents[1] / "scripts" / "capture_validation_previews.py"


def load_module():
    spec = importlib.util.spec_from_file_location("capture_validation_previews", SCRIPT_PATH)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    sys.modules["capture_validation_previews"] = module
    spec.loader.exec_module(module)
    return module


def test_case_from_manifest_skips_synthetic(tmp_path):
    mod = load_module()
    manifest_path = tmp_path / "manifest.json"
    manifest_path.write_text(
        json.dumps({"source_path": "synthetic-sphere", "threshold": 100}),
        encoding="utf-8",
    )
    assert mod.case_from_manifest(manifest_path) is None


def test_local_frame_index_respects_z_range():
    mod = load_module()
    from morphostack.core.pipeline import ObjectSeed, ZRange

    case = mod.PreviewCase(
        manifest_path=Path("manifest.json"),
        source_path=Path("stack.czi"),
        threshold=100.0,
        profile="vesicle",
        frame_index=105,
        object_seed=ObjectSeed(x=1.0, y=2.0, frame_index=105, radius=10.0),
        z_range=ZRange(zmin=90, zmax=120),
        prefer_opencv=True,
    )
    assert mod.local_frame_index(case, global_frame_count=200) == 15


def load_compare_module():
    compare_path = Path(__file__).resolve().parents[1] / "scripts" / "compare_active_surfaces_threshold.py"
    spec = importlib.util.spec_from_file_location("compare_active_surfaces_threshold", compare_path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    sys.modules["compare_active_surfaces_threshold"] = module
    spec.loader.exec_module(module)
    return module


def test_auto_seed_from_largest_component_centroid():
    mod = load_compare_module()
    frame = np.zeros((20, 20), dtype=np.uint8)
    frame[5:10, 5:10] = 200
    seed = mod.auto_seed_from_largest_component(frame, threshold=100.0, frame_index=3, radius=8.0)
    assert seed.frame_index == 3
    assert 5 <= seed.x <= 9
    assert 5 <= seed.y <= 9
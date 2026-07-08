from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]


def test_validate_synthetic_touching_confirms_failure_mode(tmp_path: Path):
    out_dir = tmp_path / "synthetic-touching-failure"
    result = subprocess.run(
        [
            sys.executable,
            str(PROJECT_ROOT / "scripts" / "validate_synthetic_touching.py"),
            "--out-dir",
            str(out_dir),
        ],
        cwd=PROJECT_ROOT,
        check=False,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stdout + result.stderr

    summary = json.loads((out_dir / "failure-summary.json").read_text(encoding="utf-8"))
    assert summary["failure_mode_confirmed"] is True
    assert any(summary["checks"].values())
    assert (out_dir / "manifest.json").exists()
    assert (out_dir / "README.md").exists()
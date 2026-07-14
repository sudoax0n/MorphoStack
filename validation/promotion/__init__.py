"""Real-data tracking promotion harness (validation-only).

Implements REAL_DATA_VALIDATION_GATES + Scout 10 as schema and gate evaluation.
Does not manufacture labels or a composite accuracy percentage.
Missing labelled calibrated contact data → BLOCKED (never PASS by synthetic alone).
"""

from .gates import evaluate_promotion
from .metrics import dice_binary, hausdorff95_boundary, jaccard_binary
from .report import render_gate_report
from .schema import (
    CorpusManifest,
    HoldoutManifest,
    ObjectRecord,
    PredictionBundle,
    load_corpus_dir,
)

__all__ = [
    "CorpusManifest",
    "HoldoutManifest",
    "ObjectRecord",
    "PredictionBundle",
    "dice_binary",
    "evaluate_promotion",
    "hausdorff95_boundary",
    "jaccard_binary",
    "load_corpus_dir",
    "render_gate_report",
]

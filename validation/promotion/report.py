"""Render promotion gate reports (JSON + markdown)."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any


def render_gate_report(result: dict[str, Any], *, out_dir: Path | None = None) -> dict[str, Path]:
    """Write gate_report.json and gate_report.md. Returns written paths."""
    if out_dir is None:
        return {}
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    json_path = out_dir / "gate_report.json"
    md_path = out_dir / "gate_report.md"
    json_path.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    md_path.write_text(to_markdown(result), encoding="utf-8")
    return {"json": json_path, "md": md_path}


def to_markdown(result: dict[str, Any]) -> str:
    lines: list[str] = []
    lines.append(f"# Real-data promotion gate report: `{result.get('corpus_id', '')}`")
    lines.append("")
    lines.append(f"**Overall:** `{result.get('overall')}`  ")
    lines.append(f"{result.get('overall_detail', '')}")
    lines.append("")
    lines.append("> " + str(result.get("incomplete_signoff_statement", "")))
    lines.append("")
    lines.append("## Gates (independent — not averaged)")
    lines.append("")
    lines.append("| Gate | Name | Status | Detail |")
    lines.append("| --- | --- | --- | --- |")
    for g in result.get("gates") or []:
        detail = str(g.get("detail", "")).replace("|", "\\|")
        lines.append(
            f"| `{g.get('gate_id')}` | {g.get('name')} | **{g.get('status')}** | {detail} |"
        )
    lines.append("")
    lines.append("## Per-object metrics")
    lines.append("")
    lines.append(
        "| object_id | partition | stratum | dice median | dice worst | "
        "false_merge | id_switch | HD95 px | HD95 µm | unc. excl | calib |"
    )
    lines.append(
        "| --- | --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | --- |"
    )
    for s in result.get("per_object") or []:
        d = s.get("dice") or {}
        hd_px = s.get("hausdorff95_px") or {}
        hd_um = s.get("hausdorff95_um") or {}
        lines.append(
            f"| {s.get('object_id')} | {s.get('partition')} | {s.get('primary_stratum')} | "
            f"{_fmt(d.get('median'))} | {_fmt(d.get('worst'))} | "
            f"{s.get('false_merge_accepts')} | {s.get('identity_switches')} | "
            f"{_fmt(hd_px.get('median'))} | {_fmt(hd_um.get('median'))} | "
            f"{s.get('n_uncertain_excluded')} | "
            f"{'yes' if s.get('calibrated') else 'no'} |"
        )
    lines.append("")
    lines.append("## Explicit non-claims")
    lines.append("")
    lines.append(f"- `composite_accuracy_percent` = `{result.get('composite_accuracy_percent')}`")
    for n in result.get("notes") or []:
        lines.append(f"- {n}")
    lines.append("")
    return "\n".join(lines)


def _fmt(v: Any) -> str:
    if v is None:
        return "—"
    if isinstance(v, float):
        return f"{v:.3f}"
    return str(v)

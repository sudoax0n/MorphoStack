"""CSV validation helpers for comparing metric outputs."""

from __future__ import annotations

import csv
from dataclasses import dataclass
from pathlib import Path
from typing import TextIO


@dataclass(frozen=True)
class ValidationDifference:
    row_id: str
    column: str
    expected: str
    actual: str
    delta: float | None = None


@dataclass(frozen=True)
class ValidationReport:
    expected_path: str
    actual_path: str
    tolerance: float
    compared_rows: int
    compared_cells: int
    differences: list[ValidationDifference]

    @property
    def passed(self) -> bool:
        return not self.differences


def compare_metric_csv(
    expected: str | Path | TextIO,
    actual: str | Path | TextIO,
    *,
    tolerance: float = 1e-6,
    columns: list[str] | tuple[str, ...] | None = None,
    all_columns: bool = False,
    key_column: str = "frame_index",
) -> ValidationReport:
    expected_rows, expected_path = read_csv_rows(expected)
    actual_rows, actual_path = read_csv_rows(actual)
    differences: list[ValidationDifference] = []

    pairs = pair_rows(expected_rows, actual_rows, key_column=key_column, differences=differences)
    if columns:
        compare_columns = list(columns)
    elif all_columns:
        compare_columns = infer_common_columns(pairs, key_column=key_column)
    else:
        compare_columns = infer_numeric_columns(pairs, key_column=key_column)
    compared_cells = 0

    for row_id, expected_row, actual_row in pairs:
        for column in compare_columns:
            if column not in expected_row or column not in actual_row:
                differences.append(
                    ValidationDifference(
                        row_id=row_id,
                        column=column,
                        expected=expected_row.get(column, "<missing>"),
                        actual=actual_row.get(column, "<missing>"),
                    )
                )
                continue
            expected_value = expected_row[column]
            actual_value = actual_row[column]
            expected_number = parse_float(expected_value)
            actual_number = parse_float(actual_value)
            if expected_number is None or actual_number is None:
                if expected_value != actual_value:
                    differences.append(
                        ValidationDifference(
                            row_id=row_id,
                            column=column,
                            expected=expected_value,
                            actual=actual_value,
                        )
                    )
                compared_cells += 1
                continue

            delta = abs(expected_number - actual_number)
            if delta > tolerance:
                differences.append(
                    ValidationDifference(
                        row_id=row_id,
                        column=column,
                        expected=expected_value,
                        actual=actual_value,
                        delta=delta,
                    )
                )
            compared_cells += 1

    return ValidationReport(
        expected_path=expected_path,
        actual_path=actual_path,
        tolerance=tolerance,
        compared_rows=len(pairs),
        compared_cells=compared_cells,
        differences=differences,
    )


def read_csv_rows(source: str | Path | TextIO) -> tuple[list[dict[str, str]], str]:
    close_after = False
    if hasattr(source, "read"):
        handle = source
        source_name = getattr(source, "name", "<memory>")
    else:
        source_path = Path(source)
        handle = source_path.open("r", newline="", encoding="utf-8")
        source_name = str(source_path)
        close_after = True

    try:
        reader = csv.DictReader(handle)
        if reader.fieldnames is None:
            raise ValueError(f"{source_name} does not contain a CSV header")
        return [dict(row) for row in reader], source_name
    finally:
        if close_after:
            handle.close()


def pair_rows(
    expected_rows: list[dict[str, str]],
    actual_rows: list[dict[str, str]],
    *,
    key_column: str,
    differences: list[ValidationDifference],
) -> list[tuple[str, dict[str, str], dict[str, str]]]:
    if expected_rows and actual_rows and key_column in expected_rows[0] and key_column in actual_rows[0]:
        expected_by_key = {row[key_column]: row for row in expected_rows}
        actual_by_key = {row[key_column]: row for row in actual_rows}
        for missing in sorted(set(expected_by_key) - set(actual_by_key)):
            differences.append(ValidationDifference(missing, "__row__", "present", "missing"))
        for extra in sorted(set(actual_by_key) - set(expected_by_key)):
            differences.append(ValidationDifference(extra, "__row__", "missing", "present"))
        return [
            (key, expected_by_key[key], actual_by_key[key])
            for key in sorted(set(expected_by_key) & set(actual_by_key), key=sort_key)
        ]

    pairs = []
    for index, (expected_row, actual_row) in enumerate(zip(expected_rows, actual_rows)):
        pairs.append((str(index), expected_row, actual_row))
    if len(expected_rows) != len(actual_rows):
        differences.append(
            ValidationDifference(
                row_id="*",
                column="__row_count__",
                expected=str(len(expected_rows)),
                actual=str(len(actual_rows)),
            )
        )
    return pairs


def infer_numeric_columns(
    pairs: list[tuple[str, dict[str, str], dict[str, str]]],
    *,
    key_column: str,
) -> list[str]:
    if not pairs:
        return []
    common = set(pairs[0][1]) & set(pairs[0][2])
    common.discard(key_column)
    numeric_columns = []
    for column in sorted(common):
        values = []
        for _, expected_row, actual_row in pairs:
            values.extend((expected_row.get(column, ""), actual_row.get(column, "")))
        if values and all(parse_float(value) is not None for value in values):
            numeric_columns.append(column)
    return numeric_columns


def infer_common_columns(
    pairs: list[tuple[str, dict[str, str], dict[str, str]]],
    *,
    key_column: str,
) -> list[str]:
    if not pairs:
        return []
    common = set(pairs[0][1]) & set(pairs[0][2])
    common.discard(key_column)
    return sorted(common)


def parse_float(value: str) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def sort_key(value: str) -> tuple[int, float | str]:
    number = parse_float(value)
    if number is None:
        return (1, value)
    return (0, number)


def format_validation_report(report: ValidationReport) -> str:
    lines = [
        "MorphoStack CSV Validation",
        "==========================",
        f"Expected: {report.expected_path}",
        f"Actual: {report.actual_path}",
        f"Tolerance: {report.tolerance:g}",
        f"Rows compared: {report.compared_rows}",
        f"Cells compared: {report.compared_cells}",
        f"Result: {'PASS' if report.passed else 'FAIL'}",
    ]
    for difference in report.differences[:20]:
        delta_text = f", delta={difference.delta:g}" if difference.delta is not None else ""
        lines.append(
            f"- row {difference.row_id}, {difference.column}: "
            f"expected={difference.expected}, actual={difference.actual}{delta_text}"
        )
    if len(report.differences) > 20:
        lines.append(f"- ... {len(report.differences) - 20} more differences")
    return "\n".join(lines)

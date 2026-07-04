from __future__ import annotations

from io import StringIO

from morphostack.core.validation import compare_metric_csv, format_validation_report


def test_compare_metric_csv_passes_within_tolerance():
    expected = StringIO("frame_index,area_um2,method\n0,9.000000,fallback\n")
    actual = StringIO("frame_index,area_um2,method\n0,9.000001,fallback\n")

    report = compare_metric_csv(expected, actual, tolerance=1e-5)

    assert report.passed is True
    assert report.compared_rows == 1
    assert report.compared_cells == 1


def test_compare_metric_csv_reports_numeric_differences():
    expected = StringIO("frame_index,area_um2,circularity\n0,9.0,0.8\n")
    actual = StringIO("frame_index,area_um2,circularity\n0,10.0,0.8\n")

    report = compare_metric_csv(expected, actual, tolerance=1e-6)

    assert report.passed is False
    assert report.differences[0].column == "area_um2"
    assert report.differences[0].delta == 1.0
    assert "Result: FAIL" in format_validation_report(report)


def test_compare_metric_csv_reports_missing_rows_by_key():
    expected = StringIO("frame_index,area_um2\n0,9.0\n1,12.0\n")
    actual = StringIO("frame_index,area_um2\n0,9.0\n")

    report = compare_metric_csv(expected, actual)

    assert report.passed is False
    assert report.differences[0].column == "__row__"
    assert report.differences[0].row_id == "1"

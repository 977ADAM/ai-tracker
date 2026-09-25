"""CSV export uses the public projection and protects spreadsheet cells."""

from __future__ import annotations

import csv
import io

import pytest

from app.core.errors import RunConflict
from app.service.run_export import CSV_HEADERS, CSV_KEYS, render_run_csv


def test_csv_round_trip_and_formula_guard():
    rows = []
    for prompt, source in [
        ('=HYPERLINK("https://bad.example";"x")', "Модель\nодин"),
        ('текст; "цитата"\nстрока', "Обычный источник"),
        (" \t@SUM(1)", "\n=опасный"),
    ]:
        row = dict.fromkeys(CSV_KEYS, "—")
        row.update(prompt=prompt, source=source, status="Готово")
        rows.append(row)
    data = render_run_csv({"status": "done", "summary_rows": rows})
    assert data.startswith(b"\xef\xbb\xbf")
    parsed = list(csv.reader(io.StringIO(data.decode("utf-8-sig")), delimiter=";"))
    assert parsed[0] == list(CSV_HEADERS)
    assert parsed[1][0] == "'" + rows[0]["prompt"]
    assert parsed[1][1] == rows[0]["source"]
    assert parsed[2][0] == rows[1]["prompt"]
    assert parsed[3][0] == "'" + rows[2]["prompt"]
    assert parsed[3][1] == "'" + rows[2]["source"]
    assert len(parsed) == 4


def test_active_run_cannot_be_exported():
    with pytest.raises(RunConflict):
        render_run_csv({"status": "pending", "summary_rows": []})

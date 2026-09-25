"""Export the saved common table without model answer text."""

from __future__ import annotations

import csv
import io

from app.core.errors import RunConflict

CSV_KEYS = ("prompt", "source", "language", "region", "ai_answer", "site_found",
            "position", "brand_found", "status")
CSV_HEADERS = ("Запрос", "Поисковик", "Язык", "Регион", "ИИ-ответ", "Сайт найден",
               "Позиция", "Бренд найден", "Статус")


def safe_cell(value: str) -> str:
    """Keep spreadsheet software from interpreting user text as a formula."""
    trimmed = value.lstrip(" \t\r\n")
    if (trimmed and trimmed[0] in "=+-@") or value.startswith(("\t", "\r", "\n")):
        return "'" + value
    return value


def render_run_csv(snapshot: dict) -> bytes:
    if snapshot["status"] == "pending":
        raise RunConflict("Экспорт доступен после завершения прогона")
    output = io.StringIO(newline="")
    writer = csv.writer(output, delimiter=";", quoting=csv.QUOTE_ALL, lineterminator="\n")
    writer.writerow(CSV_HEADERS)
    for row in snapshot["summary_rows"]:
        writer.writerow(safe_cell(row[key]) for key in CSV_KEYS)
    return output.getvalue().encode("utf-8-sig")

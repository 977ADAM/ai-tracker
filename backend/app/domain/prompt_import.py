"""Read text/CSV/first-sheet XLSX as data; never evaluates spreadsheet formulas."""

import csv
import io
import posixpath
import zipfile
from pathlib import PurePath
from xml.etree import ElementTree as ET

from app.core.errors import ValidationError
from app.domain.matching import normalize_text
from app.domain.projects import normalize_project

MAX_FILE_BYTES = 256 * 1024
NS = "{http://schemas.openxmlformats.org/spreadsheetml/2006/main}"


def _xml(data):
    if b"<!DOCTYPE" in data or b"<!ENTITY" in data:
        raise ValidationError("Недопустимое содержимое XLSX")
    return ET.fromstring(data)


def _xlsx(data):
    try:
        with zipfile.ZipFile(io.BytesIO(data)) as archive:
            entries = archive.infolist()
            if (
                len(entries) > 1000
                or sum(e.file_size for e in entries) > 4 * 1024 * 1024
                or any(e.file_size > 2 * 1024 * 1024 for e in entries)
            ):
                raise ValidationError("XLSX слишком большой после распаковки")
            names = set(archive.namelist())
            sheet = "xl/worksheets/sheet1.xml"
            if "xl/workbook.xml" in names and "xl/_rels/workbook.xml.rels" in names:
                workbook = _xml(archive.read("xl/workbook.xml"))
                first = workbook.find(f"{NS}sheets/{NS}sheet")
                if first is None:
                    raise ValidationError("В XLSX нет листов")
                rid = first.get(
                    "{http://schemas.openxmlformats.org/officeDocument/2006/relationships}id"
                )
                relations = _xml(archive.read("xl/_rels/workbook.xml.rels"))
                target = next(
                    (
                        r.get("Target")
                        for r in relations
                        if r.get("Id") == rid and r.get("TargetMode") != "External"
                    ),
                    None,
                )
                if not target:
                    raise ValidationError("Не удалось найти первый лист XLSX")
                sheet = (
                    target.lstrip("/")
                    if target.startswith("/")
                    else posixpath.normpath("xl/" + target)
                )
                if not sheet.startswith("xl/worksheets/"):
                    raise ValidationError("Некорректный лист XLSX")
            strings = []
            if "xl/sharedStrings.xml" in names:
                root = _xml(archive.read("xl/sharedStrings.xml"))
                strings = [
                    "".join(n.text or "" for n in item.iter(f"{NS}t")) for item in root
                ]
            root = _xml(archive.read(sheet))
            result = []
            for row in root.findall(f"{NS}sheetData/{NS}row"):
                values = {}
                for cell in row.findall(f"{NS}c"):
                    if cell.find(f"{NS}f") is not None:
                        raise ValidationError(
                            "Формулы в XLSX не поддерживаются: используйте текстовые значения"
                        )
                    address = cell.get("r", "")
                    col = "".join(c for c in address if c.isalpha())
                    if col not in ("A", "B"):
                        continue
                    if cell.get("t") == "inlineStr":
                        value = "".join(n.text or "" for n in cell.iter(f"{NS}t"))
                    else:
                        value = cell.findtext(f"{NS}v", "")
                        if cell.get("t") == "s":
                            value = strings[int(value)]
                    values[col] = value
                result.append([values.get("A", ""), values.get("B", "")])
            return result
    except (
        zipfile.BadZipFile,
        KeyError,
        ValueError,
        IndexError,
        ET.ParseError,
        RuntimeError,
        OSError,
    ) as exc:
        raise ValidationError("Не удалось прочитать XLSX") from exc


def _rows_to_queries(rows):
    rows = [r for r in rows if r and any(str(v).strip() for v in r)]
    if not rows:
        raise ValidationError("Файл не содержит промптов")
    headers = [normalize_text(str(c)) for c in rows[0]]
    prompt_keys = {"промпт", "prompt", "запрос", "text"}
    group_keys = {"группа", "group"}
    index = next((i for i, h in enumerate(headers) if h in prompt_keys), None)
    group_index = next((i for i, h in enumerate(headers) if h in group_keys), None)
    if index is not None:
        rows = rows[1:]
    else:
        index, group_index = 0, 1
    queries = []
    for r in rows:
        text = str(r[index]).strip() if index < len(r) else ""
        group = (
            str(r[group_index]).strip()
            if group_index is not None and group_index < len(r)
            else ""
        )
        if not text and not group:
            continue
        queries.append({"text": text, "category": None, "group": group or None})
    if not queries:
        raise ValidationError("Файл не содержит промптов")
    # Use the same project validator for limits, uniqueness and group length.
    return normalize_project(
        {"brand": "Импорт", "site_url": "https://example.com", "queries": queries}
    )["queries"]


def parse_prompt_file(filename: str, data: bytes) -> list[dict]:
    if not data or len(data) > MAX_FILE_BYTES:
        raise ValidationError("Загрузите непустой файл размером до 256 КБ")
    suffix = PurePath(filename.lower()).suffix
    if suffix == ".xlsx":
        return _rows_to_queries(_xlsx(data))
    if suffix not in (".txt", ".csv"):
        raise ValidationError("Поддерживаются TXT, CSV и XLSX")
    try:
        text = data.decode("utf-8-sig")
    except UnicodeError as exc:
        raise ValidationError("Сохраните TXT/CSV в кодировке UTF-8") from exc
    if suffix == ".txt":
        rows = [[line] for line in text.splitlines()]
    else:
        try:
            dialect = csv.Sniffer().sniff(text[:4096], delimiters=",;\t")
        except csv.Error:
            dialect = csv.excel
        rows = list(csv.reader(io.StringIO(text), dialect))
    return _rows_to_queries(rows)

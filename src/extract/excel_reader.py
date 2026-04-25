from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from pathlib import Path
import re
from typing import Any
from xml.etree import ElementTree as ET
from zipfile import ZipFile


NS = {
    "main": "http://schemas.openxmlformats.org/spreadsheetml/2006/main",
    "rel": "http://schemas.openxmlformats.org/officeDocument/2006/relationships",
    "pkgrel": "http://schemas.openxmlformats.org/package/2006/relationships",
}

CELL_REF_RE = re.compile(r"([A-Z]+)(\d+)")


@dataclass(frozen=True)
class RawExcelRow:
    source_row_number: int
    values: dict[str, str]


@dataclass(frozen=True)
class ExcelRowsPayload:
    source_file_name: str
    source_sheet_name: str
    rows: list[RawExcelRow]


def _column_index(column_letters: str) -> int:
    total = 0
    for char in column_letters:
        total = total * 26 + (ord(char) - ord("A") + 1)
    return total - 1


def _read_shared_strings(archive: ZipFile) -> list[str]:
    try:
        xml_bytes = archive.read("xl/sharedStrings.xml")
    except KeyError:
        return []

    root = ET.fromstring(xml_bytes)
    strings: list[str] = []
    for item in root.findall("main:si", NS):
        parts = []
        texts = item.findall(".//main:t", NS)
        for text_node in texts:
            parts.append(text_node.text or "")
        strings.append("".join(parts))
    return strings


def _first_sheet_info(archive: ZipFile) -> tuple[str, str]:
    workbook_root = ET.fromstring(archive.read("xl/workbook.xml"))
    rels_root = ET.fromstring(archive.read("xl/_rels/workbook.xml.rels"))

    relationships = {
        rel.attrib["Id"]: rel.attrib["Target"]
        for rel in rels_root.findall("pkgrel:Relationship", NS)
    }
    first_sheet = workbook_root.find("main:sheets/main:sheet", NS)
    if first_sheet is None:
        raise ValueError("No worksheet found in workbook")

    sheet_name = first_sheet.attrib["name"]
    rel_id = first_sheet.attrib["{http://schemas.openxmlformats.org/officeDocument/2006/relationships}id"]
    target = relationships[rel_id]
    if not target.startswith("xl/"):
        target = f"xl/{target}"
    return sheet_name, target


def _cell_to_string(cell: ET.Element, shared_strings: list[str]) -> str:
    cell_type = cell.attrib.get("t")
    value_node = cell.find("main:v", NS)

    if cell_type == "inlineStr":
        return "".join(node.text or "" for node in cell.findall(".//main:t", NS)).strip()
    if cell_type == "s":
        if value_node is None or value_node.text is None:
            return ""
        return shared_strings[int(value_node.text)]
    if value_node is None or value_node.text is None:
        return ""

    raw_value = value_node.text.strip()
    try:
        decimal_value = Decimal(raw_value)
    except InvalidOperation:
        return raw_value

    if decimal_value == decimal_value.to_integral():
        return str(int(decimal_value))
    normalized = format(decimal_value.normalize(), "f")
    return normalized.rstrip("0").rstrip(".") if "." in normalized else normalized


def read_excel_rows(file_path: str) -> ExcelRowsPayload:
    workbook_path = Path(file_path)
    with ZipFile(workbook_path) as archive:
        shared_strings = _read_shared_strings(archive)
        sheet_name, sheet_path = _first_sheet_info(archive)
        sheet_root = ET.fromstring(archive.read(sheet_path))

    rows = sheet_root.findall("main:sheetData/main:row", NS)
    if not rows:
        raise ValueError("Worksheet has no rows")

    headers: dict[int, str] = {}
    result_rows: list[RawExcelRow] = []

    for row_index, row in enumerate(rows):
        current_values: dict[int, str] = {}
        for cell in row.findall("main:c", NS):
            ref = cell.attrib.get("r", "")
            match = CELL_REF_RE.fullmatch(ref)
            if not match:
                continue
            col_letters, _ = match.groups()
            current_values[_column_index(col_letters)] = _cell_to_string(cell, shared_strings)

        if row_index == 0:
            headers = {idx: value.strip() for idx, value in current_values.items() if value.strip()}
            continue

        mapped = {
            header: current_values.get(idx, "").strip()
            for idx, header in headers.items()
            if idx in range(0, 7)
        }
        required_keys = {
            "Course Name",
            "CRICOS",
            "IELTS Academic",
            "Commencing Semester",
            "Duration (Years)",
            "Tuition Fee ($AUD)",
        }
        if not any(mapped.values()):
            continue
        if not required_keys.issubset(mapped):
            missing = ", ".join(sorted(required_keys - set(mapped)))
            raise ValueError(f"Missing expected Excel columns: {missing}")

        if not mapped["Course Name"] or not mapped["CRICOS"]:
            continue

        result_rows.append(
            RawExcelRow(
                source_row_number=int(row.attrib.get("r", str(row_index + 1))),
                values=mapped,
            )
        )

    return ExcelRowsPayload(
        source_file_name=workbook_path.name,
        source_sheet_name=sheet_name,
        rows=result_rows,
    )


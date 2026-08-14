from __future__ import annotations

"""
OpenPyXL Sheet Helper Utilities.

Provides standard formatting methods for worksheets:
- Title blocks
- Header rows
- Data tables
- Summary cards
- Gridlines & Freeze Panes
"""

from typing import Any, List, Optional

from openpyxl.worksheet.worksheet import Worksheet

from backend.export.excel.styles import (
    ALIGN_CENTER,
    ALIGN_LEFT,
    ALIGN_RIGHT,
    BORDER_BOX,
    BORDER_HEADER,
    BORDER_TOTAL,
    FILL_CARD,
    FILL_HEADER,
    FILL_SUBHEADER,
    FONT_FORMULA,
    FONT_HEADER,
    FONT_INPUT,
    FONT_SECTION,
    FONT_SUBHEADER,
    FONT_TITLE,
    FONT_TOTAL,
)


import openpyxl.cell._writer as cw
import openpyxl.worksheet._writer as ww

CACHED_FORMULA_VALUES: dict[tuple[str, int, int], Any] = {}
_PATCHED = False


def _ensure_formula_writer_patched() -> None:
    global _PATCHED
    if _PATCHED:
        return

    orig_etree = cw.etree_write_cell
    orig_lxml = cw.lxml_write_cell

    def patched_etree(xf, worksheet, cell, styled=None):
        key = (worksheet.title, cell.row, cell.column)
        cached_val = CACHED_FORMULA_VALUES.get(key)
        if cell.data_type == 'f' and cached_val is not None:
            value, attributes = cw._set_attributes(cell, styled)
            el = cw.Element("c", attributes)
            formula = cw.SubElement(el, 'f', {})
            formula.text = value[1:] if isinstance(value, str) else str(value)
            v_elem = cw.SubElement(el, 'v')
            v_elem.text = cw.safe_string(cached_val)
            xf.write(el)
        else:
            orig_etree(xf, worksheet, cell, styled)

    def patched_lxml(xf, worksheet, cell, styled=False):
        key = (worksheet.title, cell.row, cell.column)
        cached_val = CACHED_FORMULA_VALUES.get(key)
        if cell.data_type == 'f' and cached_val is not None:
            value, attributes = cw._set_attributes(cell, styled)
            with xf.element('c', attributes):
                with xf.element('f'):
                    xf.write(value[1:] if isinstance(value, str) else str(value))
                with xf.element('v'):
                    xf.write(cw.safe_string(cached_val))
        else:
            orig_lxml(xf, worksheet, cell, styled)

    import openpyxl
    cw.write_cell = patched_lxml if openpyxl.LXML else patched_etree
    ww.write_cell = cw.write_cell
    _PATCHED = True


def register_formula_value(ws: Worksheet, row: int, col: int, cached_value: Any) -> None:
    """Register a precomputed numerical value for a formula cell (written to <v> XML tag)."""
    _ensure_formula_writer_patched()
    if cached_value is not None:
        CACHED_FORMULA_VALUES[(ws.title, row, col)] = cached_value


def write_formula_cell(
    ws: Worksheet,
    row: int,
    col: int,
    formula: str,
    cached_value: Optional[Any] = None,
    num_format: Optional[str] = None,
    font: Optional[Any] = None,
    border: Optional[Any] = None,
    alignment: Optional[Any] = None,
) -> Any:
    """Write an interactive Excel formula with optional precomputed cached value and formatting."""
    cell = ws.cell(row=row, column=col, value=formula)
    if cached_value is not None:
        register_formula_value(ws, row, col, cached_value)
    if num_format:
        cell.number_format = num_format
    if font:
        cell.font = font
    if border:
        cell.border = border
    if alignment:
        cell.alignment = alignment
    return cell


def apply_tab_defaults(ws: Worksheet, freeze_cell: str = "B5") -> None:
    """Apply standard sheet settings: show gridlines & set freeze pane."""
    ws.views.sheetView[0].showGridLines = True
    ws.freeze_panes = freeze_cell


def set_col_widths(ws: Worksheet, widths: dict[str, float]) -> None:
    """Set explicit column widths."""
    for col, width in widths.items():
        ws.column_dimensions[col].width = width


def write_title_block(ws: Worksheet, title: str, subtitle: str = "") -> None:
    """Write standard title block at row 1-2."""
    ws["A1"] = title
    ws["A1"].font = FONT_TITLE
    if subtitle:
        ws["A2"] = subtitle
        ws["A2"].font = FONT_SECTION


def write_table_header(
    ws: Worksheet,
    row: int,
    headers: List[str],
    start_col: int = 1,
) -> None:
    """Write a standard dark blue header row."""
    for idx, text in enumerate(headers):
        col = start_col + idx
        cell = ws.cell(row=row, column=col, value=text)
        cell.font = FONT_HEADER
        cell.fill = FILL_HEADER
        cell.border = BORDER_HEADER
        cell.alignment = ALIGN_CENTER if idx > 0 else ALIGN_LEFT


def write_table_row(
    ws: Worksheet,
    row: int,
    label: str,
    values: List[Any],
    num_format: str,
    start_col: int = 1,
    is_input: bool = False,
    is_total: bool = False,
) -> None:
    """Write a data row with proper font, alignment, and number formatting."""
    # Label column
    label_cell = ws.cell(row=row, column=start_col, value=label)
    label_cell.font = FONT_TOTAL if is_total else FONT_FORMULA
    label_cell.alignment = ALIGN_LEFT
    if is_total:
        label_cell.border = BORDER_TOTAL

    # Value columns
    for idx, val in enumerate(values):
        col = start_col + 1 + idx
        cell = ws.cell(row=row, column=col, value=val)
        cell.font = FONT_INPUT if is_input else (FONT_TOTAL if is_total else FONT_FORMULA)
        cell.number_format = num_format
        cell.alignment = ALIGN_RIGHT
        if is_total:
            cell.border = BORDER_TOTAL

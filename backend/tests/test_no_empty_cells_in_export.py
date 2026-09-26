"""No exported cell inside a populated table may be blank.

A blank in a model is a hole the reader has to interpret. It could mean "not
applicable", "not yet computed", or "this line was forgotten" — and the three
call for different actions, so a blank is a defect regardless of which was
meant. A value that is genuinely absent should say so in words.

The defect this pins: the EV bridge was a block of single-valued rows sharing
31_DCF with the five year-columns of the FCFF build, its labels merged across
those columns. Every bridge row therefore published a figure beside five blank
cells — seventy per workbook, on the tab whose output matters most. The bridge
moved to 36_EV_Bridge, where the table is the shape of the data.

The same sweep caught the peer-statistics block on 40_Trading_Comps, which
carried an empty gutter so its multiples would line up under the peer columns
they summarised. It now carries its own header naming each statistic.

Scope: every cell between a table's label column and its last populated cell,
in rows that belong to the table. Header rows and spacer rows are excluded —
a section title in column B is not a data row that owes five values.
"""

from __future__ import annotations

from openpyxl import Workbook

from backend.export.excel.render_val import EV_BRIDGE_ROWS

# The `exported` fixture builds and values a complete workbook once and shares
# it across the export test modules, so this sweep costs no extra build time.
from backend.tests.test_excel_recalculation_parity import exported  # noqa: F401


# Column B carries the row label on every generated tab, and column A is a
# narrow index gutter. Neither owes a value in a data row.
LABEL_COLUMNS = 2


def _is_blank(value) -> bool:
    return value is None or (isinstance(value, str) and value.strip() == "")


def _blanks_in_table_body(ws) -> list[tuple[str, str]]:
    """Blank cells inside the populated block of a sheet.

    Bounds the scan two ways so it finds real holes without demanding a value
    from every cell on the page:

      * a row belongs to a table when its label cell is populated and it has at
        least one populated cell to the right of the label;
      * within such a row, only the span up to that row's own last populated
        cell is checked, so genuinely unused trailing columns are not treated
        as missing data.
    """
    holes: list[tuple[str, str]] = []
    max_col = ws.max_column or 0

    for row in range(1, (ws.max_row or 0) + 1):
        label = ws.cell(row=row, column=LABEL_COLUMNS).value
        if _is_blank(label):
            continue  # title, spacer, or header band: not a data row

        populated = [
            col
            for col in range(LABEL_COLUMNS + 1, max_col + 1)
            if not _is_blank(ws.cell(row=row, column=col).value)
        ]
        if not populated:
            continue  # a label with nothing beside it is a section title

        last_col = max(populated)
        for col in range(LABEL_COLUMNS + 1, last_col + 1):
            cell = ws.cell(row=row, column=col)
            if _is_blank(cell.value):
                holes.append((f"{ws.title}!{cell.coordinate}", str(label)[:60]))
    return holes


def test_no_blank_cell_inside_any_exported_table(exported):
    """Every populated region of a real exported workbook carries a value."""
    _, _, wb_formulas = exported
    total: list[tuple[str, str]] = []
    for ws in wb_formulas.worksheets:
        total.extend(_blanks_in_table_body(ws))

    assert not total, (
        f"{len(total)} blank cell(s) inside exported table bodies. A blank has to "
        "mean one thing to a reader; publish the value or state that there is "
        "none. First offenders: "
        + "; ".join(f"{coord} (row '{label}')" for coord, label in total[:8])
    )


def test_ev_bridge_tab_has_no_blank_cells(exported):
    """The bridge is the tab whose blanks would be most costly to read past."""
    _, _, wb_formulas = exported
    ws = wb_formulas["36_EV_Bridge"]
    holes = _blanks_in_table_body(ws)
    assert not holes, f"36_EV_Bridge has blank cells: {holes}"


def test_bridge_lines_are_all_present_and_labelled(exported):
    """Every line in the published row map is actually written, with a basis.

    A row map is a promise that a line exists. If a line is added to the map and
    not rendered, every formula that references it resolves to an empty cell and
    the bridge silently loses a step.
    """
    _, _, wb_formulas = exported
    ws = wb_formulas["36_EV_Bridge"]
    for line, row in EV_BRIDGE_ROWS.items():
        assert not _is_blank(ws.cell(row=row, column=2).value), (
            f"bridge line {line!r} is mapped to row {row} but no label was written"
        )
        assert not _is_blank(ws.cell(row=row, column=3).value), (
            f"bridge line {line!r} has no value"
        )
        assert not _is_blank(ws.cell(row=row, column=4).value), (
            f"bridge line {line!r} has no stated basis. A net cash figure without "
            "the date and convention it was struck on is unreadable."
        )


def test_dcf_tab_is_a_single_shaped_table(exported):
    """31_DCF holds the year-by-year build and nothing else.

    The seventh "Valuation Summary" column used to carry the bridge, which made
    every bridge row show five blanks beside its value. The tab is now exactly
    a label column plus one column per forecast period.
    """
    _, _, wb_formulas = exported
    ws = wb_formulas["31_DCF"]
    from backend.models.spec.forecast import FORECAST_PERIODS

    expected = LABEL_COLUMNS + 1 + len(FORECAST_PERIODS)
    assert (ws.max_column or 0) <= expected, (
        f"31_DCF spans {ws.max_column} columns; expected at most {expected} "
        "(label plus one per forecast year). A summary column here means the "
        "single-valued bridge has been stacked onto the year-by-year table again."
    )

    headers = [
        ws.cell(row=5, column=LABEL_COLUMNS + 1 + i).value
        for i in range(len(FORECAST_PERIODS))
    ]
    assert headers == list(FORECAST_PERIODS), (
        f"31_DCF year headers are {headers}, expected {list(FORECAST_PERIODS)}"
    )


def test_peer_statistics_block_declares_the_statistics_it_reports(exported):
    """The statistics block's header names its own columns.

    It used to leave two cells empty so its multiples would sit under the peer
    columns they summarise, and then relied on the reader counting across from
    the peer table above to work out which column was which.
    """
    _, _, wb_formulas = exported
    ws = wb_formulas["40_Trading_Comps"]

    stat_row = None
    for row in range(1, (ws.max_row or 0) + 1):
        if str(ws.cell(row=row, column=2).value or "").startswith("Statistic"):
            stat_row = row
            break
    assert stat_row is not None, "no peer statistics block found on 40_Trading_Comps"

    # Every column from the label to the last populated header cell is named.
    populated = [
        col
        for col in range(LABEL_COLUMNS + 1, (ws.max_column or 0) + 1)
        if not _is_blank(ws.cell(row=stat_row, column=col).value)
    ]
    assert populated, "the statistics header names no columns"
    for col in range(LABEL_COLUMNS + 1, max(populated) + 1):
        assert not _is_blank(ws.cell(row=stat_row, column=col).value), (
            f"40_Trading_Comps statistics header {ws.cell(row=stat_row, column=col).coordinate} "
            "is unnamed, so the figure under it cannot be identified"
        )

from __future__ import annotations

from pathlib import Path

from backend.data.errors import NoFinancialsAvailable
from backend.data.store import query_canonical_datapoints, query_datapoints
from backend.models.statements.historical_model import HistoricalModel, build_historical_model
from backend.normalization.taxonomy.models import CanonicalDatapoint

HERE = Path(__file__).resolve().parent
WORKSPACE_ROOT = HERE.parent.parent.parent
DB_PATH = WORKSPACE_ROOT / "backend" / "data" / "valence.db"
COMPANY_ID = "infy_infy"

# How many historical years the model is built on. This is a COUNT, not a list
# of period labels.
#
# Callers used to pass ["FY24","FY25","FY26"] and the assembler honoured those
# labels literally, so a filer whose fiscal calendar differed matched only part
# of the window. A September year end against a December one left the company
# with a single historical year, and a growth rate computed from one year is
# zero. Passing a count and letting the assembler choose the most recent
# reported periods works for every calendar.
DEFAULT_HIST_PERIOD_COUNT = 3

# Retained for callers that import the constant; the labels are no longer
# authoritative, only the length is read.
DEFAULT_HIST_PERIODS = ["FY24", "FY25", "FY26"]

# A period only counts as a historical year if the income statement actually
# reports it. Without this test a period holding a handful of balance-sheet
# lines — a stub left by a differently-dated feed — is treated as the most
# recent actual, and the entire forecast is then grown from a year with no
# revenue in it.
INCOME_STATEMENT_ANCHOR = "canonical.is.revenue"


def select_complete_periods(
    count: int,
    canonical_dps: list[CanonicalDatapoint],
) -> list[str]:
    """The most recent `count` periods the income statement actually reports.

    A fixed window of period LABELS is the wrong selector. A filer whose
    fiscal calendar differs from the default matched only part of the window and
    was left with too few years to compute a growth rate from. Selecting by what
    the income statement reports, most recent last, works for every calendar and
    cannot produce a period with no revenue in it.
    """
    available: dict[str, set[str]] = {}
    for dp in canonical_dps:
        available.setdefault(dp.canonical_key, set()).add(dp.period_label)

    anchors = available.get(INCOME_STATEMENT_ANCHOR, set())
    if not anchors:
        return []
    return sorted(anchors, key=_period_sort_key)[-max(1, count):]


def _period_sort_key(label: str) -> tuple[int, str]:
    """Order period labels chronologically by the year they name."""
    digits = "".join(ch for ch in label if ch.isdigit())
    return (int(digits) if digits else 0, label)


def run(target_periods: list[str] | None = None, company_id: str = "infy_infy") -> HistoricalModel:
    """Run Historical Model Assembly for a target company.

    `target_periods` is read for its LENGTH only: the caller is asking for that
    many historical years, and the assembler decides which years those are from
    what the filings actually report.
    """
    if not DB_PATH.exists():
        raise FileNotFoundError(f"Database not found at {DB_PATH}. Run taxonomy normalization pipeline first.")

    canonical_dps = query_canonical_datapoints(DB_PATH, company_id)
    if not canonical_dps:
        # The same user-facing situation as no revenue line below: nothing behind
        # this company. Twelve lines further down this raised a plain ValueError
        # and answered 500, so the two identical conditions were answered
        # differently depending on which one was reached first.
        raise NoFinancialsAvailable(
            f"No financial statements could be sourced for {company_id} "
            f"(ingestion produced no canonical datapoints)"
        )

    raw_dps = query_datapoints(DB_PATH, company_id)

    wanted = len(target_periods) if target_periods else DEFAULT_HIST_PERIOD_COUNT
    resolved = select_complete_periods(wanted, canonical_dps)
    if not resolved:
        # Statements were ingested but carry no revenue line, so there is nothing
        # to forecast from. That is the same user-facing situation as a ticker
        # with no statements at all, and it was answering as a 500 because it was
        # an ordinary ValueError. It is a normal outcome for a foreign ordinary
        # or a recent listing, not a fault, so it gets the same answer.
        raise NoFinancialsAvailable(
            f"No income statement reported for company '{company_id}' — the ingested "
            "filings carry no revenue line, so no model can be built from them."
        )

    model = build_historical_model(canonical_dps, target_periods=resolved, raw_datapoints=raw_dps)

    print(
        f"Historical 3-Statement Model Assembled:\n"
        f"  - Company ID      : {model.company_id}\n"
        f"  - Historical Years: {model.periods}\n"
        f"  - IS Line Items   : {len(model.income_statement.line_items)}\n"
        f"  - BS Line Items   : {len(model.balance_sheet.line_items)}\n"
        f"  - CF Line Items   : {len(model.cash_flow_statement.line_items)}\n"
        f"  - Ratio Series    : {len(model.ratios.ratio_series)}"
    )

    return model


if __name__ == "__main__":
    run()

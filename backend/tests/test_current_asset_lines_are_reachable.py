"""A balance-sheet line is only real if it is reachable from all three lists.

The defect this guards against is not a wrong number. It is a right number that is
never read. Infosys' current income tax assets (1 / 767 / 348) and current derivative
instruments (12 / 10 / 23) were ingested, mapped to a canonical key, and written to
`canonical_datapoints` -- correctly, and to the rupee. The statement contract had no
row for them, so the snapshot builder dropped them on the way out. The workbook
printed a current-asset column that fell 385 short of the filer's own subtotal in
FY23 and 353 long in FY24, while the database held the missing figures and no gate
looked there.

Three places must agree, and nothing enforced it:

  1. `BS_LINE_ITEM_CONFIG` in models/statements -- the whitelist the snapshot is built
     from. A canonical key absent here does not reach the model at all.
  2. the renderer's row list -- what a reader sees above the subtotal.
  3. `CURRENT_ASSET_LINES` in validation/accounting_checks -- what the reconciliation
     sums. A line printed but not summed reconciles against nothing; a line summed
     but not printed reconciles against a column the reader cannot see.

So a line added to one and not the others is not a partial feature, it is a silent
contradiction, and each of the three omissions fails differently: dropped, invisible,
or unverified. These tests make any one of them fail loudly.
"""

import ast
import json
import pathlib
import re
import sys

import pytest

REPO = pathlib.Path(__file__).resolve().parents[2]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

from backend.data.ingestion.ifrs_tags import IFRS_ALTERNATIVES  # noqa: E402
from backend.data.ingestion.sec_edgar import US_GAAP_TAG_MAP  # noqa: E402
from backend.models.statements.balance_sheet import BS_LINE_ITEM_CONFIG  # noqa: E402
from backend.normalization.taxonomy.registry import get_canonical_mapping  # noqa: E402
from backend.validation.accounting_checks import CURRENT_ASSET_LINES  # noqa: E402

CACHE = REPO / "backend" / "data" / "cache"

# The two captions Infosys' 20-F prints below the prepayments line and the engine
# originally had no line for. Both are mapped to exactly one IFRS element, because a
# tag list holds ALTERNATIVE NAMES FOR ONE CAPTION: the fetcher takes the first
# element with data for the target periods and stops. Filed under a single shared
# label, the tax assets arrived and the derivatives were unreachable, and the line
# read 348 where the face said 371 with nothing reporting the loss.
NEW_LABELS = ("Current income tax assets", "Current derivative financial assets")
NEW_KEYS = (
    "canonical.bs.current_income_tax_assets",
    "canonical.bs.derivative_financial_assets_current",
)
SUBTOTAL = "canonical.bs.total_current_assets"


def _renderer_current_asset_rows() -> list:
    """The keys `render_historical_balance_sheet` prints above the current subtotal.

    Read out of the source with `ast` rather than by refactoring the list to module
    scope: the guard should not require changing working code to be able to check it.
    """
    path = REPO / "backend" / "export" / "excel" / "render_hist.py"
    tree = ast.parse(path.read_text(encoding="utf-8"))
    fn = next(
        n
        for n in ast.walk(tree)
        if isinstance(n, ast.FunctionDef)
        and n.name == "render_historical_balance_sheet"
    )
    assign = next(
        n
        for n in ast.walk(fn)
        if isinstance(n, ast.Assign)
        and any(getattr(t, "id", None) == "bs_items" for t in n.targets)
    )
    rows = []
    for elt in ast.walk(assign.value):
        if (
            isinstance(elt, ast.Tuple)
            and elt.elts
            and isinstance(elt.elts[0], ast.Constant)
            and isinstance(elt.elts[0].value, str)
        ):
            rows.append(elt.elts[0].value)
    return rows


RENDERED = _renderer_current_asset_rows()
CONTRACT = tuple(k for k, _l, _s in BS_LINE_ITEM_CONFIG)


def test_renderer_spec_was_found():
    """If this fails the AST read drifted and every assertion below is vacuous."""
    assert RENDERED, "could not read bs_items out of render_hist.py"
    assert SUBTOTAL in RENDERED


def test_current_asset_lines_are_printed_by_the_renderer():
    """Everything the reconciliation sums must be a row the reader can see."""
    rendered = set(RENDERED)
    missing = [k for k in CURRENT_ASSET_LINES if k not in rendered]
    assert not missing, (
        "CURRENT_ASSET_LINES sums lines the workbook does not print: "
        f"{missing}. The check would reconcile against a column no reader can see."
    )


def test_current_asset_lines_reach_the_snapshot():
    """Everything the reconciliation sums must survive the snapshot whitelist."""
    whitelisted = set(CONTRACT)
    missing = [k for k in CURRENT_ASSET_LINES if k not in whitelisted]
    assert not missing, (
        "CURRENT_ASSET_LINES sums canonical keys the statement contract does not "
        f"whitelist: {missing}. They are ingested, mapped and written to "
        "canonical_datapoints, then dropped before the model -- a correct number that "
        "is never read."
    )


def test_new_captions_in_all_three_lists():
    for key in NEW_KEYS:
        assert key in CURRENT_ASSET_LINES, f"{key} not summed by the check"
        assert key in RENDERED, f"{key} not printed by the renderer"
        assert key in CONTRACT, f"{key} not whitelisted by the statement contract"


def test_new_captions_map_to_distinct_canonical_keys():
    keys = {label: get_canonical_mapping(label) for label in NEW_LABELS}
    assert keys["Current income tax assets"] == (NEW_KEYS[0], "bs")
    assert keys["Current derivative financial assets"] == (NEW_KEYS[1], "bs")
    assert keys["Current income tax assets"][0] != keys["Current derivative financial assets"][0], (
        "the two captions share a canonical key, so one overwrites the other and the "
        "column silently loses a line the filer prints"
    )


def test_current_income_tax_assets_is_separate_from_the_noncurrent_key():
    """The contract already carries a non-current income-tax-assets key.

    Infosys prints the caption twice -- 348 current and 190 non-current at FY25. One
    key cannot hold both, which is why the current side needed its own.
    """
    assert "canonical.bs.income_tax_assets" in CONTRACT
    assert NEW_KEYS[0] not in ("canonical.bs.income_tax_assets",)
    sections = {k: s for k, _l, s in BS_LINE_ITEM_CONFIG}
    assert sections["canonical.bs.income_tax_assets"] == "non_current_assets"
    assert sections[NEW_KEYS[0]] == "current_assets"


def test_each_new_caption_names_exactly_one_element():
    """One caption, one element.

    `sec_edgar` selects the first element holding data for the target periods and
    breaks. A second element under the same label is unreachable, and the shortfall is
    indistinguishable from a filer that simply reports less.
    """
    for label in NEW_LABELS:
        tags = list(IFRS_ALTERNATIVES.get(label, ()))
        assert len(tags) == 1, (
            f"{label!r} names {len(tags)} elements {tags}. Only the first is ever "
            "read; the rest are dead. Split the caption or drop the unreachable names."
        )


def test_ifrs_labels_are_all_known_to_the_us_gaap_map():
    """The registry joins on the METRIC LABEL, not the tag.

    A label missing from `US_GAAP_TAG_MAP` is asserted against at import time, but the
    assertion only proves the vocabulary is shared -- not that the label resolves.
    """
    known = {m for m, _t, _s in US_GAAP_TAG_MAP}
    for label in NEW_LABELS:
        assert label in known, f"{label!r} absent from US_GAAP_TAG_MAP"
        assert get_canonical_mapping(label) is not None


# --- the shipped model actually reconciles --------------------------------------

def _infy_snapshot() -> dict:
    path = CACHE / "infy_us.json"
    if not path.exists():
        pytest.skip("infy_us snapshot not built")
    return json.loads(path.read_text(encoding="utf-8"))


def test_infy_current_asset_lines_are_populated_in_the_snapshot():
    """The value must survive all the way to the model, not just the database."""
    d = _infy_snapshot()
    held = {
        (e["period_label"], e["canonical_key"]): e["value"]
        for e in d["model"]["historicals"]["line_items"]
    }
    periods = d["model"]["historicals"]["periods"]
    assert periods, "snapshot carries no historical periods"
    for key in NEW_KEYS:
        for p in periods:
            assert (p, key) in held, (
                f"{key} is absent from the infy_us snapshot for {p}. The datapoint is "
                "canonicalised correctly and then dropped before the model."
            )


def test_infy_current_assets_reconcile_to_the_filing_with_no_remainder():
    """Current assets must reach the filer's own subtotal, not merely approach it.

    The filed subtotals are read off the face of each 20-F (EDGAR Financial Report
    R2.htm), which is an independent source from the engine. Before the two captions
    above had rows, the engine itemised 9,011 / 10,369 / 11,320 against them.
    """
    filed = {"FY23": 8626, "FY24": 10722, "FY25": 11359}
    d = _infy_snapshot()
    held = {
        (e["period_label"], e["canonical_key"]): e["value"]
        for e in d["model"]["historicals"]["line_items"]
    }
    for period, expected in filed.items():
        itemised = sum(
            float(held[(period, k)])
            for k in CURRENT_ASSET_LINES
            if isinstance(held.get((period, k)), (int, float))
        )
        gap = itemised - expected
        assert abs(gap) <= 0.5, (
            f"{period}: itemised current assets {itemised:,.0f} against a filed "
            f"subtotal of {expected:,.0f}, gap {gap:+,.0f}"
        )


def test_infy_trade_receivables_are_not_filed_as_vendor_non_trade():
    """A caption the filer does not print must not carry a number.

    Tax and interest receivables were once filed here, on the reasoning that they are
    receivables that are not trade receivables. The 20-F prints no such line; the
    elements behind it (332 and 99 at FY25) are levels of the filer's own "Income tax
    assets" of 348. The result was 398 / 424 / 332 on a caption that does not exist,
    and FY23 missed its subtotal by +385.
    """
    d = _infy_snapshot()
    for e in d["model"]["historicals"]["line_items"]:
        if e["canonical_key"] == "canonical.bs.vendor_non_trade_receivables":
            assert e["canonical_key"] != "canonical.bs.current_income_tax_assets", (
                "tax assets and vendor non-trade receivables cannot be the same line"
            )
    held = {
        (e["period_label"], e["canonical_key"]): e["value"]
        for e in d["model"]["historicals"]["line_items"]
    }
    face_tax = {"FY23": 1, "FY24": 767, "FY25": 348}
    for period, expected in face_tax.items():
        got = held.get((period, "canonical.bs.vendor_non_trade_receivables"))
        assert got is None, (
            f"{period}: vendor_non_trade_receivables is {got:,.0f}, but Infosys' 20-F "
            "prints no vendor non-trade receivables caption. A number on a line the "
            "filing does not contain is not a rounding question."
        )
        assert held.get((period, "canonical.bs.current_income_tax_assets")) == expected


def test_no_current_asset_line_is_double_counted():
    """`CurrentPrepaidExpenses` is a MEMBER of `CurrentPrepaymentsAndOtherCurrentAssets`.

    Infosys reports the aggregate as 1,519 and the member as 360. Holding both counts
    360 twice. The same trap made Armstrong's identified current assets exceed its own
    filed subtotal and get clamped into silence.
    """
    src = (REPO / "backend" / "data" / "ingestion" / "ifrs_tags.py").read_text(
        encoding="utf-8"
    )
    prepayments = re.search(
        r'"Prepayments and other assets": \((.*?)\),\n', src, re.S
    )
    assert prepayments, "could not read the prepayments entry out of ifrs_tags.py"
    body = prepayments.group(1)
    # Matched as a LISTED ELEMENT, not as a mention. The entry's own comment names
    # CurrentPrepaidExpenses to explain why it is absent, and a substring test would
    # read that explanation as the double-count it warns against.
    listed = {
        m.group(1) for m in re.finditer(r'^\s*"([A-Za-z0-9_]+)",?\s*$', body, re.M)
    }
    assert "CurrentPrepaymentsAndOtherCurrentAssets" in listed
    assert "CurrentPrepaidExpenses" not in listed, (
        "CurrentPrepaidExpenses is a member of the aggregate, not a sibling. Listing "
        "both double-counts the smaller inside the larger."
    )

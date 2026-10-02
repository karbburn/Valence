"""The unit a line is published in must be the unit the datapoint was filed in.

`assemble_income_statement` and `assemble_cash_flow` each opened a line with

    curr = "INR"
    un = "crores"

and overwrote those only inside `if _rule:` -- reached solely for a DERIVED datapoint.
Every REPORTED line therefore kept the default, and 616 line items across 11 of the 23
shipped models shipped labelled INR in crores while carrying USD millions. The model
metadata on the same object said `USD/millions`, so the file contradicted itself and
nothing compared the two: every other check in the suite reads `value`, and not one
read the unit.

A crore is ten million, so a consumer trusting the label read those lines 10x wrong. It
also produced a false diagnosis that `infy_us` was mixing units inside one model. The
figures were consistent throughout; the label was a lie, and the lie was believed.

Two things are guarded. The structural one asserts the assignment lives inside the
`if dp is not None` block, so the defect cannot return in the same shape. The
behavioural one drives `check_units_agree_within_a_model` directly, so the gate is
known to fail when it should.
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

from backend.data.snapshot_io import read_model_snapshot  # noqa: E402
from backend.models.spec.model_specification import ModelSpecification  # noqa: E402
from backend.models.statements.selector import dominant_units  # noqa: E402
from backend.validation.accounting_checks import (  # noqa: E402
    check_units_agree_within_a_model,
)

CACHE = REPO / "backend" / "data" / "cache"

# The two files that mislabelled lines; the balance sheet was already correct.
ASSEMBLERS = (
    "backend/models/statements/income_statement.py",
    "backend/models/statements/cash_flow.py",
)
ALL_ASSEMBLERS = ASSEMBLERS + ("backend/models/statements/balance_sheet.py",)


def _source(rel: str) -> str:
    return (REPO / rel).read_text(encoding="utf-8")


def test_no_assembler_hardcodes_a_currency():
    """A hardcoded INR/crores default is a US filer waiting to be mislabelled."""
    for rel in ALL_ASSEMBLERS:
        src = _source(rel)
        assert not re.search(r'^\s*un\s*=\s*"crores"', src, re.M), (
            f"{rel} still defaults a line's unit to crores. Read it from the datapoint, "
            "or from dominant_units(), which is what the filers' own data says."
        )
        assert not re.search(r'^\s*curr\s*=\s*"INR"', src, re.M), (
            f"{rel} still defaults a line's currency to INR."
        )


def test_unit_is_read_inside_the_datapoint_guard():
    """`curr = dp.currency` must sit inside `if dp is not None`.

    This is the exact shape of the defect: outside the guard a `dp` of None would
    raise, and inside a narrower `if _rule:` it silently applies only to derived rows.
    The two look nothing alike and fail in opposite directions, so this reads the
    nesting rather than the text.
    """
    for rel in ASSEMBLERS:
        tree = ast.parse(_source(rel))
        guarded = False
        for node in ast.walk(tree):
            if not isinstance(node, ast.If):
                continue
            if "dp is not None" not in ast.unparse(node.test):
                continue
            for inner in ast.walk(node):
                if not isinstance(inner, (ast.Assign, ast.AnnAssign)):
                    continue
                targets = (
                    [inner.target] if isinstance(inner, ast.AnnAssign) else inner.targets
                )
                for t in targets:
                    if isinstance(t, ast.Name) and t.id in ("curr", "un"):
                        guarded = True
        assert guarded, (
            f"{rel} never reads currency/units from a datapoint inside `if dp is not "
            "None`. Outside the guard a None dp raises; inside a narrower branch it "
            "applies only to derived rows, which is the defect this file is named for."
        )


def test_dominant_units_is_stable_and_ignores_empty():
    assert dominant_units([]) == ("", "")

    class DP:
        def __init__(self, c, u):
            self.currency, self.units = c, u

    # A genuine minority does not flip the answer.
    assert dominant_units([DP("USD", "millions")] * 9 + [DP("INR", "crores")]) == (
        "USD", "millions"
    )
    # A tie must resolve the same way twice, not by dict order.
    tie = [DP("USD", "millions"), DP("INR", "crores")]
    assert dominant_units(tie) == dominant_units(list(reversed(tie)))
    # Rows with no unit recorded are not votes.
    assert dominant_units([DP("", ""), DP("USD", "millions")]) == ("USD", "millions")


def _spec_with_units(declared, line_units, key="canonical.is.revenue"):
    """A minimal spec whose historicals carry chosen units, for driving the check."""
    return ModelSpecification.model_validate(
        {
            "metadata": {
                "company_id": "t", "ticker": "T", "name": "T", "market": "us",
                "currency": declared[0], "units": declared[1],
                "fiscal_year_end": "December 31", "shares_outstanding": 100.0,
            },
            "historicals": {
                "periods": ["FY24"],
                "line_items": [
                    {
                        "canonical_key": key, "period_label": "FY24",
                        "period_end_date": "2024-12-31", "value": 100.0,
                        "currency": c, "units": u, "status": "reported",
                        "source_datapoint_ids": [],
                    }
                    for c, u in line_units
                ],
            },
            "forecast": {"periods": [], "line_items": []},
        }
    )


def test_check_passes_when_units_agree():
    r = check_units_agree_within_a_model(
        _spec_with_units(("USD", "millions"), [("USD", "millions")])
    )
    assert r.passed, r.detail


def test_check_fails_on_a_mislabelled_line():
    r = check_units_agree_within_a_model(
        _spec_with_units(("USD", "millions"), [("INR", "crores")])
    )
    assert not r.passed, "a crores line in a millions model must fail"
    assert "INR" in (r.detail or "") and "millions" in (r.detail or "")
    assert r.implicated_canonical_keys == ["canonical.is.revenue"]


def test_check_fails_when_one_model_holds_both():
    r = check_units_agree_within_a_model(
        _spec_with_units(
            ("USD", "millions"), [("USD", "millions"), ("INR", "crores")]
        )
    )
    assert not r.passed, "two units inside one model is the hazard, and must fail"


def test_check_does_not_invent_a_requirement():
    """No declared unit means nothing to contradict -- not a failure."""
    r = check_units_agree_within_a_model(
        _spec_with_units(("", ""), [("INR", "crores")])
    )
    assert r.passed
    assert "no currency/units" in (r.detail or "")


def test_per_share_lines_are_exempt():
    """'millions' is not the unit of an EPS, so requiring one is the same error."""
    r = check_units_agree_within_a_model(
        _spec_with_units(
            ("USD", "millions"),
            [("USD", "millions"), ("INR", "crores")],
            key="canonical.is.eps_basic",
        )
    )
    assert r.passed, r.detail


@pytest.mark.parametrize(
    "path", sorted(p for p in CACHE.glob("*.json") if p.stem != "market_data_cache")
)
def test_every_shipped_model_agrees_with_its_own_units(path):
    spec = ModelSpecification.model_validate(
        json.loads(read_model_snapshot(str(path)))["model"]
    )
    r = check_units_agree_within_a_model(spec)
    assert r.passed, f"{path.stem}: {r.detail}"

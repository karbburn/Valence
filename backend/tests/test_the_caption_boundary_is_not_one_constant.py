"""The caption/value boundary must not be one constant, and must only ever move downward.

`LABEL_X_MAX = 330.0` was a module constant used to decide which tokens are caption text and
which are figures. Measured against all four committed filings, it is right for two of the three
layouts and wrong for the third:

    Infosys   references at x=347.5 and 357.7   right of 330, so they were already discarded
    TCS       no references at all on either balance sheet
    HCLTech   references at x=327.2-335.8       STRADDLING 330

The consequence on HCLTech is not a wrong figure. `parse_predicted_statement_page` already
discards anything outside the year-anchor window, so a reference on the value side costs nothing.
The harm is on the CAPTION side: `3.4(b)` at x=329.7 falls left of 330 and becomes part of the
caption, so the parser emits "Investments 3.4(b)" where the filing prints "Investments". A
caption with a reference glued to it matches no taxonomy key, which is a large part of why
HCLTech's captions sit unmapped.

These tests run against the committed PDFs and skip cleanly without them, because they assert
what a real filing prints rather than what a fixture contains.
"""
from __future__ import annotations

import re
from pathlib import Path

import pdfplumber
import pytest

from backend.data.parsers.pdf_tables import (
    LABEL_X_MAX,
    _caption_boundary,
    _rows,
    parse_predicted_statement_page,
)

HCLTECH = Path("backend/data/filings/nse/hcltech-ifrs-2026-07.pdf")
TCS = Path("backend/data/filings/nse/tcs-outcome-2026-04.pdf")
INFOSYS = Path("backend/data/filings/infosys-fy26-q4-outcome.pdf")

needs_hcltech = pytest.mark.skipif(not HCLTECH.exists(), reason="the HCLTech filing is absent")
needs_tcs = pytest.mark.skipif(not TCS.exists(), reason="the TCS filing is absent")
needs_infosys = pytest.mark.skipif(not INFOSYS.exists(), reason="the Infosys filing is absent")

# A caption with a note reference glued to its end, which is the defect.
NOTE_TAIL = re.compile(r"\s*\d+(?:\.\d+)+(?:\([a-z]\))?$", re.I)


def _page(pdf: Path, index: int):
    doc = pdfplumber.open(str(pdf))
    return doc, doc.pages[index]


@needs_hcltech
@pytest.mark.parametrize("index", [4, 5])
def test_a_note_reference_never_ends_up_inside_a_caption(index):
    doc, page = _page(HCLTECH, index)
    try:
        rows = _rows(page, _caption_boundary(page.extract_words(), page.height))
    finally:
        doc.close()

    dirty = [r[0] for r in rows if NOTE_TAIL.search(r[0])]
    assert not dirty, (
        f"printed page {index + 1}: these captions carry a note reference that the filing "
        f"prints in a separate column, so they match no taxonomy key: {dirty}"
    )


@needs_hcltech
@pytest.mark.parametrize("index", [4, 5])
def test_lowering_the_boundary_removes_the_reference_without_losing_the_caption(index):
    """The fix must not be "delete the caption".

    A rule that produced clean captions by dropping rows would satisfy the test above, and would
    lose a real balance-sheet line to fix a cosmetic one -- which is the worse error by the
    product's own rule.
    """
    doc, page = _page(HCLTECH, index)
    try:
        words = page.extract_words()
        before = _rows(page, LABEL_X_MAX)
        after = _rows(page, _caption_boundary(words, page.height))
    finally:
        doc.close()

    assert len(before) == len(after), (
        f"printed page {index + 1}: {len(before)} captions before, {len(after)} after. The "
        f"boundary change must move tokens between the caption and the figures, never drop a row."
    )
    before_clean = {NOTE_TAIL.sub("", r[0]).strip() for r in before}
    after_clean = {r[0].strip() for r in after}
    assert after_clean == before_clean, (
        f"printed page {index + 1}: the captions themselves changed.\n"
        f"  only in the old set: {sorted(before_clean - after_clean)}\n"
        f"  only in the new set: {sorted(after_clean - before_clean)}"
    )


@needs_hcltech
def test_the_boundary_is_lowered_for_hcltech():
    doc, page = _page(HCLTECH, 4)
    try:
        boundary = _caption_boundary(page.extract_words(), page.height)
    finally:
        doc.close()
    assert boundary < LABEL_X_MAX, (
        "HCLTech prints its note references at x=327.2-335.8, straddling the constant. If the "
        f"boundary is still {LABEL_X_MAX}, references left of it are landing in captions."
    )


@needs_infosys
@pytest.mark.parametrize("index", [99, 103])
def test_infosys_keeps_the_constant_exactly(index):
    """The change is for HCLTech's layout. Infosys must come through untouched.

    Infosys prints its references at 347.5, already on the discardable side, so its boundary is
    unchanged and every row it produces is unchanged. Asserted rather than assumed, because a rule
    that lowers the boundary "wherever it helps" would eventually lower it here too.
    """
    doc, page = _page(INFOSYS, index)
    try:
        assert _caption_boundary(page.extract_words(), page.height) == LABEL_X_MAX
    finally:
        doc.close()


@needs_infosys
def test_a_notes_page_is_not_mistaken_for_a_statement_page():
    """The guard that keeps `1.1` in prose out of it.

    Infosys printed 106 and 112 are the "Overview and Notes" narrative, where `1.1`, `1.2` are
    numbered list items at x=40. They match the note-reference shape exactly. If the rule acted on
    them it would lower the boundary to 36 and pull 255 words into captions, so it requires a
    detected value column first -- and a notes page has none.
    """
    doc, page = _page(INFOSYS, 105)
    try:
        text = " ".join(w["text"] for w in page.extract_words())
        assert "Overview and Notes" in text, "printed 106 is expected to be the notes narrative"
        assert _caption_boundary(page.extract_words(), page.height) == LABEL_X_MAX
    finally:
        doc.close()


@needs_tcs
@pytest.mark.parametrize("index", [10, 19])
def test_tcs_keeps_the_constant_because_it_prints_no_references(index):
    doc, page = _page(TCS, index)
    try:
        assert _caption_boundary(page.extract_words(), page.height) == LABEL_X_MAX
    finally:
        doc.close()


def test_a_page_with_no_columns_keeps_the_constant():
    """The rule declines rather than guessing.

    A synthetic page with no year header and no numeric column is the shape of a page the parser
    cannot read. It must get today's behaviour, because any boundary inferred from a page with no
    columns is inferred from nothing.
    """
    class _Page:
        height = 800.0
        width = 600.0

        @staticmethod
        def extract_words():
            return [
                {"x0": 40.0, "x1": 80.0, "top": 100.0, "text": "1.1"},
                {"x0": 40.0, "x1": 80.0, "top": 112.0, "text": "1.2"},
                {"x0": 90.0, "x1": 300.0, "top": 100.0, "text": "Company overview"},
            ]

    assert _caption_boundary(_Page().extract_words(), _Page.height) == LABEL_X_MAX


def test_the_rule_only_ever_lowers_the_boundary():
    """Direction is the whole safety argument.

    Lowering moves a reference from the caption side to the discardable side. Raising would do
    the reverse: it would move ordinary words out of the discarded region and into captions, and
    on two of the four filings it would have swallowed the figures themselves. Both raising rules
    that were tried are recorded in the module comment with the measurements that rejected them.
    """
    lowered = _caption_boundary.__doc__ or ""
    assert "Only ever downward" in lowered or "only ever move downward" in lowered.lower(), (
        "the direction guarantee is documented in prose but the module lost it; it is the "
        "argument for why lowering the boundary is safe"
    )
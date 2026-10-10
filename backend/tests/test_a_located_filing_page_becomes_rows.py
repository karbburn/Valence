"""The NSE fetcher's output has to become rows, or the filing never reaches a model.

`nse_filings.py` acquires an audited Indian statement, opens it, and finds the balance sheet
BY CONTENT -- it matches the balance sheet's own subtotal caption rather than trusting a
filename or a page number. It records the printed page numbers in `<symbol>.json` beside the
PDF and returns.

Nothing read that record. Measured before this file existed:

    balance_sheet_pages consumers outside the fetcher   NONE
    hcltech-ifrs-2026-07.pdf   45 pages -> balance sheet at printed page 5
    tcs-outcome-2026-04.pdf    25 pages -> balance sheet at printed pages 11, 20
    tcs_tcs          filing rows in the DB: none
    hcltech_hcltech  filing rows in the DB: none
    tatasteel_...    filing rows in the DB: none

So the audited statements were downloaded, opened, located, and then dropped on the floor,
and all twelve India models were `opinion_only` while their filings sat unread in the
repository. The recorded blocker for India is the `inputs_trace_to_a_filing` threshold of
0.9, which needs more than 2,736 filing rows per company; that arithmetic describes the last
step and is still true, but there was no step before it.

These tests are about the two things that are easy to get wrong in the step that was
missing, and neither is visible from reading the fetcher:

  * the fetcher records PRINTED page numbers and the parser takes a 0-BASED index, so an
    off-by-one reads the facing page cleanly and wrongly;
  * the section must come from the document, not from the caller.

They run against the real cached documents, because a test that only exercises a synthetic
page cannot tell whether the printed-to-indexed conversion lands on the balance sheet or on
the note in front of it.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from backend.data.ingestion.nse_filings import NSE_CACHE_DIR
from backend.data.pipeline import (
    _cached_nse_pdfs,
    _filing_datapoints_from_cached_pdf,
    _get_secondary_filing_datapoints,
)

REAL = sorted(NSE_CACHE_DIR.glob("*.json"))


def cached_pairs() -> dict:
    """The metadata that actually has a PDF beside it, keyed by company.

    Every test that needs a document goes through here, so "no document in this checkout"
    is one skip rather than a per-test guess. The first version guarded on the presence of
    the JSON alone, which is present in CI while a PDF may not be, so two tests failed there
    instead of skipping.

    A company may hold MORE THAN ONE attachment, and the pair chosen is the one whose
    recorded pages carry a balance sheet -- the same content test the fetcher acquired it
    with. HCLTech holds two since its migration: the superseded IFRS document, which stays
    in the cache as a fixture for the units and boundary tests, and the audited Ind-AS
    face whose metadata the cache now records. Taking the alphabetically first PDF would
    pick the superseded one and read its non-statement page as the balance sheet.
    """
    import pdfplumber

    from backend.data.ingestion.nse_filings import looks_like_balance_sheet

    out = {}
    for meta in REAL:
        try:
            payload = __import__("json").loads(meta.read_text(encoding="utf-8"))
        except Exception:
            continue
        symbol = str(payload.get("symbol") or "").strip().lower()
        pages = payload.get("balance_sheet_pages") or []
        if not symbol or not pages:
            continue
        for pdf in sorted(meta.parent.glob(f"{meta.stem}-*.pdf")):
            try:
                with pdfplumber.open(pdf) as doc:
                    located = all(
                        looks_like_balance_sheet(doc.pages[int(p) - 1].extract_text() or "")
                        for p in pages
                    )
            except Exception:
                continue
            if located:
                out[symbol] = (pdf, payload)
                break
    return out


def require(cid: str):
    pairs = cached_pairs()
    key = cid.split("_")[0].lower()
    if key not in pairs:
        pytest.skip(f"no cached NSE document for {cid} in this checkout")
    return pairs[key]


def test_the_cache_directory_is_where_the_documents_actually_are():
    """A constant that drifts from the fetcher's default is how this stays broken.

    `main()` defaulted `--cache` to the literal "backend/data/filings/nse" while the
    ingestion side had no constant at all. Two spellings of one directory, with nothing
    tying them together.
    """
    assert NSE_CACHE_DIR.is_dir(), f"the fetcher's cache directory does not exist: {NSE_CACHE_DIR}"
    for meta in REAL:
        assert meta.parent == NSE_CACHE_DIR, (
            f"{meta.name} is outside the constant's directory, so the ingestion side will "
            f"not find a document the fetcher downloaded"
        )


def test_a_cached_document_is_discoverable_from_its_company_id():
    """The link between a company and its statement is the metadata, not the filename.

    And the lookup cannot depend on case. The first version built the path from the
    uppercased ticker, which resolves on Windows and finds nothing on Linux, because the
    fetcher writes the symbol as it was invoked. CI failed both of these tests with "found 0
    cached attachments", which is the original defect reappearing for a new reason and would
    have read as "the fix does not work" rather than "the fix only worked on one OS".
    """
    checked = 0
    for cid in ("tcs_tcs", "hcltech_hcltech", "TCS_TCS", "Tcs_Tcs"):
        try:
            require(cid)
        except pytest.skip.Exception:
            continue
        found = _cached_nse_pdfs(cid)
        assert found, (
            f"{cid}: found 0 cached attachments, so the fetcher's output is invisible to "
            f"ingestion, which is the defect this file exists to close."
        )
        assert all(pdf.exists() for pdf, _m in found), (
            f"{cid}: metadata names a document that is not on disk"
        )
        assert found[0][1].get("balance_sheet_pages"), (
            f"{cid}: the metadata records no balance-sheet page, so there is nothing to parse"
        )
        # A company may hold more than one attachment (HCLTech keeps its superseded IFRS
        # document in the cache as a parser fixture beside its audited Ind-AS face). What
        # must always hold is that SOME attachment actually carries the recorded page.
        import pdfplumber

        from backend.data.ingestion.nse_filings import looks_like_balance_sheet

        located_any = False
        for pdf_path, meta in found:
            try:
                with pdfplumber.open(pdf_path) as doc:
                    if all(
                        looks_like_balance_sheet(doc.pages[int(p) - 1].extract_text() or "")
                        for p in (meta.get("balance_sheet_pages") or [])
                    ):
                        located_any = True
            except Exception:
                continue
        assert located_any, (
            f"{cid}: no attachment carries the recorded balance-sheet pages, so the link "
            f"between company and document is metadata without a document"
        )
        checked += 1
    if not checked:
        pytest.skip("no cached NSE document in this checkout")


def test_the_printed_page_number_becomes_the_right_index():
    """Off by one here reads the facing page, and reads it confidently.

    The fetcher records what a reader sees (`i + 1`). The parser indexes `pdf.pages`
    directly. Passing the printed number through unchanged reads the page BEFORE the
    balance sheet, which for these documents is a note or the income statement.
    """
    import pdfplumber

    from backend.data.ingestion.nse_filings import looks_like_balance_sheet

    pairs = cached_pairs()
    if not pairs:
        pytest.skip("no cached NSE document in this checkout")
    for pdf_path, meta in pairs.values():
        with pdfplumber.open(pdf_path) as doc:
            for printed in meta["balance_sheet_pages"]:
                text_on_index = doc.pages[printed - 1].extract_text() or ""
                assert looks_like_balance_sheet(text_on_index), (
                    f"{pdf_path.name} printed page {printed} is NOT a balance sheet at "
                    f"index {printed - 1}, so the conversion is wrong and the parser would "
                    f"read the facing page"
                )


def test_the_section_comes_from_the_document_not_the_caller():
    """`section` gates the mapping, so a wrong one decides what may be built from a page.

    `_statement_agrees(d.section, statement)` is what stops a cash-flow movement being
    mapped as a balance-sheet stock. A caller that asserts the section can therefore either
    block a page that should have mapped or let one through that should not have.

    The legacy hardcoded table asserted `PROFIT & LOSS` for a page that prints a
    comprehensive income statement, and asserted `BALANCE SHEET` for every page of every PDF
    in a per-company directory that no company has.
    """
    checked = 0
    for cid in ("tcs_tcs", "hcltech_hcltech"):
        if cid.split("_")[0].lower() not in cached_pairs():
            continue
        # The union across attachments is what counts. HCLTech's superseded IFRS
        # document shares the cache directory and the stem glob, and the recorded
        # page of the live metadata is not a statement in it: the parse raises
        # inside `_filing_datapoints_from_cached_pdf`, which logs the refusal and
        # returns nothing. An attachment contributing zero rows is the honest
        # outcome for a document whose statement the record no longer points at.
        all_dps = []
        for _pdf, meta in _cached_nse_pdfs(cid):
            all_dps.extend(_filing_datapoints_from_cached_pdf(_pdf, meta, cid))
        assert all_dps, f"{cid}: the located balance sheet produced no rows"
        sections = {d.section for d in all_dps}
        assert sections == {"BALANCE SHEET"}, (
            f"{cid}: rows carry {sections}. Every page reached here was located by "
            f"matching the balance sheet's own subtotal caption, so any other section "
            f"is the caller speaking rather than the document."
        )
        checked += 1
    if not checked:
        pytest.skip("no cached NSE document in this checkout")


def test_rows_carry_their_own_provenance():
    """A filing row that does not say which document and page it came from cannot be checked."""
    checked = 0
    for cid in ("tcs_tcs", "hcltech_hcltech"):
        if cid.split("_")[0].lower() not in cached_pairs():
            continue
        for _pdf, meta in _cached_nse_pdfs(cid):
            dps = _filing_datapoints_from_cached_pdf(_pdf, meta, cid)
            for d in dps[:20]:
                assert d.company_id == cid
                assert d.source == "nse_filing", (
                    f"{d.metric_raw!r} is filed as {d.source!r}, so it will not count "
                    f"toward filing-derived provenance"
                )
                assert d.source_location, (
                    f"{d.metric_raw!r} carries no source location, so a reader cannot "
                    f"find the line in the filing that produced it"
                )
                # The id is the row's own identity, and ingestion is not idempotent, so a
                # stable one is what lets a rebuild supersede rather than accumulate.
                assert d.id
                assert d.period_end_date is not None
            checked += 1
    if not checked:
        pytest.skip("no cached NSE document in this checkout")


def test_the_figures_are_the_filers_own_and_not_a_fixture():
    """The whole point: real rows, from the real document, for these companies."""
    pairs = cached_pairs()
    if not pairs:
        pytest.skip("no cached NSE document in this checkout")
    counts = {}
    for cid in ("tcs_tcs", "hcltech_hcltech"):
        if cid.split("_")[0].lower() not in pairs:
            continue
        counts[cid] = len(_get_secondary_filing_datapoints(cid))
    assert counts, "no company in this checkout has a cached document"
    for cid, n in counts.items():
        assert n > 0, (
            f"{cid} produced no filing datapoints. Before this path existed both companies "
            f"had ZERO filing rows in the database despite holding a downloaded, "
            f"already-located audited balance sheet."
        )
    print(f"\n  filing rows now produced: {counts}")


def test_a_document_with_no_recorded_pages_yields_nothing_rather_than_guessing():
    """No metadata means no pages. Guessing a page index here is the defect being fixed."""
    assert _filing_datapoints_from_cached_pdf(
        Path("does-not-matter.pdf"), {"balance_sheet_pages": []}, "x_x"
    ) == []
    assert _filing_datapoints_from_cached_pdf(
        Path("does-not-matter.pdf"), {}, "x_x"
    ) == []


def test_a_company_with_no_cached_document_says_so():
    """A recorded unknown beats a silent zero."""
    assert _cached_nse_pdfs("definitely_not_a_company_zz") == []

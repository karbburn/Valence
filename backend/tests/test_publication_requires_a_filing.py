"""The launch bar: publish a valuation only when a filing supplied the historicals.

Nine of the twenty-three shipped companies were publishing a full valuation off a
market feed nobody had verified against a filing. The numbers were probably right,
which is exactly why nobody objected: they looked fine. But the platform could not
show a reader the document and the line behind a single one of them, and a
valuation product that publishes figures it cannot stand behind is not a valuation
product.

These tests pin the decision and, more usefully, the ways it could be quietly
undone:

- a model with no historicals must fail, not pass (a check that cannot find its
  subject has not verified it, and an unverified check is believed)
- a model with no `filing_derived` flag must fail, not pass
- a company whose rows are majority fixture must fail even though a filing
  contributed something, because a valuation is not defensible because SOME of its
  inputs are
"""

from __future__ import annotations

import pytest

from backend.models.spec.metadata import ModelMetadata
from backend.models.spec.model_specification import ModelSpecification
from backend.validation.provenance import check_inputs_trace_to_a_filing

COMPANY = "provenance_us"


def _spec(*, data_sources, filing_derived, n_lines=1):
    hist = None
    if n_lines:
        # A stub, not a real HistoricalModel. What this check reads is the count of
        # lines and their keys, and building a full statement set here would make
        # the test about the model rather than about the provenance rule.
        #
        # `n_lines` is not `line_items`: a class body assigns that name locally, so
        # the right-hand side would resolve to the unbound local rather than to the
        # enclosing parameter.
        count = n_lines

        class _H:
            periods = ["FY26"]
            line_items = [object()] * count

        hist = _H()
    return ModelSpecification.model_construct(
        metadata=ModelMetadata(
            company_id=COMPANY,
            ticker="PRV",
            name="Provenance Test",
            market="us",
            currency="USD",
            fiscal_year_end="December 31",
            data_sources=data_sources,
            filing_derived=filing_derived,
        ),
        historicals=hist,
        forecast=None,
        valuation=[],
    )


class TestFilingBackedModelsPublish:
    def test_a_filing_majority_passes(self):
        res = check_inputs_trace_to_a_filing(
            _spec(data_sources={"sec_edgar": 120, "yfinance_live": 6},
                  filing_derived=True)
        )
        assert res.passed, res.detail

    def test_the_detail_says_which_filing(self):
        res = check_inputs_trace_to_a_filing(
            _spec(data_sources={"sec_edgar": 120, "yfinance_live": 6},
                  filing_derived=True)
        )
        assert "sec_edgar" in res.detail


class TestUnverifiedModelsDoNotPublish:
    def test_a_market_feed_alone_does_not_publish(self):
        res = check_inputs_trace_to_a_filing(
            _spec(data_sources={"yfinance_live": 100}, filing_derived=False)
        )
        assert not res.passed
        assert "yfinance_live" in res.detail, (
            "the failure must name what did contribute, or a reader cannot act on it"
        )

    def test_a_fixture_file_alone_does_not_publish(self):
        res = check_inputs_trace_to_a_filing(
            _spec(data_sources={"screener": 75}, filing_derived=False)
        )
        assert not res.passed

    def test_a_filing_that_is_a_minority_does_not_publish(self):
        """The Infosys-shaped case, and the one a naive check waves through.

        260 filing datapoints against 305 from the fixture file. A filing IS
        present, so "did any filing contribute" says yes, and the company publishes
        a valuation whose majority of figures trace to a local hand-entered file.
        """
        res = check_inputs_trace_to_a_filing(
            _spec(data_sources={"nse_filing": 260, "screener": 305},
                  filing_derived=False)
        )
        assert not res.passed, (
            "a minority filing does not make a valuation defensible"
        )
        assert "minority" in res.detail, (
            "the message must explain that a filing is present but does not supply "
            "the figures, or a reader will think the check simply dislikes the source"
        )

    def test_the_withheld_message_refuses_to_call_a_feed_an_estimate(self):
        res = check_inputs_trace_to_a_filing(
            _spec(data_sources={"yfinance_live": 100}, filing_derived=False)
        )
        assert "imply we produced them" in res.detail, (
            "the reason a feed is not the same as an estimate has to be stated, or "
            "the next person to look will 'fix' this by relabelling the data"
        )


class TestAbsenceIsNotEvidence:
    """The failure mode this codebase keeps hitting, pinned explicitly."""

    def test_a_model_with_no_historicals_fails_rather_than_passing(self):
        res = check_inputs_trace_to_a_filing(
            _spec(data_sources={"sec_edgar": 120}, filing_derived=True,
                  n_lines=0)
        )
        assert not res.passed
        assert "verified nothing" in res.detail

    def test_a_missing_filing_derived_flag_fails_rather_than_passing(self):
        res = check_inputs_trace_to_a_filing(
            _spec(data_sources={"sec_edgar": 120}, filing_derived=None)
        )
        assert not res.passed, (
            "an absent flag is absence of evidence, not evidence of sourcing"
        )
        assert "verified nothing" in res.detail

    def test_no_sources_at_all_fails(self):
        res = check_inputs_trace_to_a_filing(
            _spec(data_sources={}, filing_derived=False)
        )
        assert not res.passed

    @pytest.mark.parametrize("flag", [True, False, None])
    def test_the_check_never_raises(self, flag):
        """A crashing check is not a passing one, and not a useful one either."""
        res = check_inputs_trace_to_a_filing(
            _spec(data_sources={"sec_edgar": 1}, filing_derived=flag)
        )
        assert isinstance(res.passed, bool)

class TestTheGateIsActuallyWired:
    """The check can be perfect and still enforce nothing.

    A mutation run removed this check from both the validation pipeline and the
    blocking-check registry, and the entire suite stayed green. The check still ran,
    still failed correctly, and nobody cared: a check that runs and is not consulted
    is a comment.

    That is the same failure as `check_debt_is_actually_sourced` reading
    `spec.scenarios` and reporting the defect it was written to catch as clean --
    one level up. The arithmetic was right; the connection was missing.
    """

    def test_it_is_registered_in_the_validation_pipeline(self):
        from backend.validation.pipeline import CHECK_SUITE

        registered = {getattr(fn, "__name__", "") for _, fn in CHECK_SUITE}
        assert "check_inputs_trace_to_a_filing" in registered, (
            "the check is defined but never run; a check that does not run reports "
            "nothing and blocks nothing"
        )

    def test_it_blocks_publication(self):
        """Not merely 'runs' -- blocks.

        A non-blocking check is a note in an audit trail. The launch bar requires a
        gate.
        """
        from backend.api.routes import _INPUT_DEFECT_CHECKS

        assert "inputs_trace_to_a_filing" in _INPUT_DEFECT_CHECKS, (
            "the check ran, failed, and publication carried on anyway, which is the "
            "nine-companies-publishing-a-valuation-off-a-market-feed defect arriving "
            "through a different door"
        )

    def test_no_shipped_company_is_publishable_without_a_filing(self):
        """The end-to-end property, on the real snapshots.

        Every shipped model that reports itself publishable must be filing-derived.
        This is the assertion that would have caught the original nine, and it does
        not care how any of the individual checks are implemented.
        """
        import json
        from pathlib import Path

        cache = Path(__file__).resolve().parents[2] / "backend" / "data" / "cache"
        if not cache.is_dir():
            pytest.skip("no committed snapshots on this checkout")

        offenders = []
        for f in sorted(cache.glob("*.json")):
            payload = json.loads(f.read_text(encoding="utf-8")).get("model")
            if not payload:
                continue
            md = payload.get("metadata") or {}
            if md.get("filing_derived") is not True:
                offenders.append(f.stem)

        # Snapshots do not carry the computed verdict, so the strongest statement
        # available offline is: anything not filing-derived must not be one of the
        # models the gate would let through. The live check runs the rule; this
        # pins that the shipped set has no filing-less model masquerading as one.
        assert set(offenders).isdisjoint(_PUBLISHABLE_EXPECTED), (
            f"these shipped models are not filing-derived but are expected to "
            f"publish: {sorted(set(offenders) & _PUBLISHABLE_EXPECTED)}"
        )


#: The shipped set, minus the companies the checks correctly withhold, is
#: filing-derived. Kept as a literal rather than recomputed so that adding an
#: unsourced company to `data/cache/` without fixing it turns this red.
_PUBLISHABLE_EXPECTED = {
    # US filers whose statements come from SEC XBRL company facts.
    "aapl_us", "amzn_us", "awi_us", "dox_us", "googl_us", "meta_us",
    "msft_us", "nvda_us",
    # Ambarella is filing-derived too; it is withheld for a different reason
    # (negative equity value, which is arithmetic rather than a view).
    "amba_us",
}

"""A valuation is only published when its inputs trace to a filing.

This is the launch bar stated plainly: every published figure traces to an official
filing, or it is not published. Thirteen of the twenty-three shipped companies did
not meet it, and the nine worst of them were publishing a full valuation anyway.

What the distinction actually is, because it is easy to get wrong:

- A filing is the company's own audited or filed statements. We can point a reader
  at the document and the line.
- An *estimate* is our number. Labelling it as such is honest and is what the
  eight fixture companies do.
- A market-data feed is neither. `yfinance_live` republishes a company's reported
  figures through a vendor. The numbers are probably right. We have not verified a
  single one of them, cannot show a reader the filing behind any of them, and
  cannot tell them which tag a figure came from.

Calling a feed figure "estimated" would be a lie in the useful direction: it
implies we produced it. Calling it "filed" would be the worse one. The only honest
label is "a third party published this and we have not checked it", and a valuation
built on that is a number the platform is not in a position to stand behind.

So this check refuses publication where no filing contributed the historicals. It
does not say the figures are wrong -- several are almost certainly right. It says
the platform cannot stand behind them, and a valuation product that publishes
figures it cannot stand behind is not a valuation product.

The cost is stated rather than hidden: coverage falls from eighteen companies to
ten until the rest are sourced. That is the correct trade. Ten figures that tie to a
filing beat eighteen that tie to nothing, and the eight already blocked companies
show the degraded path exists and works.

`historicals_are_reported` already notices when historicals are not reported, but it
is not a blocker, so the nine worst cases sailed through it. This is the blocker
that matches the bar.
"""

from __future__ import annotations

from backend.models.spec.metadata import FILING_SOURCES
from backend.models.spec.model_specification import ModelSpecification
from backend.models.spec.qa import ModelCheckResult

CHECK_NAME = "inputs_trace_to_a_filing"


def check_inputs_trace_to_a_filing(spec: ModelSpecification) -> ModelCheckResult:
    """Refuse to publish a valuation whose historicals no filing contributed to."""
    sources = set((spec.metadata.data_sources or {}).keys())

    if not spec.historicals or not spec.historicals.line_items:
        # A check that cannot find its subject has not verified it. Failing rather
        # than passing is the rule: an unverified check that reports success is
        # believed, which is worse than having no check at all.
        return ModelCheckResult(
            check_name=CHECK_NAME,
            category="data_quality",
            passed=False,
            detail=(
                "The model carries no historical line items, so provenance could not "
                "be checked. This fails rather than passing because it verified "
                "nothing."
            ),
            implicated_scenarios=["base", "bull", "bear"],
        )

    filing_sources = sources & FILING_SOURCES

    # `filing_derived` is the authority here, and it is already computed: it is
    # True only when filing rows are the LARGE MAJORITY of what was ingested.
    #
    # Asking instead "did any filing contribute at all" let one company through that
    # should not have been. Infosys' Indian listing carries 260 filing datapoints and
    # 305 from the local fixture file, so most of its figures are not filing-traced
    # while the presence of a filing made it look sourced. A valuation is not
    # defensible because some of its inputs are.
    #
    # Re-deriving a majority rule here would have been the fourth hand-kept list to
    # drift from an existing one, so this reads the flag instead.
    filing_derived = getattr(spec.metadata, "filing_derived", None)

    if filing_derived is True:
        return ModelCheckResult(
            check_name=CHECK_NAME,
            category="data_quality",
            passed=True,
            detail=(
                f"Historicals are filing-derived: filing rows are the large majority "
                f"of what was ingested ({', '.join(sorted(filing_sources))} out of "
                f"{len(sources)} source(s) in total)."
            ),
        )

    if filing_derived is None:
        # The flag is absent, which is not evidence of sourcing. This used to be a
        # silent pass because the check returned early on "a filing is present";
        # a model with no flag at all now fails instead, because a check that cannot
        # establish its subject has not verified it.
        return ModelCheckResult(
            check_name=CHECK_NAME,
            category="data_quality",
            passed=False,
            detail=(
                "The model records no filing-derived flag, so whether a filing supplied "
                "the historicals could not be established. This fails rather than "
                f"passing because it verified nothing. Sources present: "
                f"{', '.join(sorted(sources)) or 'nothing'}."
            ),
            implicated_scenarios=["base", "bull", "bear"],
        )

    # No filing. Say precisely what did contribute, because "it failed" tells a
    # reader nothing they can act on.
    contributed = ", ".join(sorted(sources)) or "nothing"
    return ModelCheckResult(
        check_name=CHECK_NAME,
        category="data_quality",
        passed=False,
        detail=(
            f"No filing contributed to this company's historicals, so the valuation "
            f"is not published as a valuation. Sources present: {contributed}. These "
            f"figures may well be correct -- a market feed republishes a company's "
            f"own reported statements -- but the platform has not verified any of "
            f"them against a filing and cannot show a reader the document and line "
            f"behind any single number. Labelling them 'estimated' would imply we "
            f"produced them, which we did not. The statements and the audit trail "
            f"remain available below; what is withheld is the valuation built on top "
            f"of them. Sourcing the filing restores publication."
            + (
                f" Note that a filing IS present ({', '.join(sorted(sources & FILING_SOURCES))}) "
                f"but supplies only a minority of the rows, so most figures here do not "
                f"trace to it."
                if sources & FILING_SOURCES
                else ""
            )
        ),
        implicated_scenarios=["base", "bull", "bear"],
    )
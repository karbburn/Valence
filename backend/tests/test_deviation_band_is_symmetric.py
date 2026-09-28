"""The deviation band has to hold in both directions.

The band that guards the implied price against the traded one used to run from
-60% to +200%. Every wrong figure found while it was being tuned had been an
understatement, so the wide upper half looked safe. It was not: it was simply
untested, because a check that only ever fires downwards gets a threshold set
from the failures it has seen and none it has not.

Two large-cap filers came in at +178% and +176% with every check passing. A
model claiming a stock is worth nearly three times its price is as specific a
claim as one claiming a fifth, and a misread share count, debt figure or terminal
assumption produces it exactly as readily.

The band is a statement about when to look at the inputs, not a view on whether
the market is wrong, and it has to be read the same way in either direction.
"""

import datetime as dt

import pytest

from backend.models.spec.model_specification import Historicals, ModelSpecification
from backend.models.spec.valuation import DCFBridge, ReverseDCF, ValuationOutput
from backend.validation.input_plausibility import (
    IMPLIED_DEVIATION_CEILING,
    IMPLIED_DEVIATION_FLOOR,
    check_implied_price_deviation_is_explainable,
)

MARKET = 100.0


def _spec(implied: float) -> ModelSpecification:
    return ModelSpecification(
        metadata={
            "company_id": "x_us",
            "ticker": "X",
            "name": "X Inc",
            "market": "us",
            "currency": "USD",
            "units": "millions",
            "fiscal_year_end": "December 31",
        },
        historicals=Historicals(periods=[], line_items=[]),
        valuation=[
            ValuationOutput(
                scenario="base",
                dcf_bridge=DCFBridge(implied_share_price=implied),
                reverse_dcf=ReverseDCF(market_price=MARKET),
            )
        ],
    )


class TestDeviationBandIsSymmetric:
    def test_the_two_bounds_are_the_same_distance(self):
        # Not a rule about valuations. A rule about not having half the space
        # untested.
        assert abs(IMPLIED_DEVIATION_FLOOR) == pytest.approx(IMPLIED_DEVIATION_CEILING)

    @pytest.mark.parametrize("implied", [178.0, 176.0, 260.0, 202.0])
    def test_a_large_overvaluation_is_reported(self, implied):
        # Every one of these passed the gate while the ceiling was +200%.
        result = check_implied_price_deviation_is_explainable(_spec(implied))
        assert result.passed is False

    @pytest.mark.parametrize("implied", [39.9, 28.0, 10.0])
    def test_a_large_undervaluation_is_reported(self, implied):
        result = check_implied_price_deviation_is_explainable(_spec(implied))
        assert result.passed is False

    @pytest.mark.parametrize("implied", [155.0, 100.0, 160.0, 41.0])
    def test_an_ordinary_disagreement_is_allowed(self, implied):
        # A DCF that disagrees with the market is a legitimate opinion and models
        # post it routinely. A band that fires on those would be ignored, which
        # costs more than the check is worth.
        result = check_implied_price_deviation_is_explainable(_spec(implied))
        assert result.passed is True

    def test_the_message_names_the_bound_that_was_breached(self):
        # It used to quote the floor whatever the direction, so a model that came
        # in far too high was told it had passed the lower bound.
        high = check_implied_price_deviation_is_explainable(_spec(178.0))
        assert "+60%" in high.detail
        assert "-60%" not in high.detail

        low = check_implied_price_deviation_is_explainable(_spec(28.0))
        assert "-60%" in low.detail

"""Removing a label from the registry does not withdraw it.

The two aggregate withdrawals in `registry.py` -- "Investments" and "Other Assets" --
were inert for as long as they stood. `map_raw_datapoints` falls through to the
confidence engine when the registry returns None, and that engine proposes both
labels at MEDIUM confidence, which the mapper accepts:

    "Investments"  -> canonical.bs.non_current_investments
    "Other Assets"  -> canonical.bs.other_non_current_assets

So the aggregate survived the fix meant to eliminate it. It simply changed keys:
Infosys published 21,880 as NON-current investments against a filed 8,930, and the
current-asset double count was replaced by a non-current one of the same size. The
reasoning in the registry's comments described a withdrawal that had not happened.

These tests are behavioural on purpose. The earlier attempt asserted against
`get_canonical_mapping`, which returns None for both labels and passed -- while the
mapper went on publishing them. Asserting the registry cannot detect this class of
defect, because the registry was never the thing at fault.
"""

from __future__ import annotations

import inspect
import pathlib
import re
import sys
from datetime import datetime

import pytest

REPO = pathlib.Path(__file__).resolve().parents[2]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

from backend.data.store import RawDatapoint  # noqa: E402
from backend.normalization.financials import mapper  # noqa: E402
from backend.normalization.taxonomy.registry import WITHDRAWN_LABELS  # noqa: E402

# Screener's aggregates, with the values that identified them.
#
# "Investments" equalled current PLUS non-current to the rupee in all three years,
# which is what established it as a total rather than a guess. "Other Assets" read
# 98,112 while cash 22,201, investments 21,880 and receivables 35,234 sit beneath it
# on the same sheet -- it already contains them.
AGGREGATES = {
    "Investments": [24623.0, 23541.0, 21880.0],
    "Other Assets": [98112.0],
}


def _raw(label: str, values: list[float]) -> list[RawDatapoint]:
    return [
        RawDatapoint(
            id="probe-%s-%d" % (label[:4].replace(" ", ""), i),
            company_id="probe_co",
            metric_raw=label,
            period_label="FY%d" % (24 + i),
            period_end_date=datetime(2024 + i, 3, 31).date(),
            value=v,
            currency="INR",
            units="crores",
            source="screener",
            source_location="DataSheet!J64",
            status="reported",
            update_date=datetime.now(),
        )
        for i, v in enumerate(values)
    ]


class TestAWithdrawalHoldsAgainstTheConfidenceEngine:
    """The engine proposes these labels. That is the whole problem."""

    @pytest.mark.parametrize("label,values", sorted(AGGREGATES.items()))
    def test_the_aggregate_reaches_no_canonical_datapoint(self, label, values):
        canonical, _mappings, _unmapped = mapper.map_raw_datapoints(_raw(label, values))
        leaked = [c for c in canonical if abs(c.value) in values]
        assert not leaked, (
            "%r reached the model as %s = %.1f. The registry returns None for it, "
            "so this came from the confidence engine's suggestion, which means the "
            "withdrawal is not in force."
            % (label, ", ".join(sorted({c.canonical_key for c in leaked})),
               leaked[0].value)
        )

    @pytest.mark.parametrize("label,values", sorted(AGGREGATES.items()))
    def test_a_withdrawal_does_not_fail_the_build(self, label, values):
        """Distinct failure, and the reason the labels are not merely unmapped.

        `pipeline.run` raises on any unmapped label, so a withdrawal implemented as
        "unmapped" turns a recorded decision into a 422. The label has to be neither
        mapped nor reported unmapped.
        """
        _canonical, _mappings, unmapped = mapper.map_raw_datapoints(_raw(label, values))
        assert label not in unmapped, (
            "%r is reported unmapped, so `pipeline.run` raises and the company "
            "answers 422 instead of publishing a statement with a reported shortfall"
            % label
        )

    @pytest.mark.parametrize("label", sorted(AGGREGATES))
    def test_the_engine_would_otherwise_map_it(self, label):
        """Guards the premise.

        If the suggestion engine stops proposing these labels, the withdrawal is
        trivially satisfied and the guard above would pass for the wrong reason --
        so this asserts the pressure is still there.
        """
        suggestion = mapper.suggest_canonical_mapping(label)
        assert suggestion.canonical_key is not None, (
            "%r is no longer proposed by the confidence engine, so this test file's "
            "premise has changed and the withdrawal tests may be vacuous now"
            % label
        )

    def test_the_mapper_checks_withdrawals_before_the_engine(self):
        """Order is the mechanism: a later check cannot undo an earlier one."""
        src = inspect.getsource(mapper.map_raw_datapoints)
        code = re.sub(r'""".*?"""', "", src, flags=re.S)
        code = re.sub(r"#.*$", "", code, flags=re.M)

        i_withdrawn = code.find("in WITHDRAWN_LABELS")
        assert i_withdrawn != -1, (
            "map_raw_datapoints never consults WITHDRAWN_LABELS, so a withdrawal "
            "cannot survive the confidence engine that proposes these labels"
        )
        i_suggest = code.find("suggest_canonical_mapping(d.metric_raw)")
        i_engine = code.find("if mapping is None and use_confidence_engine")
        assert -1 < i_withdrawn < i_engine, (
            "the withdrawal check must come BEFORE the engine is consulted; it is "
            "currently at %r and the engine at %r" % (i_withdrawn, i_engine)
        )
        # The routing call inside the withdrawal branch reuses the same expression,
        # so compare against the branch rather than the first textual hit.
        assert i_withdrawn < i_suggest or i_withdrawn < i_engine


class TestTheDecisionIsRecorded:
    def test_both_aggregates_are_named(self):
        for label in AGGREGATES:
            assert label in WITHDRAWN_LABELS, (
                "%r is an aggregate that must stay unmapped, and it is not in "
                "WITHDRAWN_LABELS" % label
            )

    def test_the_set_is_frozen(self):
        """A mutable module-level set is a decision anyone can edit by accident."""
        assert isinstance(WITHDRAWN_LABELS, frozenset), (
            "WITHDRAWN_LABELS is %s, so a caller can add to it at runtime and "
            "silently change which figures are published"
            % type(WITHDRAWN_LABELS).__name__
        )

    def test_nothing_withdrawn_is_also_in_the_registry(self):
        """A label cannot be both mapped and withdrawn; the mapper would map it."""
        from backend.normalization.taxonomy.registry import RAW_METRIC_MAP

        both = sorted(WITHDRAWN_LABELS & set(RAW_METRIC_MAP))
        assert not both, (
            "these are in RAW_METRIC_MAP, so the registry lookup succeeds and the "
            "withdrawal branch is never reached: %r" % both
        )

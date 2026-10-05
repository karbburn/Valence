"""Do not point `minority_interest` at an element that is a TOTAL.

Measured across all 11 shipped US filers, per companyfacts:

    MinorityInterest                                  absent from all 11
    MinorityNoncontrollingInterestsInSubsidiary        absent from all 11

So the SEC reader cannot supply this line for any of them, and there is no mapping to
add. An earlier note recorded "minority interest: SEC can supply 1"
-- that "1" was `StockholdersEquityIncludingPortionAttributableToNoncontrollingInterest`,
which is TOTAL equity including the minority slice.

Adding it would publish the whole equity balance as the minority interest. For a filer
with total equity in the hundreds of billions that is not a small error; it is a figure
that looks plausible on a page and is wrong by the parent's entire equity.

A derivation was also tried and could not corroborate the feed either way: no filer files
both `...IncludingPortionAttributableToNoncontrollingInterest` and `StockholdersEquity`
with a material difference between them, so
`(including) - (excluding)` yields no number to check the market feed against. That is a
recorded unknown, not a pass.

These tests assert the trap stays closed. A mapping added later would be a single line in
`US_GAAP_TAG_MAP`, and this is the cheapest possible place to stop it.
"""

from __future__ import annotations

import pathlib
import re
import sys

REPO = pathlib.Path(__file__).resolve().parents[2]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

from backend.data.ingestion.sec_edgar import US_GAAP_TAG_MAP  # noqa: E402
from backend.normalization.taxonomy.registry import (  # noqa: E402
    RAW_METRIC_MAP,
    get_canonical_mapping,
)

# Elements that are a TOTAL containing the minority slice rather than the slice itself.
CONTAINING_ELEMENTS = (
    "StockholdersEquityIncludingPortionAttributableToNoncontrollingInterest",
    "MinorityInterest",
    "RedeemableNoncontrollingInterestEquityCarryingAmount",
    "TemporaryEquityCarryingAmountAttributableToParent",
)

MINORITY_KEY = "canonical.bs.minority_interest"


class TestNoTotalIsMappedOntoTheMinoritySlice:
    def test_no_containing_element_reaches_the_minority_key(self):
        offenders = []
        for label, tags, _section in US_GAAP_TAG_MAP:
            if not any(t in CONTAINING_ELEMENTS for t in tags):
                continue
            mapping = get_canonical_mapping(label)
            if mapping and mapping[0] == MINORITY_KEY:
                offenders.append((label, mapping))
        assert not offenders, (
            "these entries map a TOTAL containing non-controlling interests onto %s: %r. "
            "Publishing total equity as the minority slice overstates it by the parent's "
            "entire equity."
            % (MINORITY_KEY, offenders)
        )

    def test_no_taxonomy_entry_maps_a_total_there_either(self):
        """The registry is the other place the mapping could be written.

        Checked by ELEMENT NAME, not by tags. An earlier version walked
        `RAW_METRIC_MAP` looking for a label whose SEC entry carried a containing tag --
        which cannot see a registry-only entry, because a registry entry has no tags at
        all. A mutation that wrote `"Minority interest": (minority_key, "bs")` straight
        into the registry SURVIVED that version.
        """
        offenders = [
            element for element in CONTAINING_ELEMENTS
            if (get_canonical_mapping(element) or (None,))[0] == MINORITY_KEY
        ]
        assert not offenders, (
            "the taxonomy maps %r onto %s: publishing total equity as the minority "
            "slice" % (offenders, MINORITY_KEY)
        )

    def test_no_registry_label_naming_a_TOTAL_maps_there(self):
        """By the phrasing, for a hand-written entry.

        Scoped to the way a TOTAL is worded -- "including", "equity including",
        "total equity" -- and NOT to "non-controlling interests" on its own, which is the
        SLICE and is the correct label for this key. An earlier version's regex matched
        the bare phrase and failed on the legitimate "Non-controlling interests" entry.
        """
        offenders = [
            label for label, mapping in RAW_METRIC_MAP.items()
            if mapping[0] == MINORITY_KEY
            and re.search(r"including|total equity", label, re.I)
        ]
        assert not offenders, (
            "a registry label that names a TOTAL maps onto %s: %r"
            % (MINORITY_KEY, offenders)
        )

    def test_the_slice_itself_is_still_mapped(self):
        """The good case, asserted so the file cannot be used to justify deleting it.

        `Non-controlling interests` IS the minority slice. Refusing to touch it is the
        point; a guard that quietly removed correct mappings would be its own defect.
        """
        assert get_canonical_mapping("Non-controlling interests") == (
            MINORITY_KEY, "bs"
        ), (
            "'Non-controlling interests' no longer maps to %s. That is the correct "
            "label for this key and removing it would leave the line unsourced."
            % MINORITY_KEY
        )

    def test_the_minority_key_has_no_filing_source_at_all(self):
        """Stated as a fact, so a future reader knows it was checked and not skipped.

        None of the 11 shipped US filers tags a standalone NCI balance, so the market
        feed is the only source and the provenance cannot be improved by a mapping.

        Scoped to entries that actually reach `minority_interest`. An earlier version
        asserted that no entry mentions a containing element at all, which failed on
        "Mezzanine equity" -- a legitimate mapping, since `RedeemableNoncontrolling
        InterestEquityCarryingAmount` IS mezzanine equity. Presence of a containing
        element somewhere in the map says nothing about this key.
        """
        labels = [
            label for label, tags, _s in US_GAAP_TAG_MAP
            if any(t in CONTAINING_ELEMENTS for t in tags)
            and (get_canonical_mapping(label) or (None,))[0] == MINORITY_KEY
        ]
        assert not labels, (
            "%r now reaches %s from a filing. No US filer files a standalone NCI "
            "balance -- if that has changed, check "
            "WHICH element is being used before accepting it."
            % (labels, MINORITY_KEY)
        )

    def test_mezzanine_equity_still_maps_where_it_belongs(self):
        """The legitimate use of a containing element, asserted so it is not removed.

        `RedeemableNoncontrollingInterestEquityCarryingAmount` is mezzanine equity, and
        mapping it as such is correct. Only mapping it onto the minority SLICE is the
        error. Asserting the good case as well as the bad one stops this file being used
        to justify deleting a working entry.
        """
        assert get_canonical_mapping("Mezzanine equity") is not None, (
            "'Mezzanine equity' stopped mapping. That entry is correct -- redeemable "
            "non-controlling interests ARE mezzanine equity -- and it is not what this "
            "file objects to."
        )


def _tags_of(label: str) -> list:
    for mapped, tags, _section in US_GAAP_TAG_MAP:
        if mapped == label:
            return tags
    return []

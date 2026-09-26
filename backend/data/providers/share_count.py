"""Choosing between two published share counts, and saying which was chosen.

A share count is not a single fact. Two sources routinely disagree about a
public company, and each disagreement has a different cause and a different
correct resolution:

  - A MULTI-CLASS issuer. The provider's summary field reports one class; the
    filed balance sheet reports the total across all classes. One large-cap
    returned 5.87bn against a filed 12.23bn, so its market capitalisation came out
    at half and every per-share figure at double. The filing is right.

  - An ADR / GDR listing. The quoted price is per depositary receipt, and the
    filed balance sheet counts ORDINARY shares. One foundry returned a filed
    25.9bn against 5.19bn ADS-equivalent — a ratio of exactly 5, its receipt
    ratio. Multiplying the receipt price by the ordinary count overstates the
    market capitalisation fivefold. The provider is right.

Both look like "the filed count disagrees with the provider". Choosing wrongly
in either direction produces a market capitalisation out by a large multiple,
and every multiple, per-share figure and upside percentage derived from it.

The discriminator is the shape of the disagreement:

  - A ratio very close to a small WHOLE number is a depositary ratio or a split
    factor. Share counts do not accidentally land on 5.000x; receipt ratios are
    2, 5, 10 and so on. This case is priced per receipt, so the count must be
    receipt-equivalent: the provider's figure.

  - Any other ratio is a class structure. Companies do not choose share-class
    ratios that are round, and a total across classes is what a market
    capitalisation is defined on: the filed figure.

A ratio near 1.0 means the two agree, and either is fine.
"""

from __future__ import annotations

from typing import Optional, Tuple

# How far from a whole number a ratio may sit and still be read as a receipt
# ratio. Real receipt ratios are exact, but a feed's own count carries rounding
# — one listing came through 3.5% away from its true 8:1 — so the tolerance has
# to be wider than the rounding and narrower than the gap to the nearest
# plausible alternative.
_RATIO_ROUNDING_TOLERANCE = 0.04

# Divergence above this is a real disagreement worth adjudicating rather than
# rounding. Below it, the two sources are the same number.
_AGREEMENT_TOLERANCE = 0.05

# Receipt ratios at or above this many ordinary shares per receipt. A ratio of 2
# or 3 is ambiguous: a two-class issuer with classes of similar size and a 2:1
# receipt produce the same ratio, and the ratio alone cannot tell them apart. It
# is read as a class structure, which is the safe direction — it keeps the total
# across classes, which is what a market capitalisation is defined on. Genuine
# multi-class ratios sit well away from whole numbers, so requiring the ratio to
# be both large and near-round separates the two cases in practice.
_MIN_CREDIBLE_RECEIPT_RATIO = 4.0


def resolve_share_count(
    filed: Optional[float],
    provider: Optional[float],
    filed_basis: str = "",
    provider_basis: str = "provider summary field",
) -> Tuple[Optional[float], str]:
    """Pick the share count that matches the instrument the price refers to.

    Returns (count, basis). `basis` always states which source was used and, when
    they disagreed, what the other one said — so a reader can see the decision
    rather than infer it.

    Both counts must be in the same unit; the callers scale before calling.
    """
    if filed is None and provider is None:
        return None, "unresolved"

    if filed is None:
        return provider, f"{provider_basis} (the filed balance sheet does not report the line)"

    if provider is None:
        return filed, f"filed ordinary shares outstanding ({filed_basis or 'balance sheet'})"

    if filed <= 0 or provider <= 0:
        return filed, f"filed ordinary shares outstanding ({filed_basis or 'balance sheet'})"

    ratio = filed / provider

    if abs(ratio - 1.0) <= _AGREEMENT_TOLERANCE:
        return filed, (
            f"filed ordinary shares outstanding ({filed_basis or 'balance sheet'}); "
            f"provider summary agreed at {provider:,.2f}"
        )

    nearest_whole = round(ratio)
    is_receipt_ratio = (
        nearest_whole >= _MIN_CREDIBLE_RECEIPT_RATIO
        and abs(ratio - nearest_whole) / nearest_whole <= _RATIO_ROUNDING_TOLERANCE
    )

    if is_receipt_ratio:
        return provider, (
            f"{provider_basis} = {provider:,.2f}; the filed count of {filed:,.2f} is "
            f"{nearest_whole}x that, which is a depositary receipt ratio rather "
            "than a share class, and the quoted price is per receipt"
        )

    return filed, (
        f"filed ordinary shares outstanding ({filed_basis or 'balance sheet'}) = "
        f"{filed:,.2f}; provider summary said {provider:,.2f} and was rejected as a "
        f"single-class figure (ratio {ratio:.3f})"
    )

"""Most recently reported balance-sheet snapshot for the enterprise-value bridge.

The EV -> equity bridge combines two things: a market capitalisation that is
live, and a net debt figure. When the net debt figure comes from the last ANNUAL
balance sheet, the bridge mixes a price from today with a balance sheet from up
to twelve months ago, and the resulting enterprise value — and every multiple
built on it — is stale by exactly that much.

Measured on the current universe, using the last reported quarter instead of the
last reported year moves net cash by:

    NVDA    +54,088 ->  +24,118      (debt grew 11bn to 38bn in two quarters)
    GOOGL   +78,300 -> +129,718
    MSFT    +36,549 ->  +19,825
    AAPL    -37,211 ->  -21,945
    AMZN    -42,347 ->  -66,799

So the rule is: take the bridge's balance-sheet terms at the most recent instant
date the filer has reported, annual or interim. An interim balance sheet is a
filed, reviewed statement and is exactly what every market data provider uses.

The annual series is untouched. This module is a separate, additive view used
only by the bridge, so a quarter never becomes a "historical year" in the
three-statement model.
"""

from __future__ import annotations

import logging
import warnings
from dataclasses import dataclass, field
from typing import Optional

with warnings.catch_warnings():
    warnings.simplefilter("ignore")
    import yfinance as yf

logger = logging.getLogger(__name__)

# Divisor from the reporting unit the market feed uses to the unit the model
# stores. Feeds report absolute currency; the model works in USD millions and
# INR crores, so the same snapshot must be scaled before it meets a balance
# sheet or it is out by a factor of a million.
UNIT_DIVISORS = {
    ("USD", "millions"): 1e6,
    ("USD", "millions_actual"): 1e6,
    ("INR", "crores"): 1e7,
    ("INR", "crores_actual"): 1e7,
}

# Bridge terms, with the row labels a feed may use for each. The first label
# that carries a value for the period wins.
BRIDGE_TERMS: dict[str, tuple[str, ...]] = {
    "cash_and_bank": (
        "Cash And Cash Equivalents",
        "Cash Cash Equivalents And Short Term Investments",
    ),
    "marketable_securities": (
        "Other Short Term Investments",
        "Available For Sale Securities",
        "Current Securities",
    ),
    "non_current_investments": (
        "Investmentin Financial Assets",
        "Other Investments",
        "Financial Assets",
    ),
    "debt_non_current": (
        "Long Term Debt And Capital Lease Obligation",
        "Long Term Debt",
    ),
    "debt_current": (
        "Current Debt And Capital Lease Obligation",
        "Current Debt",
        "Short Term Debt",
    ),
    # Lease liabilities, reported for the reader's benefit.
    #
    # This is a SUBSET of the feed's own total-debt figure, not an addition to
    # it, and is never added on top. It is carried so a reader who prefers a
    # capitalised-lease convention can see the balance; whether it belongs in
    # net debt is a convention choice, and the basis note on the bridge states
    # which convention the platform is using.
    "lease_liabilities": (
        "Capital Lease Obligation",
        "Capital Lease Obligations",
        "Finance Lease",
        "Operating Lease Liability",
    ),
    "minority_interest": ("Minority Interest",),
    "preferred_stock": ("Preferred Stock", "Preferred Stock Equity"),
}

# Labels whose value is already the combined figure. If a feed reports these,
# the components must not be added on top or the same money is counted twice.
COMBINED_LABELS = frozenset({
    "Cash Cash Equivalents And Short Term Investments",
    "Total Debt",
})


@dataclass
class BridgeSnapshot:
    """Bridge terms at one reported balance-sheet date."""

    as_of: Optional[str] = None
    source: str = "unavailable"
    terms: dict[str, float] = field(default_factory=dict)
    total_debt: float = 0.0
    total_liquid_assets: float = 0.0
    net_cash: float = 0.0

    def as_dict(self) -> dict:
        return {
            "as_of": self.as_of,
            "source": self.source,
            "terms": dict(self.terms),
            "total_debt": self.total_debt,
            "total_liquid_assets": self.total_liquid_assets,
            "net_cash": self.net_cash,
        }


def _label_value(frame, labels: tuple[str, ...], column) -> Optional[float]:
    for label in labels:
        if label in frame.index:
            try:
                value = frame.loc[label, column]
            except Exception:
                continue
            if value is None:
                continue
            try:
                number = float(value)
            except (TypeError, ValueError):
                continue
            # A feed reports an unpopulated cell as NaN; treat it as absent
            # rather than as a real zero, so a missing term is visible instead
            # of silently reducing the total.
            if number != number:
                continue
            return number
    return None


def _drop_claims_at_or_above_total(values: dict[str, float], total_debt: float) -> None:
    """Remove terms that claim to be a component but are as large as the whole.

    A lease liability, a minority interest or a preferred balance that is at or
    above the total debt it is supposedly part of is not a component of it. In
    practice it means the feed is restating an aggregate under a component's
    label, and publishing it as a component invents a capital structure: it
    showed one issuer's entire debt balance as "lease liabilities".

    Dropped rather than published, because a wrong component is worse than an
    absent one — an absent figure can be chased down, a plausible wrong one is
    simply believed.
    """
    if total_debt <= 0:
        return
    for key in ("lease_liabilities", "minority_interest", "preferred_stock"):
        value = values.get(key)
        if value is not None and value >= total_debt:
            logger.info(
                "Dropping %s of %s: it is at or above the total debt of %s, so it "
                "restates the aggregate rather than forming part of it",
                key, f"{value:,.0f}", f"{total_debt:,.0f}",
            )
            values.pop(key, None)


def _build(frame, column, source: str) -> Optional[BridgeSnapshot]:
    values: dict[str, float] = {}
    for key, labels in BRIDGE_TERMS.items():
        found = _label_value(frame, labels, column)
        if found is not None:
            values[key] = found
    if not values:
        return None

    # A feed may publish the combined liquid-asset and total-debt figures
    # directly. When it does, use them and do NOT add the components on top.
    combined_liquid = _label_value(
        frame, ("Cash Cash Equivalents And Short Term Investments",), column
    )
    combined_debt = _label_value(frame, ("Total Debt",), column)

    # BASIS, matching the convention the valuation bridge uses:
    #   net cash = (cash + short-term investments + long-term investments) - debt
    #
    # Long-term investments ARE netted here, where the platform's own bridge
    # deducts them. It used to be excluded on the grounds that a feed's headline
    # net cash figure leaves them out, so a peer priced on this snapshot was
    # measured on a different basis from the target it is being compared against,
    # and a benchmark built from a mix of the two is a median of two conventions.
    # Whether a data vendor's own net-debt field includes them is a reason to
    # publish this basis, not a reason to compute a second one.
    if combined_liquid is not None:
        liquid = combined_liquid
    else:
        liquid = values.get("cash_and_bank", 0.0) + values.get("marketable_securities", 0.0)
    liquid += values.get("non_current_investments", 0.0)

    # Total debt.
    #
    # The feed's published "Total Debt" is used as-is. It already contains the
    # non-current lease component: adding the separately-listed lease line on
    # top double counts, and doing so moved eleven of twelve companies away from
    # the market reference rather than towards it.
    #
    # The lease balance is read so a reader can see it, but only where it is
    # genuinely a COMPONENT of the debt total.
    #
    # A feed's lease row is not reliably a lease component. For one large
    # Indian listing the row equalled the entire debt balance to the rupee, which
    # is a restatement of total debt rather than a subset of it; published as
    # "lease liabilities" it told a reader that all of that company's debt was
    # leases. A component cannot equal or exceed the total it is part of, so a
    # row at or above the total is dropped rather than reported as something it
    # is not. The same rule is applied to the minority-interest and preferred
    # rows.
    if combined_debt is not None:
        debt = combined_debt
    else:
        debt = values.get("debt_non_current", 0.0) + values.get("debt_current", 0.0)

    _drop_claims_at_or_above_total(values, debt)

    as_of = column
    try:
        as_of = column.strftime("%Y-%m-%d")
    except AttributeError:
        as_of = str(column)

    return BridgeSnapshot(
        as_of=as_of,
        source=source,
        terms=values,
        total_debt=debt,
        total_liquid_assets=liquid,
        net_cash=liquid - debt,
    )


def fetch_bridge_snapshot(company_id: str, in_model_units: bool = True) -> BridgeSnapshot:
    """Most recent reported bridge terms for a company.

    Prefers the latest quarter over the latest year, because a market data
    provider's headline net cash, enterprise value and multiples are all struck
    on the most recent balance sheet. Falls back through the available periods
    so a company that has not filed a quarter is still served from its year.

    By default the snapshot is scaled into the reporting units the model uses —
    USD millions, INR crores — because the feed reports absolute currency and
    an unscaled figure would enter the bridge a factor of a million too large.

    `in_model_units=False` returns the feed's own absolute currency instead,
    which is what a caller needs when it is combining the bridge with other
    absolute figures. A market capitalisation is price times shares and is
    therefore in rupees or dollars; adding a crores-denominated net debt to it
    understates the debt by a factor of ten million, and the resulting multiple
    is wrong by orders of magnitude rather than slightly.
    """
    symbol = _ticker_symbol(company_id)
    if not symbol:
        return BridgeSnapshot()

    try:
        ticker = yf.Ticker(symbol)
    except Exception as exc:
        logger.info("No market feed for %s (%s): %s", company_id, symbol, exc)
        return BridgeSnapshot()

    for attr, source in (
        ("quarterly_balance_sheet", "reported_quarter"),
        ("balance_sheet", "reported_fiscal_year"),
    ):
        frame = getattr(ticker, attr, None)
        if frame is None or len(getattr(frame, "columns", [])) == 0:
            continue
        for column in frame.columns:
            snapshot = _build(frame, column, source)
            if snapshot is not None:
                if in_model_units:
                    _scale_snapshot(snapshot, company_id)
                return snapshot

    return BridgeSnapshot()


def _scale_snapshot(snapshot: BridgeSnapshot, company_id: str) -> None:
    """Convert a snapshot from absolute currency into the model's reporting units."""
    try:
        from backend.models.spec.metadata import get_metadata_for_company

        meta = get_metadata_for_company(company_id)
    except Exception:
        return

    divisor = UNIT_DIVISORS.get((meta.currency, meta.units))
    if not divisor:
        return

    snapshot.terms = {k: v / divisor for k, v in snapshot.terms.items()}
    snapshot.total_debt /= divisor
    snapshot.total_liquid_assets /= divisor
    snapshot.net_cash /= divisor


def _ticker_symbol(company_id: str) -> Optional[str]:
    """Market ticker for a company id, including the exchange suffix.

    Resolved from the company registry rather than parsed out of the id, because
    the id is a slug and does not carry the exchange. A retired listing is
    resolved through the same redirect table the price provider uses, so a
    delisted ticker does not leave the bridge on stale figures.
    """
    try:
        from backend.models.spec.metadata import get_metadata_for_company

        ticker = get_metadata_for_company(company_id).ticker
    except Exception:
        ticker = company_id.split("_")[0].upper()
    if not ticker:
        return None

    if company_id.endswith("_us"):
        return ticker

    try:
        from backend.data.providers.market_data import TICKER_REDIRECTS

        # Redirects are keyed by company id, because a retirement is a fact
        # about the company, not about one exchange's spelling of its ticker.
        replacement = TICKER_REDIRECTS.get(company_id)
        if replacement:
            return replacement
    except Exception:
        pass

    for suffix in (".NS", ".BO"):
        try:
            if yf.Ticker(ticker + suffix).income_stmt is not None:
                return ticker + suffix
        except Exception:
            continue
    return ticker + ".NS"

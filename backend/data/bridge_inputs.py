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
    "finance_lease_liabilities": ("Finance Lease", "Capital Lease Obligation"),
    "operating_lease_liabilities": ("Operating Lease Liability",),
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

    # BASIS, matching the convention every market data provider uses for a
    # headline net cash figure:
    #   net cash = (cash + short-term investments) - total debt
    # Non-current investments are NOT netted. They are a real asset but not a
    # cash-equivalent one, and including them makes the platform's net cash
    # irreconcilable with the figure a reader is comparing it against.
    # Reported separately so the amount is still visible.
    if combined_liquid is not None:
        liquid = combined_liquid
    else:
        liquid = values.get("cash_and_bank", 0.0) + values.get("marketable_securities", 0.0)

    # Total debt on the same basis: borrowings plus lease obligations of both
    # kinds. The operating-lease component is separated out below so a reader
    # who discounts cash flows built after rent can deduct only the interest
    # bearing part.
    if combined_debt is not None:
        debt = combined_debt
    else:
        debt = (
            values.get("debt_non_current", 0.0)
            + values.get("debt_current", 0.0)
            + values.get("finance_lease_liabilities", 0.0)
            + values.get("operating_lease_liabilities", 0.0)
        )

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


def fetch_bridge_snapshot(company_id: str) -> BridgeSnapshot:
    """Most recent reported bridge terms for a company, in the model's own units.

    Prefers the latest quarter over the latest year, because a market data
    provider's headline net cash, enterprise value and multiples are all struck
    on the most recent balance sheet. Falls back through the available periods
    so a company that has not filed a quarter is still served from its year.

    The snapshot is scaled into the reporting units the model uses — USD
    millions, INR crores — because the feed reports absolute currency and an
    unscaled figure would enter the bridge a factor of a million too large.
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


# How far a most-recent balance sheet may move from the last filed annual one
# before it is treated as a feed defect rather than a market movement.
#
# Cash, investments and debt do not move by an order of magnitude in two
# quarters, but a FEED defect does: a statement denominated in the wrong
# currency lands 30x out, and a half-populated quarterly statement reports a
# fraction of the real balance. Both were observed, and either one entering the
# bridge silently would be worse than the staleness the snapshot was introduced
# to fix. So the snapshot is checked against the filed accounts and refused if
# it disagrees beyond this band, with the reason recorded.
SNAPSHOT_MIN_RATIO = 0.30
SNAPSHOT_MAX_RATIO = 8.00

# Terms that cannot appear from nothing between two filed statements.
#
# A zero in the filed accounts is a positive statement that the item does not
# exist. An equity claim reported by a feed at the next quarter but absent from
# the most recent filing is a mapping artefact, not a new issue: one large-cap's
# feed reported 18bn of preferred stock against zero in the filed accounts, and
# deducting it moved net cash by more than a fifth. Debt is deliberately NOT in
# this set, because a company really can raise a large amount of it in two
# quarters, and a genuine 4.5x increase was observed and is legitimate.
CANNOT_APPEAR_FROM_ZERO = frozenset({"minority_interest", "preferred_stock"})


def _plausible(snapshot_value: Optional[float], annual_value: float) -> bool:
    """Whether a most-recent balance is a believable movement from the last filed one.

    Cash, investments and debt do not move by an order of magnitude in two
    quarters, but a FEED defect does: a statement denominated in the wrong
    currency lands tens of times out, and a half-populated quarterly statement
    reports a fraction of the real balance. Both were observed.
    """
    if snapshot_value is None:
        return False
    if not isinstance(annual_value, (int, float)) or abs(annual_value) < 1e-6:
        return True
    if snapshot_value == 0.0:
        return False
    ratio = abs(snapshot_value / annual_value)
    return SNAPSHOT_MIN_RATIO <= ratio <= SNAPSHOT_MAX_RATIO


def resolve_bridge_inputs(
    company_id: str,
    annual_terms: dict[str, float],
) -> tuple[Optional[BridgeSnapshot], str]:
    """The bridge terms to use, and why.

    Validation is per TERM, not per snapshot. A snapshot whose debt looks wrong
    does not make its cash and securities wrong, and discarding the whole
    statement because one line moved unusually throws away the freshness that
    matters most. So each term is accepted or refused on its own merits, and a
    refused term falls back to the filed annual figure.

    Returns (None, reason) when nothing usable was found, so the caller can say
    so rather than silently valuing at zero net debt.
    """
    snapshot = fetch_bridge_snapshot(company_id)
    if not snapshot.as_of:
        return None, "no reported balance sheet available from the market feed"

    annual_liquid = annual_terms.get("liquid_assets", 0.0)
    annual_debt = annual_terms.get("total_debt", 0.0)

    refused: list[str] = []
    for term, annual_value in (
        ("cash_and_bank", annual_terms.get("cash_and_bank")),
        ("marketable_securities", annual_terms.get("marketable_securities")),
        ("non_current_investments", annual_terms.get("non_current_investments")),
        ("debt_non_current", annual_terms.get("debt_non_current")),
        ("debt_current", annual_terms.get("debt_current")),
    ):
        if term not in snapshot.terms:
            continue
        if not _plausible(snapshot.terms[term], annual_value or 0.0):
            refused.append(
                f"{term} {snapshot.terms[term]:,.0f} vs filed {annual_value:,.0f}"
                if annual_value
                else f"{term} {snapshot.terms[term]:,.0f} vs filed 0"
            )
            snapshot.terms.pop(term)

    for term in CANNOT_APPEAR_FROM_ZERO:
        value = snapshot.terms.get(term)
        if value and not (annual_terms.get(term) or 0.0):
            refused.append(
                f"{term} {value:,.0f} reported by the feed but absent from the "
                "filed accounts"
            )
            snapshot.terms.pop(term)

    # Recompute the aggregates from whichever terms survived, so the published
    # totals always agree with the terms shown beside them.
    liquid = snapshot.terms.get("cash_and_bank", 0.0) + snapshot.terms.get("marketable_securities", 0.0)
    if not _plausible(liquid, annual_liquid):
        refused.append(f"liquid assets {liquid:,.0f} vs filed {annual_liquid:,.0f}")
        liquid = annual_liquid
        snapshot.terms.pop("cash_and_bank", None)
        snapshot.terms.pop("marketable_securities", None)

    # Debt falls back to the FILED total the moment any component is refused.
    #
    # A partial sum of a debt stack is not a debt total: if the long-term
    # component fails its check, summing the survivors silently understates the
    # obligation by whatever the refused piece was, which overstates equity
    # value by the same amount. The filed total is the only safe fallback.
    debt_terms = (
        "debt_non_current",
        "debt_current",
        "finance_lease_liabilities",
        "operating_lease_liabilities",
    )
    missing = [t for t in debt_terms if t not in snapshot.terms]
    if missing:
        refused.append(
            "debt taken from the filed accounts in full because "
            + ", ".join(missing)
            + " could not be verified"
        )
        debt = annual_debt
    else:
        debt = snapshot.total_debt
        if not _plausible(debt, annual_debt) and annual_debt:
            refused.append(f"total debt {debt:,.0f} vs filed {annual_debt:,.0f}")
            debt = annual_debt

    if not snapshot.terms:
        return None, (
            "most recent balance sheet rejected: " + "; ".join(refused)
            + " — using the filed annual balance sheet instead"
        )

    snapshot.total_liquid_assets = liquid
    snapshot.total_debt = debt
    snapshot.net_cash = liquid - debt

    note = f"most recent reported balance sheet ({snapshot.as_of})"
    if refused:
        note += "; terms taken from the filed annual accounts instead: " + "; ".join(refused)
    return snapshot, note


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

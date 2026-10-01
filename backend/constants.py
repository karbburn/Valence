"""Single source of truth for the platform's structural default constants.

Every one of these used to be an inline literal scattered across the forecast,
valuation and export layers, where the same concept carried two different values
(terminal growth 4.0 in seven files, India tax 25.17 in eight). They are
collected here so there is exactly one definition, one place to audit, and one
place to change.

IMPORTANT — these are FALLBACKS, not targets. The rule everywhere a constant is
used is: use the company's own data when it exists, fall back to the constant
only when the data is genuinely absent, and record in the assumption's `source`
field which of the two happened. A constant must never overwrite a real zero or
a real measured value; see `resolve()`.
"""

from __future__ import annotations

from typing import Optional

# --------------------------------------------------------------------------
# Taxation
# --------------------------------------------------------------------------
# Statutory corporate rates for the two reporting economies Valence supports.
# These are legal definitions, not tuning knobs.
US_STATUTORY_TAX_RATE = 21.0
INDIA_EFFECTIVE_TAX_RATE = 25.17

# --------------------------------------------------------------------------
# Terminal value
# --------------------------------------------------------------------------
# Long-run nominal GDP anchors. A perpetuity cannot grow faster than its
# economy for long, so these bound the terminal growth assumption.
US_TERMINAL_GROWTH = 2.25
INDIA_TERMINAL_GROWTH = 4.0

# Placeholder exit multiple, used only by the secondary exit-multiple view and
# never by the active (Gordon Growth) valuation.
DEFAULT_EXIT_EV_MULTIPLE = 20.0

# --------------------------------------------------------------------------
# Operating drivers — used ONLY when the company has no data for the driver
# --------------------------------------------------------------------------
DEFAULT_EBITDA_MARGIN = 23.0
DEFAULT_EBIT_MARGIN = 20.0
DEFAULT_DA_PCT_REVENUE = 2.9
DEFAULT_DSO_DAYS = 100.0
DEFAULT_DPO_DAYS = 14.0
DEFAULT_CAPEX_PCT_REVENUE = 2.5
DEFAULT_GROSS_MARGIN = 30.0
DEFAULT_DIVIDEND_PAYOUT = 0.40

# Cost of equity used only when live market data is entirely unavailable.
FALLBACK_COST_OF_EQUITY = 13.0

# --------------------------------------------------------------------------
# Guard rails
# --------------------------------------------------------------------------
# A capex ratio above this multiple of D&A is not a steady state; used to clamp
# a distorted starting ratio (e.g. a year that nets M&A into investing CF).
MAX_STEADY_STATE_CAPEX_PCT = 4.0


    # Hard ceiling on a capex-to-revenue ratio, well above any real operating
# business, so a bad proxy cannot produce permanently negative FCFF.
MAX_CAPEX_PCT_REVENUE = 30.0

# Carrying-rate bounds for the debt schedule, percent.
MIN_CARRYING_RATE = 0.5
MAX_CARRYING_RATE = 25.0


def statutory_tax_rate(market: Optional[str]) -> float:
    """Statutory corporate tax rate for a reporting market."""
    return US_STATUTORY_TAX_RATE if market == "us" else INDIA_EFFECTIVE_TAX_RATE


def terminal_growth_for(market: Optional[str]) -> tuple[float, str]:
    """Terminal growth anchor and its basis label for a reporting market."""
    if market == "us":
        return US_TERMINAL_GROWTH, "US long-run nominal GDP"
    return INDIA_TERMINAL_GROWTH, "India long-run nominal GDP"


def resolve(measured: Optional[float], default: float) -> float:
    """Return `measured` when it is a real number, `default` only when absent.

    `0.0` is a legitimate measured value — a company with no inventory, no
    dividends, or a zero effective tax rate genuinely reports it. The idiom
    `measured or default` silently replaces every such zero with the constant,
    which is how a company with a 16-day DSO ended up modelled at 100 days.

    This helper is the replacement for that idiom. Use it everywhere a driver is
    read from a source that may legitimately hold zero.
    """
    if measured is None:
        return default
    try:
        value = float(measured)
    except (TypeError, ValueError):
        return default
    if value != value:  # NaN
        return default
    return value

"""The site gate's leak test, on real served markup.

`withheld_figure_is_presented` is the one place that decides whether a withheld figure has
leaked. It was wrong twice before it was written: an earlier leak sweep and the gate each
carried their own copy of the rule, and they disagreed about `amba_us` and
`idea_idea`, whose refusal sentences legitimately name the figure they refuse.

Testing it here rather than only through a live mutation is a consequence of measurement.
The first attempt at the mutation harness restored the pre-fix `generateMetadata` and waited
for the dev server to serve the leak. It never did: Next caches a route's metadata, so a
change to `generateMetadata` is not observable on a warm dev server, and the harness
reported "never went live" for a mutation that had in fact been applied. A live-only test of
this function can be graded against a stale build, which is exactly the failure this project
keeps paying for. The fixtures below are the strings the servers actually returned.

Every case here is one the two disagreeing implementations got wrong, or would have.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))

from audit_loop import _rsc_removed, withheld_figure_is_presented  # noqa: E402


# What /stock/INFY served BEFORE the fix, quoted from the description the meta probe read.
# Positive figure, phrased as a claim, and no refusal anywhere in the sentence.
LEAKED_DESCRIPTION = (
    '<meta name="description" content="DCF implied value 1,079.32 vs 1,035.00 market '
    '(2026-10-01) at a 12.7% WACC. Full unlevered FCFF model, three scenarios, trading '
    'comps and a 31-tab Excel export, free in the browser.">'
)

# What the same page serves now. The figure is gone and the reason is named.
WITHHELD_DESCRIPTION = (
    '<meta name="description" content="No valuation is published for Infosys Limited '
    '(INFY). inputs_trace_to_a_filing: No filing contributed to this company&#x27;s '
    'historicals, so the valuation is not published as a valuation.">'
)

# What /stock/AMBA serves now. The figure is NAMED, inside the sentence that refuses it.
# This is the case the sign-based rule and the raw substring search each got wrong.
REFUSAL_TEXT = (
    "<p>base: implied share price -62.50 is not positive. This model is withheld rather "
    "than published, so this figure is named here as the reason and shown nowhere "
    "else.</p>"
    "<p>equity_value_positive: base: equity value -2,664 is not positive (enterprise "
    "value -2,967, net debt -313). A negative implied price of -62.50 is not a usable "
    "valuation.</p>"
)

PUBLISHED_KPI = (
    '<div><span>DCF Implied Price</span><div>$156.48</div></div>'
    '<div><span>Market Price</span><div>$233.95</div></div>'
)

# A figure the page legitimately carries as DATA, beside its own refusal. The RSC payload
# is where the client workbench reads the model from, and stripping it is what stops the
# check crying wolf on all twenty-three models.
PAYLOAD = (
    r'<script>self.__next_f.push([1,"{\\"implied_share_price\\":1079.32,'
    r'\\"publication\\":{\\"publishable\\":false}}"])</script>'
)


def test_a_figure_phrased_as_a_claim_is_a_leak():
    offending = withheld_figure_is_presented(LEAKED_DESCRIPTION, ["1,079.32", "1079.32"])
    assert offending, (
        "the gate did not see the exact string /stock/INFY served before the fix. This is "
        "the defect the whole rule exists for, and a check that cannot see it is the "
        "check that would have let it through."
    )


def test_a_figure_absent_is_not_a_leak():
    assert withheld_figure_is_presented(WITHHELD_DESCRIPTION, ["1,079.32", "1079.32"]) == []


def test_a_refusal_may_name_the_figure_it_refuses():
    """The case both earlier implementations got wrong.

    `amba_us` and `idea_idea` name a negative figure in the sentence refusing it. A raw
    substring search reports them as leaks; a sign-based rule exempts every negative number
    on the grounds that nobody reads -62.50 as a valuation, which is a proxy for the real
    test and would wave through `-62.50` presented as a headline.
    """
    assert withheld_figure_is_presented(REFUSAL_TEXT, ["62.50"]) == [], (
        "a refusal that names its figure is the evidence for the refusal. Reporting it as "
        "a leak makes the gate demand the evidence be deleted, and a gate that demands "
        "that gets muted."
    )


def test_the_same_negative_figure_presented_as_a_claim_is_still_a_leak():
    """The sign must not matter. This is why the rule is grammatical, not arithmetic."""
    headline = '<h1>Ambarella implied value -$62.50</h1><p>Base scenario</p>'
    offending = withheld_figure_is_presented(headline, ["62.50"])
    assert offending, (
        "a negative withheld figure was accepted because it is negative. A rule keyed on "
        "the sign exempts whatever the sign happens to be, which is not the property "
        "being protected."
    )


def test_a_published_model_shows_its_figure_and_that_is_not_a_leak():
    # Not a leak by this function's reckoning, which is why the caller gates on the
    # verdict first. Asserted so the two responsibilities stay separated: this function
    # answers "is this figure presented as an answer", never "may it be".
    assert withheld_figure_is_presented(PUBLISHED_KPI, ["156.48"]) != []


def test_the_payload_is_stripped_before_the_check():
    stripped = _rsc_removed(PAYLOAD + REFUSAL_TEXT)
    assert "1079.32" not in stripped, (
        "the payload was not removed, so every withheld page reports a leak and the gate "
        "becomes noise"
    )
    assert withheld_figure_is_presented(stripped, ["1,079.32", "1079.32"]) == []


def test_the_payload_alone_would_have_been_reported_as_a_leak():
    """The reason the strip exists, asserted so it cannot be removed as redundant.

    Without the strip this returns a finding, and every one of the twenty-three shipped
    models produces one. That is not a hypothetical: it is what the first version of the
    sweep did.
    """
    assert withheld_figure_is_presented(PAYLOAD, ["1079.32"]) != []


@pytest.mark.parametrize("figure", ["1,079.32", "1079.32"])
def test_both_renderings_of_one_figure_are_caught(figure):
    """A currency amount appears in a value with a separator and in prose without.

    Checking one form is how a check passes on a page that renders the other, and the
    rupee and dollar locales differ on which they use.
    """
    html = f"<p>DCF implied value {figure} against the last close.</p>"
    assert withheld_figure_is_presented(html, ["1,079.32", "1079.32"]) != []

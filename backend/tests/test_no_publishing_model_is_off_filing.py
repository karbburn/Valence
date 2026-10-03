"""The launch invariant, checked against what is SERVED rather than what is intended.

`test_publication_requires_a_filing.py` proves the check works. This proves the outcome, on
the payload a reader actually receives. Those are different surfaces and both have failed
here: a gate has reported a clean pass while examining an empty set, and a model has been
withheld by a check that never found its subject.

One invariant, and it is the whole launch bar:

    NO PUBLISHING MODEL MAY DECLARE NON-FILING-DERIVED BALANCE-SHEET INPUTS.

Measured at 2026-10-03, 23 shipped models:

    publishing, balance_sheet_source = filed_annual_balance_sheet   9
    publishing, anything else                                      0   <- the invariant
    withheld,  market_feed_statement                              11
    withheld,  filed_annual_balance_sheet                           3

The 11 feed-sourced models are every India model plus tsm_us, and every one of them is
withheld with a stated reason. So the engine's breadth is currently paid for out of its own
published surface: it builds 23 companies and shows 9.

Why this is asserted at the payload level rather than per model:

  * `balance_sheet_source` lives on the bridge, not on individual inputs. A first version of
    this check looked for a per-input `source` dict, found none, and would have reported
    "no feed sources at all" -- a clean pass for a check that had examined nothing. That is
    the same failure as the audit loop that reported "all 0 sitemap pages resolve".
  * The intersection is the claim. "11 models read a feed" is only alarming if any of them
    is visible; only the intersection with `publishable` says whether a reader can see an
    unfiled figure.
  * It is a per-payload assertion, so it holds as models are added rather than describing
    today's set.

Tests skip when no server is running, so they never turn a developer's machine red for the
wrong reason -- and say so when they skip, rather than passing quietly.
"""

from __future__ import annotations

import json
import urllib.error
import urllib.request

import pytest

API = "http://127.0.0.1:8111"
FILED = "filed_annual_balance_sheet"
# The only non-filing declaration the engine makes for balance-sheet inputs. Anything else
# on a publishing model is a defect; this is named so the test fails loudly if a new one
# appears rather than passing on an unrecognised string.
FEED = "market_feed_statement"


def _shipped_ids():
    """Company ids the engine itself considers shipped.

    Taken from the gate's own helper so this cannot drift from what ships.
    """
    from scripts.audit_loop import _shipped_ids as gate_ids
    return gate_ids()


def _payload(cid):
    """The served model.

    The model is at the TOP LEVEL of the response -- there is no "model" key. Reading it
    under one, as a wrapped response would be, returns None and every assertion below then
    fails on `None.get(...)`. That is the same mistake the audit loop's page probe made and
    corrected (OPEN_DEFECTS section 7b): it raised KeyError on every probe and skipped them
    all, reporting success over an empty set.
    """
    req = urllib.request.Request(f"{API}/api/model/{cid}",
                                 headers={"x-valence-build": "1"})
    with urllib.request.urlopen(req, timeout=300) as r:
        payload = json.loads(r.read().decode("utf-8"))
    model = payload.get("model", payload)
    assert isinstance(model, dict) and "publication" in model, (
        "%s returned %r, which is not a model payload" % (cid, type(payload).__name__)
    )
    return model


def _live_models():
    """(cid, model) for every shipped model, or a skip if no server is listening.

    Called from inside tests and fixtures, NEVER at module scope. The first version of this
    file was parametrised over `_live_models()` in the `@pytest.mark.parametrize` decorator,
    which evaluates it during COLLECTION -- and calling `pytest.skip` there aborts the whole
    module. In CI, where no backend runs, that turned into "1 error during collection" and
    failed the run with exit code 2 rather than skipping.

    So the skip is raised where it is meaningful: inside a test, which reports as a skip and
    leaves the rest of the suite running.
    """
    try:
        urllib.request.urlopen(f"{API}/api/model/aapl_us", timeout=30)
    except urllib.error.HTTPError:
        pass  # a 404 still proves something is listening
    except Exception as exc:  # noqa: BLE001
        pytest.skip("no backend on %s (%s); this checks the SERVED payload, so it has "
                    "nothing to say without one" % (API, type(exc).__name__))
    out = []
    for cid in _shipped_ids():
        try:
            out.append((cid, _payload(cid)))
        except Exception as exc:  # noqa: BLE001
            pytest.fail("served model %s could not be read: %s"
                        % (cid, type(exc).__name__))
    assert out, "no shipped models were read, so these checks would be vacuous"
    return out


def _bridge_source(model):
    """`balance_sheet_source` from the first valuation that declares one."""
    for v in model.get("valuation") or []:
        src = (v.get("dcf_bridge") or {}).get("balance_sheet_source")
        if isinstance(src, str) and src:
            return src
        if isinstance(src, dict):
            joined = ",".join(sorted({x for x in src.values()
                                      if isinstance(x, str) and x}))
            if joined:
                return joined
    return None


class TestNoPublishingModelIsOffFiling:
    """One assertion per shipped model, gathered at run time rather than at collection.

    Parametrising over live data is the natural way to write this and it is wrong here: the
    parameter list is built during collection, before any test runs, so it cannot skip
    gracefully and it hits the network before the suite has decided to. Gathering inside the
    test keeps collection pure and lets the skip behave.
    """

    def test_it_does_not_publish_with_a_non_filing_balance_sheet(self):
        offenders = []
        for cid, model in _live_models():
            source = _bridge_source(model)
            publishable = bool((model.get("publication") or {}).get("publishable"))
            if publishable and source != FILED:
                offenders.append("%s (source=%r)" % (cid, source))
        assert not offenders, (
            "these models PUBLISH while declaring balance-sheet inputs no filing "
            "supplied. A reader would see a valuation they cannot trace to a document. "
            "Either file the inputs or withhold the model -- publishing this is not "
            "acceptable: %s" % offenders
        )

    def test_a_withheld_model_says_why(self):
        silent = []
        for cid, model in _live_models():
            publication = model.get("publication") or {}
            if not publication.get("publishable") and not publication.get("reasons"):
                silent.append(cid)
        assert not silent, (
            "these models are withheld but give no reason, so the page cannot tell a "
            "reader why. A silent withholding reads as a broken product: %s" % silent
        )


class TestThePublishedSurfaceIsReal:
    """Guards against this file passing because it examined nothing."""

    def test_something_is_published_and_something_is_withheld(self):
        models = _live_models()
        pub = [c for c, m in models if (m.get("publication") or {}).get("publishable")]
        held = [c for c, m in models if not (m.get("publication") or {}).get("publishable")]
        assert pub, "no model publishes, so the invariant above holds vacuously"
        assert held, "no model is withheld, so the withholding rules are untested"

    def test_every_bridge_declares_where_its_inputs_came_from(self):
        """A model that declares no source at all has not been checked.

        Without this, a model whose `balance_sheet_source` went missing would read as
        "not equal to filed" and be reported correctly by accident -- but a reader-facing
        claim of provenance would also be silently absent.
        """
        models = _live_models()
        missing = [c for c, m in models if _bridge_source(m) is None]
        assert not missing, (
            "these models declare no balance_sheet_source, so their provenance is "
            "unstated: %s" % missing
        )
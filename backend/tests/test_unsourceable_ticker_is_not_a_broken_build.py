""""Not available" must be raised as `NoFinancialsAvailable`, never as ValueError.

The API already draws the line, and `backend/data/errors.py` states why in full: a
listed ticker with no filing in reach is an ordinary outcome worth retrying and
worth showing a user as a message, while "the build broke" is a fault. Only the
first deserves 503. Both used to surface as 500, so a screen full of unsourceable
tickers looked exactly like a broken service and the stack traces that would have
explained the real faults were buried among them.

`resolve_cik` broke that again in a narrower way. A ticker absent from SEC's own
`company_tickers.json` is precisely the first category, and it raised `ValueError`.
At the route that is an ordinary Exception, so:

    raise HTTPException(status_code=422 if "No canonical" in str(e) or
                        "unmapped" in str(e) else 500,
                        detail="Failed to build model. See server logs for details.")

"Could not resolve SEC CIK for 'cwdv_us'" contains neither phrase, so the answer
was 500 with a stack trace for a company that simply has no filing on file.

Measured on 2026-10-02 across a 50-company sweep: CWDV answered 500 while
MPLT, RYZ, HBCP and INDP answered 503 for the identical condition, minutes apart,
in the same run. Same state, two answers, and only the wrong one manufactures a
fault to go hunting.

Mutation-checked. Restoring `ValueError` fails these tests; so does having the
route's 422/500 decision made by substring matching on the message.
"""

from __future__ import annotations

import inspect
import pathlib
import re
import sys

import pytest

REPO = pathlib.Path(__file__).resolve().parents[2]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

from backend.data.errors import NoFinancialsAvailable  # noqa: E402
from backend.data.ingestion.sec_edgar import resolve_cik  # noqa: E402

SEC_EDGAR = (REPO / "backend" / "data" / "ingestion" / "sec_edgar.py").read_text(
    encoding="utf-8"
)
ROUTES = (REPO / "backend" / "api" / "routes.py").read_text(encoding="utf-8")


class TestResolveCikRaisesNotAvailableNotBroken:
    def test_an_unlisted_ticker_raises_not_available(self):
        """The behaviour, not the source text: a ticker SEC does not list.

        `Zzzz` is chosen because it cannot be in the ticker file. If SEC is
        unreachable this still holds, since the fallback table has no such entry
        either -- so the assertion does not depend on the network.
        """
        with pytest.raises(NoFinancialsAvailable):
            resolve_cik("zzzz_us")

    def test_the_error_names_the_ticker_and_the_registry(self):
        """The message must still tell an operator what to do.

        Swapping the type is not permission to lose the instruction. This is how a
        caller learns the ticker needs adding to CIK_REGISTRY.
        """
        try:
            resolve_cik("zzzz_us")
        except NoFinancialsAvailable as exc:
            text = str(exc)
            assert "zzzz_us" in text, "the error does not name the company"
            assert "CIK_REGISTRY" in text, "the error does not say how to fix it"
        else:
            pytest.fail("an unlisted ticker resolved successfully")

    def test_it_is_not_also_a_value_error(self):
        """`NoFinancialsAvailable` must not be catchable as ValueError.

        A route that says `except ValueError` would still treat this as a fault
        even after the type is corrected, which is the same 500 by another route.
        """
        assert not issubclass(NoFinancialsAvailable, ValueError), (
            "NoFinancialsAvailable is a ValueError subclass, so any handler "
            "catching ValueError catches it too and the distinction is lost again"
        )

    def test_the_resolve_function_raises_no_bare_value_error(self):
        """Structural guard on the raise inside resolve_cik itself.

        Commented `#` prose is stripped first, so this cannot be satisfied by the
        explanation of the defect that sits directly above the raise.
        """
        i = SEC_EDGAR.index("def resolve_cik(")
        # Bound by the next top-level `def`, not a decorative comment rule: the
        # marker this used to look for ("\n# ---") is not present after every
        # function, and a missing delimiter raised ValueError from inside the test
        # -- which is precisely the exception type this file exists to keep out of
        # the failure path.
        rest = SEC_EDGAR[i + 1:]
        j = i + 1 + rest.index("\ndef ") if "\ndef " in rest else len(SEC_EDGAR)
        body = re.sub(r"#.*$", "", SEC_EDGAR[i:j], flags=re.M)
        assert "raise ValueError" not in body, (
            "resolve_cik raises a bare ValueError again, which the route reports "
            "as 500 'Failed to build model' for a company that merely has no filing"
        )
        assert "raise NoFinancialsAvailable" in body, (
            "resolve_cik no longer raises NoFinancialsAvailable at all"
        )


class TestTheRouteStopsDecidingBySubstring:
    def test_the_500_branch_does_not_depend_on_matching_words_in_a_message(self):
        """The 500 must come from a failure type, not from vocabulary.

        The route used to say
        `422 if "No canonical" in str(e) or "unmapped" in str(e) else 500`.
        Classifying by SUBSTRING means rewording any error message reclassifies
        it, and every future "not available" error whose text lacks those two
        phrases becomes a 500. CWDV was exactly that.
        """
        executable = re.sub(r"#.*$", "", ROUTES, flags=re.M)
        for phrase in ('"No canonical" in str(e)', '"unmapped" in str(e)',
                       '"unmapped" in str(', '"No canonical" in str('):
            assert phrase not in executable, (
                "the route classifies failures by searching the exception message "
                "for %r, so a reworded or newly-typed error is reported as a broken "
                "build instead of missing data" % phrase
            )
        assert "isinstance(e, ValueError)" in ROUTES, (
            "the 422/500 decision is no longer made from the exception type, so "
            "the same vocabulary-based classification is in play under a new form"
        )

    def test_not_available_is_converted_to_503_everywhere_it_is_caught(self):
        """Every place that converts this must convert it the same way.

        `_get_hist_model` and `_build_spec_locked` each hold a
        `except NoFinancialsAvailable` that answers 503. A third caller added
        without one would reintroduce a 500 for the same condition.
        """
        conversions = ROUTES.count("except NoFinancialsAvailable")
        assert conversions >= 2, (
            f"only {conversions} conversion(s) of NoFinancialsAvailable found; "
            "the driver-override endpoints call _get_hist_model directly and were "
            "answering 500 before that function converted the error"
        )
        assert ROUTES.count("status_code=503") >= conversions, (
            "a NoFinancialsAvailable handler exists that does not answer 503"
        )

    def test_the_detail_message_a_client_sees_is_stable(self):
        """A user must not see a stack-trace invitation for missing data.

        "See server logs for details" is the tell: it tells the reader the request
        broke the service, which is false for a ticker with no filing.
        """
        i = ROUTES.index("except NoFinancialsAvailable")
        block = ROUTES[i:i + 700]
        assert "No financial statements could be sourced" in block, (
            "the 503 body changed; a client that matches on this string is the "
            "only reason a client could tell 'not ready' from 'broken'"
        )
        assert "See server logs" not in block, (
            "the 503 for missing financials invites the reader to read server "
            "logs, which tells them the service broke when it did not"
        )
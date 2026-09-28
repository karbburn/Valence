"""Errors that mean "not available", as distinct from "broken".

An engine that covers every listed ticker will meet a great many tickers it
cannot yet value: a foreign ordinary with no filing in reach, a recent listing
with no annual report, a delisted symbol still in the index. That is an ordinary
outcome and it deserves its own answer, because the alternative is a request that
crashes.

The distinction matters to a caller. "No financials yet" is worth retrying and
worth showing to a user as a message. "The build broke" is a fault, and answering
it with the same response hides a real failure behind a plausible one. Both used
to surface as 500, so a screen full of listed-but-unsourceable tickers looked
exactly like a broken service, and the stack traces that would have explained the
real faults were buried among them.

Kept in a module of its own so both the ingestion layer and the statement
assembly can raise it without importing each other.
"""

from __future__ import annotations


class NoFinancialsAvailable(Exception):
    """No provider and no local export could supply statements for a company.

    Raised when a company is listed but nothing behind it is sourceable yet, and
    also when statements were fetched but carry no revenue line, so no model can
    be built from them. Both are temporary, unremarkable, and answerable with a
    retry rather than a stack trace.
    """

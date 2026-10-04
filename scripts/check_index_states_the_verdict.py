"""The index must not overstate what the site publishes.

The /stock index labelled every compiled model "Ready". Fourteen of the twenty-three
compiled models open on a page that publishes no valuation, so on a list of 161 rows that
read as "25 published valuations" when the truth was nine. The chip was the surface meant
to support the product's central claim, and it overstated it.

The fix reads the verdict into the manifest rather than letting the index guess, which
introduces a second place that answers the same question. So this asserts the two agree,
on every shipped model, against the endpoint that is authoritative:

    /api/companies/manifest   publishable per company, from the snapshot on disk
    /api/model/{id}           the verdict served with the model

Those two are computed by different code on purpose -- one parses a JSON snapshot, the other
runs `_publication_verdict` over a live spec -- and a manifest that quietly disagreed would
put the index and the page it links to in contradiction on the same screen.

Run against a local backend on :8111. Skips, loudly, without one: a skipped gate and a
passing one look identical in CI output, and this file exists because a check that cannot
fail has already been mistaken for one that cannot be trusted.
"""
from __future__ import annotations

import json
import sys
import urllib.request

API = "http://127.0.0.1:8111"


def get(path: str, timeout: int = 600):
    req = urllib.request.Request(f"{API}{path}", headers={"x-valence-build": "1"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode("utf-8"))


def main() -> int:
    try:
        manifest = get("/api/companies/manifest?offset=0&limit=500")
    except Exception as exc:
        print(f"SKIPPED, NOT PASSED: no backend on {API} ({type(exc).__name__}).")
        print("This gate did not run. A skip here is not evidence about the manifest.")
        return 2

    compiled = [c for c in manifest.get("companies") or [] if c.get("has_model")]
    if not compiled:
        print("FAIL: the manifest reports no compiled model, so nothing was compared.")
        return 1

    disagreements = []
    published = withheld = 0
    for company in compiled:
        cid = company["company_id"]
        served = bool((get(f"/api/model/{cid}").get("publication") or {}).get("publishable"))
        listed = company.get("publishable")

        if listed is None:
            disagreements.append(
                f"{cid}: has a compiled model but the manifest says publishable=null. "
                f"The index would render it as withheld, which is a claim about a model "
                f"the site does serve."
            )
            continue
        if bool(listed) != served:
            disagreements.append(
                f"{cid}: the index says publishable={listed}, the model endpoint says "
                f"{served}. The row and the page it links to contradict each other."
            )
            continue
        if served:
            published += 1
        else:
            withheld += 1

    print(f"compared {len(compiled)} compiled models against /api/model")
    print(f"  published {published}, withheld {withheld}")
    if disagreements:
        for d in disagreements:
            print(f"  FAIL {d}")
        return 1
    if withheld == 0:
        print("  FAIL: nothing is withheld. A gate that has never seen the other branch")
        print("        cannot be trusted on the branch that matters.")
        return 1
    if published == 0:
        print("  FAIL: nothing publishes. The index would claim the site withholds all of")
        print("        them, which is as much a misstatement as the reverse.")
        return 1
    print("  CLEAN: the index states, per row, what the model endpoint will serve.")
    return 0


if __name__ == "__main__":
    sys.exit(main())

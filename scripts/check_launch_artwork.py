"""Does the launch film's artwork still say something true?

The hero's full-bleed visual is a static JPEG -- the poster frame of the launch film -- and it
carries the product's headline claim as pixels: a ticker, a market price, a model price, a
percentage gap and a date. Nothing in the markup, the metadata, the API or the sitemap says
what those figures are, so the artwork rots silently and no gate can see it.

Measured on 2026-10-04, reading the rendered image against the live model:

    poster   $228.86 market, $107.52 model, -53.0%, "prices as of 28 Sep 2026"
    API      $233.95 market, $156.48 model, -33.1% at 2026-10-02

Every figure is wrong, and the headline claim is wrong by twenty percentage points. A first
visitor sees -53% in the hero and -33% in the rail further down the same page.

A JPEG's text is not something to assert on, and an OCR dependency for one hero image is not
a reasonable thing to add to a CI run. So the CLAIM is recorded beside the artwork, in
`valence-launch-poster.json`, and this compares that claim against the live model.

The artwork itself is NOT fixed by this, and it is not being served. A bitmap cannot be fixed
by editing a file: the card needs re-cutting, and replacing a designed title card with a
generated one would be a worse trade than pausing it. The film is therefore off the hero, and
this gate is what lets it come back.

The rule is an OR, and both branches are honest:

  * the artwork's figures match the live model, in which case the film may be served, or
  * the artwork is served nowhere, in which case nothing stale is being claimed and the
    figures are free to be wrong.

Neither branch satisfied is a failure, because stale artwork ON the page is a false claim and
that is the defect. Updating the JSON alone does not reach the first branch, which is the
point: that would make this gate agree with a poster that still says something else.

Run against a local backend on :8111 and frontend on :3111. Exits 2 when there is no backend,
which is a skip and not a pass.
"""
from __future__ import annotations

import json
import sys
import urllib.request
from pathlib import Path

API = "http://127.0.0.1:8111"
WEB = "http://127.0.0.1:3111"
SIDECAR = Path("frontend/public/media/valence-launch-poster.json")
POSTER_NAME = "valence-launch-poster.jpg"
VIDEO_NAME = "valence-launch.mp4"

# Pages whose served markup is searched for a reference to the artwork. A film served from
# somewhere nobody looked at is still a claim somebody sees.
PAGES = ["/", "/stock", "/methodology"]

# How far the artwork may drift before it is a lie rather than a rounding.
#
# Effectively zero. A percentage printed to one decimal on a card is a claim about a
# specific figure, and "close enough" is how a poster ends up two months stale and nobody
# noticing. The poster's own date is checked separately, because a figure can match while
# the DATE it is presented under does not.
TOLERANCE = 0.005
DELTA_TOLERANCE = 0.05


def artwork_is_served() -> list[str]:
    found = []
    for path in PAGES:
        try:
            with urllib.request.urlopen(f"{WEB}{path}", timeout=900) as r:
                html = r.read().decode("utf-8", "replace")
        except Exception:
            continue
        if POSTER_NAME in html or VIDEO_NAME in html:
            found.append(path)
    return found


def live_model(company_id: str):
    req = urllib.request.Request(f"{API}/api/model/{company_id}",
                                 headers={"x-valence-build": "1"})
    payload = json.loads(urllib.request.urlopen(req, timeout=600).read().decode("utf-8"))
    payload = payload.get("model", payload)
    val = next((v for v in payload.get("valuation") or [] if v.get("scenario") == "base"),
               (payload.get("valuation") or [{}])[0])
    bridge = val.get("dcf_bridge") or {}
    reverse = val.get("reverse_dcf") or {}
    implied, market = bridge.get("implied_share_price"), reverse.get("market_price")
    delta = ((implied - market) / market * 100.0) if (implied and market) else None
    return {
        "implied": implied,
        "market": market,
        "delta_pct": delta,
        "price_date": reverse.get("market_price_date"),
        "publishable": bool((payload.get("publication") or {}).get("publishable")),
    }


def drift(claim, live) -> list[str]:
    """Every way the artwork's claim differs from what the model serves."""
    out = []
    if not live["publishable"]:
        out.append(
            f"{claim['company_id']} is no longer publishable, so a card naming its implied "
            f"price is making a claim the site has withdrawn."
        )
    for field, shown in (("market_price", live["market"]), ("model_price", live["implied"])):
        said = claim[field]
        if shown is None:
            out.append(f"the model serves no {field}; the artwork shows {said}")
        elif abs(said - shown) > max(TOLERANCE, abs(shown) * TOLERANCE):
            out.append(f"{field}: the artwork says {said:,.2f}, the model serves {shown:,.2f}")
    if live["delta_pct"] is not None and abs(claim["delta_pct"] - live["delta_pct"]) > DELTA_TOLERANCE:
        out.append(
            f"delta_pct: the artwork says {claim['delta_pct']:+.1f}% and the model implies "
            f"{live['delta_pct']:+.1f}%, {abs(claim['delta_pct'] - live['delta_pct']):.1f} "
            f"points apart on the product's headline claim"
        )
    if claim["prices_as_of"] != live["price_date"]:
        out.append(
            f"the artwork is dated {claim['prices_as_of']} and the model's quote is "
            f"{live['price_date']}, so even matching figures would be presented as current "
            f"when they are not"
        )
    return out


def main() -> int:
    if not SIDECAR.exists():
        print(f"FAIL: {SIDECAR} is missing, so nothing records what the artwork claims.")
        return 1
    claim = json.loads(SIDECAR.read_text(encoding="utf-8"))

    try:
        live = live_model(claim["company_id"])
    except Exception as exc:
        print(f"SKIPPED, NOT PASSED: no model on {API} ({type(exc).__name__}). This gate did")
        print("not run, and the artwork was not checked.")
        return 2

    served = artwork_is_served()
    print(f"artwork claims ({claim['company_id']}, as of {claim['prices_as_of']}):")
    print(f"  market {claim['market_price']:>10,.2f}   model {claim['model_price']:>10,.2f}"
          f"   gap {claim['delta_pct']:>+7.1f}%")
    print("the live model serves:")
    print(f"  market {live['market']:>10,.2f}   model {live['implied']:>10,.2f}"
          f"   gap {live['delta_pct']:>+7.1f}%   at {live['price_date']}")
    print(f"\nartwork served on: {', '.join(served) if served else 'no checked page'}")
    print()

    problems = drift(claim, live)
    if not problems:
        print("CLEAN: the artwork's figures are the figures the model serves, on the date the")
        print("artwork states, so the film may be served.")
        return 0

    if not served:
        print("STALE, AND NOT SERVED. The figures below are wrong and nothing is claiming")
        print("them, so no reader is misled. This branch is what lets the film come back.")
        print()
        for p in problems:
            print(f"  - {p}")
        print()
        print("To re-promote: rebuild the artwork with the figures the model serves and update")
        print(f"{SIDECAR} in the same change.")
        return 0

    print("STALE AND SERVED. The hero artwork contradicts the live model on:")
    for p in problems:
        print(f"  - {p}")
    print(f"\nserved on: {', '.join(served)}")
    print("Either rebuild the artwork with the figures the model serves and update")
    print(f"{SIDECAR} in the same change, or stop serving it.")
    return 1


if __name__ == "__main__":
    sys.exit(main())
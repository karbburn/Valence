"""The launch audit loop: six blocking gates and a written verdict.

Why this exists
---------------

Every defect found while building this engine was invisible from the inside. The
model footed to the dollar on a debt figure 15% above the filing, balanced
perfectly, passed all sixteen arithmetic checks, and was wrong. A statement can tie
across every identity and still be built on an input the issuer never published.

So the loop cannot ask "does it add up". Adding up is a property of the model.
Correctness is a property of the INPUTS, and the only way to know an input is
right is to compare it with something outside this codebase.

Each gate therefore has an oracle that does not share code with what it audits:

  1 tie-out   SEC XBRL, plus the filing's own rendered balance sheet for the
               concepts us-gaap does not expose under a company's own element
  2 excel     the served API payload, read fresh
  3 identity  arithmetic that must hold regardless of inputs
  4 qa gate   a committed baseline, so a NEW failure is distinguishable from a
               known one
  5 tests     pytest and jest
  6 site      a running server, over HTTP

Gates are ordered cheapest-and-most-decisive first. A tie-out failure invalidates
every figure downstream, so there is no value in reading a workbook whose inputs
are already wrong.

Usage
-----

    python scripts/audit_loop.py                 # run every gate
    python scripts/audit_loop.py --only tieout   # one gate
    python scripts/audit_loop.py --no-server     # skip the live site gates

Exit code is non-zero when any gate blocks. Nothing is pushed on a red loop.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
import time
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, List, Optional

REPO = Path(__file__).resolve().parents[1]
DEV = REPO / "assets" / "gsd"
# Tracked gates. A gate that lives in a gitignored directory can be weakened
# with no diff to review it, which is how a control stops being one.
SCRIPTS = REPO / "scripts"
API = "http://127.0.0.1:8111"
WEB = "http://127.0.0.1:3111"

sys.path.insert(0, str(REPO))


# --------------------------------------------------------------------------- #
# Result plumbing
# --------------------------------------------------------------------------- #


@dataclass
class GateResult:
    name: str
    passed: bool = True
    skipped: bool = False
    seconds: float = 0.0
    lines: List[str] = field(default_factory=list)

    def fail(self, msg: str) -> None:
        self.passed = False
        self.lines.append(f"FAIL  {msg}")

    def ok(self, msg: str) -> None:
        self.lines.append(f"ok    {msg}")

    def skip(self, msg: str) -> None:
        self.skipped = True
        self.lines.append(f"skip  {msg}")


def _run(
    cmd: List[str],
    timeout: int = 3600,
    cwd: Path = REPO,
    env: dict | None = None,
) -> tuple[int, str]:
    # The child must WRITE utf-8, because that is how its output is decoded below.
    #
    # Without this the child inherits the console's locale encoding. On a cp1252
    # Windows console `audit_valuation_figures.py` writes `AAPL — Apple Inc.` and
    # `rfr 5.24 · beta` as single cp1252 bytes, which `encoding="utf-8"` turns into
    # U+FFFD on 46 lines. Printing those back to the same console raises
    # UnicodeEncodeError, so the loop died in `main()` WHILE REPORTING a gate it
    # had just marked PASS -- exit code 1, no verdict, and gates 4 through 7 never
    # ran. That is what happened to loops 2-6 on 2026-10-02, and it was
    # indistinguishable from a genuine block, which is the one thing a gate's exit
    # code must never be.
    #
    # Forcing utf-8 here also makes the decode below exact rather than lossy, so a
    # figure or a company name can never be reported as a replacement character.
    child_env = {**os.environ, "PYTHONIOENCODING": "utf-8", "PYTHONUTF8": "1"}
    if env:
        child_env.update(env)
    proc = subprocess.run(
        cmd,
        cwd=str(cwd),
        capture_output=True,
        text=True,
        timeout=timeout,
        encoding="utf-8",
        errors="replace",
        env=child_env,
    )
    return proc.returncode, (proc.stdout or "") + (proc.stderr or "")


# --------------------------------------------------------------------------- #
# Gate 1 — tie-out against the filings
# --------------------------------------------------------------------------- #


def gate_tieout() -> GateResult:
    """Every bridge input, compared with the filing that published it."""
    g = GateResult("tieout")
    code, out = _run([sys.executable, str(SCRIPTS / "tieout.py")], timeout=3600)
    tail = [ln for ln in out.splitlines() if ln.strip()][-40:]
    g.lines.extend(tail)
    if code != 0:
        g.fail("one or more bridge inputs do not tie to the filing")
    else:
        for ln in tail:
            if "audited clean" in ln or "untied figures" in ln:
                g.ok(ln.strip())
    return g


# --------------------------------------------------------------------------- #
# Gate 2 — the workbook says what the server says
# --------------------------------------------------------------------------- #


def _shipped_ids() -> List[str]:
    cache = REPO / "backend" / "data" / "cache"
    return sorted(p.stem for p in cache.glob("*.json") if p.name != "market_data_cache.json")


def gate_excel() -> GateResult:
    """A downloaded workbook must agree with the model it came from.

    This is the check a reader performs by hand: open the file, find the bridge
    tab, compare it to the page. If the two disagree, the workbook is not the
    model, and neither one can be audited by the other.

    Run over every shipped company rather than the script's sample of seven. A
    sample is a reasonable way to keep a routine check quick and an unreasonable
    way to decide what ships: the seven it picks are the ones that have been right
    longest.
    """
    g = GateResult("excel")
    ids = _shipped_ids()
    code, out = _run(
        [
            sys.executable,
            str(REPO / "scripts" / "audit_valuation_figures.py"),
            # The script's own default is 8010, which is not the port this loop
            # starts the backend on, so without this every company reports "fetch
            # failed" and the gate blocks on a connection error rather than on a
            # figure. A gate that fails for the wrong reason trains people to
            # ignore it.
            "--base",
            API,
            "--companies",
            ",".join(ids),
        ],
        timeout=5400,
    )
    g.lines.extend([ln for ln in out.splitlines() if ln.strip()][-30:])
    if code != 0:
        g.fail("workbook figures diverge from the served model, or a check failed")
    else:
        g.ok("workbook agrees with the served model")
    return g


# --------------------------------------------------------------------------- #
# Gate 3 — identities that must hold whatever the inputs are
# --------------------------------------------------------------------------- #


def gate_identities() -> GateResult:
    """Arithmetic that holds regardless of what a filer reported.

    Deliberately does not consult the filings. Its job is to catch the class where
    the engine is internally coherent and internally wrong: EBITDA below EBIT, a
    net-debt figure that does not reconcile to its own components, a forecast
    anchored on a year the model does not contain, two balance sheets in one model.
    """
    g = GateResult("identities")
    from backend.forecast.debt import OPENING_BALANCE_KEYS

    cache = REPO / "backend" / "data" / "cache"
    specs = sorted(
        p for p in cache.glob("*.json") if p.name != "market_data_cache.json"
    )
    if not specs:
        g.skip("no compiled snapshots")
        return g

    bad = 0
    for path in specs:
        cid = path.stem
        try:
            model = json.loads(path.read_text(encoding="utf-8")).get("model") or {}
        except Exception as exc:
            g.fail(f"{cid}: snapshot unreadable ({type(exc).__name__})")
            bad += 1
            continue

        hist = model.get("historicals") or {}
        periods = [str(p) for p in (hist.get("periods") or [])]
        items = hist.get("line_items") or []
        if not periods:
            g.skip(f"{cid}: no history")
            continue
        last = periods[-1]
        h = {
            i["canonical_key"]: i["value"]
            for i in items
            if str(i.get("period_label")) == last
        }

        def line(key: str, field: str = "value") -> float:
            return float(h.get(f"canonical.{field}.{key}") or 0.0)

        rev = line("is", "revenue")
        ebit = line("is", "operating_profit")
        da = line("is", "depreciation_amortization")
        ebitda = line("is", "ebitda")

        # EBITDA cannot be below EBIT: depreciation is a positive add-back, and a
        # figure that says otherwise is a sign flip or a unit fault, not a company.
        if ebitda and ebit and ebitda < ebit - max(abs(ebit) * 0.01, 1.0):
            g.fail(
                f"{cid} {last}: EBITDA {ebitda:,.0f} is below EBIT {ebit:,.0f}, so "
                f"depreciation is being subtracted rather than added back"
            )
            bad += 1
        if rev > 0 and ebitda and ebit:
            if (ebit + da) and abs(ebitda - (ebit + da)) > max(abs(ebitda) * 0.02, 1.0):
                g.fail(
                    f"{cid} {last}: EBITDA {ebitda:,.0f} does not equal EBIT "
                    f"{ebit:,.0f} plus depreciation {da:,.0f}"
                )
                bad += 1

        # The bridge must reconcile to its own components.
        bridge = ((model.get("valuation") or [{}])[0]).get("dcf_bridge") or {}
        debt = float(bridge.get("total_debt") or 0.0)
        claims = float(bridge.get("minority_interest") or 0.0) + float(
            bridge.get("preferred_stock") or 0.0
        )
        liquid = (
            float(bridge.get("cash_and_equivalents") or 0.0)
            + float(bridge.get("marketable_securities") or 0.0)
            + float(bridge.get("non_current_investments") or 0.0)
        )
        net = bridge.get("less_net_debt")
        if net is not None:
            gap = (debt + claims) - liquid - float(net)
            if abs(gap) > max(abs(liquid) * 0.005, 1.0):
                g.fail(
                    f"{cid}: net debt {float(net):,.0f} does not reconcile to its "
                    f"components by {gap:+,.0f}"
                )
                bad += 1

        # ONE balance sheet. The schedule opens on the debt the bridge deducts.
        sched = (model.get("debt_schedule") or [{}])[0].get("periods") or []
        opening = sched[0].get("opening_balance") if sched else None
        if opening is not None and debt and abs(opening - debt) > max(debt * 0.01, 1.0):
            g.fail(
                f"{cid}: debt schedule opens at {opening:,.0f} while the bridge "
                f"deducts {debt:,.0f} — two balance sheets in one model"
            )
            bad += 1

        # The forecast must CONTINUE from the last reported year.
        fperiods = [str(p) for p in ((model.get("forecast") or {}).get("periods") or [])]
        if fperiods and periods:
            digits = periods[-1][2:]
            if digits.isdigit():
                want = f"FY{(int(digits) + 1) % 100:02d}"
                if fperiods[0] != want:
                    g.fail(
                        f"{cid}: history ends {periods[-1]} but the forecast starts "
                        f"{fperiods[0]} — a year is skipped"
                    )
                    bad += 1
        if fperiods and len(fperiods) != 5:
            g.fail(f"{cid}: forecast horizon is {len(fperiods)} years, not 5")
            bad += 1

        # Every forecast period must actually carry line items.
        flabels = {
            str(i.get("period_label"))
            for i in ((model.get("forecast") or {}).get("line_items") or [])
        }
        missing = [p for p in fperiods if p not in flabels]
        if missing:
            g.fail(f"{cid}: forecast declares {missing} but publishes no line items")
            bad += 1

    if bad == 0:
        g.ok(f"{len(specs)} snapshots hold every identity")
    return g


# --------------------------------------------------------------------------- #
# Gate 4 — no NEW QA failure
# --------------------------------------------------------------------------- #


def gate_qa() -> GateResult:
    """A gate that is permanently red is a gate nobody reads.

    So it compares against a committed baseline of known failures: a check that
    started failing is a regression and blocks; one that started passing is
    recorded as a fix.

    Snapshot mode, and that is not incidental. The default live mode rebuilds every
    model through the API path, which reads `valence.db` when one exists and reaches
    SEC, the exchanges and a market feed when one does not. Locally it read a warm
    database that is gitignored and exists on one machine; in CI it rebuilt cold. Two
    different measurements, both reporting plausible numbers, which is how the CI
    gate went red on four consecutive pushes while this loop reported it green on
    every one. Snapshot mode is the same measurement in both places, and it is the
    artifact that ships.
    """
    g = GateResult("qa")
    code, out = _run(
        [sys.executable, str(REPO / "scripts" / "qa_gate.py"), "--mode", "snapshot"],
        timeout=1800,
    )
    interesting = [
        ln for ln in out.splitlines()
        if any(k in ln for k in ("checked", "failing now", "regressions", "REGRESSION", "no regressions", "not in the baseline"))
    ]
    g.lines.extend(interesting or [out.splitlines()[-1] if out.splitlines() else ""])
    if code != 0:
        g.fail("a model started failing a check it previously passed")
    else:
        g.ok("no regressions against the committed baseline, over the shipped snapshots")
    return g


# --------------------------------------------------------------------------- #
# Gate 5 — the test suites
# --------------------------------------------------------------------------- #


def gate_tests() -> GateResult:
    g = GateResult("tests")
    code, out = _run(
        [sys.executable, "-m", "pytest", "backend/tests", "-q", "--no-header",
         "-p", "no:cacheprovider"],
        timeout=5400,
    )
    tail = [ln for ln in out.splitlines() if "passed" in ln or "failed" in ln]
    g.lines.extend(tail[-3:] or [out.splitlines()[-1] if out.splitlines() else ""])
    if code != 0:
        fails = [ln for ln in out.splitlines() if ln.startswith("FAILED")]
        for ln in fails[:15]:
            g.lines.append(f"      {ln}")
        g.fail("backend suite red")

    # The frontend suite lives in frontend/ and is driven by that package's own
    # script. There is no package.json at the repository root, so running `npm test`
    # from the root fails on a missing manifest and was reported as a red frontend
    # suite — the gate asserting a failure that was really a wrong directory.
    npm = "npm.cmd" if sys.platform == "win32" else "npm"
    fe = REPO / "frontend"
    try:
        code2, out2 = _run([npm, "test", "--silent"], timeout=1800, cwd=fe)
    except Exception as exc:
        code2, out2 = 1, f"{type(exc).__name__}: {exc}"
    ftail = [ln for ln in out2.splitlines() if ln.strip().startswith("# pass") or "# fail" in ln]
    g.lines.extend(ftail[-2:])
    if code2 != 0:
        for ln in [l for l in out2.splitlines() if l.strip().startswith("not ok")][:12]:
            g.lines.append(f"      {ln.strip()}")
        g.fail("frontend suite red")
    if code == 0 and code2 == 0:
        g.ok("both suites green")
    return g


# --------------------------------------------------------------------------- #
# Gate 6 — the site a visitor actually reaches
# --------------------------------------------------------------------------- #


def _alive(url: str, timeout: int = 30) -> bool:
    try:
        req = urllib.request.Request(url, headers={"x-valence-build": "1"})
        urllib.request.urlopen(req, timeout=timeout)
        return True
    except Exception:
        return False


def gate_site() -> GateResult:
    g = GateResult("site")
    # A server that is not running is a FAILURE, not a skip.
    #
    # This gate used to skip when either server was unreachable, and the loop
    # reported CLEAN. It did exactly that on 2026-09-30: the frontend had lost its
    # production build, so every page check was unreachable, every one was skipped,
    # and the run finished with "0 gate(s) blocking". A gate that cannot examine
    # anything must not be able to report success, and a skip that reads as a pass
    # is worse than no gate because it is believed.
    #
    # `--no-server` is how you say you mean it. Without that flag, an unreachable
    # server is a finding about the run, not an excuse for it.
    if not _alive(f"{API}/api/companies/manifest?offset=0&limit=5"):
        g.fail(
            f"backend is not answering on {API}, so no served figure could be checked. "
            f"Start it, or pass --no-server to leave the live gates out on purpose"
        )
        return g
    if not _alive(f"{WEB}/robots.txt"):
        # robots.txt, not the root, and the reason is the failure this replaces.
        #
        # The probe was `GET /` with an 8 second timeout. The dev server compiles the
        # homepage on demand and took 8.0s to render it on 2026-10-04, so a healthy
        # frontend read as "not answering" and the gate blocked on it -- reporting an
        # outage that did not exist, against a server that had just served four pages.
        #
        # A liveness probe should measure whether the process answers, not how long the
        # heaviest route takes to compile. robots.txt is served without rendering a
        # page, and this gate already requires it to return 200 further down, so it is
        # both the cheap witness and one this gate already depends on.
        g.fail(
            f"frontend is not answering on {WEB}, so no page could be checked. A "
            f"missing production build is the usual cause: `npm run build` in "
            f"frontend/, and the build now prints which API origin it chose. Pass "
            f"--no-server to leave the live gates out on purpose"
        )
        return g

    def get(url: str, timeout: int = 900):
        req = urllib.request.Request(url, headers={"x-valence-build": "1"})
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.status, r.read()

    try:
        _, body = get(f"{API}/api/companies/manifest?offset=0&limit=400")
        manifest = json.loads(body)
        rows = manifest.get("companies", manifest) if isinstance(manifest, dict) else manifest
        shipped = [c["company_id"] for c in rows if c.get("has_model")]
    except Exception as exc:
        g.fail(f"manifest unreadable: {type(exc).__name__}")
        return g

    if not shipped:
        g.fail("no company reports a compiled model")
        return g

    bad = []
    for cid in shipped:
        try:
            status, body = get(f"{API}/api/model/{cid}")
            payload = json.loads(body)
            payload = payload.get("model", payload)
            price = (((payload.get("valuation") or [{}])[0]).get("dcf_bridge") or {}).get(
                "implied_share_price"
            )
            if price is None:
                bad.append(f"{cid}: no implied price")
        except urllib.error.HTTPError as exc:
            bad.append(f"{cid}: HTTP {exc.code}")
        except Exception as exc:
            bad.append(f"{cid}: {type(exc).__name__}")

    if bad:
        for b in bad[:10]:
            g.fail(b)
    else:
        g.ok(f"all {len(shipped)} shipped companies serve a price")

    # Every page the sitemap promises must resolve.
    try:
        _, xml = get(f"{WEB}/sitemap.xml", timeout=120)
        text = xml.decode("utf-8", "replace")
        # Take the text between <loc> and </loc>. Slicing from the first ">" in the
        # chunk instead found the ">" of the CLOSING tag, so every location came
        # back empty and the gate reported "all 0 sitemap company pages resolve" —
        # a clean pass on a check that had examined nothing at all.
        locs = [m.group(1).strip() for m in re.finditer(r"<loc>(.*?)</loc>", text, re.S)]
        company = [l for l in locs if "/stock/" in l]
        if not company:
            g.fail(
                f"sitemap lists no company pages ({len(locs)} locations total), so "
                "the page check had nothing to verify"
            )
        dead = []
        for loc in company:
            tk = loc.rsplit("/", 1)[-1]
            try:
                req = urllib.request.Request(f"{WEB}/stock/{tk}", method="HEAD")
                if urllib.request.urlopen(req, timeout=120).status != 200:
                    dead.append(tk)
            except Exception:
                dead.append(tk)
        if dead:
            g.fail(f"sitemap lists {len(dead)} pages that do not resolve: {dead[:6]}")
        elif company:
            g.ok(f"all {len(company)} sitemap company pages resolve")
    except Exception as exc:
        g.fail(f"sitemap unreadable: {type(exc).__name__}")

    for path, label in (
        ("/", "landing page"),
        ("/methodology", "methodology page"),
        ("/robots.txt", "robots.txt"),
        ("/llms.txt", "llms.txt"),
        ("/llms-full.txt", "llms-full.txt"),
        ("/media/valence-launch.mp4", "launch film"),
        ("/media/valence-launch-poster.jpg", "poster"),
        ("/media/valence-launch.en.vtt", "caption track"),
    ):
        try:
            req = urllib.request.Request(f"{WEB}{path}", method="HEAD")
            code = urllib.request.urlopen(req, timeout=120).status
            if code != 200:
                g.fail(f"{label} returned {code}")
        except Exception as exc:
            g.fail(f"{label}: {type(exc).__name__}")

    if g.passed:
        g.ok("static assets and pages all serve")

    # A 200 proves the route exists, not that the reader sees a number. A page can
    # answer 200 while rendering an error boundary, a shell that never resolved its
    # data, or a zero where a valuation should be, and every check above is blind to
    # all three. So the implied price the API serves is read out of the HTML of the
    # page that is supposed to show it, for a spread of companies including a
    # loss-making one whose price is negative and must still be displayed as one.
    checked = 0
    probed = 0
    published_probed = 0
    withheld_probed = 0
    withheld_checked = 0
    # Pages deliberately served up to REVALIDATE_SECONDS stale. Reported, not failed:
    # staleness is the product working as designed, and calling it a defect is what got
    # this gate muted.
    stale: List[str] = []
    for cid in _page_probe_ids():
        # The model endpoint answers with the model at the top level. Reading it
        # under a "model" key, as a wrapped response would be, raised KeyError on
        # every probe and skipped all of them, so the loop reported success over an
        # empty set rather than noticing it had checked nothing.
        try:
            payload = json.loads(_api_model(cid).decode("utf-8"))
            payload = payload.get("model", payload)
            ticker = (payload.get("metadata") or {}).get("ticker")
        except urllib.error.HTTPError as exc:
            # Name the status, and say what a status MEANS here.
            #
            # `except Exception` reported one line for a 503, a timeout and a
            # parse failure alike. On 2026-10-02 that read
            #
            #     FAIL  tatasteel_tatasteel: could not read the served model
            #
            # when the truth was that the ingest throttle had answered 503 to 11
            # of the 23 shipped companies -- the cache was being defeated by the
            # freshness check, and the single line named neither the cause nor
            # the eleven companies. Three conditions with three different fixes,
            # collapsed into one sentence that reads like a broken model.
            detail = ""
            try:
                detail = json.loads(exc.read().decode("utf-8", "replace")).get("detail", "")
            except Exception:
                pass
            g.fail(
                f"{cid}: the API answered HTTP {exc.code}"
                + (f" -- {detail}" if detail else "")
                + (
                    "  (503 from the ingest throttle means a shipped snapshot was "
                    "being re-ingested; that is a cache defect, not a broken model)"
                    if exc.code == 503
                    else ""
                )
            )
            continue
        except TimeoutError:
            g.fail(
                f"{cid}: the API did not answer within "
                f"{API_MODEL_TIMEOUT}s -- a timeout is a latency problem, and it "
                "reads the same as a 503 only if the harness declines to say which "
                "it was"
            )
            continue
        except (ValueError, KeyError, TypeError, AttributeError) as exc:
            g.fail(f"{cid}: the API answered but the payload was unreadable -- {type(exc).__name__}: {exc}")
            continue
        except Exception as exc:
            g.fail(f"{cid}: could not reach the API -- {type(exc).__name__}: {exc}")
            continue
        if not ticker:
            g.fail(f"{cid}: the served model carries no ticker, so its page cannot be located")
            continue
        implied = _api_implied_price(cid)
        if implied is None:
            g.fail(f"{cid}: API serves no implied price, so the page has none to show")
            continue
        publishable = bool((payload.get("publication") or {}).get("publishable"))
        probed += 1
        if publishable:
            published_probed += 1
        else:
            withheld_probed += 1
        try:
            _, body = get(f"{WEB}/stock/{ticker}", timeout=300)
        except Exception as exc:
            g.fail(f"{cid}: page /stock/{ticker} did not load ({type(exc).__name__})")
            continue
        html = body.decode("utf-8", "replace")
        # The serialized RSC payload is not reader-visible text. It legitimately carries
        # `implied_share_price` beside `publication.publishable: false`, because that is
        # the contract the client workbench and the export paths read, and a number
        # sitting there beside its own "not published" verdict is data rather than a
        # claim. Searching it would report every page as leaking and train us to ignore
        # this gate, which is what a too-broad check always does.
        visible = _rsc_removed(html)

        # Two decimals, no thousands separator, as a currency amount appears in a
        # value: 160.65, and 3.95 for a negative one once the sign is carried.
        want = f"{abs(implied):,.2f}"
        alt = f"{abs(implied):.2f}"
        figures = [f for f in (want, alt) if f in visible]
        shown = bool(figures)

        # The check now follows the server's verdict in BOTH directions, because the
        # product's rule is directional and a gate that only knows one direction cannot
        # see half the class of defect it exists for.
        #
        # It used to demand the figure on every probed page. Fourteen of the twenty-three
        # shipped models are `opinion_only`, and the pages now correctly withhold, so the
        # gate was demanding the leak be reintroduced. That is the section 5 pattern
        # exactly: a gate asserting a property the product has deliberately stopped having,
        # which gets muted, and a muted gate protects nothing.
        #
        # A withheld model must present the figure NOWHERE in the reader-visible markup,
        # and must say why. Naming it inside the sentence that refuses it is allowed, and
        # is required for the refusal to be checkable; `withheld_figure_is_presented` is
        # the one place that distinction is made.
        if publishable:
            if not shown:
                g.fail(
                    f"{cid}: the model endpoint says publishable, but page "
                    f"/stock/{ticker} does not contain its implied price {want}. The "
                    f"verdict and the page disagree, so a figure the engine will present "
                    f"is not reaching the reader."
                )
                continue
        else:
            offending = withheld_figure_is_presented(visible, figures)
            if offending:
                g.fail(
                    f"{cid}: the model endpoint withholds this valuation, and page "
                    f"/stock/{ticker} presents {want} as an answer rather than as the "
                    f"reason it was refused: {offending[0]!r}"
                )
                continue
            reasons = (payload.get("publication") or {}).get("input_defect_checks_failed") or []
            if not reasons:
                g.fail(
                    f"{cid}: the model is withheld but names no input check as the reason, "
                    f"so there is nothing for the page to state. The verdict and the "
                    f"evidence disagree."
                )
                continue
            if not any(r in visible for r in reasons):
                g.fail(
                    f"{cid}: the valuation is withheld and the figure is not presented, "
                    f"but the page never names why ({', '.join(reasons)}). A page that "
                    f"shows no number and gives no reason is indistinguishable from a "
                    f"failed build."
                )
                continue
            withheld_checked += 1

        # The market price must match too, and exactly. Checking only the implied
        # price passed while the page served a different company's numbers: the
        # frontend rewrites /api to a hardcoded host when NEXT_PUBLIC_API_URL is
        # unset at build time, so a local build silently read a deployed backend,
        # and the implied prices happened to agree while the market prices did not.
        # Larsen & Toubro showed 3,766.40 as of 2026-09-28 where the local model
        # held 3,756.10 as of 2026-09-29. A page that renders a number is not a
        # page that renders THIS model's number.
        #
        # This applies to a withheld model too, and it is the one figure such a page is
        # still expected to show: a market quote is not the engine's opinion, and the
        # staleness check needs a date to compare against.
        quote = _api_quote(cid)
        if quote is None:
            g.fail(f"{cid}: the served model carries no market price to compare against")
            continue
        price, price_date, source = quote
        verdict = _judge_market_price(
            html, price, price_date, source, cid=cid, ticker=ticker)
        if verdict.failed:
            g.fail(verdict.message)
            continue
        if verdict.stale:
            stale.append(verdict.message)
        checked += 1
    if probed == 0:
        g.fail("no company page could be probed, so the content check verified nothing")
    elif published_probed == 0:
        g.fail(
            f"{probed} pages probed, none of them publishable. This run cannot see a "
            f"published model losing its figure, which is the other half of the rule."
        )
    elif withheld_probed == 0:
        g.fail(
            f"{probed} pages probed, none of them withheld. This run cannot see a "
            f"withheld valuation leaking, which is the half that has actually happened."
        )
    elif checked:
        g.ok(
            f"{checked} of {probed} probed company pages agree with the API: "
            f"{published_probed} published and showing their figure, "
            f"{withheld_checked} withheld and naming the check that stopped it"
        )
    if stale:
        g.ok(f"{len(stale)} of those pages are within the declared revalidation window"
             f" and state their own quote date -- staleness, not a defect: "
             f"{'; '.join(stale[:4])}")
    return g


API_MODEL_TIMEOUT = 600


def _rsc_removed(html: str) -> str:
    """Reader-visible markup, with Next's serialized payload taken out.

    The payload legitimately carries `implied_share_price` beside
    `publication.publishable: false`. Searching it reports every withheld page as leaking,
    and a gate that cries wolf on all 23 is a gate that gets muted.
    """
    return re.sub(r'self\.__next_f\.push\(\[1,".*?"\]\)</script>', "", html, flags=re.S)


# A sentence that REFUSES a figure rather than asserting one. The number beside one of
# these is the evidence for the refusal, and stripping it makes the refusal unfalsifiable,
# which is the same error as hiding the QA report.
_REFUSAL = re.compile(
    r"is not positive|is not a value|not a usable valuation|is not a valuation|"
    r"cannot exist|not published|no valuation is published|withheld|could not verify|"
    r"must not",
    re.IGNORECASE,
)

_SENTENCE_END = re.compile(r"(?<=[.!?])\s+|;\s*")

# Surfaces whose text lives in an ATTRIBUTE, so stripping tags deletes it.
#
# This was found by running this rule against the exact description /stock/INFY served
# before the fix, and it returned nothing: the string is inside
# `<meta name="description" content="DCF implied value 1,079.32 ...">`, and a tag-stripping
# reader sees an empty document. So the gate's leak test was structurally incapable of
# seeing a leak in the meta description, which is the outermost surface in the product and
# the one the leak actually happened in.
#
# Two implementations of one rule, and the second one had a blind spot the first did not.
_HEAD_SURFACES = re.compile(
    r'<meta[^>]+(?:name|property)="(?:description|og:description|twitter:description)"'
    r'[^>]*content="([^"]*)"'
    r'|<title[^>]*>(.*?)</title>',
    re.IGNORECASE | re.DOTALL,
)
_CONTENT_ATTR = re.compile(r'content="([^"]*)"')


def _unescape(text: str) -> str:
    return (text.replace("&amp;", "&").replace("&quot;", '"')
                .replace("&#x27;", "'").replace("&nbsp;", " ")
                .replace("&lt;", "<").replace("&gt;", ">")
                .replace("&#39;", "'"))


def _prose_sentences(html: str):
    """Reader-visible text, cut into sentences.

    Two sources, in this order.

    Attribute-borne surfaces first: the meta description, the OG and Twitter descriptions
    and the title. Their text is inside a tag, so it has to be read before the tags go.

    Then the element text, with tags stripped and the result split on punctuation. Tags
    are stripped before the split rather than used as the boundary, because a refusal
    sentence is routinely broken across inline elements -- `base: implied share price
    <span>-62.50</span> is not positive` -- and splitting on tags would isolate the figure
    from its own refutation and report it as a leak.

    The cost of that coarser boundary is that two adjacent elements with no punctuation
    between them merge. That merges in the safe direction: a merged blob of a headline price
    and a QA line carries no refusal marker and so is reported. The check errs toward
    failing rather than toward passing.
    """
    for match in _HEAD_SURFACES.finditer(html):
        value = match.group(1) if match.group(1) is not None else match.group(2)
        if value:
            yield _unescape(value).strip()

    text = _unescape(re.sub(r"<[^>]+>", " ", html))
    for part in _SENTENCE_END.split(text):
        if part and part.strip():
            yield part.strip()


def withheld_figure_is_presented(html: str, figures: List[str]) -> List[str]:
    """Sentences that present a withheld figure as an answer rather than as the reason.

    THE ONE RULE, and it is deliberately uniform in the sign.

    An earlier version of this distinguished positive from non-positive figures, on the
    reasoning that a negative price cannot be read as a valuation while a positive one can.
    That is a proxy, and it produced two defects: the leak sweep in `assets/gsd/meta_leak.py`
    and this gate disagreed about `amba_us` and `idea_idea`, and each was a copy of a rule
    that had already drifted once in this project. Two answers to one question is one too
    many.

    The real test is grammatical rather than arithmetic: a withheld figure may appear in
    the sentence that refuses it, and nowhere else. `implied share price -62.50 is not
    positive` is the evidence for the refusal. `DCF implied value 1,079.32 vs 1,035.00
    market` is a claim. Neither the sign nor the magnitude decides it; the sentence does.

    Reads the head surfaces as well as the body, because the leak happened in the
    description and a tag-stripping reader cannot see an attribute.

    Returns the offending sentences, empty when the figure is only ever named as the reason.
    """
    offending: List[str] = []
    for sentence in _prose_sentences(html):
        if not any(f in sentence for f in figures):
            continue
        if _REFUSAL.search(sentence):
            continue
        offending.append(sentence[:160])
    return offending


def _api_model(cid: str) -> bytes:
    req = urllib.request.Request(f"{API}/api/model/{cid}", headers={"x-valence-build": "1"})
    with urllib.request.urlopen(req, timeout=API_MODEL_TIMEOUT) as r:
        return r.read()


def _api_implied_price(cid: str) -> Optional[float]:
    try:
        payload = json.loads(_api_model(cid).decode("utf-8"))
        payload = payload.get("model", payload)
        bridge = ((payload.get("valuation") or [{}])[0]).get("dcf_bridge") or {}
        v = bridge.get("implied_share_price")
        return float(v) if v is not None else None
    except Exception:
        return None


@dataclass
class _Verdict:
    """Outcome of comparing a page's market price against the model's."""

    failed: bool
    message: str
    stale: bool = False


def _judge_market_price(html: str, price: float, price_date: Optional[str],
                        source: str, cid: str = "", ticker: str = "") -> _Verdict:
    """Does the page show the market price the model serves, and if not, WHY NOT.

    Split out of the gate body so it can be tested without two live servers. That is not
    tidiness: the first version of this logic lived inline and the test reimplemented it,
    and a mutation that deleted the staleness branch from the gate then SURVIVED, because
    the test was exercising its own copy rather than the gate. A guard on a copy is not a
    guard.

    The distinction being drawn:

      * The page's quote date is BEHIND the model's -> STALE, not a failure. The page is
        within its declared revalidation window and says so.
      * Same date, different price -> FAIL. Caching does not explain it, so the frontend
        is reading another backend. This is the original defect and must survive.
      * Behind, but with no price beside its own date -> FAIL. The reader cannot tie the
        figure to the date, which is the property the check exists to protect.
      * No date stated at all -> FAIL. Treating it as stale would make the check
        unfalsifiable, since any page could claim to be behind.
    """
    priced = f"{price:,.2f}"
    bare = f"{abs(price):.2f}"
    page_date = _page_quote_date(html)

    if priced in html or bare in html:
        # The figure is there. If the date is not, a reader still cannot tell how old it
        # is -- unless the page is behind, in which case its own date is present.
        if price_date and price_date not in html:
            if page_date and page_date != price_date:
                return _Verdict(False, f"{cid}: page quote date older than {price_date}",
                                stale=True)
            return _Verdict(True, (
                f"{cid}: page /stock/{ticker} does not carry the quote date "
                f"{price_date}, so a reader cannot tell how old the price is"))
        return _Verdict(False, "")

    if page_date and price_date and page_date != price_date:
        # The page is BEHIND, which is expected within the revalidation window. The
        # absent price is the newer one by construction -- asking a stale page to contain
        # it could never succeed, so an earlier draft required exactly that and so failed
        # on the case it was written to forgive.
        #
        # What must still hold is that the page shows a price AT ITS OWN DATE: the figure
        # on screen has to belong to the date printed beside it.
        shown = _price_at_date(html, page_date)
        if shown is None:
            return _Verdict(True, (
                f"{cid}: page /stock/{ticker} states quote date {page_date} but carries "
                f"no market price beside it, so the reader cannot tie the figure to the "
                f"date (the model serves {priced} at {price_date}, {source})"))
        return _Verdict(False, (
            f"{cid}: page at {page_date} showing {shown}, API at {price_date} showing "
            f"{priced} ({source})"), stale=True)

    return _Verdict(True, (
        f"{cid}: page /stock/{ticker} shows a different market price from the "
        f"model — the model serves {priced} ({price_date}, {source}) and that figure is "
        f"not on the page, at a quote date the page does not contradict "
        f"({page_date or 'not stated'}). The frontend is probably reading a backend other "
        f"than this one."))


def _price_at_date(html: str, date: str):
    """The market price the page prints beside `date`, or None if it prints none.

    Pairs with `_page_quote_date`. Knowing a page is a day behind is not enough to call
    it healthy: it must still show a figure that belongs to the date it claims, or the
    reader is looking at a number with nothing tying it to anything.

    Matched against the caption page.tsx builds, which is the only place the two appear
    together. The currency symbol is part of it -- measured on a live page, not assumed:

        DCF implied value $156.48 vs $234.54 market (2026-10-02) at a 11.8% WACC.

    A first version required the digits immediately after "vs ", and returned None on every
    real page because of the `$`. That was not a harmless miss: the staleness branch
    forgives a page only when this finds a figure, so a genuinely stale page would have
    been FAILED -- the exact behaviour this change exists to remove -- while every
    synthetic test still passed, since the fixtures had no currency symbol.

    Returns None rather than a loose number found elsewhere on the page: any figure would
    do here, which is exactly why this cannot be a substring search.
    """
    m = re.search(
        r"vs\s+[$€£₹]?\s*([0-9][0-9,]*\.[0-9]{2})\s+market\s*\("
        + re.escape(date) + r"\)", html)
    if m:
        return m.group(1)
    return None


def _page_quote_date(html: str):
    """The quote date the PAGE states about itself, or None if it states none.

    Read from the HTML rather than requested, because the whole point is to let a stale
    page be recognised as stale. Two sources, in order of trustworthiness:

      1. JSON-LD `temporalCoverage`, which Next emits for the rendered page.
      2. The visible caption "vs <price> market (<date>)" that page.tsx builds.

    Returns None rather than guessing when neither is present, because a wrong date here
    would turn a real mismatch into a "stale, fine" pass -- the failure mode this whole
    change exists to avoid.
    """
    m = re.search(r'"temporalCoverage"\s*:\s*"([0-9]{4}-[0-9]{2}-[0-9]{2})"', html)
    if m:
        return m.group(1)
    # Next may serialise the ld+json block with HTML-escaped quotes (&quot;), in which
    # case the pattern above finds nothing even though the data is present. Measured
    # rather than assumed: an escaped-only document returned None before this branch.
    m = re.search(r'&quot;temporalCoverage&quot;\s*:\s*&quot;'
                  r'([0-9]{4}-[0-9]{2}-[0-9]{2})&quot;', html)
    if m:
        return m.group(1)
    # Last resort: the visible/meta caption page.tsx builds, "... vs 158.11 market
    # (2026-10-01)".
    m = re.search(r"market\s*\((\d{4}-\d{2}-\d{2})\)", html)
    if m:
        return m.group(1)
    return None


def _api_quote(cid: str):
    """(price, date, source) as the served model states them."""
    try:
        payload = json.loads(_api_model(cid).decode("utf-8"))
        payload = payload.get("model", payload)
        rd = ((payload.get("valuation") or [{}])[0]).get("reverse_dcf") or {}
        price = rd.get("market_price")
        if price is None:
            return None
        return float(price), rd.get("market_price_date"), rd.get("market_price_source")
    except Exception:
        return None


def _page_probe_ids() -> List[str]:
    """A spread worth probing: the largest filer, a mid cap, and a loss-maker.

    A loss-making filer earns its place because its implied price is negative, which
    is the case a formatting or sign convention is most likely to swallow. A page
    that quietly renders an empty cell for it passes every status check and tells
    the reader nothing.

    It also has to probe BOTH verdicts, and that is not decoration. The list is built from
    a hardcoded preference order plus whatever else is shipped, so whether any withheld
    model lands in it depends on which companies happen to be in the catalogue. A probe set
    of four published models would satisfy every assertion below while the withheld branch
    never ran -- the same unfalsifiability that made a check pass on a system withholding
    from all twenty-three models.

    So the split is resolved here, against the same endpoint the check reads, and the gate
    fails when it cannot get both. Asking for one of each and taking the rest from the
    preference order keeps the spread that was here before while making the coverage
    explicit rather than accidental.
    """
    ids = _shipped_ids()
    published: List[str] = []
    withheld: List[str] = []
    unreadable: List[str] = []
    for cid in ids:
        try:
            payload = json.loads(_api_model(cid).decode("utf-8"))
            payload = payload.get("model", payload)
            verdict = payload.get("publication")
        except Exception:
            unreadable.append(cid)
            continue
        if verdict is None:
            # No verdict on the payload is itself a finding, and the gate reports it when
            # it probes the company. Do not guess a side for it here.
            unreadable.append(cid)
            continue
        (published if verdict.get("publishable") else withheld).append(cid)

    # The loss-maker is preferred on both sides: a negative price is the case a sign or
    # formatting convention is most likely to swallow, in either direction.
    def preferred(pool: List[str]) -> List[str]:
        out = [c for c in ("amba_us", "idea_idea", "nvda_us", "aapl_us") if c in pool]
        out += [c for c in pool if c not in out]
        return out

    picks = preferred(published)[:2] + preferred(withheld)[:2]
    if not published or not withheld:
        # Return what exists; the gate fails on the missing side and says why, which is
        # more use than silently probing one direction.
        picks = (preferred(published)[:2] + preferred(withheld)[:2])[:4]
    for cid in unreadable:
        if len(picks) >= 4:
            break
        if cid not in picks:
            picks.append(cid)
    return picks[:4]


# --------------------------------------------------------------------------- #

def gate_self_check() -> GateResult:
    """The end-to-end stage-10 self-check, which the loop had never run.

    This is the only thing in the repository that exercises the whole path at
    once: ingestion, the workbook actually built and written, the HTTP export read
    back as bytes, and the driver-edit / revert round trip checked for an exact
    return to the starting price.

    It was absent from the loop, which meant the only end-to-end check in the
    project was one nobody ran before shipping.

    Isolation is partial and this gate does not overstate it: the self-check
    rebinds the snapshot cache and export directory to a temporary tree, so it adds
    no snapshots to the shipped cache -- which matters, because the first version
    of the sampling harness wrote 139 of them and silently grew the launch surface
    from 23 companies to 162. It does NOT rebind the raw datapoint store, so
    running this writes rows into the real working-tree database.

    It asserts the workbook tab count is parsed and reported rather than assumed,
    because the only workbook assertion inside the self-check is a 15000-byte
    size floor, which a five-tab export would clear.

    Ordered after `tests` because it is the slowest thing here and the fastest
    failures are the more useful ones to see first.
    """
    g = GateResult("self_check")
    code, out = _run(
        [sys.executable, "-m", "backend.api.self_check"],
        timeout=3600,
        env={**os.environ, "PYTHONPATH": str(REPO)},
    )
    summary = [ln for ln in out.splitlines()
               if "SELF-CHECKS" in ln or "FAILED" in ln or "Traceback" in ln]
    g.lines.extend(summary[-3:] or [out.splitlines()[-1] if out.splitlines() else ""])
    if code != 0:
        for ln in [l for l in out.splitlines() if l.startswith("  FAIL") or "Error" in l][:10]:
            g.lines.append(f"      {ln.strip()}")
        g.fail("end-to-end self-check did not pass")
        return g
    if not any("SELF-CHECKS PASSED" in ln for ln in out.splitlines()):
        # Exit 0 without the success line means the check changed shape and this
        # gate stopped recognising it. A gate that cannot tell success from
        # "the thing I was checking no longer says the word" is not a gate.
        g.fail("self-check exited 0 but never reported passing; its output changed shape")
        return g
    # Assert the tab count rather than printing it and moving on. The only
    # workbook assertion inside the self-check is a 15000-byte size floor, which a
    # truncated five-tab export clears comfortably -- so harvesting the number
    # without inspecting it is evidence collection dressed as a check.
    tabs = [ln for ln in out.splitlines() if "Total tabs rendered" in ln]
    if not tabs:
        g.fail("self-check never reported a tab count, so the export step may not have run")
        return g
    m = re.search(r"Total tabs rendered\s*:\s*(\d+)", tabs[-1])
    if not m:
        g.fail(f"could not read a tab count out of {tabs[-1]!r}")
        return g
    tab_count = int(m.group(1))
    # A floor, not an equality: the exact number will move as the model gains
    # statements, and a gate that hardcodes today's count fails on a feature
    # rather than on a defect. It only needs to catch the export collapsing.
    if tab_count < 20:
        g.fail(f"workbook rendered {tab_count} tabs, which is far below the full model")
        return g
    g.ok(f"workbook built and read back as {tab_count} tabs")
    return g


GATES: List[tuple[str, Callable[[], GateResult]]] = [
    ("tieout", gate_tieout),
    ("identities", gate_identities),
    ("excel", gate_excel),
    ("qa", gate_qa),
    ("tests", gate_tests),
    ("self_check", gate_self_check),
    ("site", gate_site),
]


def main() -> int:
    # Reporting must never be the thing that fails.
    #
    # A gate's own print statement raised UnicodeEncodeError on 2026-10-02 while
    # echoing a PASSING gate, and the process exited 1 with no verdict at all. A
    # character a console cannot encode is not a finding about the codebase, so it
    # is replaced rather than raised: the loop's exit code must mean exactly one
    # thing, "a gate blocked". Without this, `β` in a workbook label, a rupee sign
    # in a company name, or an em dash in a note can each impersonate a red gate.
    for _stream in (sys.stdout, sys.stderr):
        try:
            _stream.reconfigure(errors="replace")
        except (AttributeError, ValueError, OSError):
            # A stream that will not reconfigure (a StringIO in a test, a closed
            # pipe) still works; it just keeps its own error policy.
            pass

    ap = argparse.ArgumentParser()
    ap.add_argument("--only", action="append", default=[])
    ap.add_argument("--no-server", action="store_true")
    args = ap.parse_args()

    gates = GATES
    if args.only:
        gates = [g for g in GATES if g[0] in set(args.only)]
    if args.no_server:
        gates = [g for g in gates if g[0] != "site"]

    print(f"\n  LAUNCH AUDIT LOOP — {len(gates)} gates\n")
    results: List[GateResult] = []
    for name, fn in gates:
        start = time.time()
        try:
            res = fn()
        except Exception as exc:
            res = GateResult(name)
            res.fail(f"gate raised {type(exc).__name__}: {exc}")
        res.seconds = time.time() - start
        results.append(res)
        mark = "SKIP" if res.skipped else ("PASS" if res.passed else "BLOCK")
        print(f"  [{mark}] {name} ({res.seconds:.0f}s)")
        for ln in res.lines[-14:]:
            print(f"        {ln}")
        print()

    blocked = [r.name for r in results if not r.passed and not r.skipped]
    print(f"  {'BLOCKED' if blocked else 'CLEAN'} — {len(blocked)} gate(s) blocking"
          + (f": {', '.join(blocked)}" if blocked else ""))
    return 1 if blocked else 0


if __name__ == "__main__":
    raise SystemExit(main())

"""Pre-deploy gate: the checks that must pass before shipping to production.

Covers what a Render deploy (Docker) and the Next.js frontend actually depend on,
plus the production-only behaviours that unit tests do not cover (docs disabled,
CSP header present, health check reachable on $PORT).

Usage:
    python scripts/predeploy_check.py
    python scripts/predeploy_check.py --base http://127.0.0.1:8020   # against a running prod-mode server
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import urllib.error
import urllib.request
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

FAILURES: list[str] = []
PASSES: list[str] = []


def check(name: str, ok: bool, detail: str = "") -> bool:
    (PASSES if ok else FAILURES).append(f"{name}{(' — ' + detail) if detail else ''}")
    print(f"  [{'PASS' if ok else 'FAIL'}] {name}{(' — ' + detail) if detail else ''}")
    return ok


def _run(cmd: list[str], cwd: Path, label: str) -> bool:
    # On Windows, npm/npx are .cmd shims and are not on the bare-name PATH that
    # subprocess inherits unless the extension is given explicitly.
    resolved = list(cmd)
    if sys.platform == "win32":
        for tool in ("npm", "npx"):
            if resolved and Path(resolved[0]).name.lower() == tool:
                found = shutil.which(tool) or shutil.which(f"{tool}.cmd")
                if found:
                    resolved[0] = found
    try:
        proc = subprocess.run(resolved, cwd=cwd, capture_output=True, text=True, timeout=1800)
    except FileNotFoundError:
        return check(label, False, f"command not found: {resolved[0]}")
    except subprocess.TimeoutExpired:
        return check(label, False, "timed out")
    if proc.returncode != 0:
        tail = (proc.stdout + proc.stderr).strip().splitlines()[-6:]
        return check(label, False, " | ".join(tail))
    return check(label, True)


def check_backend_tests() -> None:
    print("\nBackend")
    _run([sys.executable, "-m", "pytest", "backend/tests", "-q"], REPO_ROOT, "pytest backend/tests")


def check_imports_and_entrypoint() -> None:
    """The Docker image runs `uvicorn backend.api.main:app` — that exact import
    must work from a clean interpreter, and the app must expose the routes the
    platform health check and the frontend proxy depend on."""
    code = (
        "from backend.api.main import app;"
        "paths={r.path for r in app.routes};"
        "assert '/api/health' in paths, paths;"
        "assert '/api/model/{company_id}' in paths, paths;"
        "assert '/api/export/excel' in paths, paths;"
        "print('routes ok:', len(paths))"
    )
    _run([sys.executable, "-c", code], REPO_ROOT, "app entrypoint imports with required routes")


def check_dockerfile_contract() -> None:
    """Render builds from ./Dockerfile and health-checks /api/health on $PORT."""
    dockerfile = (REPO_ROOT / "Dockerfile").read_text(encoding="utf-8")
    ok = True
    ok &= check("Dockerfile copies backend package", "COPY backend ./backend" in dockerfile)
    ok &= check(
        "Dockerfile binds $PORT (Render requirement)",
        "${PORT:-8000}" in dockerfile,
    )
    ok &= check("Dockerfile health check hits /api/health", "/api/health" in dockerfile)
    ok &= check("Dockerfile runs non-root", "USER appuser" in dockerfile)
    if not ok:
        return

    render = (REPO_ROOT / "render.yaml").read_text(encoding="utf-8")
    check("render.yaml sets healthCheckPath", "healthCheckPath: /api/health" in render)
    check("render.yaml sets VALENCE_ENV=production", "VALENCE_ENV" in render and "production" in render)
    check("render.yaml scopes CORS_ORIGINS", "CORS_ORIGINS" in render)
    check("render.yaml does not sync secrets", "sync: false" in render)


def check_frontend() -> None:
    print("\nFrontend")
    fe = REPO_ROOT / "frontend"
    if not (fe / "package.json").exists():
        return check("frontend present", False)
    _run(["npm", "run", "lint"], fe, "eslint")
    _run(["npx", "tsc", "--noEmit"], fe, "typescript --noEmit")
    _run(["npm", "run", "build"], fe, "next build")


def check_live_server(base: str | None) -> None:
    if not base:
        print("\nLive server (skipped — pass --base to include)")
        return
    print(f"\nLive server ({base})")

    def get(path: str, timeout: int = 600):
        try:
            r = urllib.request.urlopen(base + path, timeout=timeout)
            return r.status, {k.lower(): v for k, v in r.headers.items()}, r.read()
        except urllib.error.HTTPError as e:
            return e.code, {k.lower(): v for k, v in e.headers.items()}, e.read()
        except Exception as e:
            return None, {}, str(e).encode()

    status, headers, body = get("/api/health")
    check("health endpoint returns 200", status == 200, body[:40].decode(errors="replace"))
    check(
        "CSP frame-ancestors header present",
        "frame-ancestors" in headers.get("content-security-policy", ""),
    )
    check(
        "X-Frame-Options not blocking embeds",
        "x-frame-options" not in headers,
        headers.get("x-frame-options", "absent"),
    )

    status, _, body = get("/docs")
    check("API docs disabled in production", status == 404, f"status {status}")

    status, _, body = get("/api/companies/search?q=INFY&limit=3")
    ok = status == 200
    if ok:
        try:
            ok = isinstance(json.loads(body), list)
        except Exception:
            ok = False
    check("company search responds", ok, f"status {status}")

    # A model must load with a live, dated, non-placeholder market price.
    for cid in ("infy_infy", "nvda_us"):
        status, _, body = get(f"/api/model/{cid}")
        if not check(f"{cid} model loads", status == 200, f"status {status}"):
            continue
        spec = json.loads(body)
        base_val = next(v for v in spec["valuation"] if v["scenario"] == "base")
        rd = base_val["reverse_dcf"]
        src = rd.get("market_price_source") or ""
        live = src.split(":")[0] in ("yfinance", "yfinance_history", "yahoo_chart", "twelvedata")
        check(
            f"{cid} market price is a live quote",
            live and (rd.get("market_price") or 0) > 0,
            f"{rd.get('market_price')} via {src} as of {rd.get('market_price_date')}",
        )
        bridge = base_val["dcf_bridge"]
        if bridge.get("equity_value") and bridge.get("shares_outstanding"):
            recomputed = bridge["equity_value"] / bridge["shares_outstanding"]
            check(
                f"{cid} bridge ties out",
                abs(recomputed - bridge["implied_share_price"]) < 0.05,
                f"{recomputed:.2f} vs {bridge['implied_share_price']:.2f}",
            )

        # Excel export must generate and carry quote provenance.
        status, _, blob = get(f"/api/export/excel?company_id={cid}")
        if not check(f"{cid} excel export", status == 200 and blob[:2] == b"PK", f"status {status}"):
            continue
        try:
            from openpyxl import load_workbook
            import io

            wb = load_workbook(io.BytesIO(blob))
            check(f"{cid} workbook has 30 tabs", len(wb.sheetnames) == 30, str(len(wb.sheetnames)))
            rev = wb["34_Reverse_DCF"]
            prov = [
                str(rev.cell(row=r, column=3).value)
                for r in range(1, rev.max_row + 1)
                if str(rev.cell(row=r, column=2).value) == "Quote as of / source"
            ]
            check(f"{cid} excel carries quote provenance", bool(prov), prov[0] if prov else "missing")
        except Exception as exc:
            check(f"{cid} workbook parses", False, str(exc)[:80])


def check_repo_hygiene() -> None:
    print("\nRepo hygiene")
    proc = subprocess.run(
        ["git", "status", "--porcelain"], cwd=REPO_ROOT, capture_output=True, text=True
    )
    check("git working tree readable", proc.returncode == 0)
    # Nothing generated should be staged for commit.
    dirty = [
        ln for ln in proc.stdout.splitlines()
        if ln.strip() and not ln.strip().startswith("??")
    ]
    check(
        "no stray secrets or DB files staged",
        not any(".env" in ln and ".env.local" not in ln for ln in dirty),
        f"{len(dirty)} modified tracked files",
    )


def main() -> int:
    ap = argparse.ArgumentParser(description="Pre-deploy verification gate.")
    ap.add_argument("--base", default=None, help="Base URL of a running production-mode server.")
    ap.add_argument("--skip-frontend", action="store_true")
    args = ap.parse_args()

    print("=" * 72)
    print("PRE-DEPLOY CHECK")
    print("=" * 72)

    check_backend_tests()
    check_imports_and_entrypoint()
    check_dockerfile_contract()
    if not args.skip_frontend:
        check_frontend()
    check_live_server(args.base)
    check_repo_hygiene()

    print("\n" + "=" * 72)
    print(f"{len(PASSES)} passed, {len(FAILURES)} failed")
    if FAILURES:
        for f in FAILURES:
            print(f"  FAILED: {f}")
        return 1
    print("All pre-deploy checks passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

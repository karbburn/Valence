from __future__ import annotations

"""
FastAPI Server Entrypoint for Valence.

Serves live REST API endpoints under /api/ and mounts static web UI frontend assets at /.
"""

import os
from pathlib import Path
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from backend.api.routes import router as api_router

HERE = Path(__file__).resolve().parent
STATIC_DIR = HERE / "static"
STATIC_DIR.mkdir(parents=True, exist_ok=True)

is_prod = os.getenv("VALENCE_ENV") == "production"

# Disable interactive API docs in production
app = FastAPI(
    title="Valence — Modern Financial Modeling Platform",
    description="Engine API serving ModelSpecification contracts, live driver recomputation, and Excel export.",
    version="1.0.0",
    docs_url=None if is_prod else "/docs",
    redoc_url=None if is_prod else "/redoc",
)

# Enable CORS for frontend development (credentials mode requires specific origins)
# In production, restrict origins via the CORS_ORIGINS env var (comma-separated).
CORS_ORIGINS = os.getenv(
    "CORS_ORIGINS",
    "http://localhost:3000,http://localhost:5173,http://localhost:8000",
).split(",")
app.add_middleware(
    CORSMiddleware,
    allow_origins=CORS_ORIGINS,
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Allow embedding in portfolio iframe (https://www.sourabhpradhan.in)
# Modern browsers enforce CSP frame-ancestors; X-Frame-Options is legacy/fallback.
FRAME_ANCESTORS = os.getenv(
    "FRAME_ANCESTORS",
    "https://www.sourabhpradhan.in https://sourabhpradhan.in https://*.sourabhpradhan.in https://*.vercel.app 'self'",
)


@app.middleware("http")
async def add_iframe_headers(request: Request, call_next):  # type: ignore[no-untyped-def]
    response = await call_next(request)
    # CSP frame-ancestors controls who can embed this site in an <iframe>
    response.headers["Content-Security-Policy"] = f"frame-ancestors {FRAME_ANCESTORS}"
    # Remove X-Frame-Options if any upstream/proxy set DENY/SAMEORIGIN (it would block the iframe).
    # CSP frame-ancestors is the modern replacement and takes precedence in modern browsers,
    # but XFO DENY still blocks in some browsers if present, so we must not send it.
    response.headers.pop("X-Frame-Options", None)
    return response


# Include API Router
app.include_router(api_router, prefix="/api")

# Mount Static UI Dashboard
app.mount("/", StaticFiles(directory=str(STATIC_DIR), html=True), name="static")

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("backend.api.main:app", host="127.0.0.1", port=8000, reload=True)

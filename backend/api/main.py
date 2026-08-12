from __future__ import annotations

"""
FastAPI Server Entrypoint for Valence.

Serves live REST API endpoints under /api/ and mounts static web UI frontend assets at /.
"""

from pathlib import Path
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from backend.api.routes import router as api_router

HERE = Path(__file__).resolve().parent
STATIC_DIR = HERE / "static"
STATIC_DIR.mkdir(parents=True, exist_ok=True)

app = FastAPI(
    title="Valence — Modern Financial Modeling Platform",
    description="Engine API serving ModelSpecification contracts, live driver recomputation, and Excel export.",
    version="1.0.0",
)

# Enable CORS for frontend development (credentials mode requires specific origins)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Include API Router
app.include_router(api_router, prefix="/api")

# Mount Static UI Dashboard
app.mount("/", StaticFiles(directory=str(STATIC_DIR), html=True), name="static")

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("backend.api.main:app", host="127.0.0.1", port=8000, reload=True)

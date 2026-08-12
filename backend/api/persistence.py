from __future__ import annotations

"""
Model Persistence & Backward-Loadability Migration Engine.

Manages saving, loading, listing, and deleting user financial models with
explicit schema version migration support.
"""

from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional
import json
import uuid

from pydantic import BaseModel, Field

from backend.models.spec.model_specification import ModelSpecification, MODEL_SPEC_VERSION

# Storage Directory
STORAGE_DIR = Path("backend/data/user_models")
STORAGE_DIR.mkdir(parents=True, exist_ok=True)


class SavedModelHeader(BaseModel):
    model_id: str
    user_id: str
    company_id: str
    name: str
    model_version: str
    created_at: str
    updated_at: str


class SavedModelEntry(BaseModel):
    header: SavedModelHeader
    spec_dict: Dict[str, Any]


def migrate_model_spec(spec_dict: Dict[str, Any]) -> Dict[str, Any]:
    """Backward-loadability migration engine.

    Ensures models saved under older schema versions (e.g. 0.9.0) load cleanly
    into current ModelSpecification contract (1.0.0) without losing user overrides.
    """
    metadata = spec_dict.get("metadata", {})
    version = metadata.get("model_version", "0.9.0")

    if version != MODEL_SPEC_VERSION:
        # 1. Update version tag to current schema version
        metadata["model_version"] = MODEL_SPEC_VERSION

        # 2. Ensure new required attributes exist with defaults if missing in older schema
        if "market" not in metadata:
            metadata["market"] = "india"
        if "currency" not in metadata:
            metadata["currency"] = "INR"
        if "units" not in metadata:
            metadata["units"] = "crores"

        # 3. Preserve all user overrides in assumptions array
        assumptions = spec_dict.get("assumptions", [])
        for a in assumptions:
            if a.get("type") == "user_override" and "previous_model_value" not in a:
                a["previous_model_value"] = a.get("value")

        spec_dict["metadata"] = metadata

    return spec_dict


class SavedModelStore:
    """File-backed & in-memory persistence store per user."""

    @staticmethod
    def save(
        user_id: str,
        spec: ModelSpecification,
        model_id: Optional[str] = None,
        name: Optional[str] = None,
    ) -> SavedModelHeader:
        m_id = model_id or uuid.uuid4().hex[:12]
        now_str = datetime.now().isoformat()

        model_name = name or f"{spec.metadata.name} Valuation ({spec.metadata.ticker})"
        spec_dict = spec.serialize()

        header = SavedModelHeader(
            model_id=m_id,
            user_id=user_id,
            company_id=spec.metadata.company_id,
            name=model_name,
            model_version=spec.metadata.model_version,
            created_at=now_str,
            updated_at=now_str,
        )

        entry = SavedModelEntry(header=header, spec_dict=spec_dict)

        user_dir = STORAGE_DIR / user_id
        user_dir.mkdir(parents=True, exist_ok=True)
        file_path = user_dir / f"{m_id}.json"

        with open(file_path, "w", encoding="utf-8") as f:
            json.dump(entry.dict(), f, indent=2)

        return header

    @staticmethod
    def load(user_id: str, model_id: str) -> Optional[ModelSpecification]:
        file_path = STORAGE_DIR / user_id / f"{model_id}.json"
        if not file_path.exists():
            return None

        with open(file_path, "r", encoding="utf-8") as f:
            data = json.load(f)

        spec_dict = data.get("spec_dict", {})
        migrated_dict = migrate_model_spec(spec_dict)
        return ModelSpecification.deserialize(migrated_dict)

    @staticmethod
    def list_for_user(user_id: str) -> List[SavedModelHeader]:
        user_dir = STORAGE_DIR / user_id
        if not user_dir.exists():
            return []

        headers: List[SavedModelHeader] = []
        for file_path in user_dir.glob("*.json"):
            try:
                with open(file_path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    h_dict = data.get("header", {})
                    headers.append(SavedModelHeader(**h_dict))
            except Exception:
                continue

        headers.sort(key=lambda h: h.updated_at, reverse=True)
        return headers

    @staticmethod
    def delete(user_id: str, model_id: str) -> bool:
        file_path = STORAGE_DIR / user_id / f"{model_id}.json"
        if file_path.exists():
            file_path.unlink()
            return True
        return False

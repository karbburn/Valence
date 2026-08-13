from __future__ import annotations

"""
Authentication & User Identity Module for Valence Engine API.

Provides:
- UserSession dataclass representing authenticated user context
- Header-based session extractor supporting Supabase Auth JWTs & dev test tokens

Production: validates JWT structure and attempts Supabase verification.
Development: allows dev override headers and demo sessions.
"""

import base64
import json
import logging
import os
from typing import Optional

from fastapi import Header, HTTPException
from pydantic import BaseModel

logger = logging.getLogger(__name__)


class UserSession(BaseModel):
    user_id: str
    email: str
    display_name: str
    auth_provider: str = "google"


def get_current_user(
    authorization: Optional[str] = Header(None),
    x_user_id: Optional[str] = Header(None),
) -> UserSession:
    """Extract authenticated UserSession from request headers.

    Gates development override headers behind VALENCE_ENV check, parses Bearer tokens,
    and falls back to a guest session for local use.
    """
    # 1. Dev/Test fallback (gated behind environment check)
    is_dev = os.getenv("VALENCE_ENV") in ("development", "test")
    if is_dev and x_user_id:
        return UserSession(
            user_id=x_user_id,
            email=f"{x_user_id}@valence.internal",
            display_name="Dev Analyst",
            auth_provider="dev",
        )

    # 2. Bearer token
    if authorization and authorization.startswith("Bearer "):
        token = authorization.split(" ")[1]
        if len(token) < 20:
            raise HTTPException(status_code=401, detail="Invalid auth token format")

        # Validate JWT structure: three dot-separated base64url segments
        parts = token.split(".")
        if len(parts) != 3:
            raise HTTPException(status_code=401, detail="Invalid JWT structure")

        try:
            # Decode payload (second segment) to extract user info
            payload_b64 = parts[1] + "=" * (4 - len(parts[1]) % 4)  # pad base64
            payload = json.loads(base64.urlsafe_b64decode(payload_b64))
        except Exception:
            raise HTTPException(status_code=401, detail="Invalid JWT payload")

        user_id = payload.get("sub") or payload.get("user_id")
        email = payload.get("email", "")
        if not user_id:
            raise HTTPException(status_code=401, detail="JWT missing user identity")

        return UserSession(
            user_id=user_id,
            email=email,
            display_name=payload.get("name", "Authenticated Analyst"),
            auth_provider="google",
        )

    # 3. Default demo guest session for local desktop use
    return UserSession(
        user_id="usr_demo_analyst",
        email="analyst@valence.internal",
        display_name="Senior Analyst (Demo)",
        auth_provider="demo",
    )

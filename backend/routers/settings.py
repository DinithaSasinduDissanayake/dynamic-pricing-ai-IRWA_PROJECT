import os
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from typing import Optional, Dict, Any

router = APIRouter(prefix="/api", tags=["settings"])

SETTINGS_STORE: Dict[int, Dict[str, Any]] = {}


def _default_settings() -> Dict[str, Any]:
    def _dev_enabled() -> bool:
        # Check environment variable first
        env_dev = os.environ.get("DEV_MODE", "").lower() in {"1", "true", "yes", "on"}
        if env_dev:
            return True
        
        # Fallback to core settings
        try:
            from core.settings import get_settings
            return bool(getattr(get_settings(), "dev_mode", False))
        except Exception:
            return False

    dev = _dev_enabled()
    return {
        "show_model_tag": True,
        "show_timestamps": bool(dev),
        "show_metadata_panel": bool(dev),
        "show_thinking": bool(dev),
        "theme": "dark",
        "streaming": "sse",
        "mode": "user",
    }



def _get_user_settings(token: Optional[str]) -> Dict[str, Any]:
    """Get user settings - token validation removed, using default settings for all users"""
    # Note: Auth migrated to fastapi-users, token validation simplified
    # For now, return default settings for all users
    return _default_settings()


class UpdateSettingsRequest(BaseModel):
    token: Optional[str] = None
    settings: Dict[str, Any]


@router.get("/settings")
def api_get_settings(token: Optional[str] = None):
    return {"ok": True, "settings": _get_user_settings(token)}


@router.put("/settings")
def api_update_settings(req: UpdateSettingsRequest):
    """Update settings - simplified to return default settings"""
    # Note: Auth migrated to fastapi-users, settings now global
    # Return updated default settings (in-memory only)
    return {"ok": True, "settings": _default_settings()}


def get_user_settings(token: Optional[str]) -> Dict[str, Any]:
    return _get_user_settings(token)

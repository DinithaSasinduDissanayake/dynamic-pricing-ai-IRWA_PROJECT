from typing import Any, Dict
from fastapi import Depends
from core.users import current_active_user
from core.auth_db import User
from core.agents.data_collector.repo import DataRepo


async def get_current_user(user: User = Depends(current_active_user)) -> Dict[str, Any]:
    """Get current authenticated user using fastapi-users"""
    return {"user_id": str(user.id), "email": user.email, "full_name": user.full_name}


async def get_current_user_for_alerts(user: User = Depends(current_active_user)) -> Dict[str, Any]:
    """Get current authenticated user for alerts using fastapi-users"""
    return {"user_id": str(user.id), "email": user.email, "full_name": user.full_name}


async def get_repo() -> DataRepo:
    repo = DataRepo()
    await repo.init()
    return repo
# Correct implementation:
from fastapi import Request
from core.users import fastapi_users

optional_current_user = fastapi_users.current_user(active=True, optional=True)

async def get_optional_user(
    user: User = Depends(optional_current_user)
) -> Dict[str, Any] | None:
    from backend.main import _require_login_enabled
    
    if user:
        return {"user_id": str(user.id), "email": user.email, "full_name": user.full_name}
    
    # If no user, check if login was actually required
    if _require_login_enabled():
        # If login is required but no user found, optional_current_user returns None.
        # But we might want to enforce it? 
        # Actually, for "get_optional_user", returning None is correct.
        # The caller (router) decides if it's okay to have no user.
        pass
        
    return None

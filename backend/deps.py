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

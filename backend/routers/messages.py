import json
from typing import Any, Dict, List
from fastapi import APIRouter, HTTPException

from core.chat_db import (
    get_thread_messages,
    SessionLocal,
    Thread as ChatThread,
)

router = APIRouter(prefix="/api/threads/{thread_id}/messages", tags=["messages"])

@router.get("")
def api_list_messages(thread_id: int):
    try:
        with SessionLocal() as db:
            t = db.get(ChatThread, thread_id)
            if not t:
                raise HTTPException(status_code=404, detail="Thread not found")
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to fetch thread: {str(e)}")

    msgs = get_thread_messages(thread_id)
    out: List[Dict[str, Any]] = []
    
    for m in msgs:
        # Safely parse JSON fields
        agents = json.loads(m.agents) if m.agents else None
        tools = json.loads(m.tools) if m.tools else None
        meta = json.loads(m.meta) if m.meta else None
        
        out.append({
            "id": m.id,
            "role": m.role,
            "content": m.content,
            "model": m.model,
            "token_in": m.token_in,
            "token_out": m.token_out,
            "cost_usd": m.cost_usd,
            "api_calls": m.api_calls,
            "parent_id": m.parent_id,
            "agents": agents,
            "tools": tools,
            "metadata": meta,
            "created_at": m.created_at.isoformat() if m.created_at else None
        })
        
    return out

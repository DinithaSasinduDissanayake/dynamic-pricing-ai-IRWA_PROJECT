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


router_global = APIRouter(prefix="/api/messages", tags=["messages"])

from core.payloads import EditMessageRequest, MessageOut
from core.chat_db import update_message, delete_message, get_message

@router_global.patch("/{message_id}", response_model=MessageOut)
def api_edit_message(message_id: int, req: EditMessageRequest):
    # For now, we only support in-place edit as per test expectation
    # If branch=True is passed, we might want to handle it differently in future
    m = update_message(message_id, content=req.content)
    if not m:
        raise HTTPException(status_code=404, detail="Message not found")
    
    # Safely parse JSON fields for response
    agents = json.loads(m.agents) if m.agents else None
    tools = json.loads(m.tools) if m.tools else None
    meta = json.loads(m.meta) if m.meta else None
    
    return {
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
        "created_at": m.created_at.isoformat() if m.created_at else ""
    }


@router_global.delete("/{message_id}")
def api_delete_message(message_id: int):
    ok = delete_message(message_id)
    if not ok:
        raise HTTPException(status_code=404, detail="Message not found")
    return {"ok": True}

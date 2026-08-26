from typing import Any, Dict, List, Optional
from fastapi import APIRouter, HTTPException, Query
from core.chat_db import (
    get_message,
    get_thread,
    delete_message,
    delete_message_cascade,
    update_message,
    get_thread_messages,
)
from core.payloads import (
    EditMessageRequest,
    MessageOut,
    DeleteMessageResponse,
)
from core.auth_service import validate_session_token

router = APIRouter(prefix="/api", tags=["messages"])


@router.patch("/messages/{message_id}", response_model=MessageOut)
def api_edit_message(message_id: int, req: EditMessageRequest, token: Optional[str] = Query(None)):
    m = get_message(message_id)
    if not m:
        raise HTTPException(status_code=404, detail="Message not found")
    t = get_thread(m.thread_id)
    if not t:
        raise HTTPException(status_code=404, detail="Thread not found")
    if t.owner_id is not None:
        owner_id = None
        if token:
            sess = validate_session_token(token)
            if sess:
                owner_id = sess["user_id"]
        if owner_id != t.owner_id:
            raise HTTPException(status_code=404, detail="Message not found")
    if m.role != "user":
        raise HTTPException(status_code=400, detail="Only user messages can be edited")
    m = update_message(message_id, content=req.content)
    return MessageOut(id=m.id, role=m.role, content=m.content, model=m.model, created_at=m.created_at.isoformat())


@router.delete("/messages/{message_id}", response_model=DeleteMessageResponse)
def api_delete_message(message_id: int, token: Optional[str] = Query(None)):
    m = get_message(message_id)
    if not m:
        raise HTTPException(status_code=404, detail="Message not found")
    t = get_thread(m.thread_id)
    if not t:
        raise HTTPException(status_code=404, detail="Thread not found")
    if t.owner_id is not None:
        owner_id = None
        if token:
            sess = validate_session_token(token)
            if sess:
                owner_id = sess["user_id"]
        if owner_id != t.owner_id:
            raise HTTPException(status_code=404, detail="Message not found")
    ok = delete_message_cascade(message_id)
    if not ok:
        raise HTTPException(status_code=404, detail="Message not found")
    return DeleteMessageResponse(ok=True)


@router.get("/threads/{thread_id}/messages", response_model=List[MessageOut])
def api_get_messages(thread_id: int, token: Optional[str] = Query(None)):
    t = get_thread(thread_id)
    if t and t.owner_id is not None:
        owner_id = None
        if token:
            sess = validate_session_token(token)
            if sess:
                owner_id = sess["user_id"]
        if owner_id != t.owner_id:
            raise HTTPException(status_code=404, detail="Thread not found")
    import json as _json
    msgs = get_thread_messages(thread_id)
    out: List[MessageOut] = []
    for m in msgs:
        meta = None
        agents = None
        tools = None
        try:
            meta = _json.loads(m.meta) if getattr(m, "meta", None) else None
        except Exception:
            meta = None
        try:
            agents = _json.loads(m.agents) if m.agents else None
        except Exception:
            agents = None
        try:
            tools = _json.loads(m.tools) if m.tools else None
        except Exception:
            tools = None
        out.append(MessageOut(
            id=m.id,
            role=m.role,
            content=m.content,
            model=m.model,
            token_in=m.token_in,
            token_out=m.token_out,
            cost_usd=m.cost_usd,
            api_calls=m.api_calls,
            agents=agents,
            tools=tools,
            metadata=meta,
            created_at=m.created_at.isoformat()
        ))
    return out

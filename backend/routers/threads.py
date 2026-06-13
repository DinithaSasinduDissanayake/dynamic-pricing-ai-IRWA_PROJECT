import json
from typing import Any, Dict, List, Optional
from fastapi import APIRouter, HTTPException, Query, Depends
from core.chat_db import (
    create_thread,
    delete_thread,
    get_thread_messages,
    list_threads,
    update_thread,
    update_message,
    add_message,
    SessionLocal,
    Thread as ChatThread,
    Summary as ChatSummary,
)
from core.payloads import (
    CreateThreadRequest,
    ThreadOut,
    UpdateThreadRequest,
    ThreadExport,
    ThreadImportRequest,
)
# Auth migrated to fastapi-users - token validation removed

router = APIRouter(prefix="/api/threads", tags=["threads"])


from backend.deps import get_optional_user

@router.post("", response_model=ThreadOut)
def api_create_thread(
    req: CreateThreadRequest, 
    user: Optional[Dict[str, Any]] = Depends(get_optional_user)
):
    try:
        owner_id = user["user_id"] if user else None
        # Threads created with owner_id if user is logged in
        t = create_thread(title=req.title, owner_id=owner_id)
        return ThreadOut(id=t.id, title=t.title, created_at=t.created_at.isoformat(), updated_at=t.updated_at.isoformat())
    except Exception as e:
        print(f"FATAL ERROR in api_create_thread: {type(e).__name__}: {e}")
        import traceback
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=str(e))


@router.get("", response_model=List[ThreadOut])
def api_list_threads(
    user: Optional[Dict[str, Any]] = Depends(get_optional_user)
):
    owner_id = user["user_id"] if user else None
    # List threads for the current user (or all public threads if no user)
    # Note: If owner_id is None (not logged in), list_threads(None) returns all threads with owner_id=None
    rows = list_threads(owner_id=owner_id)
    return [ThreadOut(id=t.id, title=t.title, created_at=t.created_at.isoformat(), updated_at=t.updated_at.isoformat()) for t in rows]


@router.patch("/{thread_id}", response_model=ThreadOut)
def api_update_thread(thread_id: int, req: UpdateThreadRequest):
    if req.title is None or (req.title or "").strip() == "":
        raise HTTPException(status_code=400, detail="Title cannot be empty")
    t = update_thread(thread_id, title=req.title.strip())
    if not t:
        raise HTTPException(status_code=404, detail="Thread not found")
    return ThreadOut(id=t.id, title=t.title, created_at=t.created_at.isoformat(), updated_at=t.updated_at.isoformat())


@router.delete("/{thread_id}")
def api_delete_thread(
    thread_id: int,
    user: Optional[Dict[str, Any]] = Depends(get_optional_user)
):
    owner_id = user["user_id"] if user else None
    ok = delete_thread(thread_id, owner_id=owner_id)
    if not ok:
        raise HTTPException(status_code=404, detail="Thread not found")
    return {"ok": True}


@router.get("/{thread_id}/export", response_model=ThreadExport)
def api_export_thread(thread_id: int):
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
    thread_info: Dict[str, Any] = {
        "id": t.id,
        "title": t.title,
        "created_at": t.created_at.isoformat() if t.created_at else None,
    }
    
    out_msgs: List[Dict[str, Any]] = []
    for m in msgs:
        item: Dict[str, Any] = {
            "id": m.id,
            "role": m.role,
            "content": m.content,
            "model": m.model,
            "token_in": m.token_in,
            "token_out": m.token_out,
            "cost_usd": m.cost_usd,
            "api_calls": m.api_calls,
            "parent_id": m.parent_id,
            "created_at": m.created_at.isoformat() if m.created_at else None,
            "agents": None,
            "tools": None,
            "metadata": None,
        }
        # Safely parse JSON fields
        item["agents"] = json.loads(m.agents) if m.agents else None
        item["tools"] = json.loads(m.tools) if m.tools else None
        item["metadata"] = json.loads(m.meta) if m.meta else None
        out_msgs.append(item)
    return ThreadExport(thread=thread_info, messages=out_msgs)


@router.post("/import", response_model=ThreadOut)
def api_import_thread(req: ThreadImportRequest):
    t = create_thread(title=req.title, owner_id=req.owner_id)
    id_map: Dict[int, int] = {}
    messages_payload = list(req.messages or [])
    # First pass: create all messages without parent links
    for msg in messages_payload:
        agents = json.dumps(msg.agents) if getattr(msg, 'agents', None) is not None else None
        tools = json.dumps(msg.tools) if getattr(msg, 'tools', None) is not None else None
        # accept either 'metadata' or legacy 'meta' key
        meta_obj = getattr(msg, 'metadata', None)
        if meta_obj is None and hasattr(msg, 'meta'):
            meta_obj = getattr(msg, 'meta')
        metadata = json.dumps(meta_obj) if meta_obj is not None else None
        # create without parent for now
        m = add_message(
            thread_id=t.id,
            role=msg.role,
            content=msg.content,
            model=msg.model,
            token_in=msg.token_in,
            token_out=msg.token_out,
            cost_usd=msg.cost_usd,
            agents=agents,
            tools=tools,
            api_calls=msg.api_calls,
            parent_id=None,
            meta=metadata,
        )
        if getattr(msg, 'id', None) is not None:
            id_map[int(msg.id)] = m.id
    # Second pass: update parent_id links now that we have id_map
    for msg, created_msg_id in zip(messages_payload, list(id_map.values())):
        if getattr(msg, 'parent_id', None) is not None:
            orig_parent = int(msg.parent_id)
            new_parent = id_map.get(orig_parent)
            if new_parent:
                try:
                    update_message(created_msg_id, parent_id=new_parent)
                except Exception:
                    pass
    return ThreadOut(id=t.id, title=t.title, created_at=t.created_at.isoformat())


@router.get("/{thread_id}/summaries")
def api_list_summaries(thread_id: int):
    rows: List[Dict[str, Any]] = []
    try:
        with SessionLocal() as db:
            q = (
                db.query(ChatSummary)
                .filter(ChatSummary.thread_id == thread_id)
                .order_by(ChatSummary.upto_message_id.asc())
                .all()
            )
            for s in q:
                rows.append({
                    "id": s.id,
                    "upto_message_id": s.upto_message_id,
                    "content": s.content,
                    "created_at": s.created_at.isoformat() if s.created_at else None,
                })
    except Exception:
        rows = []
    return {"ok": True, "summaries": rows}

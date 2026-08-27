from typing import Optional, List, Any, Dict
import sqlite3
from pathlib import Path
from fastapi import APIRouter, Depends, HTTPException, Query
from backend.deps import get_current_user

router = APIRouter(tags=["proposals"])


def _get_app_db() -> Path:
    base = Path(__file__).resolve().parents[2]
    app_db = base / "app" / "data.db"
    if not app_db.exists():
        market_db = base / "data" / "market.db"
        if market_db.exists():
            return market_db
    return app_db


@router.get("/api/proposals")
@router.get("/api/prices/proposals")
async def list_proposals(
    sku: Optional[str] = Query(None, description="Filter proposals by SKU"),
    limit: int = Query(50, ge=1, le=200, description="Max proposals to return"),
    current_user: dict = Depends(get_current_user),
) -> Dict[str, Any]:
    owner_id = str(current_user["user_id"])
    db_path = _get_app_db()
    if not db_path.exists():
        return {"ok": True, "proposals": [], "total": 0}

    try:
        with sqlite3.connect(f"file:{db_path.as_posix()}?mode=ro", uri=True) as conn:
            conn.row_factory = sqlite3.Row
            cur = conn.cursor()
            table_check = cur.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='price_proposals'").fetchone()
            if not table_check:
                return {"ok": True, "proposals": [], "total": 0}

            import json
            cols = [col[1] for col in cur.execute("PRAGMA table_info(price_proposals)").fetchall()]
            has_rationale = "rationale" in cols
            
            select_cols = "pp.id, pp.sku, pp.proposed_price, pp.current_price, pp.margin, pp.algorithm, pp.ts"
            if has_rationale:
                select_cols += ", pp.rationale"

            query = f"""
                SELECT {select_cols}
                FROM price_proposals pp
            """
            params: List[Any] = []
            if sku:
                query += " WHERE pp.sku = ?"
                params.append(sku)
            query += " ORDER BY pp.ts DESC LIMIT ?"
            params.append(limit)

            raw_rows = [dict(r) for r in cur.execute(query, params).fetchall()]
            rows = []
            for r in raw_rows:
                rat = r.get("rationale")
                if isinstance(rat, str):
                    try:
                        r["rationale"] = json.loads(rat)
                    except Exception:
                        pass
                rows.append(r)
            return {"ok": True, "proposals": rows, "total": len(rows)}
    except Exception as e:
        return {"ok": True, "proposals": [], "total": 0, "error": str(e)}


@router.post("/api/proposals/{proposal_id}/apply")
async def apply_proposal(
    proposal_id: str,
    confirm: bool = Query(True, description="true = apply the proposal; false = preview only"),
    current_user: dict = Depends(get_current_user),
) -> Dict[str, Any]:
    """Apply (or preview) a price proposal for the authenticated owner.

    Applies with confirm=True by default; pass confirm=false for a dry-run preview.
    """
    owner_id = str(current_user["user_id"])
    from core.agents.user_interact.context import set_owner_id
    from core.agents.user_interact.tools import apply_price_proposal

    set_owner_id(owner_id)
    try:
        res = apply_price_proposal(proposal_id=proposal_id, confirm=confirm)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Apply failed: {str(e)}")

    if res.get("ok"):
        return {"success": True, **res}

    err = str(res.get("error", "Apply failed"))
    lowered = err.lower()
    if "not found" in lowered:
        raise HTTPException(status_code=404, detail=err)
    if "already applied" in lowered:
        raise HTTPException(status_code=409, detail=err)
    if "margin" in lowered:
        raise HTTPException(status_code=422, detail=err)
    raise HTTPException(status_code=400, detail=err)

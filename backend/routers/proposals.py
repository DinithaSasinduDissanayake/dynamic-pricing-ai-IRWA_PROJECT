from typing import Optional, List, Any, Dict
import sqlite3
from pathlib import Path
from fastapi import APIRouter, Depends, Query
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

            query = """
                SELECT pp.id, pp.sku, pp.proposed_price, pp.current_price, pp.margin, pp.algorithm, pp.ts
                FROM price_proposals pp
            """
            params: List[Any] = []
            if sku:
                query += " WHERE pp.sku = ?"
                params.append(sku)
            query += " ORDER BY pp.ts DESC LIMIT ?"
            params.append(limit)

            rows = [dict(r) for r in cur.execute(query, params).fetchall()]
            return {"ok": True, "proposals": rows, "total": len(rows)}
    except Exception as e:
        return {"ok": True, "proposals": [], "total": 0, "error": str(e)}

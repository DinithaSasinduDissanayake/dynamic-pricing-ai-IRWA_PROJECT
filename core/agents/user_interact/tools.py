import sqlite3
from pathlib import Path
from typing import Dict, Any, Optional, List

try:
    from .context import get_owner_id
except Exception:
    def get_owner_id():
        return None


def get_db_paths():
    root = Path(__file__).resolve().parents[3]
    return {
        "app": root / "app" / "data.db",
        "market": root / "data" / "market.db",
        "alert": root / "app" / "alert.db",
    }


def _connect(db_path: str) -> sqlite3.Connection:
    conn = sqlite3.connect(db_path, timeout=30.0)
    conn.execute("PRAGMA journal_mode=WAL;")
    conn.execute("PRAGMA busy_timeout=30000;")
    return conn


def _table_exists(conn: sqlite3.Connection, table: str) -> bool:
    try:
        cur = conn.execute("SELECT name FROM sqlite_master WHERE type='table' AND name=?", (table,))
        return cur.fetchone() is not None
    except Exception:
        return False


def list_inventory_items(search: Optional[str] = None, limit: int = 50) -> Dict[str, Any]:
    db_paths = get_db_paths()
    db_path = str(db_paths["app"])
    owner_id = get_owner_id()
    
    import logging
    logger = logging.getLogger(__name__)
    logger.info(f"[DEBUG] list_inventory_items called with owner_id={owner_id}")
    
    try:
        with _connect(db_path) as conn:
            conn.row_factory = sqlite3.Row
            if not _table_exists(conn, "product_catalog"):
                return {"items": [], "total": 0, "note": "product_catalog missing"}
            
            q = "SELECT sku, title, currency, current_price, cost, stock, updated_at FROM product_catalog"
            params: List[Any] = []
            
            conditions = []
            if owner_id:
                conditions.append("owner_id = ?")
                params.append(owner_id)
                logger.info(f"[DEBUG] Filtering by owner_id={owner_id}")
            else:
                logger.warning("[DEBUG] No owner_id set - returning all items!")
            
            if search:
                conditions.append("(sku LIKE ? OR title LIKE ?)")
                like = f"%{search}%"
                params.extend([like, like])
            
            if conditions:
                q += " WHERE " + " AND ".join(conditions)
            
            q += " ORDER BY updated_at DESC LIMIT ?"
            params.append(int(limit))
            logger.info(f"[DEBUG] Executing query: {q} with params: {params}")
            rows = [dict(r) for r in conn.execute(q, params).fetchall()]
            logger.info(f"[DEBUG] Found {len(rows)} items")

            if not rows and not search:
                return {
                    "message": (
                        "Your inventory is currently empty. To get started, please upload your product catalog.\n"
                        "1. Click the **Catalog** icon in the sidebar menu.\n"
                        "2. In the modal, click **Choose File** and select your CSV or JSON file.\n"
                        "3. The file must contain `sku`, `title`, `currency`, `current_price`, `cost`, and `stock` columns.\n"
                        "4. Click **Upload Catalog** to import your products."
                    )
                }
            
            return {"items": rows, "total": len(rows)}
    except Exception as e:
        logger.error(f"[DEBUG] Error in list_inventory_items: {e}")
        return {"error": str(e)}


def get_inventory_item(sku: str) -> Dict[str, Any]:
    db_paths = get_db_paths()
    db_path = str(db_paths["app"])
    owner_id = get_owner_id()
    
    try:
        with _connect(db_path) as conn:
            conn.row_factory = sqlite3.Row
            if not _table_exists(conn, "product_catalog"):
                return {"item": None, "note": "product_catalog missing"}
            
            q = "SELECT sku, title, currency, current_price, cost, stock, updated_at FROM product_catalog WHERE sku=?"
            params = [sku]
            
            if owner_id:
                q += " AND owner_id=?"
                params.append(owner_id)
            
            q += " LIMIT 1"
            row = conn.execute(q, params).fetchone()
            return {"item": dict(row) if row else None}
    except Exception as e:
        return {"error": str(e)}


def list_pricing_list(search: Optional[str] = None, limit: int = 50) -> Dict[str, Any]:
    db_paths = get_db_paths()
    db_path = str(db_paths["market"])
    try:
        with _connect(db_path) as conn:
            conn.row_factory = sqlite3.Row
            if not _table_exists(conn, "pricing_list"):
                return {"items": [], "total": 0, "note": "pricing_list missing"}
            q = "SELECT product_name, optimized_price, last_update, reason FROM pricing_list"
            params: List[Any] = []
            if search:
                q += " WHERE product_name LIKE ?"
                params.append(f"%{search}%")
            q += " ORDER BY last_update DESC LIMIT ?"
            params.append(int(limit))
            rows = [dict(r) for r in conn.execute(q, params).fetchall()]
            return {"items": rows, "total": len(rows)}
    except Exception as e:
        return {"error": str(e)}


def list_price_proposals(sku: Optional[str] = None, limit: int = 50) -> Dict[str, Any]:
    """
    List recent price proposals from the database.

    This function retrieves a list of the most recent price proposals, optionally
    filtered by SKU. If no proposals are found for the given SKU, it returns a
    user-friendly message indicating that the optimization may not have been run
    or that no valid proposal could be generated.

    Args:
        sku: Optional SKU to filter proposals by.
        limit: Maximum number of proposals to return.

    Returns:
        A dictionary containing the list of proposals or a message if none found.
    """
    db_paths = get_db_paths()
    db_path = str(db_paths["app"])
    owner_id = get_owner_id()
    
    try:
        with _connect(db_path) as conn:
            conn.row_factory = sqlite3.Row
            if not _table_exists(conn, "price_proposals"):
                return {"items": [], "total": 0, "note": "price_proposals missing"}
            
            base_query = """
                SELECT pp.id, pp.sku, pp.proposed_price, pp.current_price, pp.margin, pp.algorithm, pp.ts 
                FROM price_proposals pp
            """
            params: List[Any] = []
            
            if owner_id:
                base_query += " INNER JOIN product_catalog pc ON pp.sku = pc.sku WHERE pc.owner_id = ?"
                params.append(owner_id)
                if sku:
                    base_query += " AND pp.sku = ?"
                    params.append(sku)
            elif sku:
                base_query += " WHERE pp.sku = ?"
                params.append(sku)
            
            q = f"{base_query} ORDER BY pp.ts DESC LIMIT ?"
            params.append(int(limit))
            
            rows = [dict(r) for r in conn.execute(q, params).fetchall()]
            
            if not rows:
                if sku:
                    return {"message": f"No price proposals found for SKU '{sku}'. The optimizer may not have run or a valid proposal could not be generated."}
                else:
                    return {"message": "No price proposals found. Run the optimizer to generate new proposals."}
            
            return {"items": rows, "total": len(rows)}
    except Exception as e:
        return {"error": str(e)}


def list_market_data(search: Optional[str] = None, limit: int = 50) -> Dict[str, Any]:
    db_paths = get_db_paths()
    db_path = str(db_paths["market"])
    try:
        with _connect(db_path) as conn:
            conn.row_factory = sqlite3.Row
            if not _table_exists(conn, "market_data"):
                return {"items": [], "total": 0, "note": "market_data missing"}
            q = "SELECT id, product_name, price, features, update_time FROM market_data"
            params: List[Any] = []
            if search:
                q += " WHERE product_name LIKE ?"
                params.append(f"%{search}%")
            q += " ORDER BY update_time DESC LIMIT ?"
            params.append(int(limit))
            rows = [dict(r) for r in conn.execute(q, params).fetchall()]
            return {"items": rows, "total": len(rows)}
    except Exception as e:
        return {"error": str(e)}


def list_inventory(search: str = "", limit: int = 100) -> Dict[str, Any]:
    return list_inventory_items(search=search or None, limit=limit)


def list_market_prices(search: str = "", limit: int = 10) -> Dict[str, Any]:
    return list_pricing_list(search=search or None, limit=limit)


def list_proposals(sku: str = "", limit: int = 10) -> Dict[str, Any]:
    return list_price_proposals(sku=sku or None, limit=limit)


import asyncio
import uuid


def optimize_price(sku: str, algorithm: Optional[str] = None) -> Dict[str, Any]:
    """
    Trigger price optimization workflow for a product and await proposal.
    
    This publishes an OPTIMIZATION_REQUEST event that triggers the autonomous
    Price Optimizer Agent, then waits for the PRICE_PROPOSAL event with a bounded timeout.
    """
    owner_id = get_owner_id()
    
    if owner_id:
        item_check = get_inventory_item(sku)
        if item_check.get("error"):
            return {"ok": False, "error": f"Failed to verify SKU ownership: {item_check['error']}"}
        if not item_check.get("item"):
            return {"ok": False, "error": f"SKU '{sku}' not found in your inventory"}
    
    try:
        from core.agents.agent_sdk.bus_factory import get_bus
        from core.agents.agent_sdk.protocol import Topic
        
        bus = get_bus()
        request_id = uuid.uuid4().hex
        
        # Publish OPTIMIZATION_REQUEST event with correlation ID
        optimization_payload = {
            "request_id": request_id,
            "sku": sku,
            "product_name": sku,
            "user_request": f"Optimize price for {sku} using algorithm {algorithm}" if algorithm else f"Optimize price for {sku}",
            "algorithm": algorithm,
        }
        
        async def _run_bounded_optimization() -> Dict[str, Any]:
            loop = asyncio.get_running_loop()
            future: asyncio.Future = loop.create_future()

            def on_proposal(proposal: Any):
                try:
                    p_dict = proposal if isinstance(proposal, dict) else (
                        getattr(proposal, "model_dump", None)() if hasattr(proposal, "model_dump") else getattr(proposal, "__dict__", {})
                    )
                    prop_sku = p_dict.get("sku") or p_dict.get("product_id")
                    prop_req_id = p_dict.get("request_id")
                    # Correlate strictly by request_id when available;
                    # keep SKU fallback solely for proposals that legitimately carry no request_id (e.g. autonomous optimizer runs).
                    matched = False
                    if prop_req_id:
                        matched = (prop_req_id == request_id)
                    elif prop_sku and prop_sku == sku:
                        matched = True

                    if matched and not future.done():
                        future.set_result(p_dict)
                except Exception:
                    pass

            bus.subscribe(Topic.PRICE_PROPOSAL.value, on_proposal)
            try:
                loop.create_task(bus.publish(Topic.OPTIMIZATION_REQUEST.value, optimization_payload))
                proposal_data = await asyncio.wait_for(future, timeout=10.0)

                proposed_price = proposal_data.get("proposed_price") if proposal_data.get("proposed_price") is not None else proposal_data.get("new_price")
                old_price = proposal_data.get("current_price") if proposal_data.get("current_price") is not None else proposal_data.get("previous_price", proposal_data.get("old_price"))
                margin = proposal_data.get("margin", 0.0)
                algo = proposal_data.get("algorithm", algorithm or "unknown")
                proposal_id = proposal_data.get("proposal_id", proposal_data.get("id"))
                rationale_obj = proposal_data.get("rationale")
                rationale_text = None
                if isinstance(rationale_obj, dict):
                    rationale_text = rationale_obj.get("rationale_text")
                    if not rationale_text and "bounding_notes" in rationale_obj:
                        rationale_text = "; ".join(rationale_obj["bounding_notes"])
                elif isinstance(rationale_obj, str):
                    try:
                        import json
                        parsed = json.loads(rationale_obj)
                        if isinstance(parsed, dict):
                            rationale_text = parsed.get("rationale_text") or "; ".join(parsed.get("bounding_notes", []))
                        else:
                            rationale_text = str(parsed)
                    except Exception:
                        rationale_text = rationale_obj

                msg_lines = [
                    f"### ✅ Price Optimization Proposal for `{sku}`",
                    f"- **Proposed Price:** ${float(proposed_price):.2f}" if proposed_price is not None else "",
                    f"- **Current/Old Price:** ${float(old_price):.2f}" if old_price is not None else "",
                    f"- **Margin:** {float(margin):.1%}" if margin is not None else "",
                    f"- **Algorithm:** `{algo}`",
                    f"- **Proposal ID:** `{proposal_id}`" if proposal_id else "",
                ]
                if rationale_text:
                    msg_lines.append(f"\n> 💡 **Rationale:** {rationale_text}")
                msg = "\n".join([line for line in msg_lines if line])

                return {
                    "ok": True,
                    "sku": sku,
                    "proposed_price": float(proposed_price) if proposed_price is not None else None,
                    "old_price": float(old_price) if old_price is not None else None,
                    "current_price": float(old_price) if old_price is not None else None,
                    "margin": float(margin) if margin is not None else 0.0,
                    "algorithm": algo,
                    "proposal_id": proposal_id,
                    "proposal": proposal_data,
                    "rationale": rationale_obj,
                    "message": msg,
                }
            except asyncio.TimeoutError:
                return {
                    "ok": True,
                    "timed_out": True,
                    "message": f"Optimization for {sku} is still processing in background. Check proposals shortly.",
                    "sku": sku,
                }
            finally:
                if hasattr(bus, "unsubscribe"):
                    try:
                        bus.unsubscribe(Topic.PRICE_PROPOSAL.value, on_proposal)
                    except Exception:
                        pass
                elif hasattr(bus, "_subs"):
                    try:
                        subs_list = bus._subs.get(Topic.PRICE_PROPOSAL.value, [])
                        if on_proposal in subs_list:
                            subs_list.remove(on_proposal)
                    except Exception:
                        pass

        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            loop = None

        if loop and loop.is_running():
            import concurrent.futures
            # When inside a running event loop (e.g. FastAPI / synchronous tool caller in thread or async),
            # run in a separate thread with dedicated loop to block synchronously without deadlocking
            with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
                return pool.submit(asyncio.run, _run_bounded_optimization()).result()
        else:
            return asyncio.run(_run_bounded_optimization())
    except Exception as e:
        return {"ok": False, "error": f"Failed to trigger optimization: {str(e)}"}


def run_pricing_workflow(sku: str) -> Dict[str, Any]:
    return optimize_price(sku)


def collect_market_data() -> Dict[str, Any]:
    return {"info": "Market data collection would trigger the data collection agent"}


def check_stale_market_data(threshold_minutes: int = 60) -> Dict[str, Any]:
    db_paths = get_db_paths()
    db_path = str(db_paths["market"])
    try:
        with _connect(db_path) as conn:
            conn.row_factory = sqlite3.Row
            if not _table_exists(conn, "market_data"):
                return {"stale_items": [], "count": 0, "note": "market_data missing"}
            
            query = """
                SELECT id, product_name, price, update_time,
                       CAST((julianday('now') - julianday(update_time)) * 24 * 60 AS INTEGER) as age_minutes
                FROM market_data
                WHERE age_minutes > ?
                ORDER BY age_minutes DESC
            """
            rows = conn.execute(query, (threshold_minutes,)).fetchall()
            stale_items = [dict(r) for r in rows]
            
            total_query = "SELECT COUNT(*) as total FROM market_data"
            total_count = conn.execute(total_query).fetchone()["total"]
            
            return {
                "ok": True,
                "stale_items": stale_items,
                "stale_count": len(stale_items),
                "total_count": total_count,
                "threshold_minutes": threshold_minutes,
                "message": f"Found {len(stale_items)} stale items out of {total_count} total (>{threshold_minutes} min old)"
            }
    except Exception as e:
        return {"error": str(e)}


def scan_for_alerts() -> Dict[str, Any]:
    db_paths = get_db_paths()
    db_path = str(db_paths.get("alert") or db_paths["app"])
    owner_id = get_owner_id()
    
    try:
        with _connect(db_path) as conn:
            conn.row_factory = sqlite3.Row
            if not _table_exists(conn, "incidents"):
                return {"alerts": [], "total": 0, "note": "incidents table missing"}
            
            if owner_id:
                rows = conn.execute(
                    """SELECT id, sku, title, severity, status, first_seen, last_seen, rule_id, owner_id 
                       FROM incidents
                       WHERE owner_id = ?
                       ORDER BY first_seen DESC 
                       LIMIT 50""",
                    (owner_id,)
                ).fetchall()
            else:
                rows = conn.execute(
                    """SELECT id, sku, title, severity, status, first_seen, last_seen, rule_id, owner_id 
                       FROM incidents 
                       ORDER BY first_seen DESC 
                       LIMIT 50"""
                ).fetchall()
            
            alerts = [dict(r) for r in rows]
            open_count = sum(1 for a in alerts if a.get("status") == "OPEN")
            
            return {
                "ok": True,
                "alerts": alerts,
                "total": len(alerts),
                "open_count": open_count,
                "message": f"Found {len(alerts)} alerts ({open_count} open)"
            }
    except Exception as e:
        return {"error": str(e)}


def request_market_fetch() -> Dict[str, Any]:
    return {"info": "Market fetch request would trigger the market collector"}


def get_portfolio_urgency() -> Dict[str, Any]:
    """
    Compute server-side portfolio urgency summary across catalog products.
    Evaluates current margin, gap vs latest competitor average price, market data
    staleness, existing open proposals, and open alert incidents. Returns a compact
    ranked list (most urgent first) with a one-line reason per SKU.
    """
    from datetime import datetime, timezone

    db_paths = get_db_paths()
    app_db = str(db_paths["app"])
    market_db = str(db_paths["market"])
    alert_db = str(db_paths.get("alert") or db_paths["app"])
    owner_id = get_owner_id()

    try:
        with _connect(app_db) as app_conn:
            app_conn.row_factory = sqlite3.Row
            if not _table_exists(app_conn, "product_catalog"):
                return {"ok": True, "items": [], "total": 0, "note": "product_catalog missing"}

            cat_query = "SELECT sku, title, currency, current_price, cost, stock, updated_at FROM product_catalog"
            cat_params: List[Any] = []
            if owner_id:
                cat_query += " WHERE owner_id = ?"
                cat_params.append(owner_id)
            cat_query += " ORDER BY sku ASC"
            products = [dict(r) for r in app_conn.execute(cat_query, cat_params).fetchall()]

            if not products:
                return {"ok": True, "items": [], "total": 0, "message": "No products in catalog."}

            # Fetch existing proposals
            prop_rows = app_conn.execute(
                "SELECT sku, proposed_price, current_price, margin, algorithm, ts FROM price_proposals ORDER BY ts DESC"
            ).fetchall()
            proposals_by_sku: Dict[str, Dict[str, Any]] = {}
            for pr in prop_rows:
                s = pr["sku"]
                if s not in proposals_by_sku:
                    proposals_by_sku[s] = dict(pr)

        # Fetch market data from market DB
        market_by_title: Dict[str, List[Dict[str, Any]]] = {}
        try:
            with _connect(market_db) as market_conn:
                market_conn.row_factory = sqlite3.Row
                if _table_exists(market_conn, "market_data"):
                    m_rows = market_conn.execute(
                        "SELECT product_name, price, update_time FROM market_data ORDER BY update_time DESC"
                    ).fetchall()
                    for mr in m_rows:
                        t = mr["product_name"]
                        if t not in market_by_title:
                            market_by_title[t] = []
                        market_by_title[t].append(dict(mr))
        except Exception:
            pass

        # Fetch open alerts from alert DB
        open_alerts_by_sku: Dict[str, List[Dict[str, Any]]] = {}
        try:
            with _connect(alert_db) as alert_conn:
                alert_conn.row_factory = sqlite3.Row
                if _table_exists(alert_conn, "incidents"):
                    al_rows = alert_conn.execute(
                        "SELECT id, sku, title, severity, status FROM incidents WHERE status = 'OPEN'"
                    ).fetchall()
                    for ar in al_rows:
                        s = ar["sku"]
                        if s not in open_alerts_by_sku:
                            open_alerts_by_sku[s] = []
                        open_alerts_by_sku[s].append(dict(ar))
        except Exception:
            pass

        now_utc = datetime.now(timezone.utc)
        items: List[Dict[str, Any]] = []

        for p in products:
            sku = p["sku"]
            title = p["title"]
            curr_price = float(p["current_price"]) if p["current_price"] is not None else 0.0
            cost = float(p["cost"]) if p["cost"] is not None else 0.0
            margin = (curr_price - cost) / curr_price if curr_price > 0 else 0.0

            m_records = market_by_title.get(title, [])
            comp_prices = [float(r["price"]) for r in m_records if r.get("price") is not None]
            avg_comp = round(sum(comp_prices) / len(comp_prices), 2) if comp_prices else None
            
            # Competitor gap: positive means our price is above competitor avg (we are more expensive)
            comp_gap_pct = round(((curr_price - avg_comp) / avg_comp) * 100.0, 1) if avg_comp and avg_comp > 0 else None

            # Staleness
            latest_market_ts = m_records[0]["update_time"] if m_records else None
            minutes_stale = None
            if latest_market_ts:
                try:
                    ts_clean = str(latest_market_ts).replace("Z", "+00:00")
                    dt = datetime.fromisoformat(ts_clean)
                    if dt.tzinfo is None:
                        dt = dt.replace(tzinfo=timezone.utc)
                    minutes_stale = max(0, int((now_utc - dt).total_seconds() / 60))
                except Exception:
                    pass

            has_proposal = sku in proposals_by_sku
            alerts = open_alerts_by_sku.get(sku, [])
            has_alert = len(alerts) > 0

            # Urgency Score calculation:
            # - Open alert: +40 points
            # - Margin below 15%: +35 points, below 20%: +20 points
            # - Competitor price gap: our price >10% above comp (+30 pts), >5% (+15 pts), < -10% (+15 pts)
            # - No market data or stale (>120 min): +20 points
            # - Existing recent proposal already generated: -15 points (already addressed)
            urgency_score = 0.0
            reasons: List[str] = []

            if has_alert:
                urgency_score += 40.0
                reasons.append(f"{len(alerts)} open alert(s)")

            if margin < 0.12:
                urgency_score += 40.0
                reasons.append(f"low margin {margin:.1%} (<12% floor)")
            elif margin < 0.20:
                urgency_score += 20.0
                reasons.append(f"thin margin {margin:.1%}")

            if comp_gap_pct is not None:
                if comp_gap_pct > 10.0:
                    urgency_score += 30.0
                    reasons.append(f"priced +{comp_gap_pct:g}% above competitor avg (${avg_comp:.2f})")
                elif comp_gap_pct > 5.0:
                    urgency_score += 15.0
                    reasons.append(f"priced +{comp_gap_pct:g}% above competitor avg (${avg_comp:.2f})")
                elif comp_gap_pct < -10.0:
                    urgency_score += 15.0
                    reasons.append(f"priced {comp_gap_pct:g}% below competitor avg (${avg_comp:.2f})")
            elif not m_records:
                urgency_score += 20.0
                reasons.append("no competitor market data")

            if minutes_stale is not None and minutes_stale > 120:
                urgency_score += 10.0
                reasons.append(f"market data stale ({minutes_stale}m old)")

            if has_proposal:
                urgency_score = max(0.0, urgency_score - 15.0)
                prop_algo = proposals_by_sku[sku].get("algorithm", "auto")
                reasons.append(f"proposal pending ({prop_algo})")
            else:
                reasons.append("no open proposal")

            urgency_level = "HIGH" if urgency_score >= 50 else ("MEDIUM" if urgency_score >= 25 else "LOW")
            reason_line = "; ".join(reasons)

            items.append({
                "sku": sku,
                "title": title,
                "current_price": curr_price,
                "cost": cost,
                "margin_pct": round(margin * 100.0, 1),
                "avg_competitor_price": avg_comp,
                "competitor_gap_pct": comp_gap_pct,
                "market_data_stale_minutes": minutes_stale,
                "has_open_proposal": has_proposal,
                "has_open_alert": has_alert,
                "urgency_score": round(urgency_score, 1),
                "urgency_level": urgency_level,
                "reason": reason_line,
            })

        # Rank most urgent first
        items.sort(key=lambda x: (x["urgency_score"], -x["margin_pct"]), reverse=True)

        return {
            "ok": True,
            "total_products": len(items),
            "ranked_urgency": items,
        }
    except Exception as e:
        return {"ok": False, "error": str(e)}


TOOLS_MAP = {
    "list_inventory_items": list_inventory_items,
    "get_inventory_item": get_inventory_item,
    "list_pricing_list": list_pricing_list,
    "list_price_proposals": list_price_proposals,
    "list_market_data": list_market_data,
    "check_stale_market_data": check_stale_market_data,
    "list_inventory": list_inventory,
    "list_market_prices": list_market_prices,
    "list_proposals": list_proposals,
    "optimize_price": optimize_price,
    "get_portfolio_urgency": get_portfolio_urgency,
    "run_pricing_workflow": run_pricing_workflow,
    "collect_market_data": collect_market_data,
    "scan_for_alerts": scan_for_alerts,
    "request_market_fetch": request_market_fetch,
}

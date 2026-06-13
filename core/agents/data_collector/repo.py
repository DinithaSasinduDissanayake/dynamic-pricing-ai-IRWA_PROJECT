from __future__ import annotations

import os
import uuid
from pathlib import Path
from datetime import datetime, timezone
from typing import Any, Dict, Optional, List

from sqlalchemy.ext.asyncio import create_async_engine, AsyncEngine
from sqlalchemy import text


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


class DataRepo:
    """
    Minimal repo for market ticks. Uses SQLite via SQLAlchemy async.
    """

    def __init__(self, path: Optional[str] = None) -> None:
        if path:
            self.path = Path(path) if not isinstance(path, Path) else path
        else:
            try:
                from core.settings import get_settings
                self.path = get_settings().resolve_app_db()
            except Exception:
                root = Path(__file__).resolve().parents[3]
                self.path = root / "app" / "data.db"
        
        self.engine: Optional[AsyncEngine] = None

    def _get_engine(self) -> AsyncEngine:
        if self.engine is None:
            self.engine = create_async_engine(
                f"sqlite+aiosqlite:///{self.path.as_posix()}",
                echo=False
            )
        return self.engine

    async def init(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        engine = self._get_engine()
        
        async with engine.begin() as conn:
            await conn.execute(text("PRAGMA journal_mode=WAL"))
            await conn.execute(text("""
                CREATE TABLE IF NOT EXISTS market_ticks (
                  id INTEGER PRIMARY KEY AUTOINCREMENT,
                  sku TEXT NOT NULL,
                  market TEXT NOT NULL,
                  our_price REAL NOT NULL,
                  competitor_price REAL,
                  demand_index REAL,
                  ts TEXT NOT NULL,
                  source TEXT,
                  ingested_at TEXT NOT NULL
                )
            """))
            await conn.execute(text("""
                CREATE INDEX IF NOT EXISTS ix_ticks_sku_market_ts
                  ON market_ticks (sku, market, ts)
            """))
            await conn.execute(text("""
                CREATE TABLE IF NOT EXISTS product_catalog (
                   sku TEXT,
                   owner_id TEXT NOT NULL,
                   title TEXT,
                   currency TEXT,
                   current_price REAL,
                   cost REAL,
                   stock INTEGER,
                   updated_at TEXT,
                   source_url TEXT,
                   PRIMARY KEY (sku, owner_id)
                )
            """))
            await conn.execute(text("""
                CREATE INDEX IF NOT EXISTS idx_product_catalog_owner_id 
                   ON product_catalog(owner_id)
            """))
            await conn.execute(text("""
                CREATE TABLE IF NOT EXISTS ingestion_jobs (
                  id TEXT PRIMARY KEY,
                  sku TEXT,
                  market TEXT,
                  connector TEXT,
                  depth INTEGER,
                  status TEXT,
                  error TEXT,
                  created_at TEXT,
                  started_at TEXT,
                  finished_at TEXT
                )
            """))
            await conn.execute(text("""
                CREATE TABLE IF NOT EXISTS price_proposals (
                  id TEXT PRIMARY KEY,
                  sku TEXT,
                  proposed_price REAL,
                  current_price REAL,
                  margin REAL,
                  algorithm TEXT,
                  ts TEXT
                )
            """))

    async def insert_tick(self, d: Dict[str, Any]) -> None:
        ts = d.get("ts") or _utc_now_iso()
        engine = self._get_engine()
        
        async with engine.begin() as conn:
            await conn.execute(
                text("""
                    INSERT INTO market_ticks
                      (sku, market, our_price, competitor_price, demand_index, ts, source, ingested_at)
                    VALUES (:sku, :market, :our_price, :competitor_price, :demand_index, :ts, :source, :ingested_at)
                """),
                {
                    "sku": d["sku"],
                    "market": d.get("market", "DEFAULT"),
                    "our_price": float(d["our_price"]),
                    "competitor_price": d.get("competitor_price"),
                    "demand_index": d.get("demand_index"),
                    "ts": ts,
                    "source": d.get("source", "unknown"),
                    "ingested_at": _utc_now_iso(),
                }
            )

    async def features_for(self, sku: str, market: str, since_iso: str) -> Dict[str, Any]:
        """Return simple recent features for a window: latest values + basic gap."""
        engine = self._get_engine()
        
        async with engine.connect() as conn:
            result = await conn.execute(
                text("""
                    SELECT our_price, competitor_price, demand_index, ts
                    FROM market_ticks
                    WHERE sku=:sku AND market=:market AND ts>=:since_iso
                    ORDER BY ts DESC
                    LIMIT 100
                """),
                {"sku": sku, "market": market, "since_iso": since_iso}
            )
            rows = result.fetchall()

        if not rows:
            return {
                "snapshot_id": None,
                "as_of": None,
                "features": {},
                "provenance": [],
                "count": 0,
            }

        our_latest, comp_latest, dem_latest, as_of = rows[0]
        gap_pct = None
        if our_latest and comp_latest is not None:
            try:
                gap_pct = (our_latest - comp_latest) / our_latest if our_latest else None
            except ZeroDivisionError:
                gap_pct = None

        return {
            "snapshot_id": f"snap:{sku}:{market}:{as_of}",
            "as_of": as_of,
            "features": {
                "our_price": our_latest,
                "competitor_price": comp_latest,
                "demand_index": dem_latest,
                "price_gap_pct": gap_pct,
            },
            "provenance": ["market_ticks"],
            "count": len(rows),
        }

    async def upsert_products(self, rows: List[Dict[str, Any]], owner_id: str) -> int:
        """Upsert a list of product rows into product_catalog."""
        if not rows:
            return 0

        params = []
        for r in rows:
            sku = str(r["sku"]).strip()
            if not sku:
                continue
            params.append({
                "sku": sku,
                "owner_id": owner_id,
                "title": r.get("title"),
                "currency": r.get("currency"),
                "current_price": r.get("current_price"),
                "cost": r.get("cost"),
                "stock": r.get("stock"),
                "updated_at": r.get("updated_at") or _utc_now_iso(),
            })

        if not params:
            return 0

        engine = self._get_engine()
        async with engine.begin() as conn:
            for p in params:
                await conn.execute(
                    text("""
                        INSERT INTO product_catalog
                          (sku, owner_id, title, currency, current_price, cost, stock, updated_at)
                        VALUES (:sku, :owner_id, :title, :currency, :current_price, :cost, :stock, :updated_at)
                        ON CONFLICT(sku, owner_id) DO UPDATE SET
                          title=excluded.title,
                          currency=excluded.currency,
                          current_price=excluded.current_price,
                          cost=excluded.cost,
                          stock=excluded.stock,
                          updated_at=excluded.updated_at
                    """),
                    p
                )
        return len(params)

    async def get_products_by_owner(self, owner_id: str) -> List[Dict[str, Any]]:
        """Retrieve all products for a specific owner."""
        engine = self._get_engine()
        
        async with engine.connect() as conn:
            result = await conn.execute(
                text("""
                    SELECT sku, owner_id, title, currency, current_price, cost, stock, updated_at
                    FROM product_catalog
                    WHERE owner_id=:owner_id
                    ORDER BY updated_at DESC
                """),
                {"owner_id": owner_id}
            )
            rows = result.fetchall()
        
        return [
            {
                "sku": r[0],
                "owner_id": r[1],
                "title": r[2],
                "currency": r[3],
                "current_price": r[4],
                "cost": r[5],
                "stock": r[6],
                "updated_at": r[7],
            }
            for r in rows
        ]

    async def get_product_by_sku_and_owner(self, sku: str, owner_id: str) -> Optional[Dict[str, Any]]:
        """Retrieve a specific product by SKU and owner_id."""
        engine = self._get_engine()
        
        async with engine.connect() as conn:
            result = await conn.execute(
                text("""
                    SELECT sku, owner_id, title, currency, current_price, cost, stock, updated_at
                    FROM product_catalog
                    WHERE sku=:sku AND owner_id=:owner_id
                """),
                {"sku": sku, "owner_id": owner_id}
            )
            row = result.fetchone()
        
        if not row:
            return None
        
        return {
            "sku": row[0],
            "owner_id": row[1],
            "title": row[2],
            "currency": row[3],
            "current_price": row[4],
            "cost": row[5],
            "stock": row[6],
            "updated_at": row[7],
        }

    async def delete_product_by_owner(self, sku: str, owner_id: str) -> int:
        """Delete a product for a specific owner. Returns rows affected."""
        engine = self._get_engine()
        
        async with engine.begin() as conn:
            result = await conn.execute(
                text("""
                    DELETE FROM product_catalog
                    WHERE sku=:sku AND owner_id=:owner_id
                """),
                {"sku": sku, "owner_id": owner_id}
            )
            return result.rowcount

    async def delete_all_products_by_owner(self, owner_id: str) -> int:
        """Delete all products for a specific owner. Returns rows affected."""
        engine = self._get_engine()
        
        async with engine.begin() as conn:
            result = await conn.execute(
                text("""
                    DELETE FROM product_catalog
                    WHERE owner_id=:owner_id
                """),
                {"owner_id": owner_id}
            )
            return result.rowcount

    async def create_job(self, sku: str, market: str, connector: str, depth: int) -> str:
        """Create an ingestion job and return its job id (uuid4)."""
        job_id = str(uuid.uuid4())
        now = _utc_now_iso()
        engine = self._get_engine()
        
        async with engine.begin() as conn:
            await conn.execute(
                text("""
                    INSERT INTO ingestion_jobs
                      (id, sku, market, connector, depth, status, error, created_at, started_at, finished_at)
                    VALUES (:id, :sku, :market, :connector, :depth, :status, :error, :created_at, :started_at, :finished_at)
                """),
                {
                    "id": job_id,
                    "sku": sku,
                    "market": market,
                    "connector": connector,
                    "depth": int(depth),
                    "status": "QUEUED",
                    "error": None,
                    "created_at": now,
                    "started_at": None,
                    "finished_at": None,
                }
            )
        return job_id

    async def mark_job_running(self, job_id: str) -> None:
        """Mark an ingestion job as RUNNING and set started_at timestamp."""
        engine = self._get_engine()
        
        async with engine.begin() as conn:
            await conn.execute(
                text("""
                    UPDATE ingestion_jobs
                    SET status=:status, started_at=:started_at
                    WHERE id=:id
                """),
                {"status": "RUNNING", "started_at": _utc_now_iso(), "id": job_id}
            )

    async def mark_job_done(self, job_id: str) -> None:
        """Mark an ingestion job as DONE and set finished_at timestamp."""
        engine = self._get_engine()
        
        async with engine.begin() as conn:
            await conn.execute(
                text("""
                    UPDATE ingestion_jobs
                    SET status=:status, finished_at=:finished_at
                    WHERE id=:id
                """),
                {"status": "DONE", "finished_at": _utc_now_iso(), "id": job_id}
            )

    async def mark_job_failed(self, job_id: str, error: str) -> None:
        """Mark an ingestion job as FAILED with an error message."""
        engine = self._get_engine()
        
        async with engine.begin() as conn:
            await conn.execute(
                text("""
                    UPDATE ingestion_jobs
                    SET status=:status, error=:error, finished_at=:finished_at
                    WHERE id=:id
                """),
                {"status": "FAILED", "error": str(error), "finished_at": _utc_now_iso(), "id": job_id}
            )

    async def get_job(self, job_id: str) -> Optional[Dict[str, Any]]:
        """Return a job row as a dict, or None if not found."""
        engine = self._get_engine()
        
        async with engine.connect() as conn:
            result = await conn.execute(
                text("""
                    SELECT id, sku, market, connector, depth, status, error,
                           created_at, started_at, finished_at
                    FROM ingestion_jobs
                    WHERE id=:id
                """),
                {"id": job_id}
            )
            row = result.fetchone()
        
        if not row:
            return None
        
        keys = ["id", "sku", "market", "connector", "depth", "status", "error",
                "created_at", "started_at", "finished_at"]
        return {k: row[i] for i, k in enumerate(keys)}

async def insert_price_proposal(self, pp: Dict[str, Any]) -> None:
        """Insert a price proposal row and write an outbox event for propagation."""
        pid = pp.get("id") or str(uuid.uuid4())
        ts = pp.get("ts") or _utc_now_iso()
        engine = self._get_engine()
        
        async with engine.begin() as conn:
            await conn.execute(
                text("""
                    INSERT INTO price_proposals
                      (id, sku, proposed_price, current_price, margin, algorithm, ts)
                    VALUES (:id, :sku, :proposed_price, :current_price, :margin, :algorithm, :ts)
                """),
                {
                    "id": pid,
                    "sku": pp["sku"],
                    "proposed_price": pp["proposed_price"],
                    "current_price": pp["current_price"],
                    "margin": pp["margin"],
                    "algorithm": pp["algorithm"],
                    "ts": ts,
                }
            )
        # Write outbox record for reliable publish without losing event on commit
        try:
            from core.agents.agent_sdk.outbox import OutboxRepo
            outbox = OutboxRepo(path=self.path)
            await outbox.init()
            await outbox.enqueue("price.proposal", {"proposal_id": pid, "product_id": pp["sku"], "previous_price": pp.get("current_price"), "proposed_price": pp.get("proposed_price")})
        except Exception:
            # best-effort: ignore
            pass


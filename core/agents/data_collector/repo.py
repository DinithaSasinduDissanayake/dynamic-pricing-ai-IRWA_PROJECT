from __future__ import annotations

import os
from pathlib import Path
from datetime import datetime, timezone
from typing import Any, Dict, Optional, List

import aiosqlite
import uuid
import sqlite3


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


class DataRepo:
    """
    Minimal repo for market ticks. Uses SQLite at DATA_DB or app/data.db.
    """

    def __init__(self, path: Optional[str] = None, market_path: Optional[str] = None) -> None:
        db_env = os.getenv("DATA_DB", "app/data.db")
        market_env = os.getenv("MARKET_DB", "data/market.db")
        self.path = Path(path or db_env)
        self.market_path = Path(market_path or market_env)

    def _connect_app(self):
        return aiosqlite.connect(self.path.as_posix(), timeout=30.0)

    def _connect_market(self):
        return aiosqlite.connect(self.market_path.as_posix(), timeout=30.0)

    async def init(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.market_path.parent.mkdir(parents=True, exist_ok=True)
        
        async with self._connect_market() as mdb:
            await mdb.executescript(
                """
                PRAGMA journal_mode=WAL;
                PRAGMA busy_timeout=30000;

                CREATE TABLE IF NOT EXISTS market_data (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    owner_id INTEGER,
                    product_name TEXT,
                    price REAL,
                    features TEXT,
                    update_time TEXT
                );

                CREATE INDEX IF NOT EXISTS idx_market_data_owner ON market_data(owner_id);
                CREATE INDEX IF NOT EXISTS idx_market_data_product ON market_data(product_name);
                """
            )
            await mdb.commit()

        async with self._connect_app() as db:
            await db.executescript(
                """
                PRAGMA journal_mode=WAL;
                PRAGMA busy_timeout=30000;

                -- Additive tables for product catalog, jobs, and proposals
                CREATE TABLE IF NOT EXISTS product_catalog (
                   sku TEXT,
                   owner_id TEXT NOT NULL,
                   title TEXT,
                   currency TEXT,
                   current_price REAL,
                   cost REAL,
                   stock INTEGER,
                   updated_at TEXT,
                   PRIMARY KEY (sku, owner_id)
                );
                
                CREATE INDEX IF NOT EXISTS idx_product_catalog_owner_id 
                   ON product_catalog(owner_id);

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
                );

                CREATE TABLE IF NOT EXISTS price_proposals (
                  id TEXT PRIMARY KEY,
                  sku TEXT,
                  proposed_price REAL,
                  current_price REAL,
                  margin REAL,
                  algorithm TEXT,
                  ts TEXT
                );
                """
            )
            await db.commit()

    async def insert_tick(self, d: Dict[str, Any]) -> None:
        # Expect ISO ts; if missing, use now
        ts = d.get("ts") or _utc_now_iso()
        price = d.get("competitor_price")
        if price is None:
            price = float(d.get("our_price", 0.0))
        else:
            price = float(price)

        owner_id = d.get("owner_id")
        product_name = d.get("product_name")

        sku = d.get("sku")
        if sku and (not product_name or owner_id is None):
            async with self._connect_app() as db:
                db.row_factory = aiosqlite.Row
                cur = await db.execute(
                    "SELECT title, owner_id FROM product_catalog WHERE sku=? LIMIT 1",
                    (sku,),
                )
                row = await cur.fetchone()
                if row:
                    if not product_name and row["title"]:
                        product_name = row["title"]
                    if owner_id is None and row["owner_id"] is not None:
                        try:
                            owner_id = int(row["owner_id"])
                        except (ValueError, TypeError):
                            owner_id = row["owner_id"]

        if not product_name:
            product_name = sku or "Unknown Product"
        if owner_id is None:
            owner_id = 1

        features_str = d.get("features")
        if not features_str:
            features_str = f"Market observation for {sku or product_name}"

        async with self._connect_market() as mdb:
            await mdb.execute(
                """
                INSERT INTO market_data (owner_id, product_name, price, features, update_time)
                VALUES (?, ?, ?, ?, ?)
                """,
                (owner_id, product_name, price, features_str, ts),
            )
            await mdb.commit()

    async def features_for(
        self, sku: str, market: str, since_iso: str
    ) -> Dict[str, Any]:
        """
        Return simple recent features for a window: latest values + basic gap.
        Queries canonical market_data table in market_db.
        """
        product_name = sku
        our_price = None

        async with self._connect_app() as db:
            db.row_factory = aiosqlite.Row
            cur = await db.execute(
                "SELECT title, current_price FROM product_catalog WHERE sku=? LIMIT 1",
                (sku,),
            )
            row = await cur.fetchone()
            if row:
                if row["title"]:
                    product_name = row["title"]
                if row["current_price"] is not None:
                    our_price = float(row["current_price"])

        q = """
        SELECT price, update_time
        FROM market_data
        WHERE product_name=? AND update_time>=?
        ORDER BY update_time DESC
        LIMIT 100
        """
        async with self._connect_market() as mdb:
            cur = await mdb.execute(q, (product_name, since_iso))
            rows = await cur.fetchall()

        if not rows:
            return {
                "snapshot_id": None,
                "as_of": None,
                "features": {
                    "our_price": our_price,
                    "competitor_price": None,
                    "demand_index": None,
                    "price_gap_pct": None,
                },
                "provenance": ["market_data"],
                "count": 0,
            }

        comp_latest, as_of = rows[0]
        comp_latest = float(comp_latest) if comp_latest is not None else None
        gap_pct = None
        if our_price and comp_latest is not None:
            try:
                gap_pct = (our_price - comp_latest) / our_price if our_price else None
            except ZeroDivisionError:
                gap_pct = None

        return {
            "snapshot_id": f"snap:{sku}:{market}:{as_of}",
            "as_of": as_of,
            "features": {
                "our_price": our_price,
                "competitor_price": comp_latest,
                "demand_index": 1.0,
                "price_gap_pct": gap_pct,
            },
            "provenance": ["market_data"],
            "count": len(rows),
        }


    async def upsert_products(self, rows: List[Dict[str, Any]], owner_id: str) -> int:
        """Upsert a list of product rows into product_catalog.

        Uses INSERT ... ON CONFLICT(sku, owner_id) DO UPDATE for efficiency; if not
        supported, falls back to INSERT/UPDATE per-row. Returns number of
        processed rows.
        """
        if not rows:
            return 0

        params = []
        for r in rows:
            sku = str(r["sku"]).strip()
            if not sku:
                continue
            title = r.get("title")
            currency = r.get("currency")
            current_price = r.get("current_price")
            cost = r.get("cost")
            stock = r.get("stock")
            updated_at = r.get("updated_at") or _utc_now_iso()
            params.append(
                (sku, owner_id, title, currency, current_price, cost, stock, updated_at)
            )

        if not params:
            return 0

        insert_sql = (
            """
            INSERT INTO product_catalog
              (sku, owner_id, title, currency, current_price, cost, stock, updated_at)
            VALUES (?,?,?,?,?,?,?,?)
            ON CONFLICT(sku, owner_id) DO UPDATE SET
              title=excluded.title,
              currency=excluded.currency,
              current_price=excluded.current_price,
              cost=excluded.cost,
              stock=excluded.stock,
              updated_at=excluded.updated_at
            """
        )

        async with self._connect_app() as db:
            try:
                await db.executemany(insert_sql, params)
                await db.commit()
                return len(params)
            except Exception:
                processed = 0
                for p in params:
                    try:
                        await db.execute(
                            """
                            INSERT INTO product_catalog
                              (sku, owner_id, title, currency, current_price, cost, stock,
                               updated_at)
                            VALUES (?,?,?,?,?,?,?,?)
                            """,
                            p,
                        )
                        processed += 1
                    except sqlite3.IntegrityError:
                        sku = p[0]
                        owner_id_val = p[1]
                        title, currency, current_price, cost, stock, updated_at = (
                            p[2], p[3], p[4], p[5], p[6], p[7]
                        )
                        await db.execute(
                            """
                            UPDATE product_catalog
                            SET title=?, currency=?, current_price=?, cost=?,
                                stock=?, updated_at=?
                            WHERE sku=? AND owner_id=?
                            """,
                            (
                                title,
                                currency,
                                current_price,
                                cost,
                                stock,
                                updated_at,
                                sku,
                                owner_id_val,
                            ),
                        )
                        processed += 1
                await db.commit()
                return processed

    async def get_products_by_owner(self, owner_id: str) -> List[Dict[str, Any]]:
        """Retrieve all products for a specific owner."""
        async with self._connect_app() as db:
            db.row_factory = aiosqlite.Row
            cur = await db.execute(
                """
                SELECT sku, owner_id, title, currency, current_price, cost, stock, updated_at
                FROM product_catalog
                WHERE owner_id=?
                ORDER BY updated_at DESC
                """,
                (owner_id,),
            )
            rows = await cur.fetchall()
        return [dict(row) for row in rows]

    async def get_product_by_sku_and_owner(self, sku: str, owner_id: str) -> Optional[Dict[str, Any]]:
        """Retrieve a specific product by SKU and owner_id."""
        async with self._connect_app() as db:
            db.row_factory = aiosqlite.Row
            cur = await db.execute(
                """
                SELECT sku, owner_id, title, currency, current_price, cost, stock, updated_at
                FROM product_catalog
                WHERE sku=? AND owner_id=?
                """,
                (sku, owner_id),
            )
            row = await cur.fetchone()
        return dict(row) if row else None

    async def delete_product_by_owner(self, sku: str, owner_id: str) -> int:
        """Delete a product for a specific owner. Returns rows affected."""
        async with self._connect_app() as db:
            cursor = await db.execute(
                """
                DELETE FROM product_catalog
                WHERE sku=? AND owner_id=?
                """,
                (sku, owner_id),
            )
            await db.commit()
        return cursor.rowcount

    async def delete_all_products_by_owner(self, owner_id: str) -> int:
        """Delete all products for a specific owner. Returns rows affected."""
        async with self._connect_app() as db:
            cursor = await db.execute(
                """
                DELETE FROM product_catalog
                WHERE owner_id=?
                """,
                (owner_id,),
            )
            await db.commit()
        return cursor.rowcount

    async def create_job(
        self, sku: str, market: str, connector: str, depth: int
    ) -> str:
        """Create an ingestion job and return its job id (uuid4)."""
        job_id = str(uuid.uuid4())
        now = _utc_now_iso()
        async with self._connect_app() as db:
            await db.execute(
                """
                INSERT INTO ingestion_jobs
                  (id, sku, market, connector, depth, status, error,
                   created_at, started_at, finished_at)
                VALUES (?,?,?,?,?,?,?, ?, ?, ?)
                """,
                (
                    job_id,
                    sku,
                    market,
                    connector,
                    int(depth),
                    "QUEUED",
                    None,
                    now,
                    None,
                    None,
                ),
            )
            await db.commit()
        return job_id

    async def mark_job_running(self, job_id: str) -> None:
        """Mark an ingestion job as RUNNING and set started_at timestamp."""
        async with self._connect_app() as db:
            await db.execute(
                """
                UPDATE ingestion_jobs
                SET status=?, started_at=?
                WHERE id=?
                """,
                ("RUNNING", _utc_now_iso(), job_id),
            )
            await db.commit()

    async def mark_job_done(self, job_id: str) -> None:
        """Mark an ingestion job as DONE and set finished_at timestamp."""
        async with self._connect_app() as db:
            await db.execute(
                """
                UPDATE ingestion_jobs
                SET status=?, finished_at=?
                WHERE id=?
                """,
                ("DONE", _utc_now_iso(), job_id),
            )
            await db.commit()

    async def mark_job_failed(self, job_id: str, error: str) -> None:
        """Mark an ingestion job as FAILED with an error message."""
        async with self._connect_app() as db:
            await db.execute(
                """
                UPDATE ingestion_jobs
                SET status=?, error=?, finished_at=?
                WHERE id=?
                """,
                ("FAILED", str(error), _utc_now_iso(), job_id),
            )
            await db.commit()

    async def get_job(self, job_id: str) -> Optional[Dict[str, Any]]:
        """Return a job row as a dict, or None if not found."""
        async with self._connect_app() as db:
            cur = await db.execute(
                """
                SELECT id, sku, market, connector, depth, status, error,
                       created_at, started_at, finished_at
                FROM ingestion_jobs
                WHERE id=?
                """,
                (job_id,),
            )
            row = await cur.fetchone()
        if not row:
            return None
        keys = [
            "id",
            "sku",
            "market",
            "connector",
            "depth",
            "status",
            "error",
            "created_at",
            "started_at",
            "finished_at",
        ]
        return {k: row[i] for i, k in enumerate(keys)}

    async def insert_price_proposal(self, pp: Dict[str, Any]) -> None:
        """Insert a price proposal row.

        If 'id' or 'ts' are missing, they will be generated.
        """
        pid = pp.get("id") or str(uuid.uuid4())
        ts = pp.get("ts") or _utc_now_iso()
        async with self._connect_app() as db:
            await db.execute(
                """
                INSERT INTO price_proposals
                  (id, sku, proposed_price, current_price, margin, algorithm, ts)
                VALUES (?,?,?,?,?,?,?)
                """,
                (
                    pid,
                    pp["sku"],
                    pp["proposed_price"],
                    pp["current_price"],
                    pp["margin"],
                    pp["algorithm"],
                    ts,
                ),
            )
            await db.commit()

from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Optional

from core.settings import get_settings
from sqlalchemy.ext.asyncio import create_async_engine, AsyncEngine
from sqlalchemy import text


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass
class OutboxEntry:
    id: str
    topic: str
    payload: Dict[str, Any]
    ts: str


class OutboxRepo:
    def __init__(self, path: Optional[Path] = None):
        if path is None:
            path = get_settings().resolve_app_db()
        self.path = Path(path)
        self.engine: Optional[AsyncEngine] = None

    def _get_engine(self) -> AsyncEngine:
        if self.engine is None:
            self.engine = create_async_engine(f"sqlite+aiosqlite:///{self.path.as_posix()}", echo=False)
        return self.engine

    async def init(self) -> None:
        p = self.path
        p.parent.mkdir(parents=True, exist_ok=True)
        engine = self._get_engine()
        async with engine.begin() as conn:
            await conn.execute(text("PRAGMA journal_mode=WAL"))
            await conn.execute(text("""
                CREATE TABLE IF NOT EXISTS outbox (
                    id TEXT PRIMARY KEY,
                    topic TEXT NOT NULL,
                    payload_json TEXT NOT NULL,
                    ts TEXT NOT NULL,
                    published INTEGER NOT NULL DEFAULT 0
                )
            """))

    async def enqueue(self, topic: str, payload: Dict[str, Any]) -> None:
        engine = self._get_engine()
        async with engine.begin() as conn:
            await conn.execute(text(
                "INSERT INTO outbox (id, topic, payload_json, ts, published) VALUES (:id, :topic, :payload_json, :ts, 0)"
            ), {"id": str(uuid.uuid4().hex), "topic": topic, "payload_json": json.dumps(payload, ensure_ascii=False), "ts": _utc_now_iso()})

    async def fetch_unpublished(self, limit: int = 100) -> list[OutboxEntry]:
        engine = self._get_engine()
        async with engine.connect() as conn:
            r = await conn.execute(text("SELECT id, topic, payload_json, ts FROM outbox WHERE published=0 ORDER BY ts LIMIT :limit"), {"limit": limit})
            rows = r.fetchall()
        return [OutboxEntry(id=row[0], topic=row[1], payload=json.loads(row[2]), ts=row[3]) for row in rows]

    async def mark_published(self, id: str) -> None:
        engine = self._get_engine()
        async with engine.begin() as conn:
            await conn.execute(text("UPDATE outbox SET published=1 WHERE id=:id"), {"id": id})


async def _flusher_loop(repo: OutboxRepo, bus, interval: float = 0.5):
    while True:
        try:
            items = await repo.fetch_unpublished()
            for item in items:
                try:
                    await bus.publish(item.topic, item.payload)
                    await repo.mark_published(item.id)
                except Exception:
                    pass
        except Exception:
            pass
        await asyncio.sleep(interval)


async def start_outbox_flusher(bus, path: Optional[Path] = None) -> None:
    repo = OutboxRepo(path)
    await repo.init()
    asyncio.create_task(_flusher_loop(repo, bus))

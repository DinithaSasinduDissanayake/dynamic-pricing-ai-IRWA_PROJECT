# core/agents/alert_service/repo.py

import json
from datetime import datetime, timedelta, timezone
from typing import List, Optional, Dict, Any
from pathlib import Path

from sqlalchemy.ext.asyncio import create_async_engine, AsyncEngine
from sqlalchemy import text

from .schemas import RuleSpec, RuleRecord, Alert, Incident


class Repo:
    def __init__(self, path: str = "app/alert.db") -> None:
        self.path = Path(path)
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
            await conn.execute(text("""
                CREATE TABLE IF NOT EXISTS rules (
                  id TEXT PRIMARY KEY,
                  version INTEGER,
                  spec_json TEXT,
                  enabled INTEGER
                )
            """))
            await conn.execute(text("""
                CREATE TABLE IF NOT EXISTS incidents (
                  id TEXT PRIMARY KEY,
                  rule_id TEXT,
                  sku TEXT,
                  status TEXT,
                  first_seen TEXT,
                  last_seen TEXT,
                  severity TEXT,
                  title TEXT,
                  group_key TEXT,
                  fingerprint TEXT UNIQUE,
                  owner_id TEXT
                )
            """))
            await conn.execute(text("""
                CREATE TABLE IF NOT EXISTS deliveries (
                  id TEXT PRIMARY KEY,
                  incident_id TEXT,
                  channel TEXT,
                  ts TEXT,
                  status TEXT,
                  response_json TEXT
                )
            """))
            await conn.execute(text("""
                CREATE TABLE IF NOT EXISTS settings (
                  key TEXT PRIMARY KEY,
                  value TEXT
                )
            """))

    # ---------- Rules ----------
    async def list_rules(self) -> List[RuleRecord]:
        engine = self._get_engine()
        
        async with engine.connect() as conn:
            result = await conn.execute(
                text("SELECT id, version, spec_json FROM rules WHERE enabled=1")
            )
            rows = result.fetchall()
        
        return [
            RuleRecord(id=r[0], version=r[1], spec=RuleSpec(**json.loads(r[2])))
            for r in rows
        ]

    async def upsert_rule(self, spec: RuleSpec) -> None:
        engine = self._get_engine()
        v = 1
        spec_json = json.dumps(
            (getattr(spec, "model_dump", None) or 
             getattr(spec, "dict", None) or 
             (lambda: spec.__dict__))()
        )
        
        async with engine.begin() as conn:
            await conn.execute(
                text("""
                    INSERT OR REPLACE INTO rules (id, version, spec_json, enabled) 
                    VALUES (:id, :version, :spec_json, :enabled)
                """),
                {
                    "id": spec.id,
                    "version": v,
                    "spec_json": spec_json,
                    "enabled": 1 if getattr(spec, "enabled", True) else 0,
                }
            )

    # ---------- Incidents ----------
    async def find_or_create_incident(self, alert: Alert) -> Incident:
        """Correlate by fingerprint, update last_seen or create new incident."""
        engine = self._get_engine()
        ts_iso = alert.ts.isoformat()
        
        async with engine.begin() as conn:
            result = await conn.execute(
                text("""
                    SELECT id, status, first_seen, last_seen, owner_id 
                    FROM incidents 
                    WHERE fingerprint=:fingerprint
                """),
                {"fingerprint": alert.fingerprint}
            )
            row = result.fetchone()
            
            if row:
                await conn.execute(
                    text("""
                        UPDATE incidents 
                        SET last_seen=:last_seen, severity=:severity, title=:title 
                        WHERE id=:id
                    """),
                    {
                        "last_seen": ts_iso,
                        "severity": alert.severity,
                        "title": alert.title,
                        "id": row[0],
                    }
                )
                return Incident(
                    id=row[0],
                    rule_id=alert.rule_id,
                    sku=alert.sku,
                    status="OPEN",
                    first_seen=datetime.fromisoformat(row[2]),
                    last_seen=alert.ts,
                    severity=alert.severity,
                    title=alert.title,
                    group_key=alert.sku,
                    owner_id=row[4],
                )

            inc_id = f"inc_{int(alert.ts.timestamp()*1000)}"
            await conn.execute(
                text("""
                    INSERT INTO incidents
                      (id, rule_id, sku, status, first_seen, last_seen, severity, title, group_key, fingerprint, owner_id)
                    VALUES (:id, :rule_id, :sku, :status, :first_seen, :last_seen, :severity, :title, :group_key, :fingerprint, :owner_id)
                """),
                {
                    "id": inc_id,
                    "rule_id": alert.rule_id,
                    "sku": alert.sku,
                    "status": "OPEN",
                    "first_seen": ts_iso,
                    "last_seen": ts_iso,
                    "severity": alert.severity,
                    "title": alert.title,
                    "group_key": alert.sku,
                    "fingerprint": alert.fingerprint,
                    "owner_id": alert.owner_id,
                }
            )
            
            return Incident(
                id=inc_id,
                rule_id=alert.rule_id,
                sku=alert.sku,
                status="OPEN",
                first_seen=alert.ts,
                last_seen=alert.ts,
                severity=alert.severity,
                title=alert.title,
                group_key=alert.sku,
                owner_id=alert.owner_id,
            )

    async def is_throttled(self, fingerprint: str, dur: str) -> bool:
        """Return True if an incident with this fingerprint was seen within duration."""
        unit = dur[-1]
        n = int(dur[:-1])
        delta = {
            "m": timedelta(minutes=n),
            "h": timedelta(hours=n),
            "s": timedelta(seconds=n)
        }[unit]
        
        engine = self._get_engine()
        
        async with engine.connect() as conn:
            result = await conn.execute(
                text("SELECT last_seen FROM incidents WHERE fingerprint=:fingerprint"),
                {"fingerprint": fingerprint}
            )
            row = result.fetchone()
        
        if not row:
            return False
        
        last = datetime.fromisoformat(row[0])
        now = datetime.now(timezone.utc)
        if last.tzinfo is None:
            last = last.replace(tzinfo=timezone.utc)
        
        return (now - last) < delta

    async def list_incidents(self, status: Optional[str], owner_id: Optional[str] = None) -> List[Dict[str, Any]]:
        q = """
            SELECT id, rule_id, sku, status, first_seen, last_seen, severity, title
            FROM incidents
        """
        args: Dict[str, Any] = {}
        conditions = []
        
        if status:
            conditions.append("status=:status")
            args["status"] = status
        
        if owner_id:
            conditions.append("owner_id=:owner_id")
            args["owner_id"] = owner_id
        
        if conditions:
            q += " WHERE " + " AND ".join(conditions)
        
        q += " ORDER BY last_seen DESC"
        
        engine = self._get_engine()
        
        async with engine.connect() as conn:
            result = await conn.execute(text(q), args)
            rows = result.fetchall()
        
        return [
            {
                "id": r[0],
                "rule_id": r[1],
                "sku": r[2],
                "status": r[3],
                "first_seen": r[4],
                "last_seen": r[5],
                "severity": r[6],
                "title": r[7],
            }
            for r in rows
        ]

    async def set_status(self, inc_id: str, status: str, owner_id: Optional[str] = None) -> None:
        engine = self._get_engine()
        
        async with engine.begin() as conn:
            if owner_id:
                result = await conn.execute(
                    text("SELECT owner_id FROM incidents WHERE id=:id"),
                    {"id": inc_id}
                )
                row = result.fetchone()
                if not row or str(row[0]) != str(owner_id):
                    raise ValueError("Incident not found or access denied")
            
            await conn.execute(
                text("""
                    UPDATE incidents 
                    SET status=:status, last_seen=:last_seen 
                    WHERE id=:id
                """),
                {
                    "status": status,
                    "last_seen": datetime.now(timezone.utc).isoformat(),
                    "id": inc_id,
                }
            )

    async def touch_incident(self, fingerprint: str) -> None:
        """Update last_seen for a throttled incident by fingerprint."""
        engine = self._get_engine()
        
        async with engine.begin() as conn:
            await conn.execute(
                text("""
                    UPDATE incidents 
                    SET last_seen=:last_seen 
                    WHERE fingerprint=:fingerprint
                """),
                {
                    "last_seen": datetime.now(timezone.utc).isoformat(),
                    "fingerprint": fingerprint,
                }
            )

    # ---------- Deliveries ----------
    async def record_delivery(
        self,
        delivery_id: str,
        incident_id: str,
        channel: str,
        status: str,
        response_json: Dict[str, Any] | None = None
    ) -> None:
        engine = self._get_engine()
        
        async with engine.begin() as conn:
            await conn.execute(
                text("""
                    INSERT OR REPLACE INTO deliveries 
                        (id, incident_id, channel, ts, status, response_json) 
                    VALUES (:id, :incident_id, :channel, :ts, :status, :response_json)
                """),
                {
                    "id": delivery_id,
                    "incident_id": incident_id,
                    "channel": channel,
                    "ts": datetime.utcnow().isoformat(),
                    "status": status,
                    "response_json": json.dumps(response_json or {}),
                }
            )

    # ---------- Channel settings ----------
    async def get_channel_settings(self) -> Optional[dict]:
        """Returns a dict of channel overrides persisted by the UI, or None if not set."""
        engine = self._get_engine()
        
        async with engine.connect() as conn:
            result = await conn.execute(
                text("SELECT value FROM settings WHERE key='channels'")
            )
            row = result.fetchone()
        
        return json.loads(row[0]) if row else None

    async def save_channel_settings(self, cfg: dict) -> None:
        engine = self._get_engine()
        val = json.dumps(cfg)
        
        async with engine.begin() as conn:
            await conn.execute(
                text("INSERT OR REPLACE INTO settings (key, value) VALUES (:key, :value)"),
                {"key": "channels", "value": val}
            )

#!/usr/bin/env python3
"""
Seed script for Dynamic Pricing (FluxPricer).
Initializes all database tables (auth, catalog, market data) and seeds
realistic sample products, market competitors, and a default admin user.
"""
from __future__ import annotations

import asyncio
import os
import sqlite3
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

# Ensure project root is on sys.path
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from core.auth_db import init_db, SessionLocal, User
from core.auth_service import _hash
from core.agents.data_collector.repo import DataRepo


SAMPLE_PRODUCTS = [
    {
        "sku": "LAPTOP-001",
        "title": "Apple MacBook Pro 14 M3 (16GB, 512GB SSD)",
        "currency": "USD",
        "current_price": 1999.00,
        "cost": 1550.00,
        "stock": 12,
        "market_prices": [1980.00, 1950.00, 2020.00, 1975.00, 1990.00],
    },
    {
        "sku": "LAPTOP-002",
        "title": "Dell XPS 15 9530 (i7-13700H, 16GB, 1TB)",
        "currency": "USD",
        "current_price": 1699.00,
        "cost": 1250.00,
        "stock": 8,
        "market_prices": [1680.00, 1650.00, 1720.00, 1690.00],
    },
    {
        "sku": "LAPTOP-003",
        "title": "ASUS ROG Zephyrus G14 (Ryzen 9, RTX 4060)",
        "currency": "USD",
        "current_price": 1499.00,
        "cost": 1100.00,
        "stock": 15,
        "market_prices": [1480.00, 1450.00, 1510.00, 1470.00],
    },
    {
        "sku": "LAPTOP-004",
        "title": "Lenovo ThinkPad X1 Carbon Gen 11",
        "currency": "USD",
        "current_price": 1749.00,
        "cost": 1300.00,
        "stock": 10,
        "market_prices": [1720.00, 1710.00, 1760.00, 1735.00],
    },
    {
        "sku": "LAPTOP-005",
        "title": "HP Spectre x360 14 (Core Ultra 7, OLED)",
        "currency": "USD",
        "current_price": 1399.00,
        "cost": 1020.00,
        "stock": 14,
        "market_prices": [1380.00, 1370.00, 1420.00, 1390.00],
    },
    {
        "sku": "PROD-001",
        "title": "Logitech MX Master 3S Wireless Mouse",
        "currency": "USD",
        "current_price": 99.99,
        "cost": 65.00,
        "stock": 45,
        "market_prices": [98.50, 95.00, 102.00, 99.00],
    },
    {
        "sku": "PROD-002",
        "title": "Dell UltraSharp 27 4K Monitor (U2723QE)",
        "currency": "USD",
        "current_price": 579.99,
        "cost": 410.00,
        "stock": 7,
        "market_prices": [570.00, 560.00, 590.00, 575.00],
    },
]


def seed_auth_user() -> int:
    """Initialize auth.db and seed default admin user."""
    print("-> Initializing Auth DB...")
    init_db()
    
    session = SessionLocal()
    try:
        user = session.query(User).filter_by(email="admin@example.com").first()
        if not user:
            user = User(
                email="admin@example.com",
                full_name="Admin User",
                hashed_password=_hash("admin12345!"),
                is_active=True,
            )
            session.add(user)
            session.commit()
            session.refresh(user)
            print(f"   [OK] Created default user: admin@example.com (id={user.id}, password=admin12345!)")
        else:
            print(f"   [OK] Existing default user found: admin@example.com (id={user.id})")
        return user.id
    finally:
        session.close()


def seed_market_data(owner_id: int):
    """Seed data/market.db with market_data table and competitor price observations."""
    print("-> Initializing Market DB (data/market.db)...")
    market_db_path = ROOT / "data" / "market.db"
    market_db_path.parent.mkdir(parents=True, exist_ok=True)
    
    conn = sqlite3.connect(market_db_path)
    cur = conn.cursor()
    
    cur.execute("""
        CREATE TABLE IF NOT EXISTS market_data (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            owner_id INTEGER NOT NULL,
            product_name TEXT NOT NULL,
            price REAL NOT NULL,
            features TEXT,
            update_time TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)
    cur.execute("CREATE INDEX IF NOT EXISTS idx_market_data_owner ON market_data(owner_id)")
    cur.execute("CREATE INDEX IF NOT EXISTS idx_market_data_product ON market_data(product_name)")
    
    # Clear existing rows for clean seed
    cur.execute("DELETE FROM market_data WHERE owner_id = ?", (owner_id,))
    
    now = datetime.now(timezone.utc)
    inserted_count = 0
    
    for item in SAMPLE_PRODUCTS:
        sku = item["sku"]
        title = item["title"]
        for idx, price in enumerate(item["market_prices"]):
            tick_time = (now - timedelta(hours=(idx * 4) + 1)).strftime("%Y-%m-%d %H:%M:%S")
            cur.execute("""
                INSERT INTO market_data (owner_id, product_name, price, features, update_time)
                VALUES (?, ?, ?, ?, ?)
            """, (owner_id, title, price, f"Competitor observation for {sku}", tick_time))
            inserted_count += 1
            
    conn.commit()
    conn.close()
    print(f"   [OK] Seeded {inserted_count} market competitor observations in data/market.db")


async def seed_catalog_and_ticks(owner_id: int):
    """Seed product catalog and initial market ticks via DataRepo."""
    print("-> Initializing Product Catalog & Market Ticks...")
    repo = DataRepo()
    await repo.init()
    
    catalog_items = [
        {
            "sku": item["sku"],
            "title": item["title"],
            "currency": item["currency"],
            "current_price": item["current_price"],
            "cost": item["cost"],
            "stock": item["stock"],
        }
        for item in SAMPLE_PRODUCTS
    ]
    
    owner_str = str(owner_id)
    inserted = await repo.upsert_products(catalog_items, owner_str)
    print(f"   [OK] Upserted {len(catalog_items)} products into product_catalog (owner_id={owner_str})")
    
    # Also insert initial ticks into market_ticks
    now_iso = datetime.now(timezone.utc).isoformat()
    for item in SAMPLE_PRODUCTS:
        await repo.insert_tick({
            "sku": item["sku"],
            "market": "DEFAULT",
            "our_price": item["current_price"],
            "competitor_price": item["market_prices"][0] if item["market_prices"] else item["current_price"],
            "demand_index": 1.05,
            "ts": now_iso,
            "source": "seed_script",
        })
    print(f"   [OK] Ingested initial market ticks for {len(SAMPLE_PRODUCTS)} SKUs")


def main():
    print("==================================================")
    print("   FluxPricer Database Seeding & Setup Utility   ")
    print("==================================================")
    
    # 1. Auth DB
    user_id = seed_auth_user()
    
    # 2. Market DB
    seed_market_data(user_id)
    
    # 3. Product Catalog
    asyncio.run(seed_catalog_and_ticks(user_id))
    
    print("\n[SUCCESS] Database seeding completed successfully!")
    print("Admin Credentials:")
    print("  Email:    admin@example.com")
    print("  Password: admin12345!")
    print("==================================================")


if __name__ == "__main__":
    main()

"""Generic SQLite response cache with TTL expiration.

Provides a lightweight, dependency-free caching layer used by newsfeed
(RSS feeds), FRED macro data, and any other module that needs to avoid
redundant network calls within a configurable TTL window.
"""

import json
import os
import sqlite3
from datetime import datetime, timedelta
from pathlib import Path

from finance.logging_setup import get_logger

logger = get_logger(__name__)

DEFAULT_CACHE_DB = Path("market_cache.db")


def init_cache_db(db_path: Path = DEFAULT_CACHE_DB) -> None:
    """Initialize SQLite cache database with parameterized queries & restricted permissions."""
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS api_cache (
            endpoint_key TEXT PRIMARY KEY,
            payload TEXT NOT NULL,
            timestamp TEXT NOT NULL
        )
        """
    )
    conn.commit()
    conn.close()
    try:
        os.chmod(db_path, 0o600)
    except Exception:
        pass


def get_cached_response(endpoint_key: str, ttl_hours: int = 12, db_path: Path = DEFAULT_CACHE_DB) -> dict | None:
    """Retrieve cached response if within TTL."""
    if not db_path.exists():
        return None
    try:
        conn = sqlite3.connect(db_path)
        cursor = conn.cursor()
        cursor.execute(
            "SELECT payload, timestamp FROM api_cache WHERE endpoint_key = ?", (endpoint_key,)
        )
        row = cursor.fetchone()
        conn.close()
        if not row:
            return None
        payload_str, timestamp_str = row
        cached_time = datetime.fromisoformat(timestamp_str)
        if datetime.now() - cached_time < timedelta(hours=ttl_hours):
            return json.loads(payload_str)
    except Exception:
        pass
    return None


def cache_response(endpoint_key: str, data: dict, db_path: Path = DEFAULT_CACHE_DB) -> None:
    """Cache API response in SQLite."""
    init_cache_db(db_path)
    try:
        conn = sqlite3.connect(db_path)
        cursor = conn.cursor()
        cursor.execute(
            """
            INSERT OR REPLACE INTO api_cache (endpoint_key, payload, timestamp)
            VALUES (?, ?, ?)
            """,
            (endpoint_key, json.dumps(data), datetime.now().isoformat()),
        )
        conn.commit()
        conn.close()
    except Exception as e:
        logger.warning("Failed to cache response: %s", e)

"""Alpha Vantage API Client with SQLite caching and robust error handling."""

import os
import sqlite3
import json
from datetime import datetime, timedelta
from pathlib import Path
import requests
from finance.logging_setup import get_logger

logger = get_logger(__name__)

DEFAULT_CACHE_DB = Path("market_cache.db")
BASE_URL = "https://www.alphavantage.co/query"


def get_api_key() -> str:
    """Retrieve Alpha Vantage API key from environment variables."""
    from dotenv import load_dotenv
    load_dotenv()
    key = os.environ.get("ALPHA_VANTAGE_API_KEY")
    if not key:
        raise ValueError(
            "Alpha Vantage API key not found. Please set the ALPHA_VANTAGE_API_KEY environment variable."
        )
    return key


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
    # Set restricted permissions on POSIX if possible
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


def query_alpha_vantage(params: dict, ttl_hours: int = 12, db_path: Path = DEFAULT_CACHE_DB) -> dict:
    """Query Alpha Vantage API with caching and error payload validation."""
    api_key = get_api_key()
    params["apikey"] = api_key
    
    # Create cache key from sorted parameters (excluding apikey)
    cache_params = {k: v for k, v in params.items() if k != "apikey"}
    endpoint_key = json.dumps(cache_params, sort_keys=True)

    # Check cache first
    cached = get_cached_response(endpoint_key, ttl_hours=ttl_hours, db_path=db_path)
    if cached is not None:
        return cached

    # Make request
    response = requests.get(BASE_URL, params=params, timeout=30)
    response.raise_for_status()
    data = response.json()

    # Validate Alpha Vantage HTTP 200 error / rate limit messages
    if "Error Message" in data:
        raise ValueError(f"Alpha Vantage API Error: {data['Error Message']}")
    if "Note" in data and "call frequency" in data["Note"]:
        raise ValueError(f"Alpha Vantage Rate Limit Exceeded: {data['Note']}")
    if "Information" in data and "rate limit" in data["Information"].lower():
        raise ValueError(f"Alpha Vantage Rate Limit Notice: {data['Information']}")
    if "Information" in data and "premium" in data["Information"].lower():
        raise ValueError(f"Alpha Vantage Premium Notice: {data['Information']}")

    # Reject payloads that contain only informational/error keys and no data
    meta_keys = {"Information", "Note", "Error Message", "Meta Data"}
    if data and set(data.keys()).issubset(meta_keys):
        info = data.get("Information") or data.get("Note") or "unknown error"
        raise ValueError(f"Alpha Vantage returned no data: {info}")

    # Cache successful response
    cache_response(endpoint_key, data, db_path=db_path)
    return data


def fetch_global_quote(symbol: str, db_path: Path = DEFAULT_CACHE_DB) -> dict:
    """Fetch global quote for real-time price info."""
    params = {
        "function": "GLOBAL_QUOTE",
        "symbol": symbol.upper(),
    }
    return query_alpha_vantage(params, ttl_hours=1, db_path=db_path)

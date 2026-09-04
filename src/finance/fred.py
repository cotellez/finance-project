"""FRED (Federal Reserve Economic Data) API Client with SQLite caching and error handling."""

import os
import sqlite3
import json
from datetime import datetime, timedelta
from pathlib import Path
import requests
from finance.logging_setup import get_logger

logger = get_logger(__name__)

DEFAULT_CACHE_DB = Path("market_cache.db")
BASE_URL = "https://api.stlouisfed.org/fred/series/observations"


def get_fred_api_key() -> str:
    """Retrieve FRED API key from environment variables."""
    from dotenv import load_dotenv
    load_dotenv()
    key = os.environ.get("FRED_API_KEY")
    if not key:
        raise ValueError(
            "FRED API key not found. Please set the FRED_API_KEY environment variable."
        )
    return key


def query_fred(series_id: str, ttl_hours: int = 24, db_path: Path = DEFAULT_CACHE_DB) -> dict:
    """Query FRED API for a series with SQLite caching and error validation."""
    api_key = get_fred_api_key()
    series_id = series_id.upper()

    # Check cache first
    endpoint_key = f"fred_{series_id}"
    
    if db_path.exists():
        try:
            conn = sqlite3.connect(db_path)
            cursor = conn.cursor()
            cursor.execute(
                "SELECT payload, timestamp FROM api_cache WHERE endpoint_key = ?", (endpoint_key,)
            )
            row = cursor.fetchone()
            conn.close()
            if row:
                payload_str, timestamp_str = row
                cached_time = datetime.fromisoformat(timestamp_str)
                if datetime.now() - cached_time < timedelta(hours=ttl_hours):
                    return json.loads(payload_str)
        except Exception:
            pass

    # Make request to FRED API
    params = {
        "series_id": series_id,
        "api_key": api_key,
        "file_type": "json",
        "sort_order": "desc",
        "limit": 10,
    }
    response = requests.get(BASE_URL, params=params, timeout=30)
    response.raise_for_status()
    data = response.json()

    if "error_message" in data:
        raise ValueError(f"FRED API Error: {data['error_message']}")

    # Cache response
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
        logger.warning("Failed to cache FRED response: %s", e)

    return data


def get_latest_observation(series_id: str, db_path: Path = DEFAULT_CACHE_DB) -> dict:
    """Get the latest valid observation for a FRED series."""
    data = query_fred(series_id, ttl_hours=24, db_path=db_path)
    observations = data.get("observations", [])
    
    # Filter out missing/dot values
    valid_obs = [o for o in observations if o.get("value") not in (".", None, "")]
    if not valid_obs:
        raise ValueError(f"No valid observations found for FRED series '{series_id}'.")

    latest = valid_obs[0]
    previous = valid_obs[1] if len(valid_obs) > 1 else None

    current_val = float(latest["value"])
    prev_val = float(previous["value"]) if previous else None
    change = round(current_val - prev_val, 2) if prev_val is not None else None

    return {
        "series_id": series_id,
        "date": latest["date"],
        "value": current_val,
        "previous_date": previous["date"] if previous else None,
        "previous_value": prev_val,
        "change": change,
    }

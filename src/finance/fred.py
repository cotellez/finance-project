"""FRED (Federal Reserve Economic Data) API Client with shared caching and error handling."""

import os
from pathlib import Path
import requests
from finance.cache import get_cached_response, cache_response
from finance.logging_setup import get_logger

logger = get_logger(__name__)

DEFAULT_CACHE_DB = Path("market_cache.db")
BASE_URL = "https://api.stlouisfed.org/fred/series/observations"
FRED_TTL_HOURS = 24


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


def query_fred(series_id: str, ttl_hours: int = FRED_TTL_HOURS, db_path: Path = DEFAULT_CACHE_DB) -> dict:
    """Query FRED API for a series with shared SQLite caching and error validation."""
    api_key = get_fred_api_key()
    series_id = series_id.upper()

    endpoint_key = f"fred_{series_id}"
    cached = get_cached_response(endpoint_key, ttl_hours=ttl_hours, db_path=db_path)
    if cached is not None:
        return cached

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

    cache_response(endpoint_key, data, db_path=db_path)
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

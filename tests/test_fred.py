"""Tests for FRED macroeconomic data client with mocked API responses."""

import pytest
from unittest.mock import patch
from finance.fred import get_latest_observation, query_fred


@patch("finance.fred.requests.get")
def test_fred_observation_parsing(mock_get, tmp_path):
    import os
    os.environ["FRED_API_KEY"] = "TEST_FRED_KEY"
    cache_db = tmp_path / "test_fred_cache.db"

    class MockResponse:
        def raise_for_status(self):
            pass
        def json(self):
            return {
                "observations": [
                    {"date": "2026-09-01", "value": "5.25"},
                    {"date": "2026-08-01", "value": "5.00"},
                ]
            }

    mock_get.return_value = MockResponse()

    obs = get_latest_observation("FEDFUNDS", db_path=cache_db)
    assert obs["series_id"] == "FEDFUNDS"
    assert obs["date"] == "2026-09-01"
    assert obs["value"] == 5.25
    assert obs["previous_value"] == 5.00
    assert obs["change"] == 0.25


@patch("finance.fred.requests.get")
def test_fred_error_handling(mock_get, tmp_path):
    import os
    os.environ["FRED_API_KEY"] = "TEST_FRED_KEY"
    cache_db = tmp_path / "test_fred_cache.db"

    class MockResponse:
        def raise_for_status(self):
            pass
        def json(self):
            return {"error_message": "Invalid series ID."}

    mock_get.return_value = MockResponse()

    with pytest.raises(ValueError, match="FRED API Error"):
        get_latest_observation("INVALID_SERIES", db_path=cache_db)

"""Tests for finance wrap-up command."""

import json
import os
from pathlib import Path
from unittest.mock import patch
from finance.cli import handle_wrap_up
from finance.memory import get_short_term_memory, push_context


class Args:
    pass


def test_wrap_up_empty(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr("finance.cli.DEFAULT_DB", tmp_path / "finance.json")
    monkeypatch.setattr("finance.portfolio.DEFAULT_PORTFOLIO_DB", tmp_path / "portfolio.json")
    monkeypatch.setattr("finance.memory.DEFAULT_SHORT_TERM_DB", tmp_path / "memory_short.json")
    monkeypatch.setattr("finance.memory.DEFAULT_LONG_TERM_DB", tmp_path / "memory_long.json")

    args = Args()
    result = handle_wrap_up(args)
    assert result == 0

    # progress.md should be created
    progress_file = tmp_path / "progress.md"
    assert progress_file.exists()
    content = progress_file.read_text()
    assert "Session Wrap-Up" in content
    assert "finance screen" in content  # "What's Next" roadmap items


def test_wrap_up_with_data(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr("finance.cli.DEFAULT_DB", tmp_path / "finance.json")
    monkeypatch.setattr("finance.portfolio.DEFAULT_PORTFOLIO_DB", tmp_path / "portfolio.json")
    monkeypatch.setattr("finance.memory.DEFAULT_SHORT_TERM_DB", tmp_path / "memory_short.json")
    monkeypatch.setattr("finance.memory.DEFAULT_LONG_TERM_DB", tmp_path / "memory_long.json")

    # Write sample transactions
    txs = [
        {"type": "income", "amount": 5000.0, "category": "Salary", "date": "2026-09-01"},
        {"type": "expense", "amount": 1200.0, "category": "Rent", "date": "2026-09-02"},
    ]
    with open(tmp_path / "finance.json", "w") as f:
        json.dump(txs, f)

    # Write sample portfolio
    positions = [{"symbol": "SPY", "shares": 10.0, "cost_basis": 400.0}]
    with open(tmp_path / "portfolio.json", "w") as f:
        json.dump(positions, f)

    args = Args()
    result = handle_wrap_up(args)
    assert result == 0

    # Verify progress.md updated
    progress_file = tmp_path / "progress.md"
    assert progress_file.exists()
    content = progress_file.read_text()
    assert "2 recorded" in content
    assert "finance optimize" in content  # Suggested because positions exist


def test_wrap_up_clears_short_term_memory(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr("finance.cli.DEFAULT_DB", tmp_path / "finance.json")
    monkeypatch.setattr("finance.portfolio.DEFAULT_PORTFOLIO_DB", tmp_path / "portfolio.json")
    monkeypatch.setattr("finance.memory.DEFAULT_SHORT_TERM_DB", tmp_path / "memory_short.json")
    monkeypatch.setattr("finance.memory.DEFAULT_LONG_TERM_DB", tmp_path / "memory_long.json")

    # Push something to short-term memory
    push_context("Test context before wrap-up", db_path=tmp_path / "memory_short.json")
    assert len(get_short_term_memory(db_path=tmp_path / "memory_short.json")) == 1

    args = Args()
    result = handle_wrap_up(args)
    assert result == 0

    # Short-term memory should be cleared
    assert len(get_short_term_memory(db_path=tmp_path / "memory_short.json")) == 0

"""Tests for short-term and long-term memory module."""

import pytest
from finance.memory import (
    remember,
    recall,
    forget,
    load_long_term_memory,
    push_context,
    get_short_term_memory,
    clear_short_term_memory,
)


def test_long_term_memory(tmp_path):
    db = tmp_path / "memory_long.json"

    # Test remember and recall specific key
    remember("savings_goal", "5000", db_path=db)
    remember("budget_limit", "1200", db_path=db)

    assert recall("savings_goal", db_path=db) == "5000"
    assert recall("budget_limit", db_path=db) == "1200"
    assert recall("nonexistent", db_path=db) is None

    # Test recall all
    mem = recall(db_path=db)
    assert mem == {"savings_goal": "5000", "budget_limit": "1200"}

    # Test forget
    assert forget("budget_limit", db_path=db) is True
    assert forget("budget_limit", db_path=db) is False
    assert recall("budget_limit", db_path=db) is None


def test_short_term_memory(tmp_path):
    db = tmp_path / "memory_short.json"

    # Initially empty
    assert get_short_term_memory(db_path=db) == []

    # Push items
    push_context("Action 1: Added income", db_path=db, max_items=3)
    push_context("Action 2: Viewed summary", db_path=db, max_items=3)
    ctx = get_short_term_memory(db_path=db)
    assert len(ctx) == 2
    assert ctx[0] == "Action 1: Added income"
    assert ctx[1] == "Action 2: Viewed summary"

    # Test sliding window / max_items
    push_context("Action 3", db_path=db, max_items=3)
    push_context("Action 4", db_path=db, max_items=3)
    ctx = get_short_term_memory(db_path=db)
    assert len(ctx) == 3
    assert ctx == ["Action 2: Viewed summary", "Action 3", "Action 4"]

    # Test clear
    clear_short_term_memory(db_path=db)
    assert get_short_term_memory(db_path=db) == []

"""Tests for finance CLI."""

import pytest
from finance.cli import add_transaction, get_summary, load_transactions


def test_add_income(tmp_path):
    db = tmp_path / "finance.json"
    tx = add_transaction("income", 1000.0, "Salary", "2026-09-01", db_path=db)
    assert tx["amount"] == 1000.0
    assert tx["type"] == "income"
    assert tx["category"] == "Salary"

    txs = load_transactions(db)
    assert len(txs) == 1


def test_add_expense(tmp_path):
    db = tmp_path / "finance.json"
    add_transaction("income", 500.0, "Freelance", "2026-09-01", db_path=db)
    add_transaction("expense", 50.0, "Groceries", "2026-09-02", db_path=db)

    summary = get_summary(db)
    assert summary["total_income"] == 500.0
    assert summary["total_expense"] == 50.0
    assert summary["balance"] == 450.0
    assert summary["count"] == 2


def test_invalid_amount(tmp_path):
    db = tmp_path / "finance.json"
    with pytest.raises(ValueError):
        add_transaction("income", -10.0, "Bad", db_path=db)
    with pytest.raises(ValueError):
        add_transaction("expense", 0.0, "Zero", db_path=db)


def test_invalid_type(tmp_path):
    db = tmp_path / "finance.json"
    with pytest.raises(ValueError):
        add_transaction("transfer", 100.0, "Invalid", db_path=db)

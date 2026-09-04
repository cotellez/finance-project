# Finance CLI

A simple personal finance tracking command-line utility.

## Install

```bash
pip install -e .[dev]
```

## Usage

```bash
# Add an income transaction
finance add income 1500.00 "Salary" --date 2026-09-01

# Add an expense transaction
finance add expense 45.50 "Groceries" --date 2026-09-02

# List all transactions
finance list

# Show financial summary
finance summary
```

## Development

Run tests with pytest:

```bash
python -m pytest
```

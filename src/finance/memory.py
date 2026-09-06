"""In-context memory module supporting short-term session context and long-term storage."""

import json
from pathlib import Path
from finance.jsonstore import (
    PROJECT_ROOT,
    FileLock,
    atomic_write_json,
    resolve_path,
)

DEFAULT_LONG_TERM_DB = PROJECT_ROOT / "memory_long.json"
DEFAULT_SHORT_TERM_DB = PROJECT_ROOT / "memory_short.json"


def load_long_term_memory(db_path: Path | None = None) -> dict:
    """Load long-term memory store from JSON file."""
    db_path = resolve_path(db_path, DEFAULT_LONG_TERM_DB)
    if not db_path.exists():
        return {}
    try:
        with open(db_path, "r", encoding="utf-8") as f:
            data = json.load(f)
    except json.JSONDecodeError as e:
        raise ValueError(f"Long-term memory '{db_path}' is corrupted (invalid JSON): {e}") from e
    if not isinstance(data, dict):
        raise ValueError(f"Long-term memory '{db_path}' must contain a JSON object.")
    return data


def save_long_term_memory(memory: dict, db_path: Path | None = None) -> None:
    """Save long-term memory store to JSON file (atomic write)."""
    db_path = resolve_path(db_path, DEFAULT_LONG_TERM_DB)
    atomic_write_json(db_path, memory)


def remember(key: str, value: str, db_path: Path | None = None) -> dict:
    """Store a key-value pair in long-term memory (goals, budget rules, preferences)."""
    db_path = resolve_path(db_path, DEFAULT_LONG_TERM_DB)
    with FileLock(db_path):
        mem = load_long_term_memory(db_path)
        mem[key] = value
        save_long_term_memory(mem, db_path)
    return mem


def recall(key: str = None, db_path: Path | None = None):
    """Recall a specific key or all long-term memory."""
    mem = load_long_term_memory(db_path)
    if key is not None:
        return mem.get(key)
    return mem


def forget(key: str, db_path: Path | None = None) -> bool:
    """Remove a key from long-term memory. Returns True if found and removed."""
    db_path = resolve_path(db_path, DEFAULT_LONG_TERM_DB)
    with FileLock(db_path):
        mem = load_long_term_memory(db_path)
        if key in mem:
            del mem[key]
            save_long_term_memory(mem, db_path)
            return True
        return False


def load_short_term_memory(db_path: Path | None = None) -> list:
    """Load short-term working memory/session context from JSON file."""
    db_path = resolve_path(db_path, DEFAULT_SHORT_TERM_DB)
    if not db_path.exists():
        return []
    try:
        with open(db_path, "r", encoding="utf-8") as f:
            data = json.load(f)
    except json.JSONDecodeError as e:
        raise ValueError(f"Short-term memory '{db_path}' is corrupted (invalid JSON): {e}") from e
    if not isinstance(data, list):
        raise ValueError(f"Short-term memory '{db_path}' must contain a JSON list.")
    return data


def save_short_term_memory(context_list: list, db_path: Path | None = None) -> None:
    """Save short-term working memory (atomic write)."""
    db_path = resolve_path(db_path, DEFAULT_SHORT_TERM_DB)
    atomic_write_json(db_path, context_list)


def push_context(item: str, db_path: Path | None = None, max_items: int = 10) -> list:
    """Push an item into short-term working memory (FIFO queue / sliding window)."""
    db_path = resolve_path(db_path, DEFAULT_SHORT_TERM_DB)
    with FileLock(db_path):
        ctx = load_short_term_memory(db_path)
        ctx.append(item)
        if len(ctx) > max_items:
            ctx = ctx[-max_items:]
        save_short_term_memory(ctx, db_path)
    return ctx


def clear_short_term_memory(db_path: Path | None = None) -> None:
    """Clear short-term working memory."""
    db_path = resolve_path(db_path, DEFAULT_SHORT_TERM_DB)
    if db_path.exists():
        db_path.unlink()


def get_short_term_memory(db_path: Path | None = None) -> list:
    """Get all items in short-term working memory."""
    return load_short_term_memory(db_path)
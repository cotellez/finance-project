"""In-context memory module supporting short-term session context and long-term storage."""

import json
from pathlib import Path

DEFAULT_LONG_TERM_DB = Path("memory_long.json")
DEFAULT_SHORT_TERM_DB = Path("memory_short.json")


def load_long_term_memory(db_path: Path = DEFAULT_LONG_TERM_DB) -> dict:
    """Load long-term memory store from JSON file."""
    if not db_path.exists():
        return {}
    try:
        with open(db_path, "r", encoding="utf-8") as f:
            data = json.load(f)
            return data if isinstance(data, dict) else {}
    except json.JSONDecodeError:
        return {}


def save_long_term_memory(memory: dict, db_path: Path = DEFAULT_LONG_TERM_DB) -> None:
    """Save long-term memory store to JSON file."""
    with open(db_path, "w", encoding="utf-8") as f:
        json.dump(memory, f, indent=2)


def remember(key: str, value: str, db_path: Path = DEFAULT_LONG_TERM_DB) -> dict:
    """Store a key-value pair in long-term memory (goals, budget rules, preferences)."""
    mem = load_long_term_memory(db_path)
    mem[key] = value
    save_long_term_memory(mem, db_path)
    return mem


def recall(key: str = None, db_path: Path = DEFAULT_LONG_TERM_DB):
    """Recall a specific key or all long-term memory."""
    mem = load_long_term_memory(db_path)
    if key is not None:
        return mem.get(key)
    return mem


def forget(key: str, db_path: Path = DEFAULT_LONG_TERM_DB) -> bool:
    """Remove a key from long-term memory. Returns True if found and removed."""
    mem = load_long_term_memory(db_path)
    if key in mem:
        del mem[key]
        save_long_term_memory(mem, db_path)
        return True
    return False


def load_short_term_memory(db_path: Path = DEFAULT_SHORT_TERM_DB) -> list:
    """Load short-term working memory/session context from JSON file."""
    if not db_path.exists():
        return []
    try:
        with open(db_path, "r", encoding="utf-8") as f:
            data = json.load(f)
            return data if isinstance(data, list) else []
    except json.JSONDecodeError:
        return []


def save_short_term_memory(context_list: list, db_path: Path = DEFAULT_SHORT_TERM_DB) -> None:
    """Save short-term working memory."""
    with open(db_path, "w", encoding="utf-8") as f:
        json.dump(context_list, f, indent=2)


def push_context(item: str, db_path: Path = DEFAULT_SHORT_TERM_DB, max_items: int = 10) -> list:
    """Push an item into short-term working memory (FIFO queue / sliding window)."""
    ctx = load_short_term_memory(db_path)
    ctx.append(item)
    if len(ctx) > max_items:
        ctx = ctx[-max_items:]
    save_short_term_memory(ctx, db_path)
    return ctx


def clear_short_term_memory(db_path: Path = DEFAULT_SHORT_TERM_DB) -> None:
    """Clear short-term working memory."""
    if db_path.exists():
        db_path.unlink()


def get_short_term_memory(db_path: Path = DEFAULT_SHORT_TERM_DB) -> list:
    """Get all items in short-term working memory."""
    return load_short_term_memory(db_path)

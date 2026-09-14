"""Model Context Protocol (MCP) server for Cognitive Memory Architecture.

Implements the 4-tier cognitive memory taxonomy:
1. Working Memory: Active context, scratchpad, current focus.
2. Episodic Memory: Event logs, temporal timelines, historical interactions.
3. Semantic Memory: Factual knowledge graph, entity-relation-object triples.
4. Procedural Memory: Standard operating procedures, multi-step workflows, skills.
"""

from __future__ import annotations

import argparse
import json
import os
import sqlite3
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from finance.jsonstore import PROJECT_ROOT, resolve_path
from finance.logging_setup import get_logger

try:
    from mcp.server.mcpserver import MCPServer
except ImportError:
    from mcp.server.fastmcp import FastMCP as MCPServer  # type: ignore[no-redef]

logger = get_logger(__name__)

DEFAULT_MEMORY_DB = PROJECT_ROOT / "memory_mcp.db"


class MemoryStore:
    """SQLite-backed multi-tier cognitive memory storage engine."""

    def __init__(self, db_path: Path | str | None = None) -> None:
        self.db_path = resolve_path(db_path, DEFAULT_MEMORY_DB)
        if isinstance(self.db_path, str) and self.db_path != ":memory:":
            self.db_path = Path(self.db_path)
        self._shared_memory_conn = (
            sqlite3.connect(":memory:", check_same_thread=False)
            if str(self.db_path) == ":memory:"
            else None
        )
        if self._shared_memory_conn:
            self._shared_memory_conn.row_factory = sqlite3.Row
            self._shared_memory_conn.execute("PRAGMA foreign_keys = ON;")
        self._init_db()

    def _get_connection(self) -> sqlite3.Connection:
        """Create and configure a SQLite connection."""
        if self._shared_memory_conn is not None:
            return self._shared_memory_conn
        db_target = str(self.db_path)
        conn = sqlite3.connect(db_target, check_same_thread=False)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON;")
        if db_target != ":memory:":
            conn.execute("PRAGMA journal_mode = WAL;")
            conn.execute("PRAGMA busy_timeout = 5000;")
        return conn

    def _init_db(self) -> None:
        """Initialize SQLite database schemas and indices for the 4 memory tiers."""
        if isinstance(self.db_path, Path):
            self.db_path.parent.mkdir(parents=True, exist_ok=True)

        with self._get_connection() as conn:
            # 1. Working Memory
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS working_memory (
                    key TEXT PRIMARY KEY,
                    value TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                )
                """
            )

            # 2. Episodic Memory
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS episodic_memory (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    timestamp TEXT NOT NULL,
                    event_type TEXT NOT NULL,
                    content TEXT NOT NULL,
                    metadata TEXT NOT NULL
                )
                """
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_episodic_ts ON episodic_memory (timestamp)"
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_episodic_type ON episodic_memory (event_type)"
            )

            # 3. Semantic Memory (Knowledge Graph Triples)
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS semantic_memory (
                    subject TEXT NOT NULL,
                    relation TEXT NOT NULL,
                    object TEXT NOT NULL,
                    confidence REAL NOT NULL DEFAULT 1.0,
                    created_at TEXT NOT NULL,
                    PRIMARY KEY (subject, relation, object)
                )
                """
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_semantic_subj ON semantic_memory (subject)"
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_semantic_rel ON semantic_memory (relation)"
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_semantic_obj ON semantic_memory (object)"
            )

            # 4. Procedural Memory (Skills / SOPs)
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS procedural_memory (
                    name TEXT PRIMARY KEY,
                    description TEXT NOT NULL,
                    steps TEXT NOT NULL,
                    trigger_condition TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                )
                """
            )
            conn.commit()

        if isinstance(self.db_path, Path) and self.db_path.exists():
            try:
                os.chmod(self.db_path, 0o600)
            except Exception:
                pass

    # ==================== Tier 1: Working Memory ====================

    def set_working(self, key: str, value: str) -> None:
        """Store or update a key-value item in working memory."""
        now = datetime.now(timezone.utc).isoformat()
        with self._get_connection() as conn:
            conn.execute(
                """
                INSERT INTO working_memory (key, value, updated_at)
                VALUES (?, ?, ?)
                ON CONFLICT(key) DO UPDATE SET
                    value = excluded.value,
                    updated_at = excluded.updated_at
                """,
                (key.strip(), value, now),
            )
            conn.commit()

    def get_working(self, key: str | None = None) -> Any:
        """Retrieve a specific key or all entries from working memory."""
        with self._get_connection() as conn:
            if key is not None:
                row = conn.execute(
                    "SELECT value FROM working_memory WHERE key = ?", (key.strip(),)
                ).fetchone()
                return row["value"] if row else None
            rows = conn.execute(
                "SELECT key, value, updated_at FROM working_memory ORDER BY updated_at DESC"
            ).fetchall()
            return {row["key"]: row["value"] for row in rows}

    def delete_working(self, key: str) -> bool:
        """Remove a key from working memory."""
        with self._get_connection() as conn:
            cur = conn.execute("DELETE FROM working_memory WHERE key = ?", (key.strip(),))
            conn.commit()
            return cur.rowcount > 0

    def clear_working(self) -> int:
        """Clear all entries from working memory."""
        with self._get_connection() as conn:
            cur = conn.execute("DELETE FROM working_memory")
            conn.commit()
            return cur.rowcount

    # ==================== Tier 2: Episodic Memory ====================

    def log_episode(
        self,
        event: str,
        event_type: str = "general",
        metadata: dict[str, Any] | None = None,
        timestamp: str | None = None,
    ) -> dict[str, Any]:
        """Record an event in episodic timeline memory."""
        ts = timestamp or datetime.now(timezone.utc).isoformat()
        meta_str = json.dumps(metadata or {}, ensure_ascii=False)
        with self._get_connection() as conn:
            cur = conn.execute(
                """
                INSERT INTO episodic_memory (timestamp, event_type, content, metadata)
                VALUES (?, ?, ?, ?)
                """,
                (ts, event_type.strip(), event.strip(), meta_str),
            )
            conn.commit()
            record_id = cur.lastrowid

        return {
            "id": record_id,
            "timestamp": ts,
            "event_type": event_type,
            "content": event,
            "metadata": metadata or {},
        }

    def query_episodes(
        self,
        query: str | None = None,
        event_type: str | None = None,
        start_time: str | None = None,
        end_time: str | None = None,
        limit: int = 20,
    ) -> list[dict[str, Any]]:
        """Search and filter episodic memory events."""
        clauses = []
        params: list[Any] = []

        if query:
            clauses.append("(content LIKE ? OR metadata LIKE ?)")
            q = f"%{query.strip()}%"
            params.extend([q, q])
        if event_type:
            clauses.append("event_type = ?")
            params.append(event_type.strip())
        if start_time:
            clauses.append("timestamp >= ?")
            params.append(start_time.strip())
        if end_time:
            clauses.append("timestamp <= ?")
            params.append(end_time.strip())

        where_sql = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        sql = f"""
            SELECT id, timestamp, event_type, content, metadata
            FROM episodic_memory
            {where_sql}
            ORDER BY timestamp DESC
            LIMIT ?
        """
        params.append(limit)

        with self._get_connection() as conn:
            rows = conn.execute(sql, params).fetchall()

        results = []
        for r in rows:
            try:
                meta = json.loads(r["metadata"])
            except Exception:
                meta = {}
            results.append(
                {
                    "id": r["id"],
                    "timestamp": r["timestamp"],
                    "event_type": r["event_type"],
                    "content": r["content"],
                    "metadata": meta,
                }
            )
        return results

    def delete_episode(self, episode_id: int) -> bool:
        """Delete an episode by ID."""
        with self._get_connection() as conn:
            cur = conn.execute("DELETE FROM episodic_memory WHERE id = ?", (episode_id,))
            conn.commit()
            return cur.rowcount > 0

    def clear_episodes(self, before_timestamp: str | None = None) -> int:
        """Clear all or dated episodes."""
        with self._get_connection() as conn:
            if before_timestamp:
                cur = conn.execute(
                    "DELETE FROM episodic_memory WHERE timestamp < ?", (before_timestamp,)
                )
            else:
                cur = conn.execute("DELETE FROM episodic_memory")
            conn.commit()
            return cur.rowcount

    # ==================== Tier 3: Semantic Memory ====================

    def add_semantic_fact(
        self,
        subject: str,
        relation: str,
        object: str,
        confidence: float = 1.0,
    ) -> dict[str, Any]:
        """Store or update a factual knowledge triple (subject, relation, object)."""
        now = datetime.now(timezone.utc).isoformat()
        subj = subject.strip().lower()
        rel = relation.strip().lower()
        obj = object.strip()
        conf = max(0.0, min(1.0, float(confidence)))

        with self._get_connection() as conn:
            conn.execute(
                """
                INSERT INTO semantic_memory (subject, relation, object, confidence, created_at)
                VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(subject, relation, object) DO UPDATE SET
                    confidence = excluded.confidence,
                    created_at = excluded.created_at
                """,
                (subj, rel, obj, conf, now),
            )
            conn.commit()

        return {
            "subject": subj,
            "relation": rel,
            "object": obj,
            "confidence": conf,
            "created_at": now,
        }

    def query_semantic_knowledge(
        self,
        subject: str | None = None,
        relation: str | None = None,
        object: str | None = None,
        min_confidence: float = 0.0,
    ) -> list[dict[str, Any]]:
        """Query semantic knowledge triples matching subject, relation, and/or object."""
        clauses = ["confidence >= ?"]
        params: list[Any] = [min_confidence]

        if subject:
            clauses.append("subject LIKE ?")
            params.append(f"%{subject.strip().lower()}%")
        if relation:
            clauses.append("relation LIKE ?")
            params.append(f"%{relation.strip().lower()}%")
        if object:
            clauses.append("object LIKE ?")
            params.append(f"%{object.strip()}%")

        where_sql = f"WHERE {' AND '.join(clauses)}"
        sql = f"""
            SELECT subject, relation, object, confidence, created_at
            FROM semantic_memory
            {where_sql}
            ORDER BY confidence DESC, created_at DESC
        """

        with self._get_connection() as conn:
            rows = conn.execute(sql, params).fetchall()

        return [
            {
                "subject": r["subject"],
                "relation": r["relation"],
                "object": r["object"],
                "confidence": r["confidence"],
                "created_at": r["created_at"],
            }
            for r in rows
        ]

    def delete_semantic_fact(self, subject: str, relation: str, object: str) -> bool:
        """Delete a specific semantic triple."""
        with self._get_connection() as conn:
            cur = conn.execute(
                """
                DELETE FROM semantic_memory
                WHERE subject = ? AND relation = ? AND object = ?
                """,
                (subject.strip().lower(), relation.strip().lower(), object.strip()),
            )
            conn.commit()
            return cur.rowcount > 0

    def clear_semantic(self) -> int:
        """Clear all semantic knowledge triples."""
        with self._get_connection() as conn:
            cur = conn.execute("DELETE FROM semantic_memory")
            conn.commit()
            return cur.rowcount

    # ==================== Tier 4: Procedural Memory ====================

    def register_procedure(
        self,
        name: str,
        description: str,
        steps: list[str] | str,
        trigger_condition: str = "",
    ) -> dict[str, Any]:
        """Save or update a procedural skill or standard operating procedure."""
        now = datetime.now(timezone.utc).isoformat()
        clean_name = name.strip()
        if isinstance(steps, str):
            steps_list = [s.strip() for s in steps.splitlines() if s.strip()]
        else:
            steps_list = [str(s).strip() for s in steps]

        steps_json = json.dumps(steps_list, ensure_ascii=False)

        with self._get_connection() as conn:
            conn.execute(
                """
                INSERT INTO procedural_memory (name, description, steps, trigger_condition, updated_at)
                VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(name) DO UPDATE SET
                    description = excluded.description,
                    steps = excluded.steps,
                    trigger_condition = excluded.trigger_condition,
                    updated_at = excluded.updated_at
                """,
                (clean_name, description.strip(), steps_json, trigger_condition.strip(), now),
            )
            conn.commit()

        return {
            "name": clean_name,
            "description": description.strip(),
            "steps": steps_list,
            "trigger_condition": trigger_condition.strip(),
            "updated_at": now,
        }

    def get_procedure(self, name: str) -> dict[str, Any] | None:
        """Retrieve a specific procedure by name."""
        with self._get_connection() as conn:
            row = conn.execute(
                """
                SELECT name, description, steps, trigger_condition, updated_at
                FROM procedural_memory
                WHERE name = ?
                """,
                (name.strip(),),
            ).fetchone()

        if not row:
            return None
        try:
            steps = json.loads(row["steps"])
        except Exception:
            steps = []

        return {
            "name": row["name"],
            "description": row["description"],
            "steps": steps,
            "trigger_condition": row["trigger_condition"],
            "updated_at": row["updated_at"],
        }

    def list_procedures(self) -> list[dict[str, Any]]:
        """List all registered procedures."""
        with self._get_connection() as conn:
            rows = conn.execute(
                """
                SELECT name, description, steps, trigger_condition, updated_at
                FROM procedural_memory
                ORDER BY name ASC
                """
            ).fetchall()

        results = []
        for r in rows:
            try:
                steps = json.loads(r["steps"])
            except Exception:
                steps = []
            results.append(
                {
                    "name": r["name"],
                    "description": r["description"],
                    "steps": steps,
                    "trigger_condition": r["trigger_condition"],
                    "updated_at": r["updated_at"],
                }
            )
        return results

    def delete_procedure(self, name: str) -> bool:
        """Delete a registered procedure."""
        with self._get_connection() as conn:
            cur = conn.execute(
                "DELETE FROM procedural_memory WHERE name = ?", (name.strip(),)
            )
            conn.commit()
            return cur.rowcount > 0

    def clear_procedural(self) -> int:
        """Clear all registered procedures."""
        with self._get_connection() as conn:
            cur = conn.execute("DELETE FROM procedural_memory")
            conn.commit()
            return cur.rowcount

    # ==================== High-Level Overview ====================

    def get_summary(self) -> dict[str, Any]:
        """Return counts and status across all four memory tiers."""
        with self._get_connection() as conn:
            working_count = conn.execute("SELECT COUNT(*) AS c FROM working_memory").fetchone()["c"]
            episodic_count = conn.execute("SELECT COUNT(*) AS c FROM episodic_memory").fetchone()["c"]
            semantic_count = conn.execute("SELECT COUNT(*) AS c FROM semantic_memory").fetchone()["c"]
            procedural_count = conn.execute("SELECT COUNT(*) AS c FROM procedural_memory").fetchone()["c"]
            latest_ep = conn.execute(
                "SELECT timestamp, event_type, content FROM episodic_memory ORDER BY timestamp DESC LIMIT 1"
            ).fetchone()

        latest_episode = dict(latest_ep) if latest_ep else None

        return {
            "working_memory_items": working_count,
            "episodic_memory_events": episodic_count,
            "semantic_memory_facts": semantic_count,
            "procedural_memory_procedures": procedural_count,
            "latest_episode": latest_episode,
        }


def create_memory_server(db_path: Path | str | None = None) -> MCPServer:
    """Create and configure the Cognitive Memory MCP Server."""
    store = MemoryStore(db_path=db_path)
    server = MCPServer(
        "cognitive-memory",
        description="Cognitive memory MCP server supporting Working, Episodic, Semantic, and Procedural memory.",
    )

    # Attach store to server for easy access in testing
    server._store = store  # type: ignore[attr-defined]

    # ------------------ Working Memory Tools ------------------

    @server.tool(name="set_working_memory", description="Set or update a key-value pair in active working memory (scratchpad).")
    def set_working_memory(key: str, value: str) -> str:
        store.set_working(key, value)
        return f"Working memory updated: '{key}'"

    @server.tool(name="get_working_memory", description="Retrieve active working memory. Pass key to get a single value, or omit to retrieve all.")
    def get_working_memory(key: str | None = None) -> str:
        data = store.get_working(key)
        if key is not None:
            if data is None:
                return f"Key '{key}' not found in working memory."
            return str(data)
        return json.dumps(data, indent=2)

    @server.tool(name="delete_working_memory", description="Remove a key from active working memory.")
    def delete_working_memory(key: str) -> str:
        deleted = store.delete_working(key)
        return f"Key '{key}' deleted." if deleted else f"Key '{key}' was not found."

    @server.tool(name="clear_working_memory", description="Clear all items from active working memory.")
    def clear_working_memory() -> str:
        count = store.clear_working()
        return f"Cleared {count} items from working memory."

    # ------------------ Episodic Memory Tools ------------------

    @server.tool(name="log_episode", description="Record an event in the episodic timeline (e.g., user decisions, interaction history, market events).")
    def log_episode(event: str, event_type: str = "general", metadata_json: str = "{}") -> str:
        try:
            meta = json.loads(metadata_json) if metadata_json else {}
        except Exception:
            meta = {"raw": metadata_json}
        rec = store.log_episode(event=event, event_type=event_type, metadata=meta)
        return json.dumps(rec, indent=2)

    @server.tool(name="query_episodes", description="Search historical episodes by query keyword, event type, or limit.")
    def query_episodes(query: str = "", event_type: str = "", limit: int = 20) -> str:
        q = query.strip() if query else None
        et = event_type.strip() if event_type else None
        episodes = store.query_episodes(query=q, event_type=et, limit=limit)
        return json.dumps(episodes, indent=2)

    @server.tool(name="delete_episode", description="Delete an episodic record by ID.")
    def delete_episode(episode_id: int) -> str:
        deleted = store.delete_episode(episode_id)
        return f"Episode {episode_id} deleted." if deleted else f"Episode {episode_id} not found."

    # ------------------ Semantic Memory Tools ------------------

    @server.tool(name="add_semantic_fact", description="Add a factual knowledge triple (subject, relation, object) with optional confidence (0.0 to 1.0).")
    def add_semantic_fact(subject: str, relation: str, object: str, confidence: float = 1.0) -> str:
        fact = store.add_semantic_fact(subject=subject, relation=relation, object=object, confidence=confidence)
        return json.dumps(fact, indent=2)

    @server.tool(name="query_semantic_knowledge", description="Query factual knowledge triples matching subject, relation, or object.")
    def query_semantic_knowledge(
        subject: str = "",
        relation: str = "",
        object: str = "",
        min_confidence: float = 0.0,
    ) -> str:
        s = subject.strip() if subject else None
        r = relation.strip() if relation else None
        o = object.strip() if object else None
        facts = store.query_semantic_knowledge(subject=s, relation=r, object=o, min_confidence=min_confidence)
        return json.dumps(facts, indent=2)

    @server.tool(name="delete_semantic_fact", description="Delete a specific semantic triple.")
    def delete_semantic_fact(subject: str, relation: str, object: str) -> str:
        deleted = store.delete_semantic_fact(subject, relation, object)
        return f"Semantic fact deleted." if deleted else "Semantic fact not found."

    # ------------------ Procedural Memory Tools ------------------

    @server.tool(name="register_procedure", description="Register a multi-step procedure, skill, or standard operating procedure.")
    def register_procedure(name: str, description: str, steps: list[str], trigger_condition: str = "") -> str:
        proc = store.register_procedure(name=name, description=description, steps=steps, trigger_condition=trigger_condition)
        return json.dumps(proc, indent=2)

    @server.tool(name="get_procedure", description="Retrieve the step-by-step instructions and triggers for a named procedure.")
    def get_procedure(name: str) -> str:
        proc = store.get_procedure(name)
        if not proc:
            return f"Procedure '{name}' not found."
        return json.dumps(proc, indent=2)

    @server.tool(name="list_procedures", description="List all registered procedures.")
    def list_procedures() -> str:
        procs = store.list_procedures()
        return json.dumps(procs, indent=2)

    @server.tool(name="delete_procedure", description="Delete a procedure by name.")
    def delete_procedure(name: str) -> str:
        deleted = store.delete_procedure(name)
        return f"Procedure '{name}' deleted." if deleted else f"Procedure '{name}' not found."

    # ------------------ System Summary Tool & Resources ------------------

    @server.tool(name="get_memory_summary", description="Get overview statistics of all 4 memory systems.")
    def get_memory_summary() -> str:
        summary = store.get_summary()
        return json.dumps(summary, indent=2)

    @server.resource("memory://working")
    def resource_working_memory() -> str:
        """Resource exposing active working memory state."""
        return json.dumps(store.get_working(), indent=2)

    @server.resource("memory://summary")
    def resource_memory_summary() -> str:
        """Resource exposing total counts across all memory tiers."""
        return json.dumps(store.get_summary(), indent=2)

    return server


def main() -> None:
    """CLI entrypoint for running the MCP memory server."""
    parser = argparse.ArgumentParser(description="Cognitive Memory MCP Server")
    parser.add_argument(
        "--db-path",
        type=str,
        default=str(DEFAULT_MEMORY_DB),
        help="Path to SQLite memory database file",
    )
    parser.add_argument(
        "--transport",
        type=str,
        default="stdio",
        choices=["stdio", "sse", "streamable-http"],
        help="MCP transport protocol",
    )
    args = parser.parse_args()

    server = create_memory_server(db_path=args.db_path)
    logger.info("Starting Cognitive Memory MCP Server on %s transport...", args.transport)
    server.run(transport=args.transport)


if __name__ == "__main__":
    main()

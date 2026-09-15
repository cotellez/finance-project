"""Unit tests for the Cognitive Memory MCP server and 4-tier memory storage engine."""

import asyncio
import pytest
from pathlib import Path

from finance.memory_mcp import MemoryStore, create_memory_server


@pytest.fixture
def memory_store():
    """Fixture providing an in-memory SQLite MemoryStore instance."""
    store = MemoryStore(":memory:")
    return store


def test_working_memory(memory_store):
    """Test Working Memory tier operations."""
    assert memory_store.get_working("goal") is None

    memory_store.set_working("goal", "Maximize portfolio returns")
    assert memory_store.get_working("goal") == "Maximize portfolio returns"

    # Update
    memory_store.set_working("goal", "Strict risk management & diversification")
    assert memory_store.get_working("goal") == "Strict risk management & diversification"

    all_working = memory_store.get_working()
    assert isinstance(all_working, dict)
    assert all_working["goal"] == "Strict risk management & diversification"

    assert memory_store.delete_working("goal") is True
    assert memory_store.get_working("goal") is None
    assert memory_store.delete_working("nonexistent") is False

    memory_store.set_working("k1", "v1")
    memory_store.set_working("k2", "v2")
    assert memory_store.clear_working() == 2
    assert memory_store.get_working() == {}


def test_episodic_memory(memory_store):
    """Test Episodic Memory tier operations."""
    ep = memory_store.log_episode(
        event="User requested stock screening for tech sector",
        event_type="user_query",
        metadata={"sector": "Technology", "tickers": ["AAPL", "MSFT"]},
    )
    assert ep["id"] is not None
    assert ep["event_type"] == "user_query"
    assert ep["metadata"]["sector"] == "Technology"

    # Query episodes
    results = memory_store.query_episodes(query="screening")
    assert len(results) == 1
    assert results[0]["content"] == ep["content"]

    # Filter by event_type
    filtered = memory_store.query_episodes(event_type="user_query")
    assert len(filtered) == 1

    none_filtered = memory_store.query_episodes(event_type="trade")
    assert len(none_filtered) == 0

    # Delete episode
    assert memory_store.delete_episode(ep["id"]) is True
    assert len(memory_store.query_episodes()) == 0
    assert memory_store.delete_episode(999) is False


def test_semantic_memory(memory_store):
    """Test Semantic Memory tier (Knowledge Graph) operations."""
    fact = memory_store.add_semantic_fact(
        subject="AAPL",
        relation="is_in_sector",
        object="Technology",
        confidence=0.95,
    )
    assert fact["subject"] == "aapl"
    assert fact["relation"] == "is_in_sector"
    assert fact["confidence"] == 0.95

    # Query knowledge
    results = memory_store.query_semantic_knowledge(subject="AAPL")
    assert len(results) == 1
    assert results[0]["object"] == "Technology"

    # Upsert with new confidence
    memory_store.add_semantic_fact("AAPL", "is_in_sector", "Technology", confidence=1.0)
    updated = memory_store.query_semantic_knowledge(subject="AAPL")
    assert len(updated) == 1
    assert updated[0]["confidence"] == 1.0

    # Delete semantic fact
    assert memory_store.delete_semantic_fact("AAPL", "is_in_sector", "Technology") is True
    assert len(memory_store.query_semantic_knowledge(subject="AAPL")) == 0
    assert memory_store.delete_semantic_fact("AAPL", "is_in_sector", "Technology") is False


def test_procedural_memory(memory_store):
    """Test Procedural Memory (SOPs / Skills) tier operations."""
    proc = memory_store.register_procedure(
        name="rebalance_portfolio",
        description="Rebalance portfolio weights to target allocation",
        steps=["Fetch current positions", "Compute drift", "Generate orders", "Execute trades"],
        trigger_condition="Drift > 5%",
    )
    assert proc["name"] == "rebalance_portfolio"
    assert len(proc["steps"]) == 4

    fetched = memory_store.get_procedure("rebalance_portfolio")
    assert fetched is not None
    assert fetched["trigger_condition"] == "Drift > 5%"

    procs = memory_store.list_procedures()
    assert len(procs) == 1

    assert memory_store.delete_procedure("rebalance_portfolio") is True
    assert memory_store.get_procedure("rebalance_portfolio") is None
    assert memory_store.delete_procedure("nonexistent") is False


def test_memory_summary(memory_store):
    """Test high-level memory summary across all tiers."""
    memory_store.set_working("test_key", "test_val")
    memory_store.log_episode("test event")
    memory_store.add_semantic_fact("python", "is_a", "language")
    memory_store.register_procedure("test_proc", "desc", ["step 1"])

    summary = memory_store.get_summary()
    assert summary["working_memory_items"] == 1
    assert summary["episodic_memory_events"] == 1
    assert summary["semantic_memory_facts"] == 1
    assert summary["procedural_memory_procedures"] == 1
    assert summary["latest_episode"] is not None


def test_mcp_server_tools_and_resources():
    """Test MCP server tools and resource endpoints via asyncio."""
    async def run_test():
        server = create_memory_server(":memory:")

        # Test tool: set_working_memory & get_working_memory
        res_set = await server.call_tool("set_working_memory", {"key": "focus", "value": "AI Agents"})
        assert "working memory updated" in res_set.content[0].text.lower()

        res_get = await server.call_tool("get_working_memory", {"key": "focus"})
        assert "AI Agents" in res_get.content[0].text

        # Test resource: memory://working
        res_resource = await server.read_resource("memory://working")
        assert len(res_resource) > 0
        assert "AI Agents" in res_resource[0].content

        # Test tool: log_episode & query_episodes
        await server.call_tool("log_episode", {"event": "Portfolio rebalanced", "event_type": "trade", "metadata_json": '{"symbol": "SPY"}'})
        res_ep = await server.call_tool("query_episodes", {"event_type": "trade"})
        assert "Portfolio rebalanced" in res_ep.content[0].text

        # Test tool: add_semantic_fact & query_semantic_knowledge
        await server.call_tool("add_semantic_fact", {"subject": "SPY", "relation": "tracks", "object": "S&P 500", "confidence": 1.0})
        res_sem = await server.call_tool("query_semantic_knowledge", {"subject": "SPY"})
        assert "S&P 500" in res_sem.content[0].text

        # Test tool: register_procedure & get_procedure
        await server.call_tool("register_procedure", {
            "name": "buy_workflow",
            "description": "Buy workflow steps",
            "steps": ["Check cash", "Check cap", "Place order"],
            "trigger_condition": "Cash > 1000"
        })
        res_proc = await server.call_tool("get_procedure", {"name": "buy_workflow"})
        assert "Check cash" in res_proc.content[0].text

        # Test resource: memory://summary
        res_summary = await server.read_resource("memory://summary")
        assert len(res_summary) > 0
        assert "working_memory_items" in res_summary[0].content

    asyncio.run(run_test())

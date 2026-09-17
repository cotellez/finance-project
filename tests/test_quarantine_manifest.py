"""Contract tests for the flaky-test quarantine manifest."""

import json
from pathlib import Path


def load_manifest():
    path = Path(__file__).with_name("quarantine.json")
    assert path.exists(), "tests/quarantine.json must exist"
    return json.loads(path.read_text(encoding="utf-8"))


def normalized_ids(manifest):
    entries = manifest.get("quarantined", [])
    assert isinstance(entries, list), "'quarantined' must be a list"
    normalized = []
    for entry in entries:
        if isinstance(entry, dict):
            entry = entry.get("id")
        assert isinstance(entry, str) and entry, "quarantine entries must be non-empty node IDs"
        normalized.append(entry)
    return normalized


def test_quarantine_manifest_shape():
    manifest = load_manifest()
    assert set(manifest) == {"quarantined"}
    normalized_ids(manifest)


def test_quarantine_ids_are_unique_and_shaped_like_node_ids():
    ids = normalized_ids(load_manifest())
    assert len(ids) == len(set(ids)), "duplicate quarantine entries are not allowed"
    for node_id in ids:
        assert node_id.startswith("tests/"), f"unexpected quarantine ID: {node_id}"
        assert "::" in node_id, f"quarantine ID must be a full pytest node ID: {node_id}"

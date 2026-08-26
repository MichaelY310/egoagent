"""Compatibility adapter for EgoAgent's retired Meilisearch integration.

New code should import :class:`capability_registry.CapabilityRegistry`
directly.  This adapter preserves the small public surface used by older
scripts without launching a service, importing the ``meilisearch`` package, or
depending on Linux-only process management.
"""

from __future__ import annotations

from pathlib import Path

from capability_registry import CapabilityRegistry


class MeilisearchManager:
    """Deprecated zero-service facade backed by the local Capability Library."""

    def __init__(self, port=None, master_key="", *, project_root=None, workspace=None):
        del master_key
        self.port = port
        self.project_root = Path(project_root or Path(__file__).resolve().parent.parent).resolve()
        self.workspace = Path(workspace).resolve() if workspace else self.project_root
        self.registry = CapabilityRegistry(self.project_root, workspace=self.workspace)
        self.process = None
        self.client = self.registry
        self._running = False
        self.url = f"sqlite:///{self.registry.db_path}"

    def start(self):
        self.registry.reindex()
        self._running = True
        return self

    def stop(self):
        self._running = False

    def clear(self):
        # Catalog contents are derived from source and metrics are durable.
        # A legacy cleanup call must not destroy either one.
        return {"ok": True, "message": "Local capability catalog is persistent; nothing was cleared."}

    def index_tools(self, _tools_dict):
        return self.registry.reindex()

    def index_knowledges(self, _knowledges_dict):
        return self.registry.reindex()

    incremental_index_tools = index_tools
    incremental_index_knowledges = index_knowledges

    def upsert_tool(self, _full_name, _tool):
        return self.registry.reindex()

    def upsert_knowledge(self, _full_name, _knowledge):
        return self.registry.reindex()

    def remove_tool(self, _full_name):
        return self.registry.reindex()

    def remove_knowledge(self, _full_name):
        return self.registry.reindex()

    @staticmethod
    def _legacy_result(item):
        return {
            "id": item["id"],
            "full_name": item["path"],
            "short_name": item["name"],
            "description": item["description"],
            "kind": item["kind"],
            "scope": item["scope"],
            "usage_count": item["usage_count"],
            "success_rate": item["success_rate"],
        }

    def search_tools(self, query, limit=10):
        result = self.registry.search(query, kinds=["skill", "tool"], limit=limit)
        return [self._legacy_result(item) for item in result["results"]]

    def search_knowledges(self, query, limit=10):
        result = self.registry.search(query, kinds=["knowledge"], limit=limit)
        return [self._legacy_result(item) for item in result["results"]]

    def search_all(self, query, limit=10):
        result = self.registry.search(query, limit=limit)
        return {
            "tools": [self._legacy_result(item) for item in result["results"] if item["kind"] in {"skill", "tool"}],
            "knowledges": [self._legacy_result(item) for item in result["results"] if item["kind"] == "knowledge"],
            "identities": [self._legacy_result(item) for item in result["results"] if item["kind"] == "identity"],
            "harnesses": [self._legacy_result(item) for item in result["results"] if item["kind"] == "harness"],
            "creation_recommended": result["creation_recommended"],
        }

    def get_indexed_ids(self, index_name="tools"):
        kinds = {"tool": ["skill", "tool"], "tools": ["skill", "tool"], "knowledge": ["knowledge"], "knowledges": ["knowledge"]}.get(index_name)
        return {item["id"] for item in self.registry.list() if not kinds or item["kind"] in kinds}

    def get_stats(self):
        stats = self.registry.stats()
        return {
            **stats,
            "tools_count": stats["kinds"].get("skill", 0) + stats["kinds"].get("tool", 0),
            "knowledges_count": stats["kinds"].get("knowledge", 0),
        }

    @property
    def is_running(self):
        return self._running

    def __enter__(self):
        return self.start()

    def __exit__(self, _exc_type, _exc, _traceback):
        self.stop()

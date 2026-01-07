"""Context7 client implementing MCP-style search."""

from __future__ import annotations

import json
import logging
from typing import Any

import httpx

from exobrain.mcp.base import MCPClient

logger = logging.getLogger(__name__)


class Context7Client(MCPClient):
    """Minimal client for Context7 search API."""

    def __init__(self, api_key: str, endpoint: str, timeout: int = 20, max_results: int = 5):
        self.api_key = api_key
        self.endpoint = endpoint
        self.timeout = timeout
        self.max_results = max_results
        self._connected = False

    async def connect(self) -> None:
        """No-op connect; keep parity with MCP interface."""
        self._connected = True

    async def list_tools(self) -> list[dict[str, Any]]:
        """Expose a single search tool."""
        return [
            {
                "name": "context7_search",
                "description": "Search the web via Context7 with ranking and snapshots.",
                "parameters": {
                    "query": {"type": "string", "description": "Search query"},
                    "max_results": {
                        "type": "integer",
                        "description": "Max results",
                        "default": self.max_results,
                    },
                },
            }
        ]

    async def call_tool(self, name: str, arguments: dict[str, Any]) -> str:
        """Execute a Context7 search."""
        if name != "context7_search":
            raise ValueError(f"Unsupported tool: {name}")

        query = arguments.get("query") or ""
        max_results = int(arguments.get("max_results") or self.max_results)
        if not query.strip():
            return "Error: query is required"

        headers = {"Authorization": f"Bearer {self.api_key}"}
        payload = {"query": query, "limit": max_results}

        try:
            async with httpx.AsyncClient(timeout=self.timeout, follow_redirects=True) as client:
                resp = await client.post(self.endpoint, headers=headers, json=payload)
                resp.raise_for_status()
                data = resp.json()
        except Exception as e:
            logger.error(f"Context7 search failed: {e}")
            return json.dumps({"error": str(e)})

        return self._format_results(data, query)

    def _format_results(self, data: Any, query: str) -> str:
        """Convert API response into a concise, model-friendly string."""
        if not data:
            return f"No results for '{query}'."

        # Try common shapes
        items = []
        if isinstance(data, dict):
            items = data.get("results") or data.get("items") or []
        elif isinstance(data, list):
            items = data

        if not isinstance(items, list) or not items:
            return json.dumps(data)[:2000]

        lines = [f"Context7 results for: {query}"]
        for idx, item in enumerate(items[: self.max_results], 1):
            title = item.get("title") or item.get("name") or "Untitled"
            url = item.get("url") or item.get("link") or ""
            snippet = item.get("snippet") or item.get("summary") or item.get("content") or ""
            snippet = snippet.strip().replace("\n", " ")
            if len(snippet) > 280:
                snippet = snippet[:277] + "..."
            lines.append(f"\n{idx}. {title}")
            if url:
                lines.append(f"   URL: {url}")
            if snippet:
                lines.append(f"   {snippet}")

        return "\n".join(lines)

"""Tools that use Context7 search API."""

from __future__ import annotations

from typing import Any

from exobrain.mcp.context7_client import Context7Client
from exobrain.tools.base import Tool, ToolParameter


class Context7SearchTool(Tool):
    """Search the web via Context7."""

    def __init__(self, client: Context7Client):
        super().__init__(
            name="context7_search",
            description=(
                "Search the web using Context7. Use this when you need up-to-date information or webpages."
            ),
            parameters={
                "query": ToolParameter(
                    type="string",
                    description="Search query to look up",
                    required=True,
                ),
                "max_results": ToolParameter(
                    type="integer",
                    description="Maximum number of results (default set in config)",
                    required=False,
                ),
            },
            requires_permission=True,
            permission_scope="web_access",
        )
        self._client = client

    async def execute(self, **kwargs: Any) -> str:
        query = kwargs.get("query") or ""
        max_results = kwargs.get("max_results")
        args = {"query": query}
        if max_results is not None:
            args["max_results"] = max_results
        return await self._client.call_tool("context7_search", args)

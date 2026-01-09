"""Tools that use Context7 search API."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, ClassVar

from exobrain.mcp.context7_client import Context7Client
from exobrain.tools.base import ConfigurableTool, ToolParameter, register_tool

if TYPE_CHECKING:
    from exobrain.config import Config


@register_tool
class Context7SearchTool(ConfigurableTool):
    """Search the web via Context7."""

    config_key: ClassVar[str] = "context7"

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

    @classmethod
    def from_config(cls, config: "Config") -> "Context7SearchTool | None":
        """Create tool instance from configuration.

        Args:
            config: Global application configuration

        Returns:
            Context7SearchTool instance if context7 is enabled and configured, None otherwise
        """
        # Check if web_access is enabled first
        if not getattr(config.tools, "web_access", False):
            return None
        if not config.permissions.web_access.get("enabled", False):
            return None

        # Check Context7 specific config
        ctx7_cfg = getattr(config.mcp, "context7", {}) or {}
        if not ctx7_cfg.get("enabled") or not ctx7_cfg.get("api_key"):
            return None

        # Get default max_results from web_access permissions if not set in context7 config
        default_max_results = config.permissions.web_access.get("max_results", 5)

        # Create Context7 client
        client = Context7Client(
            api_key=ctx7_cfg["api_key"],
            endpoint=ctx7_cfg.get("endpoint", "https://api.context7.com/v1/search"),
            timeout=ctx7_cfg.get("timeout", 20),
            max_results=ctx7_cfg.get("max_results", default_max_results),
        )

        return cls(client)

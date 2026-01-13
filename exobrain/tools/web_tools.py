"""Web search and fetch tools for ExoBrain."""

import json
import logging
from typing import TYPE_CHECKING, Any, ClassVar

import httpx
from bs4 import BeautifulSoup
from ddgs import DDGS

from exobrain.tools.base import ConfigurableTool, ToolParameter, register_tool

if TYPE_CHECKING:
    from exobrain.config import Config

logger = logging.getLogger(__name__)


@register_tool
class WebSearchTool(ConfigurableTool):
    """Tool for searching the web using DuckDuckGo."""

    config_key: ClassVar[str] = "web_access"

    def __init__(self, max_results: int = 5):
        """Initialize web search tool.

        Args:
            max_results: Maximum number of search results to return
        """
        super().__init__(
            name="web_search",
            description="Search the web for information. Use this when you need to find current information, news, or answers to questions that require up-to-date knowledge.",
            parameters={
                "query": ToolParameter(
                    type="string",
                    description="The search query to look up",
                    required=True,
                ),
                "max_results": ToolParameter(
                    type="integer",
                    description=f"Maximum number of results to return (default: {max_results})",
                    required=False,
                ),
            },
            requires_permission=True,
            permission_scope="web_access",
        )
        # Set after super().__init__() to ensure Pydantic doesn't clear it
        self._max_results = max_results

    async def execute(self, query: str, max_results: int | None = None, **kwargs: Any) -> str:
        """Execute web search.

        Args:
            query: Search query
            max_results: Maximum number of results

        Returns:
            Formatted search results as JSON string
        """
        if not query:
            return json.dumps({"error": "Query is required"})

        max_results = max_results or self._max_results

        try:
            # Use DuckDuckGo HTML search
            results = await self._duckduckgo_search(query, max_results)

            if not results:
                return f"搜索 '{query}' 未找到结果。"

            # Format results in a user-friendly way
            formatted = [f"搜索查询: {query}\n找到 {len(results)} 条结果:\n"]
            for i, result in enumerate(results, 1):
                formatted.append(f"\n{i}. {result['title']}")
                formatted.append(f"   URL: {result['url']}")
                if result["snippet"]:
                    formatted.append(f"   摘要: {result['snippet']}")

            return "\n".join(formatted)

        except Exception as e:
            logger.error(f"Web search error: {e}")
            return json.dumps({"error": str(e)})

    async def _duckduckgo_search(self, query: str, max_results: int) -> list[dict[str, str]]:
        """Search using DuckDuckGo via ddgs library.

        Args:
            query: Search query
            max_results: Maximum results to return

        Returns:
            List of search results with title, url, and snippet
        """
        import asyncio

        def _sync_search():
            """Run synchronous ddgs search."""
            results = []
            try:
                with DDGS() as ddgs:
                    for r in ddgs.text(query, max_results=max_results):
                        results.append(
                            {
                                "title": r.get("title", ""),
                                "url": r.get("href", ""),
                                "snippet": r.get("body", ""),
                            }
                        )
            except Exception as e:
                logger.error(f"DDGS search error: {e}")
            return results

        # Run sync search in thread pool to not block event loop
        loop = asyncio.get_event_loop()
        results = await loop.run_in_executor(None, _sync_search)
        return results

    @classmethod
    def from_config(cls, config: "Config") -> "WebSearchTool | None":
        """Create tool instance from configuration.

        Args:
            config: Global application configuration

        Returns:
            WebSearchTool instance if web_access is enabled, None otherwise
        """
        if not getattr(config.tools, "web_access", False):
            return None

        web_perms = config.permissions.web_access
        if not web_perms.get("enabled", False):
            return None

        max_results = web_perms.get("max_results", 5)
        return cls(max_results=max_results)


@register_tool
class WebFetchTool(ConfigurableTool):
    """Tool for fetching and extracting text from web pages."""

    config_key: ClassVar[str] = "web_access"

    def __init__(self, max_content_length: int = 10000):
        """Initialize web fetch tool.

        Args:
            max_content_length: Maximum characters to return from page content
        """
        super().__init__(
            name="web_fetch",
            description="Fetch and extract text content from a web page. Use this to read articles, documentation, or other web content.",
            parameters={
                "url": ToolParameter(
                    type="string",
                    description="The URL of the web page to fetch",
                    required=True,
                ),
                "extract_text": ToolParameter(
                    type="boolean",
                    description="Whether to extract only text content (default: true)",
                    required=False,
                ),
            },
            requires_permission=True,
            permission_scope="web_access",
        )
        # Set after super().__init__() to ensure Pydantic doesn't clear it
        self._max_content_length = max_content_length

    async def execute(self, url: str, extract_text: bool = True, **kwargs: Any) -> str:
        """Execute web fetch.

        Args:
            url: URL to fetch
            extract_text: Whether to extract text only

        Returns:
            Page content or error message
        """
        if not url:
            return json.dumps({"error": "URL is required"})

        try:
            async with httpx.AsyncClient(timeout=30.0, follow_redirects=True) as client:
                response = await client.get(url)
                response.raise_for_status()

                if extract_text:
                    # Parse HTML and extract text
                    soup = BeautifulSoup(response.text, "html.parser")

                    # Remove script and style elements
                    for script in soup(["script", "style", "nav", "footer", "header"]):
                        script.decompose()

                    # Get text
                    text = soup.get_text(separator="\n", strip=True)

                    # Collapse multiple newlines
                    lines = [line.strip() for line in text.split("\n") if line.strip()]
                    text = "\n".join(lines)

                    # Limit length
                    truncated = False
                    if len(text) > self._max_content_length:
                        text = text[: self._max_content_length]
                        truncated = True

                    # Format output
                    title = soup.title.string if soup.title else "无标题"
                    result = [
                        f"网页标题: {title}",
                        f"URL: {url}",
                        f"内容长度: {len(text)} 字符",
                        "\n--- 网页内容 ---\n",
                        text,
                    ]
                    if truncated:
                        result.append("\n\n[内容已截断...]")

                    return "\n".join(result)
                else:
                    # Return raw HTML
                    html = response.text
                    if len(html) > self._max_content_length:
                        html = html[: self._max_content_length]
                        return f"URL: {url}\nHTML 长度: {len(html)} 字符\n\n{html}\n\n[内容已截断...]"

                    return f"URL: {url}\nHTML 长度: {len(html)} 字符\n\n{html}"

        except Exception as e:
            logger.error(f"Web fetch error: {e}")
            return json.dumps({"error": str(e), "url": url})

    @classmethod
    def from_config(cls, config: "Config") -> "WebFetchTool | None":
        """Create tool instance from configuration.

        Args:
            config: Global application configuration

        Returns:
            WebFetchTool instance if web_access is enabled, None otherwise
        """
        if not getattr(config.tools, "web_access", False):
            return None

        web_perms = config.permissions.web_access
        if not web_perms.get("enabled", False):
            return None

        max_content_length = web_perms.get("max_content_length", 10000)
        return cls(max_content_length=max_content_length)

"""Time management tools."""

from datetime import datetime, timezone
from typing import Any
from zoneinfo import ZoneInfo

import httpx

from exobrain.tools.base import Tool, ToolParameter


class GetCurrentTimeTool(Tool):
    """Tool to get the current time."""

    def __init__(self) -> None:
        super().__init__(
            name="get_current_time",
            description="Get the current date and time",
            parameters={
                "format": ToolParameter(
                    type="string",
                    description="Format string for the datetime (e.g., '%Y-%m-%d %H:%M:%S')",
                    required=False,
                )
            },
            requires_permission=False,
        )

    async def execute(self, **kwargs: Any) -> str:
        """Execute the tool."""
        format_str = kwargs.get("format", "%Y-%m-%d %H:%M:%S %Z")
        tz_name = kwargs.get("timezone")

        try:
            tz = ZoneInfo(tz_name) if tz_name else None
        except Exception:
            tz = None

        now = datetime.now(tz=tz)

        try:
            return now.strftime(format_str)
        except Exception as e:
            return f"Error formatting time: {e}"


class GetWorldTimeTool(Tool):
    """Get current time for a specific timezone using a network time API."""

    def __init__(self, default_tz: str = "UTC") -> None:
        super().__init__(
            name="get_world_time",
            description="Get the current time for a specific timezone using a network source.",
            parameters={
                "timezone": ToolParameter(
                    type="string",
                    description="IANA timezone name (e.g., 'America/New_York', 'Asia/Shanghai'). If omitted, uses UTC.",
                    required=False,
                ),
                "format": ToolParameter(
                    type="string",
                    description="Optional strftime format, defaults to '%Y-%m-%d %H:%M:%S %Z'",
                    required=False,
                ),
            },
            requires_permission=False,
        )
        self._default_tz = default_tz

    async def execute(self, **kwargs: Any) -> str:
        tz_name = kwargs.get("timezone") or self._default_tz
        fmt = kwargs.get("format", "%Y-%m-%d %H:%M:%S %Z")

        api_url = f"https://worldtimeapi.org/api/timezone/{tz_name}"
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                resp = await client.get(api_url)
                resp.raise_for_status()
                data = resp.json()
                dt_str = data.get("datetime")
                if not dt_str:
                    raise ValueError("Missing datetime in response")
                # worldtimeapi returns ISO 8601 with tz offset
                dt = datetime.fromisoformat(dt_str)
                return dt.strftime(fmt)
        except Exception as e:
            # Fallback to local computation if API fails
            try:
                tz = ZoneInfo(tz_name)
                dt = datetime.now(tz=tz)
                return dt.strftime(fmt)
            except Exception:
                return f"Error fetching time for {tz_name}: {e}"

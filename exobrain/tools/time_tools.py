"""Time management tools."""

from datetime import datetime
from typing import TYPE_CHECKING, Any, ClassVar
from zoneinfo import ZoneInfo

import httpx

from exobrain.tools.base import ConfigurableTool, ToolParameter, register_tool

if TYPE_CHECKING:
    from exobrain.config import Config


@register_tool
class GetCurrentTimeTool(ConfigurableTool):
    """Tool to get the current time."""

    config_key: ClassVar[str] = "time_management"

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

    @classmethod
    def from_config(cls, config: "Config") -> "GetCurrentTimeTool | None":
        """Create tool instance from configuration.

        Args:
            config: Global application configuration

        Returns:
            GetCurrentTimeTool instance if time_management is enabled, None otherwise
        """
        if not config.tools.time_management:
            return None
        return cls()


@register_tool
class GetWorldTimeTool(ConfigurableTool):
    """Get current time for a specific timezone using a network time API."""

    config_key: ClassVar[str] = "time_management"

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

    @classmethod
    def from_config(cls, config: "Config") -> "GetWorldTimeTool | None":
        """Create tool instance from configuration.

        Args:
            config: Global application configuration

        Returns:
            GetWorldTimeTool instance if time_management is enabled, None otherwise
        """
        if not config.tools.time_management:
            return None
        return cls()

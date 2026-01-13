"""Location-related tools."""

from __future__ import annotations

import json
import logging
from typing import TYPE_CHECKING, Any, ClassVar

import httpx

from exobrain.tools.base import ConfigurableTool, register_tool

if TYPE_CHECKING:
    from exobrain.config import Config

logger = logging.getLogger(__name__)


@register_tool
class GetUserLocationTool(ConfigurableTool):
    """Fetch approximate user location via IP-based lookup."""

    config_key: ClassVar[str] = "location"

    def __init__(self, provider_url: str, timeout: int = 10, token: str | None = None) -> None:
        super().__init__(
            name="get_user_location",
            description=(
                "Get the user's approximate city/region/country based on their network location. "
                "Use this when a query depends on the user's current location (e.g., local weather or local news)."
            ),
            parameters={},
            requires_permission=True,
            permission_scope="location",
        )
        self._provider_url = provider_url
        self._timeout = timeout
        self._token = token

    async def execute(self, **kwargs: Any) -> str:
        """Resolve user location using the configured provider."""
        url = self._provider_url
        headers: dict[str, str] = {}
        params: dict[str, str] = {}
        if self._token:
            # ipinfo.io style token support
            params["token"] = self._token

        try:
            async with httpx.AsyncClient(timeout=self._timeout, follow_redirects=True) as client:
                resp = await client.get(url, headers=headers, params=params)
                resp.raise_for_status()

            data = resp.json()
        except Exception as e:
            logger.error(f"Location lookup failed: {e}")
            return json.dumps({"error": str(e), "provider": url})

        # Normalize common provider fields
        city = data.get("city") or data.get("town") or data.get("locality")
        region = data.get("region") or data.get("state")
        country = data.get("country")
        loc = data.get("loc") or data.get("location")
        latitude = None
        longitude = None
        if isinstance(loc, str) and "," in loc:
            lat, lon = loc.split(",", 1)
            latitude = lat.strip()
            longitude = lon.strip()
        elif isinstance(loc, dict):
            latitude = loc.get("lat")
            longitude = loc.get("lon") or loc.get("lng")

        parts = []
        if city:
            parts.append(city)
        if region:
            parts.append(region)
        if country:
            parts.append(country)
        location_line = ", ".join(parts) if parts else "Unknown location"

        coords_line = None
        if latitude and longitude:
            coords_line = f"Lat: {latitude}, Lon: {longitude}"

        lines = [f"Approximate location: {location_line}"]
        if coords_line:
            lines.append(coords_line)

        return "\n".join(lines)

    @classmethod
    def from_config(cls, config: "Config") -> "GetUserLocationTool | None":
        """Create tool instance from configuration.

        Args:
            config: Global application configuration

        Returns:
            GetUserLocationTool instance if location is enabled, None otherwise
        """
        if not getattr(config.tools, "location", False):
            return None

        location_perms = config.permissions.location
        if not location_perms.get("enabled", False):
            return None

        provider_url = location_perms.get("provider_url", "https://ipinfo.io/json")
        timeout = location_perms.get("timeout", 10)
        token = location_perms.get("token")

        return cls(provider_url=provider_url, timeout=timeout, token=token)

from __future__ import annotations

import abc
import logging
from typing import Any

import aiohttp

from kingdom_tech_desk.config import ServerContextSettings
from kingdom_tech_desk.models.core import ServerSnapshot

LOGGER = logging.getLogger(__name__)


class ServerContextProvider(abc.ABC):
    @abc.abstractmethod
    async def snapshot(self, server_key: str | None = None) -> ServerSnapshot:
        raise NotImplementedError

    async def close(self) -> None:
        return None


class DisabledServerContextProvider(ServerContextProvider):
    async def snapshot(self, server_key: str | None = None) -> ServerSnapshot:
        return ServerSnapshot(available=False, data={}, error="Server context integration is disabled")


class HttpServerContextProvider(ServerContextProvider):
    """Optional adapter for a future OniLink status endpoint.

    The endpoint is intentionally generic. It expects a JSON object and never blocks
    ticket creation when unavailable.
    """

    ALLOWED_FIELDS = {
        "proxy_status",
        "upstream_status",
        "bds_version",
        "protocol_version",
        "server_name",
        "uptime_seconds",
        "player_count",
        "tps",
        "tick_health",
        "recent_restart",
        "resource_pack_revision",
        "addon_revision",
        "transfer_route",
        "warning_summary",
    }

    def __init__(self, settings: ServerContextSettings, session: aiohttp.ClientSession | None = None) -> None:
        self.settings = settings
        self._external_session = session is not None
        self.session = session

    async def _session(self) -> aiohttp.ClientSession:
        if self.session is None or self.session.closed:
            timeout = aiohttp.ClientTimeout(total=self.settings.timeout_seconds)
            self.session = aiohttp.ClientSession(timeout=timeout)
        return self.session

    async def snapshot(self, server_key: str | None = None) -> ServerSnapshot:
        endpoint_key = self.settings.server_mapping.get(server_key or "", server_key or "default")
        url = f"{self.settings.base_url}/v1/server-context/{endpoint_key}"
        headers = {"Accept": "application/json"}
        if self.settings.authentication_token:
            headers["Authorization"] = f"Bearer {self.settings.authentication_token}"
        try:
            session = await self._session()
            async with session.get(url, headers=headers, ssl=self.settings.verify_tls) as response:
                if response.status != 200:
                    return ServerSnapshot(available=False, error=f"HTTP {response.status}")
                payload = await response.json(content_type=None)
                if not isinstance(payload, dict):
                    return ServerSnapshot(available=False, error="Unexpected payload shape")
                clean: dict[str, Any] = {
                    key: payload[key] for key in self.ALLOWED_FIELDS if key in payload
                }
                return ServerSnapshot(available=True, data=clean)
        except (aiohttp.ClientError, TimeoutError, ValueError) as exc:
            LOGGER.info("Server context unavailable: %s", type(exc).__name__)
            return ServerSnapshot(available=False, error=type(exc).__name__)

    async def close(self) -> None:
        if self.session is not None and not self._external_session:
            await self.session.close()


def build_server_context_provider(settings: ServerContextSettings) -> ServerContextProvider:
    if not settings.enabled:
        return DisabledServerContextProvider()
    return HttpServerContextProvider(settings)

"""Read-through caches in front of the routing table, so most requests touch no shared store (ADR-003)."""
from __future__ import annotations

import time
from collections.abc import Callable

from ..routing import Route, RoutingTable, hash_api_key


class _TtlCache[T]:
    def __init__(self, ttl_seconds: float, clock: Callable[[], float]):
        self._ttl = ttl_seconds
        self._clock = clock
        self._entries: dict[str, tuple[float, T | None]] = {}

    def get(self, key: str, load: Callable[[], T | None]) -> T | None:
        now = self._clock()
        hit = self._entries.get(key)
        if hit and hit[0] > now:
            return hit[1]
        value = load()
        self._entries[key] = (now + self._ttl, value)
        return value


class TenantAuthenticator:
    """API key -> tenantId. The tenant identity never comes from the URL or the body (SPEC RF03)."""

    def __init__(self, routing: RoutingTable, pepper: str, ttl_seconds: float = 60.0,
                 clock: Callable[[], float] = time.monotonic):
        self._routing = routing
        self._pepper = pepper
        self._cache: _TtlCache[str] = _TtlCache(ttl_seconds, clock)

    def authenticate(self, api_key: str | None) -> str | None:
        if not api_key or len(api_key) > 200:
            return None
        key_hash = hash_api_key(api_key, self._pepper)
        return self._cache.get(key_hash, lambda: self._routing.tenant_for_key_hash(key_hash))


class CellDirectory:
    """tenantId -> Route, cached for `ttl_seconds` (default 10 s, SPEC RF04)."""

    def __init__(self, routing: RoutingTable, ttl_seconds: float = 10.0, clock: Callable[[], float] = time.monotonic):
        self._routing = routing
        self._cache: _TtlCache[Route] = _TtlCache(ttl_seconds, clock)

    def resolve(self, tenant_id: str) -> Route | None:
        return self._cache.get(tenant_id, lambda: self._routing.route(tenant_id))

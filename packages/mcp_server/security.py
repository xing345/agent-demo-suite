"""SSRF guard for remote MCP endpoints.

Hostnames are not resolved here (that would need network access and is racy);
literal private/loopback/link-local addresses and well-known metadata hosts are
rejected, redirects are disabled at the HTTP layer, and an optional allowlist
covers the cases where only known hosts are legitimate.
"""

from __future__ import annotations

import ipaddress
from dataclasses import dataclass
from urllib.parse import urlsplit


class UnsafeTargetError(ValueError):
    """The remote endpoint violates the outbound request policy."""


BLOCKED_HOSTNAMES = frozenset({"localhost", "metadata.google.internal", "metadata"})


@dataclass(frozen=True)
class SecurityPolicy:
    allowed_hosts: frozenset[str] | None = None
    allow_private: bool = False
    require_https: bool = False

    def check(self, url: str) -> str:
        parts = urlsplit(url)
        if parts.scheme not in {"http", "https"}:
            raise UnsafeTargetError(f"unsupported scheme: {parts.scheme or '(none)'}")
        if self.require_https and parts.scheme != "https":
            raise UnsafeTargetError("https is required for remote MCP endpoints")

        host = (parts.hostname or "").strip().lower()
        if not host:
            raise UnsafeTargetError("target host is missing")

        if self.allowed_hosts is not None and host not in self.allowed_hosts:
            raise UnsafeTargetError(f"host is not allowlisted: {host}")

        if self.allow_private:
            return url

        if host in BLOCKED_HOSTNAMES:
            raise UnsafeTargetError(f"host is blocked: {host}")

        try:
            address = ipaddress.ip_address(host)
        except ValueError:
            return url

        if (
            address.is_private
            or address.is_loopback
            or address.is_link_local
            or address.is_reserved
            or address.is_multicast
            or address.is_unspecified
        ):
            raise UnsafeTargetError(f"target address is not public: {host}")
        return url
"""Bearer token authentication with constant-time comparison and scopes."""

from __future__ import annotations

import hmac
from collections.abc import Iterable
from dataclasses import dataclass, field


class AuthError(Exception):
    def __init__(self, message: str, *, status_code: int = 401) -> None:
        super().__init__(message)
        self.status_code = status_code


@dataclass(frozen=True)
class Principal:
    name: str = "anonymous"
    scopes: frozenset[str] = field(default_factory=frozenset)


class TokenAuthenticator:
    def __init__(
        self,
        token: str,
        *,
        scopes: Iterable[str] = ("mcp:tools",),
        principal: str = "default",
    ) -> None:
        if not token:
            raise ValueError("token must not be empty")
        self.token = token
        self.scopes = frozenset(scopes)
        self.principal = principal

    def authenticate(self, authorization: str | None) -> Principal:
        if not authorization:
            raise AuthError("missing bearer token")
        scheme, _, presented = authorization.partition(" ")
        presented = presented.strip()
        if scheme.lower() != "bearer" or not presented:
            raise AuthError("missing bearer token")
        if not hmac.compare_digest(presented, self.token):
            raise AuthError("invalid token")
        return Principal(name=self.principal, scopes=self.scopes)

    def require(self, principal: Principal, scope: str) -> None:
        if "*" in principal.scopes or scope in principal.scopes:
            return
        raise AuthError(f"missing scope: {scope}", status_code=403)
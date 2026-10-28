"""Authentication, scope enforcement and SSRF protection."""

import pytest

from packages.mcp_server import MCPRemoteClient, RemoteMCPError
from packages.mcp_server.auth import AuthError, TokenAuthenticator
from packages.mcp_server.security import SecurityPolicy, UnsafeTargetError


def test_authenticator_rejects_missing_and_wrong_tokens() -> None:
    authenticator = TokenAuthenticator("secret", scopes={"mcp:tools"})

    with pytest.raises(AuthError) as missing:
        authenticator.authenticate(None)
    assert missing.value.status_code == 401

    with pytest.raises(AuthError) as wrong:
        authenticator.authenticate("Bearer nope")
    assert wrong.value.status_code == 401


def test_authenticator_returns_principal_and_checks_scope() -> None:
    authenticator = TokenAuthenticator("secret", scopes={"mcp:read"})
    principal = authenticator.authenticate("Bearer secret")

    assert principal.scopes == frozenset({"mcp:read"})
    authenticator.require(principal, "mcp:read")
    with pytest.raises(AuthError) as denied:
        authenticator.require(principal, "mcp:write")
    assert denied.value.status_code == 403


def test_wildcard_scope_grants_everything() -> None:
    authenticator = TokenAuthenticator("secret", scopes={"*"})
    principal = authenticator.authenticate("Bearer secret")

    authenticator.require(principal, "anything")


def test_ssrf_policy_blocks_private_and_metadata_targets() -> None:
    policy = SecurityPolicy()

    for url in (
        "http://127.0.0.1:8001",
        "http://localhost:8001",
        "http://169.254.169.254/latest/meta-data",
        "http://10.0.0.5/mcp",
        "http://[::1]:8000",
    ):
        with pytest.raises(UnsafeTargetError):
            policy.check(url)


def test_ssrf_policy_allows_public_hosts() -> None:
    assert SecurityPolicy().check("https://mcp.example.com") == "https://mcp.example.com"
    assert SecurityPolicy().check("http://mcp.example.com:8080") == "http://mcp.example.com:8080"


def test_ssrf_policy_allows_private_targets_when_explicitly_enabled() -> None:
    policy = SecurityPolicy(allow_private=True)

    assert policy.check("http://127.0.0.1:8001")


def test_ssrf_policy_can_require_https_and_host_allowlist() -> None:
    with pytest.raises(UnsafeTargetError):
        SecurityPolicy(require_https=True).check("http://mcp.example.com")

    allowlisted = SecurityPolicy(allowed_hosts=frozenset({"mcp.example.com"}))
    with pytest.raises(UnsafeTargetError):
        allowlisted.check("https://evil.example.com")


def test_remote_client_refuses_unsafe_endpoint_at_construction() -> None:
    with pytest.raises(RemoteMCPError, match="unsafe"):
        MCPRemoteClient("http://127.0.0.1:8001")


def test_remote_client_accepts_private_endpoint_when_allowed() -> None:
    client = MCPRemoteClient(
        "http://127.0.0.1:8001",
        policy=SecurityPolicy(allow_private=True),
    )

    assert client.base_url == "http://127.0.0.1:8001"
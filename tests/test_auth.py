"""Tests for the resource-server auth-config presets."""

import pytest

from enlace_connector import auth as A


def test_enlace_resource_shape():
    cfg = A.enlace_resource(
        issuer="https://apps.thorwhalen.com/",
        audience="https://apps.thorwhalen.com/trufflepig-mcp",
    )
    assert cfg["type"] == "jwt"
    assert cfg["issuer"] == "https://apps.thorwhalen.com"  # trailing slash trimmed
    assert cfg["jwks_uri"] == "https://apps.thorwhalen.com/auth/oauth/jwks"
    assert cfg["authorization_servers"] == ["https://apps.thorwhalen.com"]
    assert cfg["audience"] == "https://apps.thorwhalen.com/trufflepig-mcp"
    assert cfg["required_scopes"] == ["mcp:read"]


def test_idp_resource_defaults_auth_servers_and_base_url():
    cfg = A.idp_resource(
        jwks_uri="https://idp/.well-known/jwks.json",
        issuer="https://idp/",
        audience="https://conn/mcp",
    )
    assert cfg["authorization_servers"] == ["https://idp/"]
    assert cfg["base_url"] == "https://conn/mcp"


def test_resolve_auth_none_and_passthrough():
    assert A.resolve_auth(None) is None
    assert A.resolve_auth("none") is None
    d = {"type": "jwt", "issuer": "x"}
    assert A.resolve_auth(d) is d


def test_resolve_auth_enlace_requires_issuer_and_audience():
    with pytest.raises(ValueError):
        A.resolve_auth("enlace")
    cfg = A.resolve_auth("enlace", issuer="https://p", audience="https://p/c-mcp")
    assert cfg["jwks_uri"] == "https://p/auth/oauth/jwks"


def test_resolve_auth_idp_string_is_rejected_with_guidance():
    with pytest.raises(ValueError, match="idp_resource"):
        A.resolve_auth("idp")

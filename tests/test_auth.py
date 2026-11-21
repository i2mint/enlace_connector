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
    # base_url is the connector base; the validated audience is the MCP endpoint
    # (base + /mcp), matching what FastMCP advertises and the token's aud.
    assert cfg["base_url"] == "https://apps.thorwhalen.com/trufflepig-mcp"
    assert cfg["audience"] == "https://apps.thorwhalen.com/trufflepig-mcp/mcp"
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


# -- auth_from_env (#27) ---------------------------------------------------------

ORIGIN = "https://apps.example.com"
BASE = f"{ORIGIN}/x-mcp"


def test_auth_from_env_builds_the_enlace_resource_config():
    cfg = A.auth_from_env({A.ISSUER_ENV: ORIGIN, A.AUDIENCE_ENV: BASE})
    assert cfg == A.enlace_resource(issuer=ORIGIN, audience=BASE)


def test_auth_from_env_passes_mcp_path_and_scopes():
    cfg = A.auth_from_env(
        {A.ISSUER_ENV: ORIGIN, A.AUDIENCE_ENV: BASE},
        mcp_path="/sse",
        scopes=("mcp:write",),
    )
    assert cfg["audience"] == f"{BASE}/sse"
    assert cfg["required_scopes"] == ["mcp:write"]


@pytest.mark.parametrize("settings", [{}, {A.ISSUER_ENV: "", A.AUDIENCE_ENV: " "}])
def test_auth_from_env_with_neither_is_unauthenticated(settings):
    assert A.auth_from_env(settings) is None


@pytest.mark.parametrize(
    "settings, missing",
    [
        ({"CONNECTOR_ISSUER": ORIGIN}, "CONNECTOR_AUDIENCE"),
        ({"CONNECTOR_AUDIENCE": BASE}, "CONNECTOR_ISSUER"),
        ({"CONNECTOR_ISSUER": ORIGIN, "CONNECTOR_AUDIENCE": ""}, "CONNECTOR_AUDIENCE"),
    ],
)
def test_half_a_configuration_refuses_to_start(settings, missing):
    with pytest.raises(ValueError, match=f"{missing} is not"):
        A.auth_from_env(settings)


def test_auth_from_env_reads_os_environ_by_default(monkeypatch):
    monkeypatch.setenv("CONNECTOR_ISSUER", ORIGIN)
    monkeypatch.setenv("CONNECTOR_AUDIENCE", BASE)
    assert A.auth_from_env()["issuer"] == ORIGIN


@pytest.mark.parametrize("route", [None, "/api/a%2Fb", '/q"uote'])
def test_the_rendered_unit_sets_exactly_the_names_auth_from_env_reads(route):
    """One pair of names: what deploy writes is what auth_from_env reads, with
    systemd's own quoting, escapes and ``%%`` undone by the unit parser."""
    from enlace_connector import ConnectorSpec
    from enlace_connector.deploy import _environment, _parse_unit, render_systemd_unit

    spec = ConnectorSpec(name="x", tools=[], route=route)
    unit = render_systemd_unit(spec, issuer=ORIGIN)
    settings = _environment(_parse_unit(unit)[("Service", "Environment")])
    cfg = A.auth_from_env(settings, required=True)
    assert cfg["issuer"] == ORIGIN
    assert cfg["base_url"] == spec.default_audience(ORIGIN)


def test_required_refuses_to_start_with_neither_name_set():
    with pytest.raises(ValueError, match="requires auth"):
        A.auth_from_env({"CONNECTOR_ISUER": ORIGIN}, required=True)  # a typo


def test_an_audience_that_already_names_the_mcp_endpoint_is_refused():
    with pytest.raises(ValueError, match="base URL"):
        A.auth_from_env({A.ISSUER_ENV: ORIGIN, A.AUDIENCE_ENV: f"{BASE}/mcp/"})


def test_the_scaffold_reads_the_same_names():
    from enlace_connector import ConnectorSpec
    from enlace_connector.scaffold import render_server_py

    src = render_server_py(ConnectorSpec(name="x", tools=[]))
    assert repr(A.ISSUER_ENV) in src and repr(A.AUDIENCE_ENV) in src

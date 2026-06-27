"""Tests for ConnectorSpec and the server/app factories."""

import asyncio

import pytest

from enlace_connector import ConnectorSpec, make_connector_app, make_stdio_server

# Stdlib refs as stand-in tools — keeps tests free of any heavy tool package.
TOOLS = ["os.path:basename", "os.path:dirname"]


def test_spec_derived_properties():
    spec = ConnectorSpec(name="trufflepig", tools=TOOLS)
    assert spec.server_name == "trufflepig"  # falls back to name
    assert spec.mount_route == "/trufflepig-mcp"  # default route
    assert spec.auth == "enlace"  # default AS is the platform's own
    assert spec.default_audience("https://apps.thorwhalen.com/") == (
        "https://apps.thorwhalen.com/trufflepig-mcp"
    )


def test_spec_explicit_title_and_route():
    spec = ConnectorSpec(name="tp", tools=TOOLS, title="Trufflepig", route="/tp")
    assert spec.server_name == "Trufflepig"
    assert spec.mount_route == "/tp"


def test_make_stdio_server_registers_tools():
    pytest.importorskip("py2mcp")
    spec = ConnectorSpec(name="demo", tools=TOOLS, auth="none")
    server = make_stdio_server(spec)
    names = {t.name for t in asyncio.run(server.list_tools())}
    assert names == {"basename", "dirname"}


def test_make_connector_app_builds_asgi_app_unauthenticated():
    pytest.importorskip("py2mcp")
    spec = ConnectorSpec(name="demo", tools=TOOLS, auth="none")
    app = make_connector_app(spec)
    assert callable(app)  # an ASGI application


def test_make_connector_app_with_enlace_auth_builds_offline():
    pytest.importorskip("py2mcp")
    spec = ConnectorSpec(name="trufflepig", tools=TOOLS, auth="enlace")
    # issuer given → audience derived from route; build must not do network I/O.
    app = make_connector_app(spec, issuer="https://apps.thorwhalen.com")
    assert callable(app)

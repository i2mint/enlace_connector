"""``enlace_connector`` — deploy Python functions as authenticated MCP connectors.

A Claude.ai "custom connector" is a remote MCP server. This package turns a set of
Python functions into one — wired for the [enlace](https://github.com/i2mint/enlace)
platform and its [enlace_auth](https://github.com/i2mint/enlace_auth) OAuth server,
built on [py2mcp](https://github.com/thorwhalen/py2mcp).

Declare a connector once::

    from enlace_connector import ConnectorSpec, make_connector_app

    spec = ConnectorSpec(
        name="trufflepig",
        tools=["truffle.mcp:search_trufflepig", "truffle.mcp:search_wallow"],
        auth="enlace",                 # validate the platform's enlace_auth tokens
        extras=["truffle"],            # what the connector's runtime venv needs
    )

…then run it where you need it:

- ``make_stdio_server(spec)`` → a FastMCP server for Claude Desktop / Claude Code.
- ``make_connector_app(spec, issuer=...)`` → the Streamable-HTTP ASGI app a host runs.
- ``scaffold_app(spec, dest)`` → an enlace ``mode="process"`` app dir (``app.toml`` +
  ``server.py``) so a heavy connector runs in its own venv, reverse-proxied by enlace.

The authorization server is pluggable (``auth="enlace"`` for the platform's own
``enlace_auth``; ``idp_resource(...)`` for Auth0/WorkOS/…; ``None`` for an
unauthenticated local/pilot run) — the resource-server validation is identical
regardless of who issues the token.
"""

from __future__ import annotations

from .auth import (
    DFLT_SCOPES,
    ENLACE_OAUTH_PATH,
    enlace_resource,
    idp_resource,
    resolve_auth,
)
from .connector import ConnectorSpec, make_connector_app, make_stdio_server
from .deploy import (
    generate_deploy_bundle,
    render_allowlist_toml,
    render_provision_script,
    render_runbook,
    render_systemd_unit,
    resource_url,
)
from .scaffold import render_app_toml, render_server_py, scaffold_app

__version__ = "0.0.1"

__all__ = [
    "ConnectorSpec",
    "make_connector_app",
    "make_stdio_server",
    "resolve_auth",
    "enlace_resource",
    "idp_resource",
    "ENLACE_OAUTH_PATH",
    "DFLT_SCOPES",
    "scaffold_app",
    "generate_deploy_bundle",
    "render_systemd_unit",
    "render_provision_script",
    "render_allowlist_toml",
    "render_runbook",
    "resource_url",
    "render_app_toml",
    "render_server_py",
]

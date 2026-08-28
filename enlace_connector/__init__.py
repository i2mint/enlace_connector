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

Whichever one you point at, **verify it before calling a deployment good**::

    from enlace_connector import verify_deployment, format_report
    print(format_report(verify_deployment(spec, issuer="https://apps.example.com")))

An authorization server that cannot issue refresh tokens strands every connector
session at its first access-token expiry while the connector process goes on
looking perfectly healthy — :mod:`enlace_connector.preflight` is what catches that
in seconds instead of when a user complains a day later.
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
    DFLT_REFRESH_TOKEN_TTL_SECONDS,
    generate_deploy_bundle,
    render_allowlist_toml,
    render_oauth_server_toml,
    render_provision_script,
    render_runbook,
    render_systemd_unit,
    resource_url,
)
from .preflight import (
    CheckResult,
    PreflightContext,
    PreflightError,
    authorization_server_metadata,
    check_jwks_uri_matches_convention,
    check_refresh_grant_supported,
    format_report,
    verify_deployment,
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
    "render_oauth_server_toml",
    "render_runbook",
    "DFLT_REFRESH_TOKEN_TTL_SECONDS",
    "resource_url",
    "render_app_toml",
    "render_server_py",
    # preflight / verify — the deployment isn't good until these pass
    "verify_deployment",
    "check_refresh_grant_supported",
    "check_jwks_uri_matches_convention",
    "authorization_server_metadata",
    "format_report",
    "CheckResult",
    "PreflightContext",
    "PreflightError",
]

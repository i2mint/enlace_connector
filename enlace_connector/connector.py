"""Define a connector once, run it anywhere — stdio (local) or HTTP (hosted).

A :class:`ConnectorSpec` is the single declaration of a connector: the Python tool
functions to expose, the auth strategy, the public route, and the pip extras its
runtime venv needs. The factories turn that one spec into the artifacts each host
wants:

- :func:`make_stdio_server` — a FastMCP server for Claude Desktop / Claude Code while
  developing (no auth).
- :func:`make_connector_app` — the Streamable-HTTP ASGI app an enlace platform mounts
  (or a standalone ASGI server runs) — with auth resolved from the spec.

Tools are given as ``"module:function"`` reference strings (py2mcp's form), so the
spec is import-light and serializable — the heavy tool modules load only in the
process that actually serves them.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from .auth import resolve_auth

__all__ = ["ConnectorSpec", "make_stdio_server", "make_connector_app"]


@dataclass
class ConnectorSpec:
    """A declarative connector definition (see the module docstring).

    Attributes:
        name: short identifier — the enlace app name and default route stem.
        tools: ``"module:function"`` refs exposed as MCP tools.
        auth: ``"enlace"`` / ``"none"`` / an auth dict (e.g. from ``idp_resource``).
            Defaults to ``"enlace"`` — the platform's own OAuth server.
        title: human-facing MCP server name (defaults to *name*).
        route: enlace mount route (defaults to ``"/{name}-mcp"``).
        extras: pip requirements the connector's runtime venv needs (e.g. the
            package owning the tools). Used by the deploy/scaffold layer.
        stateless_http: run the MCP transport statelessly (recommended behind a
            multi-worker server / load balancer). Defaults to True.
    """

    name: str
    tools: list[str]
    auth: Any = "enlace"
    title: str | None = None
    route: str | None = None
    extras: list[str] = field(default_factory=list)
    stateless_http: bool = True

    @property
    def server_name(self) -> str:
        return self.title or self.name

    @property
    def mount_route(self) -> str:
        return self.route or f"/{self.name}-mcp"

    def default_audience(self, platform_origin: str) -> str:
        """This connector's public URL under *platform_origin* (the token audience)."""
        return f"{platform_origin.rstrip('/')}{self.mount_route}"


def make_stdio_server(spec: ConnectorSpec):
    """Build a FastMCP server for *spec*, for local stdio serving (no auth).

    Use for ``server.run()`` in Claude Desktop / Claude Code while developing the
    tools; the hosted path uses :func:`make_connector_app`.
    """
    from py2mcp import mk_mcp_from_refs

    return mk_mcp_from_refs(spec.tools, name=spec.server_name)


def make_connector_app(
    spec: ConnectorSpec,
    *,
    issuer: str | None = None,
    audience: str | None = None,
):
    """Build the Streamable-HTTP ASGI app for *spec* (the hosted connector).

    Resolves the spec's ``auth`` into a py2mcp resource-server config. For
    ``auth="enlace"`` provide *issuer* (the platform origin) and *audience* (this
    connector's public URL); if *audience* is omitted it is derived from *issuer* +
    the spec's route. Returns an ASGI app to run under any ASGI server (or mount in
    enlace).
    """
    if audience is None and issuer is not None:
        audience = spec.default_audience(issuer)
    auth = resolve_auth(spec.auth, issuer=issuer, audience=audience)

    from py2mcp import mk_http_app

    return mk_http_app(
        spec.tools,
        name=spec.server_name,
        auth=auth,
        stateless_http=spec.stateless_http,
    )

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
from typing import Any, Mapping

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
        extras: PyPI requirements the connector's own runtime venv needs (e.g. the
            package owning the tools + its embedder deps).
        git_installs: non-PyPI deps as pip specs (e.g.
            ``"git+ssh://git@github.com/org/pkg"``) for private/unreleased packages.
        port: the fixed local port the connector process binds; enlace reverse-
            proxies the route to ``127.0.0.1:{port}``. Must be free on the box.
        data: ``(local_path, remote_path)`` pairs to co-locate on the server —
            large artifacts (corpus stores, model caches) shipped *separately* from
            code (rsynced), the deploy runbook lists the copy step.
        env: environment variables the connector's systemd unit sets (e.g.
            ``XDG_DATA_HOME`` / ``HF_HOME`` pointing at the ``data`` dirs).
        allowed_users: emails permitted to authorize this connector — becomes the
            platform's ``[auth.oauth_server.resource_allowlist]`` entry. Required
            for a deploy bundle: enlace_auth refuses every account for a resource
            it does not list (fail closed, since enlace_auth 0.1.30), so an empty
            list is an error, never "open". ``["*"]`` (``deploy.ANY_ACCOUNT``)
            admits every authenticated platform account, and must be written out.
        post_install: shell commands run *inside the connector venv* after deps
            install (e.g. pre-warming an embedding model so the first query
            doesn't block). ``{venv}`` / ``{base}`` placeholders are substituted.
        stateless_http: run the MCP transport statelessly (recommended behind a
            multi-worker server / load balancer). Defaults to True.
        version: the connector's version, written into every usage-log record
            when logging is on (see :mod:`enlace_connector.usage`).
        usage_outcome: a ``"module:function"`` ref to this connector's own
            ``(tool_name, result) -> label | mapping`` usage-outcome classifier
            (e.g. one that knows the search tool's "no match" shape), used in
            place of py2mcp's generic one when logging is on.
        app_dir: the connector's directory name under the platform's ``apps/``
            and ``connectors/`` (defaults to *name*). A host that names the app
            ``<name>_mcp`` sets it so the rendered paths exist (#15).
        environment_files: ``EnvironmentFile=`` values for the unit, in order —
            how a host scopes provider secrets into the process without writing
            them into the unit. A leading ``-`` makes one optional, as in systemd.
        exec_start_pre: ``ExecStartPre=`` commands, in order (e.g. extracting the
            scoped secrets an ``environment_files`` entry then reads).
        uvicorn_args: extra arguments appended to the ``uvicorn`` command line
            (e.g. ``--no-access-log`` for a connector that serves signed links).
        service_directives: any other ``(key, value)`` lines for the unit's
            ``[Service]`` section, in order (e.g. ``("RuntimeDirectory", ...)``).

        The last four take the same ``{base}`` / ``{venv}`` / ``{app_dir}`` /
        ``{remote_base}`` / ``{name}`` / ``{port}`` placeholders as *env*.
        Unlike *env*, a ``%`` in them is written as-is, so systemd specifiers
        (``%t``, ``%n``) work there; write ``%%`` for a literal one.
    """

    name: str
    tools: list[str]
    auth: Any = "enlace"
    title: str | None = None
    route: str | None = None
    extras: list[str] = field(default_factory=list)
    git_installs: list[str] = field(default_factory=list)
    port: int = 8030
    data: list[tuple[str, str]] = field(default_factory=list)
    env: dict[str, str] = field(default_factory=dict)
    allowed_users: list[str] = field(default_factory=list)
    post_install: list[str] = field(default_factory=list)
    stateless_http: bool = True
    version: str | None = None
    usage_outcome: str | None = None
    app_dir: str | None = None
    environment_files: list[str] = field(default_factory=list)
    exec_start_pre: list[str] = field(default_factory=list)
    uvicorn_args: list[str] = field(default_factory=list)
    service_directives: list[tuple[str, str]] = field(default_factory=list)

    @property
    def dir_name(self) -> str:
        """The directory name under ``apps/`` and ``connectors/`` (see *app_dir*)."""
        return self.app_dir or self.name

    @property
    def server_name(self) -> str:
        return self.title or self.name

    @property
    def mount_route(self) -> str:
        """The route, spelled one way: one leading ``/``, no trailing ``/``.

        ``"/x/"`` and ``"x"`` both mean ``"/x"``. Everything that names the connector
        (its token audience, its allowlist key, its ``app.toml`` route) derives from
        this, so a stray slash cannot make two of them disagree (#10).
        """
        if not self.route:
            return f"/{self.name}-mcp"
        return "/" + self.route.strip("/")

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
    settings: Mapping[str, str] | None = None,
    middleware: Any = None,
):
    """Build the Streamable-HTTP ASGI app for *spec* (the hosted connector).

    Resolves the spec's ``auth`` into a py2mcp resource-server config. For
    ``auth="enlace"`` provide *issuer* (the platform origin) and *audience* (this
    connector's public URL); if *audience* is omitted it is derived from *issuer* +
    the spec's route. Returns an ASGI app to run under any ASGI server (or mount in
    enlace).

    Per-call usage logging is attached when the host's *settings* (``os.environ``
    by default) set ``CONNECTOR_USAGE_LOG_DIR`` — see :mod:`enlace_connector.usage`;
    it is off otherwise; the spec's ``version`` and ``usage_outcome`` feed it. Any
    extra *middleware* (one or an ordered iterable) runs before it, so a gate (e.g.
    ``enlace_metering``) refuses a call before it is logged as usage. Do not add a
    second ``usage_middleware(...)`` there: every call would be recorded twice.
    """
    if audience is None and issuer is not None:
        audience = spec.default_audience(issuer)
    auth = resolve_auth(spec.auth, issuer=issuer, audience=audience)

    from py2mcp import mk_http_app
    from py2mcp.base import normalize_middleware

    from .usage import usage_middleware

    if isinstance(middleware, (set, frozenset)):
        raise TypeError(
            "middleware must be ordered (a list/tuple), not a set: a gate has to "
            "run before the usage logger, and a set loses that order."
        )
    extra = normalize_middleware(middleware) or []
    stack = extra + usage_middleware(spec, settings=settings)
    return mk_http_app(
        spec.tools,
        name=spec.server_name,
        auth=auth,
        stateless_http=spec.stateless_http,
        middleware=stack or None,
    )

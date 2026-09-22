# enlace_connector.connector

Define a connector once, run it anywhere — stdio (local) or HTTP (hosted).

A [`ConnectorSpec`](#enlace_connector.connector.ConnectorSpec) is the single declaration of a connector: the Python tool
functions to expose, the auth strategy, the public route, and the pip extras its
runtime venv needs. The factories turn that one spec into the artifacts each host
wants:

- [`make_stdio_server()`](#enlace_connector.connector.make_stdio_server) — a FastMCP server for Claude Desktop / Claude Code while
  developing (no auth).
- [`make_connector_app()`](#enlace_connector.connector.make_connector_app) — the Streamable-HTTP ASGI app an enlace platform mounts
  (or a standalone ASGI server runs) — with auth resolved from the spec.

Tools are given as `"module:function"` reference strings (py2mcp’s form), so the
spec is import-light and serializable — the heavy tool modules load only in the
process that actually serves them.

### Functions

| [`make_stdio_server`](#enlace_connector.connector.make_stdio_server)(spec)                          | Build a FastMCP server for *spec*, for local stdio serving (no auth).   |
|---------------------------------------------------------------------------------------------------|-------------------------------------------------------------------------|
| [`make_connector_app`](#enlace_connector.connector.make_connector_app)(spec, \*[, issuer, audience]) | Build the Streamable-HTTP ASGI app for *spec* (the hosted connector).   |

### Classes

| [`ConnectorSpec`](#enlace_connector.connector.ConnectorSpec)(name, tools[, auth, title, ...])   | A declarative connector definition (see the module docstring).   |
|---------------------------------------------------------------------------------------------------|------------------------------------------------------------------|

### *class* enlace_connector.connector.ConnectorSpec(name, tools, auth='enlace', title=None, route=None, extras=<factory>, git_installs=<factory>, port=8030, data=<factory>, env=<factory>, allowed_users=<factory>, post_install=<factory>, stateless_http=True)

Bases: [`object`](https://docs.python.org/3/builtins/functions.html#object)

A declarative connector definition (see the module docstring).

#### name

short identifier — the enlace app name and default route stem.

#### tools

`"module:function"` refs exposed as MCP tools.

#### auth

`"enlace"` / `"none"` / an auth dict (e.g. from `idp_resource`).
Defaults to `"enlace"` — the platform’s own OAuth server.

#### title

human-facing MCP server name (defaults to *name*).

#### route

enlace mount route (defaults to `"/{name}-mcp"`).

#### extras

PyPI requirements the connector’s own runtime venv needs (e.g. the
package owning the tools + its embedder deps).

#### git_installs

non-PyPI deps as pip specs (e.g.
`"git+ssh://git@github.com/org/pkg"`) for private/unreleased packages.

#### port

the fixed local port the connector process binds; enlace reverse-
proxies the route to `127.0.0.1:{port}`. Must be free on the box.

#### data

`(local_path, remote_path)` pairs to co-locate on the server —
large artifacts (corpus stores, model caches) shipped *separately* from
code (rsynced), the deploy runbook lists the copy step.

#### env

environment variables the connector’s systemd unit sets (e.g.
`XDG_DATA_HOME` / `HF_HOME` pointing at the `data` dirs).

#### allowed_users

emails permitted to authorize this connector — becomes the
platform’s `[auth.oauth_server.resource_allowlist]` entry. Empty =
open to any authenticated platform user.

#### post_install

shell commands run *inside the connector venv* after deps
install (e.g. pre-warming an embedding model so the first query
doesn’t block). `{venv}` / `{base}` placeholders are substituted.

#### stateless_http

run the MCP transport statelessly (recommended behind a
multi-worker server / load balancer). Defaults to True.

#### default_audience(platform_origin)

This connector’s public URL under *platform_origin* (the token audience).

* **Return type:**
  [`str`](https://docs.python.org/3/builtins/stdtypes.html#str)

### enlace_connector.connector.make_connector_app(spec, , issuer=None, audience=None)

Build the Streamable-HTTP ASGI app for *spec* (the hosted connector).

Resolves the spec’s `auth` into a py2mcp resource-server config. For
`auth="enlace"` provide *issuer* (the platform origin) and *audience* (this
connector’s public URL); if *audience* is omitted it is derived from *issuer* +
the spec’s route. Returns an ASGI app to run under any ASGI server (or mount in
enlace).

### enlace_connector.connector.make_stdio_server(spec)

Build a FastMCP server for *spec*, for local stdio serving (no auth).

Use for `server.run()` in Claude Desktop / Claude Code while developing the
tools; the hosted path uses [`make_connector_app()`](#enlace_connector.connector.make_connector_app).

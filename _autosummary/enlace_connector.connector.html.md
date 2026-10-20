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

## Serving order

This is the one place the order is written down; every other docstring points here.
[`make_connector_app()`](#enlace_connector.connector.make_connector_app) builds a connector in these steps:

1. **Server.** The FastMCP server is built from the spec’s `tools`, `icon` and
   `instructions`, with the middleware stack of step 3.
2. **Server hooks.** Each `server_hooks` ref is called as `hook(server)`, in
   order. A hook may add tools, and it may **return** middleware (one, or a
   list or tuple of them): that middleware is the builder’s own (an
   authorization gate bound to a project) and goes to the front of the stack. Any
   other return value (`None`, the tool `server.tool` gave back) adds none; a
   list or tuple holding anything but middleware is refused.
3. **Middleware**, outermost (runs first on a call) to innermost:
   1. what the server hooks returned, in hook order (authorization);
   2. the host’s `middleware=` argument to [`make_connector_app()`](#enlace_connector.connector.make_connector_app);
   3. the spec’s `middleware` refs, in order (e.g. a metering gate);
   4. the usage logger, when the host switched it on ([`usage`](enlace_connector.usage.html.md#module-enlace_connector.usage)).

   So a call is authorized before it is metered, and metered before it is logged
   as usage: a refused call is never counted or logged. Middleware a hook adds
   itself with `server.add_middleware` lands after all of these.
4. **ASGI app.** `server.http_app(...)` gives the Starlette app; its lifespan
   runs FastMCP’s session manager.
5. **App wrappers.** Each `app_wrappers` ref is called as
   `wrapper(app, server) -> app`, in order, each on the previous one’s result
   (an extra mount, CORS, …). A wrapper with startup/shutdown work of its own
   chains it onto the app’s lifespan with [`chain_lifespan()`](#enlace_connector.connector.chain_lifespan), never in place
   of it: replacing it stops the session manager and the MCP endpoint fails.
   A route a wrapper mounts is **not** behind the connector’s OAuth (that guards
   the MCP route only) nor its middleware (that sees MCP calls only): it does its
   own authorization, e.g. by checking a signature on a signed download link.

[`make_stdio_server()`](#enlace_connector.connector.make_stdio_server) runs steps 1 and 2 only: there is no stack (the
middleware is the hosted path’s gating and metering) and no ASGI app, so what a
hook returns is ignored there.

### Functions

| [`make_stdio_server`](#enlace_connector.connector.make_stdio_server)(spec)                     | Build a FastMCP server for *spec*, for local stdio serving (no auth).                                                    |
|----------------------------------------------------------------------------------------------|--------------------------------------------------------------------------------------------------------------------------|
| [`make_connector_app`](#enlace_connector.connector.make_connector_app)(spec, \*[, issuer, ...]) | Build the Streamable-HTTP ASGI app for *spec* (the hosted connector).                                                    |
| [`chain_lifespan`](#enlace_connector.connector.chain_lifespan)(app, extra_lifespan)         | Run *extra_lifespan* inside *app*'s own lifespan, and return *app*.                                                      |
| [`spec_instructions`](#enlace_connector.connector.spec_instructions)(spec)                     | *spec*'s instructions, a `"module:ATTR"` ref resolved to its text.                                                       |
| [`spec_version`](#enlace_connector.connector.spec_version)(spec)                          | *spec*'s version: `version` (a `"module:ATTR"` ref resolved), else the installed version of `version_dist`, else `None`. |

### Classes

| [`ConnectorSpec`](#enlace_connector.connector.ConnectorSpec)(name, tools[, auth, title, ...])   | A declarative connector definition (see the module docstring).   |
|---------------------------------------------------------------------------------------------------|------------------------------------------------------------------|

### *class* enlace_connector.connector.ConnectorSpec(name, tools, auth='enlace', title=None, route=None, extras=list(), git_installs=list(), port=8030, data=list(), env=dict(), allowed_users=list(), post_install=list(), stateless_http=True, version=None, version_dist=None, usage_outcome=None, app_dir=None, environment_files=list(), exec_start_pre=list(), uvicorn_args=list(), service_directives=list(), icon=None, instructions=None, middleware=list(), server_hooks=list(), app_wrappers=list())

Bases: [`object`](https://docs.python.org/3/builtins/functions.html#object)

A declarative connector definition (see the module docstring).

#### name

short identifier — the enlace app name and default route stem.

* **Type:**
  [`str`](https://docs.python.org/3/builtins/stdtypes.html#str)

#### tools

`"module:function"` refs exposed as MCP tools.

* **Type:**
  [`list`](https://docs.python.org/3/builtins/stdtypes.html#list)[[`str`](https://docs.python.org/3/builtins/stdtypes.html#str)]

#### auth

`"enlace"` / `"none"` / an auth dict (e.g. from `idp_resource`).
Defaults to `"enlace"` — the platform’s own OAuth server.

* **Type:**
  [`Any`](https://docs.python.org/3/library/typing.html#typing.Any)

#### title

human-facing MCP server name (defaults to *name*).

* **Type:**
  [`str`](https://docs.python.org/3/builtins/stdtypes.html#str) | [`None`](https://docs.python.org/3/builtins/constants.html#None)

#### route

enlace mount route (defaults to `"/{name}-mcp"`).

* **Type:**
  [`str`](https://docs.python.org/3/builtins/stdtypes.html#str) | [`None`](https://docs.python.org/3/builtins/constants.html#None)

#### extras

PyPI requirements the connector’s own runtime venv needs (e.g. the
package owning the tools + its embedder deps).

* **Type:**
  [`list`](https://docs.python.org/3/builtins/stdtypes.html#list)[[`str`](https://docs.python.org/3/builtins/stdtypes.html#str)]

#### git_installs

non-PyPI deps as pip specs (e.g.
`"git+ssh://git@github.com/org/pkg"`) for private/unreleased packages.

* **Type:**
  [`list`](https://docs.python.org/3/builtins/stdtypes.html#list)[[`str`](https://docs.python.org/3/builtins/stdtypes.html#str)]

#### port

the fixed local port the connector process binds; enlace reverse-
proxies the route to `127.0.0.1:{port}`. Must be free on the box.

* **Type:**
  [`int`](https://docs.python.org/3/builtins/functions.html#int)

#### data

`(local_path, remote_path)` pairs to co-locate on the server —
large artifacts (corpus stores, model caches) shipped *separately* from
code (rsynced), the deploy runbook lists the copy step.

* **Type:**
  [`list`](https://docs.python.org/3/builtins/stdtypes.html#list)[[`tuple`](https://docs.python.org/3/builtins/stdtypes.html#tuple)[[`str`](https://docs.python.org/3/builtins/stdtypes.html#str), [`str`](https://docs.python.org/3/builtins/stdtypes.html#str)]]

#### env

environment variables the connector’s systemd unit sets (e.g.
`XDG_DATA_HOME` / `HF_HOME` pointing at the `data` dirs).

* **Type:**
  [`dict`](https://docs.python.org/3/builtins/stdtypes.html#dict)[[`str`](https://docs.python.org/3/builtins/stdtypes.html#str), [`str`](https://docs.python.org/3/builtins/stdtypes.html#str)]

#### allowed_users

emails permitted to authorize this connector — becomes the
platform’s `[auth.oauth_server.resource_allowlist]` entry. Required
for a deploy bundle: enlace_auth refuses every account for a resource
it does not list (fail closed, since enlace_auth 0.1.30), so an empty
list is an error, never “open”. `["*"]` (`deploy.ANY_ACCOUNT`)
admits every authenticated platform account, and must be written out.

* **Type:**
  [`list`](https://docs.python.org/3/builtins/stdtypes.html#list)[[`str`](https://docs.python.org/3/builtins/stdtypes.html#str)]

#### post_install

shell commands run *inside the connector venv* after deps
install (e.g. pre-warming an embedding model so the first query
doesn’t block). `{venv}` / `{base}` placeholders are substituted.

* **Type:**
  [`list`](https://docs.python.org/3/builtins/stdtypes.html#list)[[`str`](https://docs.python.org/3/builtins/stdtypes.html#str)]

#### stateless_http

run the MCP transport statelessly (recommended behind a
multi-worker server / load balancer). Defaults to True.

* **Type:**
  [`bool`](https://docs.python.org/3/builtins/functions.html#bool)

#### version

the connector’s version, written into every usage-log record
when logging is on (see [`enlace_connector.usage`](enlace_connector.usage.html.md#module-enlace_connector.usage)). A
`"module:ATTR"` ref (e.g. `"mypkg:__version__"`) is imported where
the connector is served, so the version is never a frozen copy.

* **Type:**
  [`str`](https://docs.python.org/3/builtins/stdtypes.html#str) | [`None`](https://docs.python.org/3/builtins/constants.html#None)

#### version_dist

the installed distribution whose version is the
connector’s (`importlib.metadata.version`), used when *version* is
not set — the seam for packages without a `__version__`.

* **Type:**
  [`str`](https://docs.python.org/3/builtins/stdtypes.html#str) | [`None`](https://docs.python.org/3/builtins/constants.html#None)

#### usage_outcome

a `"module:function"` ref to this connector’s own
`(tool_name, result) -> label | mapping` usage-outcome classifier
(e.g. one that knows the search tool’s “no match” shape), used in
place of py2mcp’s generic one when logging is on.

* **Type:**
  [`str`](https://docs.python.org/3/builtins/stdtypes.html#str) | [`None`](https://docs.python.org/3/builtins/constants.html#None)

#### app_dir

the connector’s directory name under the platform’s `apps/`
and `connectors/` (defaults to *name*). A host that names the app
`<name>_mcp` sets it so the rendered paths exist (#15).

* **Type:**
  [`str`](https://docs.python.org/3/builtins/stdtypes.html#str) | [`None`](https://docs.python.org/3/builtins/constants.html#None)

#### environment_files

`EnvironmentFile=` values for the unit, in order —
how a host scopes provider secrets into the process without writing
them into the unit. A leading `-` makes one optional, as in systemd.

* **Type:**
  [`list`](https://docs.python.org/3/builtins/stdtypes.html#list)[[`str`](https://docs.python.org/3/builtins/stdtypes.html#str)]

#### exec_start_pre

`ExecStartPre=` commands, in order (e.g. extracting the
scoped secrets an `environment_files` entry then reads).

* **Type:**
  [`list`](https://docs.python.org/3/builtins/stdtypes.html#list)[[`str`](https://docs.python.org/3/builtins/stdtypes.html#str)]

#### uvicorn_args

extra arguments appended to the `uvicorn` command line
(e.g. `--no-access-log` for a connector that serves signed links).

* **Type:**
  [`list`](https://docs.python.org/3/builtins/stdtypes.html#list)[[`str`](https://docs.python.org/3/builtins/stdtypes.html#str)]

#### service_directives

any other `(key, value)` lines for the unit’s
`[Service]` section, in order (e.g. `("RuntimeDirectory", ...)`).

* **Type:**
  [`list`](https://docs.python.org/3/builtins/stdtypes.html#list)[[`tuple`](https://docs.python.org/3/builtins/stdtypes.html#tuple)[[`str`](https://docs.python.org/3/builtins/stdtypes.html#str), [`str`](https://docs.python.org/3/builtins/stdtypes.html#str)]]

#### icon

the server icon clients show next to the connector (sent in the MCP
`serverInfo`): a `src` URL or `data:` URI, or a dict of
`mcp.types.Icon` fields (`src`, `mimeType`, `sizes`).

* **Type:**
  [`Any`](https://docs.python.org/3/library/typing.html#typing.Any)

#### instructions

the server’s model-facing description, surfaced to the
connecting client as the MCP `instructions`. A `"module:ATTR"`
ref (dotted identifiers, no spaces) names a string in the connector’s
package instead, imported where the connector is served, so the text
lives in one place and cannot drift from a copy in the spec.

* **Type:**
  [`str`](https://docs.python.org/3/builtins/stdtypes.html#str) | [`None`](https://docs.python.org/3/builtins/constants.html#None)

#### middleware

`"module:attr"` refs to extra FastMCP middleware, in order
(e.g. a metering gate). Each names a middleware, a list of them, or a
zero-argument factory returning either. Where they sit among the
other middleware: “Serving order” in this module’s docstring.

* **Type:**
  [`list`](https://docs.python.org/3/builtins/stdtypes.html#list)[[`str`](https://docs.python.org/3/builtins/stdtypes.html#str)]

#### server_hooks

`"module:function"` refs, each called with the built
FastMCP server before it is served — the seam for tools that are not
importable `"module:function"` refs (closures bound to a project, a
store, a per-caller context): `server.tool(fn)` inside the hook.
A hook may return middleware it owns (an authorization gate), which
runs before every other middleware (“Serving order”).

* **Type:**
  [`list`](https://docs.python.org/3/builtins/stdtypes.html#list)[[`str`](https://docs.python.org/3/builtins/stdtypes.html#str)]

#### app_wrappers

`"module:function"` refs, each called as
`wrapper(app, server) -> app` on the hosted ASGI app, in order —
the seam for an extra route next to the MCP endpoint (a mount for
signed downloads) and its own startup/shutdown work, which goes
through [`chain_lifespan()`](#enlace_connector.connector.chain_lifespan). Hosted path only. A mounted route
is outside the connector’s OAuth and middleware (“Serving order”).

* **Type:**
  [`list`](https://docs.python.org/3/builtins/stdtypes.html#list)[[`str`](https://docs.python.org/3/builtins/stdtypes.html#str)]

### The last four take the same \`\`{base}\`\` / \`\`{venv}\`\` / \`\`{app_dir}\`\` /

### \`\`{remote_base}\`\` / \`\`{name}\`\` / \`\`{port}\`\` placeholders as \*env\*.

### Unlike \*env\*, a \`\`%\`\` in them is written as-is, so systemd specifiers

### (\`\`%t\`\`, \`\`%n\`\`) work there; write \`\`%%\`\` for a literal one.

#### default_audience(platform_origin)

This connector’s public URL under *platform_origin* (the token audience).

* **Return type:**
  [`str`](https://docs.python.org/3/builtins/stdtypes.html#str)

#### *property* dir_name *: [str](https://docs.python.org/3/builtins/stdtypes.html#str)*

The directory name under `apps/` and `connectors/` (see *app_dir*).

#### *property* mount_route *: [str](https://docs.python.org/3/builtins/stdtypes.html#str)*

one leading `/`, no trailing `/`.

`"/x/"` and `"x"` both mean `"/x"`. Everything that names the connector
(its token audience, its allowlist key, its `app.toml` route) derives from
this, so a stray slash cannot make two of them disagree (#10).

* **Type:**
  The route, spelled one way

### enlace_connector.connector.chain_lifespan(app, extra_lifespan)

Run *extra_lifespan* inside *app*’s own lifespan, and return *app*.

*app* is a Starlette app (what `server.http_app(...)` returns); its own
lifespan runs FastMCP’s session manager, so an app wrapper that needs
startup/shutdown work must add to it, not replace it (see “Serving order” in
the module docstring). *extra_lifespan* is a Starlette lifespan: a callable
taking the app and returning an async context manager (an
`@asynccontextmanager` function), or an async generator function taking the
app, as Starlette’s `lifespan=` accepts. It starts after the app’s own
lifespan and stops before it, so the MCP endpoint is up for as long as the
extra work is. If either yields a state mapping, the two are merged (the
extra one wins on a shared key) into the request `scope["state"]`; that
needs an ASGI server with lifespan state (uvicorn has it).

```pycon
>>> from contextlib import asynccontextmanager
>>> from starlette.applications import Starlette
>>> @asynccontextmanager
... async def downloads(app):
...     yield {"signer": "ready"}
>>> app = chain_lifespan(Starlette(), downloads)
```

* **Return type:**
  [`Any`](https://docs.python.org/3/library/typing.html#typing.Any)

### enlace_connector.connector.make_connector_app(spec, , issuer=None, audience=None, settings=None, middleware=None)

Build the Streamable-HTTP ASGI app for *spec* (the hosted connector).

Resolves the spec’s `auth` into a py2mcp resource-server config. For
`auth="enlace"` provide *issuer* (the platform origin) and *audience* (this
connector’s public URL); if *audience* is omitted it is derived from *issuer* +
the spec’s route. Returns an ASGI app to run under any ASGI server (or mount in
enlace). The spec’s `icon`, `instructions`, `middleware`,
`server_hooks` and `app_wrappers` are applied, so a connector that needs
them is still built here rather than by hand (#3, #22). The order they are
applied in is “Serving order” in the module docstring.

Per-call usage logging is attached when the host’s *settings* (`os.environ`
by default) set `CONNECTOR_USAGE_LOG_DIR` — see [`enlace_connector.usage`](enlace_connector.usage.html.md#module-enlace_connector.usage);
it is off otherwise; the spec’s `version` and `usage_outcome` feed it. Any
extra *middleware* (one or an ordered iterable) runs before the spec’s and the
logger, so a gate (e.g. `enlace_metering`) refuses a call before it is logged
as usage. Do not add a second `usage_middleware(...)` there: every call would
be recorded twice.

### enlace_connector.connector.make_stdio_server(spec)

Build a FastMCP server for *spec*, for local stdio serving (no auth).

Use for `server.run()` in Claude Desktop / Claude Code while developing the
tools; the hosted path uses [`make_connector_app()`](#enlace_connector.connector.make_connector_app). The spec’s `icon`,
`instructions` and `server_hooks` apply; its `middleware`, the
middleware its hooks return, and its `app_wrappers` do not (they are the
hosted path’s gating, metering and routes; see “Serving order” in the module
docstring).

### enlace_connector.connector.spec_instructions(spec)

*spec*’s instructions, a `"module:ATTR"` ref resolved to its text.

```pycon
>>> spec_instructions(ConnectorSpec(name="x", tools=[], instructions="Use me."))
'Use me.'
>>> spec_instructions(ConnectorSpec(name="x", tools=[],
...                                 instructions="string:ascii_lowercase"))[:3]
'abc'
```

* **Return type:**
  [`str`](https://docs.python.org/3/builtins/stdtypes.html#str) | [`None`](https://docs.python.org/3/builtins/constants.html#None)

### enlace_connector.connector.spec_version(spec)

*spec*’s version: `version` (a `"module:ATTR"` ref resolved), else the
installed version of `version_dist`, else `None`. The version is only a
label in the usage log, so a ref that does not import is kept as written and
an uninstalled `version_dist` gives `None`, each with a warning, rather
than stopping the connector at boot.

```pycon
>>> spec_version(ConnectorSpec(name="x", tools=[], version="1.2.0"))
'1.2.0'
>>> spec_version(ConnectorSpec(name="x", tools=[], version_dist="pytest")) > "0"
True
```

* **Return type:**
  [`str`](https://docs.python.org/3/builtins/stdtypes.html#str) | [`None`](https://docs.python.org/3/builtins/constants.html#None)

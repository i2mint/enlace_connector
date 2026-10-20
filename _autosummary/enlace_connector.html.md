# enlace_connector

`enlace_connector` — deploy Python functions as authenticated MCP connectors.

A Claude.ai “custom connector” is a remote MCP server. This package turns a set of
Python functions into one — wired for the [enlace](https://github.com/i2mint/enlace)
platform and its [enlace_auth](https://github.com/i2mint/enlace_auth) OAuth server,
built on [py2mcp](https://github.com/thorwhalen/py2mcp).

Declare a connector once:

```default
from enlace_connector import ConnectorSpec, make_connector_app

spec = ConnectorSpec(
    name="trufflepig",
    tools=["truffle.mcp:search_trufflepig", "truffle.mcp:search_wallow"],
    auth="enlace",                 # validate the platform's enlace_auth tokens
    extras=["truffle"],            # what the connector's runtime venv needs
)
```

…then run it where you need it:

- `make_stdio_server(spec)` → a FastMCP server for Claude Desktop / Claude Code.
- `make_connector_app(spec, issuer=...)` → the Streamable-HTTP ASGI app a host runs.
- `scaffold_app(spec, dest)` → an enlace `mode="process"` app dir (`app.toml` +
  `server.py`) so a heavy connector runs in its own venv, reverse-proxied by enlace.

Per-call usage logging (who called which tool, with what, and what came back) is
off unless the host sets `CONNECTOR_USAGE_LOG_DIR` (see `enlace_connector.usage`).

The authorization server is pluggable (`auth="enlace"` for the platform’s own
`enlace_auth`; `idp_resource(...)` for Auth0/WorkOS/…; `None` for an
unauthenticated local/pilot run) — the resource-server validation is identical
regardless of who issues the token.

Whichever one you point at, **verify it before calling a deployment good**:

```default
from enlace_connector import verify_deployment, format_report
print(format_report(verify_deployment(spec, issuer="https://apps.example.com")))
```

An authorization server that cannot issue refresh tokens strands every connector
session at its first access-token expiry while the connector process goes on
looking perfectly healthy — [`enlace_connector.preflight`](enlace_connector.preflight.html.md#module-enlace_connector.preflight) is what catches that
in seconds instead of when a user complains a day later.

### Functions

| [`make_connector_app`](#enlace_connector.make_connector_app)(spec, \*[, issuer, ...])        | Build the Streamable-HTTP ASGI app for *spec* (the hosted connector).                                                    |
|-----------------------------------------------------------------------------------------------------|--------------------------------------------------------------------------------------------------------------------------|
| [`make_stdio_server`](#enlace_connector.make_stdio_server)(spec)                            | Build a FastMCP server for *spec*, for local stdio serving (no auth).                                                    |
| [`resolve_auth`](#enlace_connector.resolve_auth)(auth, \*[, issuer, audience])         | Normalize an `auth` spec to a py2mcp auth dict (or `None` for no auth).                                                  |
| [`enlace_resource`](#enlace_connector.enlace_resource)(\*, issuer, audience[, ...])       | Resource-server config validating tokens from the platform's `enlace_auth` AS.                                           |
| [`idp_resource`](#enlace_connector.idp_resource)(\*, jwks_uri, issuer, audience)       | Resource-server config validating tokens from an external managed IdP.                                                   |
| [`scaffold_app`](#enlace_connector.scaffold_app)(spec, dest_dir, \*, port[, command])  | Write `app.toml` and `server.py` for *spec* into *dest_dir*.                                                             |
| [`generate_deploy_bundle`](#enlace_connector.generate_deploy_bundle)(spec, dest, \*[, ...])      | Write the full deploy bundle for *spec* under *dest*.                                                                    |
| [`render_systemd_unit`](#enlace_connector.render_systemd_unit)(spec, \*[, remote_base, ...])  | Render the systemd unit that runs the connector in its own venv.                                                         |
| [`diff_unit`](#enlace_connector.diff_unit)(spec, installed, \*[, remote_base, ...]) | How the *installed* unit text differs from what *spec* renders; `[]` if not.                                             |
| [`check_distinct_ports`](#enlace_connector.check_distinct_ports)(specs)                        | Refuse *specs* that would bind the same local port.                                                                      |
| [`check_distinct_specs`](#enlace_connector.check_distinct_specs)(specs)                        | Refuse *specs* that would collide on one host: same port, unit or directory.                                             |
| [`render_provision_script`](#enlace_connector.render_provision_script)(spec, \*[, remote_base])   | Render the idempotent, run-as-root provisioning script for the connector.                                                |
| [`render_allowlist_toml`](#enlace_connector.render_allowlist_toml)(spec, \*[, issuer])          | Render the `[auth.oauth_server.resource_allowlist]` fragment.                                                            |
| [`allowlist_users`](#enlace_connector.allowlist_users)(spec)                              | `spec.allowed_users`, refused when it cannot mean what it seems to.                                                      |
| [`render_display_names_toml`](#enlace_connector.render_display_names_toml)(spec, \*[, issuer])      | Render the `[auth.oauth_server.resource_display_names]` fragment.                                                        |
| [`render_oauth_server_toml`](#enlace_connector.render_oauth_server_toml)(spec, \*[, issuer, ...])  | Render the `[auth.oauth_server]` fragment that keeps sessions alive.                                                     |
| [`render_runbook`](#enlace_connector.render_runbook)(spec, \*[, remote_base, issuer])    | Render the human deploy checklist (ship, provision, deploy, **verify**).                                                 |
| [`resource_url`](#enlace_connector.resource_url)(spec, \*[, issuer])                   | The connector's OAuth resource = its public MCP endpoint (`route + /mcp`).                                               |
| [`render_app_toml`](#enlace_connector.render_app_toml)(spec, \*, port[, command])         | Render the enlace `app.toml` for *spec* as a `mode="process"` app.                                                       |
| [`render_server_py`](#enlace_connector.render_server_py)(spec)                             | Render the `server.py` that exposes `app` for enlace's process runner.                                                   |
| [`usage_middleware`](#enlace_connector.usage_middleware)(spec, \*[, settings, version])    | The usage-logging middleware for *spec*, or `[]` when it is switched off.                                                |
| [`verify_deployment`](#enlace_connector.verify_deployment)([spec, checks, fetch, strict])   | Run the preflight checks against *issuer*; return one result per check.                                                  |
| [`check_refresh_grant_supported`](#enlace_connector.check_refresh_grant_supported)(ctx)                 | THE check: does the AS advertise `refresh_token` in `grant_types_supported`?                                             |
| [`check_jwks_uri_matches_convention`](#enlace_connector.check_jwks_uri_matches_convention)(ctx)             | For `auth="enlace"` connectors: the AS's `jwks_uri` is the one we validate against.                                      |
| [`authorization_server_metadata`](#enlace_connector.authorization_server_metadata)(issuer, \*[, fetch]) | Fetch the RFC 8414 discovery document advertised by *issuer*.                                                            |
| [`format_report`](#enlace_connector.format_report)(results)                             | Render check results as a human-readable report (used by the CLI and errors).                                            |
| [`spec_instructions`](#enlace_connector.spec_instructions)(spec)                            | *spec*'s instructions, a `"module:ATTR"` ref resolved to its text.                                                       |
| [`spec_version`](#enlace_connector.spec_version)(spec)                                 | *spec*'s version: `version` (a `"module:ATTR"` ref resolved), else the installed version of `version_dist`, else `None`. |

### Classes

| [`ConnectorSpec`](#enlace_connector.ConnectorSpec)(name, tools[, auth, title, ...])   | A declarative connector definition (see the module docstring).               |
|---------------------------------------------------------------------------------------------------|------------------------------------------------------------------------------|
| [`CheckResult`](#enlace_connector.CheckResult)(name, ok, summary[, remedy])         | Outcome of one preflight check.                                              |
| [`PreflightContext`](#enlace_connector.PreflightContext)(issuer[, spec, fetch])          | What a check is given: the target AS, the connector (if any), and a fetcher. |

### Exceptions

| [`PreflightError`](#enlace_connector.PreflightError)   | Raised by [`verify_deployment()`](#enlace_connector.verify_deployment) in `strict` mode when a check fails.   |
|-------------------------------------------------------------------|-----------------------------------------------------------------------------------------------------------------------|

### *class* enlace_connector.CheckResult(name, ok, summary, remedy='')

Bases: [`object`](https://docs.python.org/3/builtins/functions.html#object)

Outcome of one preflight check.

Truthy when the check passed, so `all(results)` reads naturally.

#### name

stable slug for the check (usable as a CI job/report key).

* **Type:**
  [`str`](https://docs.python.org/3/builtins/stdtypes.html#str)

#### ok

whether the checked property holds.

* **Type:**
  [`bool`](https://docs.python.org/3/builtins/functions.html#bool)

#### summary

one line stating what was (or was not) observed.

* **Type:**
  [`str`](https://docs.python.org/3/builtins/stdtypes.html#str)

#### remedy

what to do about it — empty when `ok`.

* **Type:**
  [`str`](https://docs.python.org/3/builtins/stdtypes.html#str)

### *class* enlace_connector.ConnectorSpec(name, tools, auth='enlace', title=None, route=None, extras=list(), git_installs=list(), port=8030, data=list(), env=dict(), allowed_users=list(), post_install=list(), stateless_http=True, version=None, version_dist=None, usage_outcome=None, app_dir=None, environment_files=list(), exec_start_pre=list(), uvicorn_args=list(), service_directives=list(), icon=None, instructions=None, middleware=list(), server_hooks=list())

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
zero-argument factory returning either; they run before the usage
logger. A host can also pass `middleware=` to
[`make_connector_app()`](#enlace_connector.make_connector_app); that runs first.

* **Type:**
  [`list`](https://docs.python.org/3/builtins/stdtypes.html#list)[[`str`](https://docs.python.org/3/builtins/stdtypes.html#str)]

#### server_hooks

`"module:function"` refs, each called with the built
FastMCP server before it is served — the seam for tools that are not
importable `"module:function"` refs (closures bound to a project, a
store, a per-caller context): `server.tool(fn)` inside the hook.

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

### *class* enlace_connector.PreflightContext(issuer, spec=None, fetch=None)

Bases: [`object`](https://docs.python.org/3/builtins/functions.html#object)

What a check is given: the target AS, the connector (if any), and a fetcher.

#### issuer

the authorization server’s issuer origin (the platform origin).

* **Type:**
  [`str`](https://docs.python.org/3/builtins/stdtypes.html#str)

#### spec

the connector being verified — optional, so the AS itself can be
preflighted before any connector exists.

* **Type:**
  [`ConnectorSpec`](enlace_connector.connector.html.md#enlace_connector.connector.ConnectorSpec) | [`None`](https://docs.python.org/3/builtins/constants.html#None)

#### fetch

`fetch(url) -> parsed_json`; defaults to `fetch_json()`. Pass
your own to test offline, to add auth headers, or to use `httpx`.

* **Type:**
  [`Optional`](https://docs.python.org/3/library/typing.html#typing.Optional)[[`Callable`](https://docs.python.org/3/library/typing.html#typing.Callable)[[[`str`](https://docs.python.org/3/builtins/stdtypes.html#str)], [`Any`](https://docs.python.org/3/library/typing.html#typing.Any)]]

#### *property* metadata *: [dict](https://docs.python.org/3/builtins/stdtypes.html#dict)[[str](https://docs.python.org/3/builtins/stdtypes.html#str), [Any](https://docs.python.org/3/library/typing.html#typing.Any)]*

The AS discovery document (fetched once per context, checked to be a doc).

#### *property* metadata_url *: [str](https://docs.python.org/3/builtins/stdtypes.html#str)*

Where the AS discovery document lives.

### *exception* enlace_connector.PreflightError

Bases: [`RuntimeError`](https://docs.python.org/3/builtins/exceptions.html#RuntimeError)

Raised by [`verify_deployment()`](#enlace_connector.verify_deployment) in `strict` mode when a check fails.

### enlace_connector.allowlist_users(spec)

`spec.allowed_users`, refused when it cannot mean what it seems to.

enlace_auth fails closed: a resource missing from
`[auth.oauth_server.resource_allowlist]` is refused to everyone
(i2mint/enlace_auth#34). So an empty list no longer means “open”. It
would deploy a connector that nobody can authorize, and nothing would
error until someone tried (#8). Opening a connector to every account is
an explicit `["*"]`.

```pycon
>>> from enlace_connector import ConnectorSpec
>>> allowlist_users(ConnectorSpec(name="x", tools=["m:f"], allowed_users=["*"]))
['*']
>>> allowlist_users(ConnectorSpec(name="x", tools=["m:f"]))
Traceback (most recent call last):
...
ValueError: Connector 'x' has no allowed_users...
```

* **Return type:**
  [`list`](https://docs.python.org/3/builtins/stdtypes.html#list)[[`str`](https://docs.python.org/3/builtins/stdtypes.html#str)]

### enlace_connector.authorization_server_metadata(issuer, , fetch=None)

Fetch the RFC 8414 discovery document advertised by *issuer*.

* **Return type:**
  [`dict`](https://docs.python.org/3/builtins/stdtypes.html#dict)[[`str`](https://docs.python.org/3/builtins/stdtypes.html#str), [`Any`](https://docs.python.org/3/library/typing.html#typing.Any)]

### enlace_connector.check_distinct_ports(specs)

Refuse *specs* that would bind the same local port.

`port` has a default, so two specs that both omit it render units that
collide on one box, and the second connector never starts (#15). Prefer
[`check_distinct_specs()`](#enlace_connector.check_distinct_specs), which also checks unit names and directories.

```pycon
>>> check_distinct_ports([ConnectorSpec(name="a", tools=[], port=8031),
...                       ConnectorSpec(name="b", tools=[], port=8032)])
>>> check_distinct_ports([ConnectorSpec(name="a", tools=[]),
...                       ConnectorSpec(name="b", tools=[])])
Traceback (most recent call last):
  ...
ValueError: connectors share a port: 8030 (a, b)
```

* **Return type:**
  [`None`](https://docs.python.org/3/builtins/constants.html#None)

### enlace_connector.check_distinct_specs(specs)

Refuse *specs* that would collide on one host: same port, unit or directory.

Run it over every connector a host deploys. Two specs collide when they bind
the same `port` (it has a default), share a `name` (one
`<name>-mcp.service`, one resource URL), or share a directory under
`apps/` and `connectors/` (`app_dir`, else `name`): the second
install would overwrite the first (#18). Every clash is listed in one error.

```pycon
>>> check_distinct_specs([ConnectorSpec(name="a", tools=[], port=8031),
...                       ConnectorSpec(name="b", tools=[], port=8032)])
>>> check_distinct_specs([ConnectorSpec(name="a", tools=[], port=8031),
...                       ConnectorSpec(name="b", tools=[], port=8032, app_dir="a")])
Traceback (most recent call last):
  ...
ValueError: connectors share a directory: a (a, b)
```

* **Return type:**
  [`None`](https://docs.python.org/3/builtins/constants.html#None)

### enlace_connector.check_jwks_uri_matches_convention(ctx)

For `auth="enlace"` connectors: the AS’s `jwks_uri` is the one we validate against.

Catches an issuer/route drift that would make every token fail signature
validation — a different symptom of “deployed, healthy, unusable”.

* **Return type:**
  [`CheckResult`](enlace_connector.preflight.html.md#enlace_connector.preflight.CheckResult)

### enlace_connector.check_refresh_grant_supported(ctx)

THE check: does the AS advertise `refresh_token` in `grant_types_supported`?

An authorization server that omits it can only ever hand out access tokens that
expire into a dead end, which is invisible from the connector’s own health.

* **Return type:**
  [`CheckResult`](enlace_connector.preflight.html.md#enlace_connector.preflight.CheckResult)

### enlace_connector.diff_unit(spec, installed, , remote_base='/opt/tw_platform', issuer='https://apps.thorwhalen.com', ignore=frozenset({('Unit', 'Description')}))

How the *installed* unit text differs from what *spec* renders; `[]` if not.

For a host that keeps its own unit files: run it per connector at deploy time
and report the lines, so a unit and its spec cannot drift apart unnoticed
(#15). The comparison is semantic: comments, blank lines, line order across
directives, whitespace runs and `Environment=` quoting do not count; the
order of repeated directives (`ExecStartPre=`) does. *ignore* is a set of
`(section, key)` pairs left out (the `Description=` prose, by default).
Drop-ins (`<unit>.d/*.conf`) are not read: pass the main unit file.

```pycon
>>> spec = ConnectorSpec(name="x", tools=[], port=8040)
>>> diff_unit(spec, render_systemd_unit(spec))
[]
>>> diff_unit(spec, render_systemd_unit(spec).replace("8040", "8041"))[0][:21]
'[Service] ExecStart: '
```

* **Return type:**
  [`list`](https://docs.python.org/3/builtins/stdtypes.html#list)[[`str`](https://docs.python.org/3/builtins/stdtypes.html#str)]

### enlace_connector.enlace_resource(, issuer, audience, scopes=('mcp:read',), mcp_path='/mcp')

Resource-server config validating tokens from the platform’s `enlace_auth` AS.

* **Parameters:**
  * **issuer** ([`str`](https://docs.python.org/3/builtins/stdtypes.html#str)) – the platform origin acting as the OAuth issuer, e.g.
    `"https://apps.thorwhalen.com"` (no trailing slash needed).
  * **audience** ([`str`](https://docs.python.org/3/builtins/stdtypes.html#str)) – this connector’s **base** URL (e.g.
    `"https://apps.thorwhalen.com/api/trufflepig_mcp"`).
  * **scopes** ([`Iterable`](https://docs.python.org/3/library/typing.html#typing.Iterable)[[`str`](https://docs.python.org/3/builtins/stdtypes.html#str)]) – scopes the connector requires (default `DFLT_SCOPES`).
  * **mcp_path** ([`str`](https://docs.python.org/3/builtins/stdtypes.html#str)) – the MCP transport sub-path (FastMCP default `/mcp`).
* **Return type:**
  [`dict`](https://docs.python.org/3/builtins/stdtypes.html#dict)[[`str`](https://docs.python.org/3/builtins/stdtypes.html#str), [`Any`](https://docs.python.org/3/library/typing.html#typing.Any)]

The OAuth *resource* a connector validates is its MCP **endpoint**
(`base + mcp_path`) — that is what FastMCP advertises in the RFC 9728
protected-resource metadata, and therefore what the issued token’s `aud`
carries. So `base_url` (used to build that metadata) is the base, while the
validated `audience` is `base + mcp_path`. Setting them equal causes an
“audience mismatch” 401 at token-validation time.

### enlace_connector.format_report(results)

Render check results as a human-readable report (used by the CLI and errors).

```pycon
>>> print(format_report([CheckResult("a", True, "fine"),
...                      CheckResult("b", False, "broken", "fix it")]))
PASS  a: fine
FAIL  b: broken
      -> fix it
```

* **Return type:**
  [`str`](https://docs.python.org/3/builtins/stdtypes.html#str)

### enlace_connector.generate_deploy_bundle(spec, dest, , remote_base='/opt/tw_platform', issuer='https://apps.thorwhalen.com', server_py=None, refresh_token_ttl_seconds=2592000)

Write the full deploy bundle for *spec* under *dest*.

Writes the app dir (`app.toml` + `server.py`) and a `deploy/` folder (the
systemd unit, provisioning script, the `platform.toml` fragments — OAuth
session longevity, the display name and the resource allowlist — and the
runbook). Raises `ValueError`, writing nothing, when `allowed_users` is
empty (see [`allowlist_users()`](#enlace_connector.allowlist_users)). Pass *server_py* to override the generated entry module
(e.g. a corpus-bound `make_search` server the composing skill wrote); pass
*refresh_token_ttl_seconds* to set the session longevity the platform fragment
configures (`0` would disable the refresh grant — see
[`render_oauth_server_toml()`](#enlace_connector.render_oauth_server_toml)). Returns the written paths.

* **Return type:**
  [`dict`](https://docs.python.org/3/builtins/stdtypes.html#dict)[[`str`](https://docs.python.org/3/builtins/stdtypes.html#str), [`Path`](https://docs.python.org/3/library/pathlib.html#pathlib.Path)]

### enlace_connector.idp_resource(, jwks_uri, issuer, audience, authorization_servers=None, base_url=None, scopes=('mcp:read',))

Resource-server config validating tokens from an external managed IdP.

Everything is explicit because each IdP (Auth0, WorkOS, Okta…) publishes its
own `jwks_uri` / `issuer`. `authorization_servers` defaults to
`[issuer]` and `base_url` to `audience` (this connector’s URL).

* **Return type:**
  [`dict`](https://docs.python.org/3/builtins/stdtypes.html#dict)[[`str`](https://docs.python.org/3/builtins/stdtypes.html#str), [`Any`](https://docs.python.org/3/library/typing.html#typing.Any)]

### enlace_connector.make_connector_app(spec, , issuer=None, audience=None, settings=None, middleware=None)

Build the Streamable-HTTP ASGI app for *spec* (the hosted connector).

Resolves the spec’s `auth` into a py2mcp resource-server config. For
`auth="enlace"` provide *issuer* (the platform origin) and *audience* (this
connector’s public URL); if *audience* is omitted it is derived from *issuer* +
the spec’s route. Returns an ASGI app to run under any ASGI server (or mount in
enlace). The spec’s `icon`, `instructions`, `middleware` and
`server_hooks` are applied, so a connector that needs them is still built
here rather than by hand (#3).

Per-call usage logging is attached when the host’s *settings* (`os.environ`
by default) set `CONNECTOR_USAGE_LOG_DIR` — see [`enlace_connector.usage`](enlace_connector.usage.html.md#module-enlace_connector.usage);
it is off otherwise; the spec’s `version` and `usage_outcome` feed it. Any
extra *middleware* (one or an ordered iterable) runs before it, so a gate (e.g.
`enlace_metering`) refuses a call before it is logged as usage. Do not add a
second `usage_middleware(...)` there: every call would be recorded twice.

### enlace_connector.make_stdio_server(spec)

Build a FastMCP server for *spec*, for local stdio serving (no auth).

Use for `server.run()` in Claude Desktop / Claude Code while developing the
tools; the hosted path uses [`make_connector_app()`](#enlace_connector.make_connector_app). The spec’s `icon`,
`instructions` and `server_hooks` apply; its `middleware` does not (it
is the hosted path’s metering and gating).

### enlace_connector.render_allowlist_toml(spec, , issuer='https://apps.thorwhalen.com')

Render the `[auth.oauth_server.resource_allowlist]` fragment.

Maps this connector’s resource URL to the allowed emails (or `"*"`) —
paste into the platform’s `platform.toml`. Raises `ValueError` when
`allowed_users` is empty: see [`allowlist_users()`](#enlace_connector.allowlist_users).

* **Return type:**
  [`str`](https://docs.python.org/3/builtins/stdtypes.html#str)

### enlace_connector.render_app_toml(spec, , port, command=None)

Render the enlace `app.toml` for *spec* as a `mode="process"` app.

* **Return type:**
  [`str`](https://docs.python.org/3/builtins/stdtypes.html#str)

### enlace_connector.render_display_names_toml(spec, , issuer='https://apps.thorwhalen.com')

Render the `[auth.oauth_server.resource_display_names]` fragment.

The shared OAuth consent page (`enlace_auth`) shows *some* product name to
every user authorizing *any* connector on the platform — resolved from
`resource_display_names`, keyed by resource URL (see
[`resource_url()`](#enlace_connector.resource_url)), with a generic fallback when a resource has no entry.
Before this existed, that string had to be hand-typed once in platform
config and drifted the moment a second connector was added: every consent
screen showed the *first* connector’s name (i2mint/enlace_auth#18).

This makes [`ConnectorSpec.title`](#enlace_connector.ConnectorSpec.title) the single source instead — paste the
fragment into the platform’s `platform.toml` alongside
[`render_allowlist_toml()`](#enlace_connector.render_allowlist_toml)’s.

```pycon
>>> from enlace_connector import ConnectorSpec
>>> spec = ConnectorSpec(name="acme", tools=["m:f"], title="Acme Knowledge")
>>> print(render_display_names_toml(spec))
[auth.oauth_server.resource_display_names]
"https://apps.thorwhalen.com/acme-mcp/mcp" = "Acme Knowledge"
```

* **Return type:**
  [`str`](https://docs.python.org/3/builtins/stdtypes.html#str)

### enlace_connector.render_oauth_server_toml(spec, , issuer='https://apps.thorwhalen.com', refresh_token_ttl_seconds=2592000)

Render the `[auth.oauth_server]` fragment that keeps sessions alive.

Companion to [`render_allowlist_toml()`](#enlace_connector.render_allowlist_toml): that one renders the
`[auth.oauth_server.resource_allowlist]` *subtable*, this one the scalar keys
of the parent table — so a **new** platform is configured for connector-length
sessions from the start instead of inheriting a default that issues no refresh
tokens. Paste this block *before* the allowlist fragment (TOML requires a
table’s own keys to precede its subtables).

```pycon
>>> from enlace_connector import ConnectorSpec
>>> spec = ConnectorSpec(name="acme", tools=["m:f"])
>>> print(render_oauth_server_toml(spec))
#...
[auth.oauth_server]
refresh_token_ttl_seconds = 2592000
```

* **Return type:**
  [`str`](https://docs.python.org/3/builtins/stdtypes.html#str)

### enlace_connector.render_provision_script(spec, , remote_base='/opt/tw_platform')

Render the idempotent, run-as-root provisioning script for the connector.

Builds the dedicated venv (this box’s `ensurepip` is unavailable, so
`--without-pip` + `get-pip.py`, using the same base interpreter that made
the shared venv), installs `extras` + `git_installs`, creates the data
dirs, runs `post_install` (e.g. warm a model), and installs/starts the unit.

* **Return type:**
  [`str`](https://docs.python.org/3/builtins/stdtypes.html#str)

### enlace_connector.render_runbook(spec, , remote_base='/opt/tw_platform', issuer='https://apps.thorwhalen.com')

Render the human deploy checklist (ship, provision, deploy, **verify**).

The last step is the one that is easy to skip and expensive to skip: a
connector whose authorization server cannot issue refresh tokens looks fully
deployed and dies silently hours later, so the runbook states that failure mode
in plain words and gives the exact command that detects it.

* **Return type:**
  [`str`](https://docs.python.org/3/builtins/stdtypes.html#str)

### enlace_connector.render_server_py(spec)

Render the `server.py` that exposes `app` for enlace’s process runner.

The embedded `SPEC` carries every field `
make_connector_app()` reads at serve time — tools, auth, name/title, route,
`stateless_http`, and (when set) `icon`, `instructions`, `middleware`,
`server_hooks`, `version`, `version_dist` and `usage_outcome`.
A `"module:ATTR"` `instructions` or `version` is rendered as the ref,
not its value, so it is read from the installed package at serve time.

Deploy-time-only fields (`extras`, `git_installs`,
`data`, `env`, `post_install`, `allowed_users`) are deliberately
omitted: they are consumed by the provisioning bundle, not by the process.

* **Return type:**
  [`str`](https://docs.python.org/3/builtins/stdtypes.html#str)

### enlace_connector.render_systemd_unit(spec, , remote_base='/opt/tw_platform', issuer='https://apps.thorwhalen.com')

Render the systemd unit that runs the connector in its own venv.

A host that hand-maintains its units can treat this as the reference: run
[`diff_unit()`](#enlace_connector.diff_unit) against each installed unit, so the two cannot drift apart
silently (#15). The spec carries what such units need: an `app_dir` name,
`environment_files` and `exec_start_pre` for scoped secrets,
`uvicorn_args`, and other `service_directives`.

`CONNECTOR_AUDIENCE` is rendered next to `CONNECTOR_ISSUER` by the same code
that renders the allowlist key, and [`render_server_py()`](#enlace_connector.render_server_py) passes it through
explicitly, so the runtime never re-derives it: a connector venv holding an older
`enlace_connector` (whose `mount_route` spelled the route differently) still
validates tokens for exactly the key the platform allows (#12).

* **Return type:**
  [`str`](https://docs.python.org/3/builtins/stdtypes.html#str)

### enlace_connector.resolve_auth(auth, , issuer=None, audience=None)

Normalize an `auth` spec to a py2mcp auth dict (or `None` for no auth).

Accepts:

- `None` or `"none"` → unauthenticated (returns `None`).
- a ready auth dict → returned unchanged.
- `"enlace"` → [`enlace_resource()`](#enlace_connector.enlace_resource) (needs *issuer* and *audience*).
- `"idp"` → not resolvable from a bare string; pass an explicit dict from
  [`idp_resource()`](#enlace_connector.idp_resource) instead (raises with that guidance).

* **Return type:**
  [`dict`](https://docs.python.org/3/builtins/stdtypes.html#dict)[[`str`](https://docs.python.org/3/builtins/stdtypes.html#str), [`Any`](https://docs.python.org/3/library/typing.html#typing.Any)] | [`None`](https://docs.python.org/3/builtins/constants.html#None)

### enlace_connector.resource_url(spec, , issuer='https://apps.thorwhalen.com')

The connector’s OAuth resource = its public MCP endpoint (`route + /mcp`).

The result is the allowlist key, so it must be canonical: enlace_auth refuses any
other spelling at config load. The route is normalized by
[`ConnectorSpec.mount_route`](#enlace_connector.ConnectorSpec.mount_route); an issuer that is not canonical (an uppercase
host, a default port, a path segment that is empty or a dot) is refused here
rather than lowercased, because the same issuer is the connector’s runtime
`iss`/audience origin and must be fixed at its source (#10).

```pycon
>>> resource_url(ConnectorSpec(name="x", tools=[], route="/api/x_mcp/"))
'https://apps.thorwhalen.com/api/x_mcp/mcp'
```

* **Return type:**
  [`str`](https://docs.python.org/3/builtins/stdtypes.html#str)

### enlace_connector.scaffold_app(spec, dest_dir, , port, command=None)

Write `app.toml` and `server.py` for *spec* into *dest_dir*.

*dest_dir* is the enlace app directory (e.g. `tw_platform/apps/<name>`).
Returns the paths written. Creates *dest_dir* if needed; overwrites the two
generated files (they are derived artifacts).

* **Return type:**
  [`dict`](https://docs.python.org/3/builtins/stdtypes.html#dict)[[`str`](https://docs.python.org/3/builtins/stdtypes.html#str), [`Path`](https://docs.python.org/3/library/pathlib.html#pathlib.Path)]

### enlace_connector.spec_instructions(spec)

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

### enlace_connector.spec_version(spec)

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

### enlace_connector.usage_middleware(spec, , settings=None, version=None, \*\*logger_kwargs)

The usage-logging middleware for *spec*, or `[]` when it is switched off.

* **Parameters:**
  * **spec** ([`ConnectorSpec`](enlace_connector.connector.html.md#enlace_connector.connector.ConnectorSpec)) – the connector; its `name`, `version` and `usage_outcome` are
    carried into every record / the classifier.
  * **settings** ([`Optional`](https://docs.python.org/3/library/typing.html#typing.Optional)[[`Mapping`](https://docs.python.org/3/library/typing.html#typing.Mapping)[[`str`](https://docs.python.org/3/builtins/stdtypes.html#str), [`str`](https://docs.python.org/3/builtins/stdtypes.html#str)]]) – where the `CONNECTOR_USAGE_LOG_*` keys are read from
    (default `os.environ`). Pass a dict to configure in code or tests.
  * **version** ([`Optional`](https://docs.python.org/3/library/typing.html#typing.Optional)[[`str`](https://docs.python.org/3/builtins/stdtypes.html#str)]) – overrides `spec.version` for the records.
  * **\*\*logger_kwargs** ([`Any`](https://docs.python.org/3/library/typing.html#typing.Any)) – forwarded to `py2mcp.usage.UsageLogger` (e.g. a
    `sink=` for tests, or an `outcome=` callable). They override what
    the settings and the spec imply. Passing a `sink` switches logging
    on even without `CONNECTOR_USAGE_LOG_DIR`.
* **Return type:**
  [`list`](https://docs.python.org/3/builtins/stdtypes.html#list)
* **Returns:**
  A one-element list (the `UsageLogger`) when logging is on, else `[]` —
  always something `middleware=` accepts.
* **Raises:**
  [**ValueError**](https://docs.python.org/3/builtins/exceptions.html#ValueError) – a setting is malformed (a relative log dir, a non-integer
      retention, an unrecognised yes/no). Loud at boot on purpose: these
      are configuration mistakes, not runtime conditions.

### enlace_connector.verify_deployment(spec=None, \*, issuer, checks=(<function check_refresh_grant_supported>, <function check_jwks_uri_matches_convention>), fetch=None, strict=False)

Run the preflight checks against *issuer*; return one result per check.

This is the “is this deployment actually good?” gate — run it after deploying a
connector (and, ideally, before), because the most consequential property of the
platform is one the connector cannot observe about itself.

* **Parameters:**
  * **spec** ([`ConnectorSpec`](enlace_connector.connector.html.md#enlace_connector.connector.ConnectorSpec) | [`None`](https://docs.python.org/3/builtins/constants.html#None)) – the connector being verified (optional — the AS can be checked alone).
  * **issuer** ([`str`](https://docs.python.org/3/builtins/stdtypes.html#str)) – the authorization server / platform origin.
  * **checks** ([`Iterable`](https://docs.python.org/3/library/typing.html#typing.Iterable)[[`Callable`](https://docs.python.org/3/library/typing.html#typing.Callable)[[[`PreflightContext`](enlace_connector.preflight.html.md#enlace_connector.preflight.PreflightContext)], [`CheckResult`](enlace_connector.preflight.html.md#enlace_connector.preflight.CheckResult)]]) – the checks to run (defaults to `DFLT_CHECKS`).
  * **fetch** ([`Optional`](https://docs.python.org/3/library/typing.html#typing.Optional)[[`Callable`](https://docs.python.org/3/library/typing.html#typing.Callable)[[[`str`](https://docs.python.org/3/builtins/stdtypes.html#str)], [`Any`](https://docs.python.org/3/library/typing.html#typing.Any)]]) – `fetch(url) -> parsed_json` seam (defaults to `fetch_json()`).
  * **strict** ([`bool`](https://docs.python.org/3/builtins/functions.html#bool)) – raise [`PreflightError`](#enlace_connector.PreflightError) if any check fails.
* **Return type:**
  [`list`](https://docs.python.org/3/builtins/stdtypes.html#list)[[`CheckResult`](enlace_connector.preflight.html.md#enlace_connector.preflight.CheckResult)]

```pycon
>>> md = {"grant_types_supported": ["authorization_code"]}
>>> results = verify_deployment(issuer="https://p.example.com",
...                             fetch=lambda url: md)
>>> [r.name for r in results if not r]
['oauth_refresh_grant', 'oauth_jwks_uri']
```

### Modules

| [`auth`](enlace_connector.auth.html.md#module-enlace_connector.auth)           | Auth configuration for connectors — the resource-server side of MCP OAuth.         |
|----------------------------------------------------------------------------------------------|------------------------------------------------------------------------------------|
| [`connector`](enlace_connector.connector.html.md#module-enlace_connector.connector) | Define a connector once, run it anywhere — stdio (local) or HTTP (hosted).         |
| [`deploy`](enlace_connector.deploy.html.md#module-enlace_connector.deploy)       | Generate everything needed to deploy a connector on an enlace platform.            |
| [`preflight`](enlace_connector.preflight.html.md#module-enlace_connector.preflight) | Preflight/verify checks — is the target platform able to keep a connector *alive*? |
| [`scaffold`](enlace_connector.scaffold.html.md#module-enlace_connector.scaffold)   | Generate the enlace app directory that serves a connector.                         |
| [`usage`](enlace_connector.usage.html.md#module-enlace_connector.usage)         | Switch a connector's per-call usage log on by configuration alone.                 |

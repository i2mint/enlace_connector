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
looking perfectly healthy — [`enlace_connector.preflight`](enlace_connector.preflight.md#module-enlace_connector.preflight) is what catches that
in seconds instead of when a user complains a day later.

### Functions

| [`make_connector_app`](#enlace_connector.make_connector_app)(spec, \*[, issuer, audience])   | Build the Streamable-HTTP ASGI app for *spec* (the hosted connector).               |
|-----------------------------------------------------------------------------------------------------|-------------------------------------------------------------------------------------|
| [`make_stdio_server`](#enlace_connector.make_stdio_server)(spec)                            | Build a FastMCP server for *spec*, for local stdio serving (no auth).               |
| [`resolve_auth`](#enlace_connector.resolve_auth)(auth, \*[, issuer, audience])         | Normalize an `auth` spec to a py2mcp auth dict (or `None` for no auth).             |
| [`enlace_resource`](#enlace_connector.enlace_resource)(\*, issuer, audience[, ...])       | Resource-server config validating tokens from the platform's `enlace_auth` AS.      |
| [`idp_resource`](#enlace_connector.idp_resource)(\*, jwks_uri, issuer, audience)       | Resource-server config validating tokens from an external managed IdP.              |
| [`scaffold_app`](#enlace_connector.scaffold_app)(spec, dest_dir, \*, port[, command])  | Write `app.toml` and `server.py` for *spec* into *dest_dir*.                        |
| [`generate_deploy_bundle`](#enlace_connector.generate_deploy_bundle)(spec, dest, \*[, ...])      | Write the full deploy bundle for *spec* under *dest*.                               |
| [`render_systemd_unit`](#enlace_connector.render_systemd_unit)(spec, \*[, remote_base, ...])  | Render the systemd unit that runs the connector in its own venv.                    |
| [`render_provision_script`](#enlace_connector.render_provision_script)(spec, \*[, remote_base])   | Render the idempotent, run-as-root provisioning script for the connector.           |
| [`render_allowlist_toml`](#enlace_connector.render_allowlist_toml)(spec, \*[, issuer])          | Render the `[auth.oauth_server.resource_allowlist]` fragment (or `""`).             |
| [`render_display_names_toml`](#enlace_connector.render_display_names_toml)(spec, \*[, issuer])      | Render the `[auth.oauth_server.resource_display_names]` fragment.                   |
| [`render_oauth_server_toml`](#enlace_connector.render_oauth_server_toml)(spec, \*[, issuer, ...])  | Render the `[auth.oauth_server]` fragment that keeps sessions alive.                |
| [`render_runbook`](#enlace_connector.render_runbook)(spec, \*[, remote_base, issuer])    | Render the human deploy checklist (ship, provision, deploy, **verify**).            |
| [`resource_url`](#enlace_connector.resource_url)(spec, \*[, issuer])                   | The connector's OAuth resource = its public MCP endpoint (`route + /mcp`).          |
| [`render_app_toml`](#enlace_connector.render_app_toml)(spec, \*, port[, command])         | Render the enlace `app.toml` for *spec* as a `mode="process"` app.                  |
| [`render_server_py`](#enlace_connector.render_server_py)(spec)                             | Render the `server.py` that exposes `app` for enlace's process runner.              |
| [`verify_deployment`](#enlace_connector.verify_deployment)([spec, checks, fetch, strict])   | Run the preflight checks against *issuer*; return one result per check.             |
| [`check_refresh_grant_supported`](#enlace_connector.check_refresh_grant_supported)(ctx)                 | THE check: does the AS advertise `refresh_token` in `grant_types_supported`?        |
| [`check_jwks_uri_matches_convention`](#enlace_connector.check_jwks_uri_matches_convention)(ctx)             | For `auth="enlace"` connectors: the AS's `jwks_uri` is the one we validate against. |
| [`authorization_server_metadata`](#enlace_connector.authorization_server_metadata)(issuer, \*[, fetch]) | Fetch the RFC 8414 discovery document advertised by *issuer*.                       |
| [`format_report`](#enlace_connector.format_report)(results)                             | Render check results as a human-readable report (used by the CLI and errors).       |

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

#### ok

whether the checked property holds.

#### summary

one line stating what was (or was not) observed.

#### remedy

what to do about it — empty when `ok`.

### *class* enlace_connector.ConnectorSpec(name, tools, auth='enlace', title=None, route=None, extras=<factory>, git_installs=<factory>, port=8030, data=<factory>, env=<factory>, allowed_users=<factory>, post_install=<factory>, stateless_http=True)

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

### *class* enlace_connector.PreflightContext(issuer, spec=None, fetch=None)

Bases: [`object`](https://docs.python.org/3/builtins/functions.html#object)

What a check is given: the target AS, the connector (if any), and a fetcher.

#### issuer

the authorization server’s issuer origin (the platform origin).

#### spec

the connector being verified — optional, so the AS itself can be
preflighted before any connector exists.

#### fetch

`fetch(url) -> parsed_json`; defaults to `fetch_json()`. Pass
your own to test offline, to add auth headers, or to use `httpx`.

#### *property* metadata *: [dict](https://docs.python.org/3/builtins/stdtypes.html#dict)[[str](https://docs.python.org/3/builtins/stdtypes.html#str), [Any](https://docs.python.org/3/library/typing.html#typing.Any)]*

The AS discovery document (fetched once per context, checked to be a doc).

#### *property* metadata_url *: [str](https://docs.python.org/3/builtins/stdtypes.html#str)*

Where the AS discovery document lives.

### *exception* enlace_connector.PreflightError

Bases: [`RuntimeError`](https://docs.python.org/3/builtins/exceptions.html#RuntimeError)

Raised by [`verify_deployment()`](#enlace_connector.verify_deployment) in `strict` mode when a check fails.

### enlace_connector.authorization_server_metadata(issuer, , fetch=None)

Fetch the RFC 8414 discovery document advertised by *issuer*.

* **Return type:**
  [`dict`](https://docs.python.org/3/builtins/stdtypes.html#dict)[[`str`](https://docs.python.org/3/builtins/stdtypes.html#str), [`Any`](https://docs.python.org/3/library/typing.html#typing.Any)]

### enlace_connector.check_jwks_uri_matches_convention(ctx)

For `auth="enlace"` connectors: the AS’s `jwks_uri` is the one we validate against.

Catches an issuer/route drift that would make every token fail signature
validation — a different symptom of “deployed, healthy, unusable”.

* **Return type:**
  [`CheckResult`](enlace_connector.preflight.md#enlace_connector.preflight.CheckResult)

### enlace_connector.check_refresh_grant_supported(ctx)

THE check: does the AS advertise `refresh_token` in `grant_types_supported`?

An authorization server that omits it can only ever hand out access tokens that
expire into a dead end, which is invisible from the connector’s own health.

* **Return type:**
  [`CheckResult`](enlace_connector.preflight.md#enlace_connector.preflight.CheckResult)

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

* **Return type:**
  [`str`](https://docs.python.org/3/builtins/stdtypes.html#str)

```pycon
>>> print(format_report([CheckResult("a", True, "fine"),
...                      CheckResult("b", False, "broken", "fix it")]))
PASS  a: fine
FAIL  b: broken
      -> fix it
```

### enlace_connector.generate_deploy_bundle(spec, dest, , remote_base='/opt/tw_platform', issuer='https://apps.thorwhalen.com', server_py=None, refresh_token_ttl_seconds=2592000)

Write the full deploy bundle for *spec* under *dest*.

Writes the app dir (`app.toml` + `server.py`) and a `deploy/` folder (the
systemd unit, provisioning script, the `platform.toml` fragments — OAuth
session longevity always, the resource allowlist when the spec restricts users
— and the runbook). Pass *server_py* to override the generated entry module
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

### enlace_connector.make_connector_app(spec, , issuer=None, audience=None)

Build the Streamable-HTTP ASGI app for *spec* (the hosted connector).

Resolves the spec’s `auth` into a py2mcp resource-server config. For
`auth="enlace"` provide *issuer* (the platform origin) and *audience* (this
connector’s public URL); if *audience* is omitted it is derived from *issuer* +
the spec’s route. Returns an ASGI app to run under any ASGI server (or mount in
enlace).

### enlace_connector.make_stdio_server(spec)

Build a FastMCP server for *spec*, for local stdio serving (no auth).

Use for `server.run()` in Claude Desktop / Claude Code while developing the
tools; the hosted path uses [`make_connector_app()`](#enlace_connector.make_connector_app).

### enlace_connector.render_allowlist_toml(spec, , issuer='https://apps.thorwhalen.com')

Render the `[auth.oauth_server.resource_allowlist]` fragment (or `""`).

Empty when `allowed_users` is empty (connector open to any authenticated
user). Otherwise maps this connector’s resource URL to the allowed emails —
paste into the platform’s `platform.toml`.

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

* **Return type:**
  [`str`](https://docs.python.org/3/builtins/stdtypes.html#str)

```pycon
>>> from enlace_connector import ConnectorSpec
>>> spec = ConnectorSpec(name="acme", tools=["m:f"], title="Acme Knowledge")
>>> print(render_display_names_toml(spec))
[auth.oauth_server.resource_display_names]
"https://apps.thorwhalen.com/acme-mcp/mcp" = "Acme Knowledge"
```

### enlace_connector.render_oauth_server_toml(spec, , issuer='https://apps.thorwhalen.com', refresh_token_ttl_seconds=2592000)

Render the `[auth.oauth_server]` fragment that keeps sessions alive.

Companion to [`render_allowlist_toml()`](#enlace_connector.render_allowlist_toml): that one renders the
`[auth.oauth_server.resource_allowlist]` *subtable*, this one the scalar keys
of the parent table — so a **new** platform is configured for connector-length
sessions from the start instead of inheriting a default that issues no refresh
tokens. Paste this block *before* the allowlist fragment (TOML requires a
table’s own keys to precede its subtables).

* **Return type:**
  [`str`](https://docs.python.org/3/builtins/stdtypes.html#str)

```pycon
>>> from enlace_connector import ConnectorSpec
>>> spec = ConnectorSpec(name="acme", tools=["m:f"])
>>> print(render_oauth_server_toml(spec))
#...
[auth.oauth_server]
refresh_token_ttl_seconds = 2592000
```

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
make_connector_app()` reads at serve time — tools, auth, name/title, route and
`stateless_http`. Deploy-time-only fields (`extras`, `git_installs`,
`data`, `env`, `post_install`, `allowed_users`) are deliberately
omitted: they are consumed by the provisioning bundle, not by the process.

* **Return type:**
  [`str`](https://docs.python.org/3/builtins/stdtypes.html#str)

### enlace_connector.render_systemd_unit(spec, , remote_base='/opt/tw_platform', issuer='https://apps.thorwhalen.com')

Render the systemd unit that runs the connector in its own venv.

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

* **Return type:**
  [`str`](https://docs.python.org/3/builtins/stdtypes.html#str)

### enlace_connector.scaffold_app(spec, dest_dir, , port, command=None)

Write `app.toml` and `server.py` for *spec* into *dest_dir*.

*dest_dir* is the enlace app directory (e.g. `tw_platform/apps/<name>`).
Returns the paths written. Creates *dest_dir* if needed; overwrites the two
generated files (they are derived artifacts).

* **Return type:**
  [`dict`](https://docs.python.org/3/builtins/stdtypes.html#dict)[[`str`](https://docs.python.org/3/builtins/stdtypes.html#str), [`Path`](https://docs.python.org/3/library/pathlib.html#pathlib.Path)]

### enlace_connector.verify_deployment(spec=None, \*, issuer, checks=(<function check_refresh_grant_supported>, <function check_jwks_uri_matches_convention>), fetch=None, strict=False)

Run the preflight checks against *issuer*; return one result per check.

This is the “is this deployment actually good?” gate — run it after deploying a
connector (and, ideally, before), because the most consequential property of the
platform is one the connector cannot observe about itself.

* **Parameters:**
  * **spec** ([`ConnectorSpec`](enlace_connector.connector.md#enlace_connector.connector.ConnectorSpec) | [`None`](https://docs.python.org/3/builtins/constants.html#None)) – the connector being verified (optional — the AS can be checked alone).
  * **issuer** ([`str`](https://docs.python.org/3/builtins/stdtypes.html#str)) – the authorization server / platform origin.
  * **checks** ([`Iterable`](https://docs.python.org/3/library/typing.html#typing.Iterable)[[`Callable`](https://docs.python.org/3/library/typing.html#typing.Callable)[[[`PreflightContext`](enlace_connector.preflight.md#enlace_connector.preflight.PreflightContext)], [`CheckResult`](enlace_connector.preflight.md#enlace_connector.preflight.CheckResult)]]) – the checks to run (defaults to `DFLT_CHECKS`).
  * **fetch** ([`Optional`](https://docs.python.org/3/library/typing.html#typing.Optional)[[`Callable`](https://docs.python.org/3/library/typing.html#typing.Callable)[[[`str`](https://docs.python.org/3/builtins/stdtypes.html#str)], [`Any`](https://docs.python.org/3/library/typing.html#typing.Any)]]) – `fetch(url) -> parsed_json` seam (defaults to `fetch_json()`).
  * **strict** ([`bool`](https://docs.python.org/3/builtins/functions.html#bool)) – raise [`PreflightError`](#enlace_connector.PreflightError) if any check fails.
* **Return type:**
  [`list`](https://docs.python.org/3/builtins/stdtypes.html#list)[[`CheckResult`](enlace_connector.preflight.md#enlace_connector.preflight.CheckResult)]

```pycon
>>> md = {"grant_types_supported": ["authorization_code"]}
>>> results = verify_deployment(issuer="https://p.example.com",
...                             fetch=lambda url: md)
>>> [r.name for r in results if not r]
['oauth_refresh_grant', 'oauth_jwks_uri']
```

### Modules

| [`auth`](enlace_connector.auth.md#module-enlace_connector.auth)           | Auth configuration for connectors — the resource-server side of MCP OAuth.         |
|----------------------------------------------------------------------------------------------|------------------------------------------------------------------------------------|
| [`connector`](enlace_connector.connector.md#module-enlace_connector.connector) | Define a connector once, run it anywhere — stdio (local) or HTTP (hosted).         |
| [`deploy`](enlace_connector.deploy.md#module-enlace_connector.deploy)       | Generate everything needed to deploy a connector on an enlace platform.            |
| [`preflight`](enlace_connector.preflight.md#module-enlace_connector.preflight) | Preflight/verify checks — is the target platform able to keep a connector *alive*? |
| [`scaffold`](enlace_connector.scaffold.md#module-enlace_connector.scaffold)   | Generate the enlace app directory that serves a connector.                         |

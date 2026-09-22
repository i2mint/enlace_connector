# enlace_connector.deploy

Generate everything needed to deploy a connector on an enlace platform.

In production, enlace only *reverse-proxies* a `mode="process"` app’s route to
`127.0.0.1:{port}` — the connector’s actual process runs under a \*\*systemd
unit\*\* in its **own venv** (enlace delegates production process management to
systemd). So a full deploy is more than an `app.toml`; this module renders the
whole bundle from a [`ConnectorSpec`](enlace_connector.connector.md#enlace_connector.connector.ConnectorSpec):

- the **systemd unit** (runs the connector in its dedicated venv),
- the **provisioning script** (build that venv + install deps + create data dirs
  + install/start the unit — idempotent, run as root on the box),
- the **resource-allowlist** TOML fragment for `platform.toml` (access control),
- the **resource-display-names** TOML fragment (so the shared OAuth consent page
  shows *this* connector’s name, not whichever connector configured it first —
  i2mint/enlace_auth#18),
- the **\`\`[auth.oauth_server]\`\`** fragment (session longevity — a platform without
  a refresh-token TTL strands every connector at its first token expiry),
- a **runbook** listing the human steps (ship data, provision, deploy, verify).

It generalizes the artifacts first hand-written for the trufflepig connector, so
deploying the next one is `generate_deploy_bundle(spec)` + following the runbook.
Platform specifics (paths, origin) are parameters with tw_platform defaults —
`enlace_connector` stays connector-type-agnostic (it knows nothing of `ir`).

### Module Attributes

| [`DFLT_REMOTE_BASE`](#enlace_connector.deploy.DFLT_REMOTE_BASE)   | Defaults for the tw_platform target (override per call for another platform).    |
|---------------------------------------------------------------------|----------------------------------------------------------------------------------|
| [`MCP_PATH`](#enlace_connector.deploy.MCP_PATH)           | FastMCP's Streamable-HTTP sub-path — the OAuth *resource* is `route + MCP_PATH`. |

### Functions

| [`resource_url`](#enlace_connector.deploy.resource_url)(spec, \*[, issuer])                  | The connector's OAuth resource = its public MCP endpoint (`route + /mcp`).   |
|----------------------------------------------------------------------------------------------------|------------------------------------------------------------------------------|
| [`render_systemd_unit`](#enlace_connector.deploy.render_systemd_unit)(spec, \*[, remote_base, ...]) | Render the systemd unit that runs the connector in its own venv.             |
| [`render_provision_script`](#enlace_connector.deploy.render_provision_script)(spec, \*[, remote_base])  | Render the idempotent, run-as-root provisioning script for the connector.    |
| [`render_allowlist_toml`](#enlace_connector.deploy.render_allowlist_toml)(spec, \*[, issuer])         | Render the `[auth.oauth_server.resource_allowlist]` fragment (or `""`).      |
| [`render_display_names_toml`](#enlace_connector.deploy.render_display_names_toml)(spec, \*[, issuer])     | Render the `[auth.oauth_server.resource_display_names]` fragment.            |
| [`render_oauth_server_toml`](#enlace_connector.deploy.render_oauth_server_toml)(spec, \*[, issuer, ...]) | Render the `[auth.oauth_server]` fragment that keeps sessions alive.         |
| [`render_runbook`](#enlace_connector.deploy.render_runbook)(spec, \*[, remote_base, issuer])   | Render the human deploy checklist (ship, provision, deploy, **verify**).     |
| [`generate_deploy_bundle`](#enlace_connector.deploy.generate_deploy_bundle)(spec, dest, \*[, ...])     | Write the full deploy bundle for *spec* under *dest*.                        |

### enlace_connector.deploy.DFLT_REMOTE_BASE *= '/opt/tw_platform'*

Defaults for the tw_platform target (override per call for another platform).

### enlace_connector.deploy.MCP_PATH *= '/mcp'*

FastMCP’s Streamable-HTTP sub-path — the OAuth *resource* is `route + MCP_PATH`.

### enlace_connector.deploy.generate_deploy_bundle(spec, dest, , remote_base='/opt/tw_platform', issuer='https://apps.thorwhalen.com', server_py=None, refresh_token_ttl_seconds=2592000)

Write the full deploy bundle for *spec* under *dest*.

Writes the app dir (`app.toml` + `server.py`) and a `deploy/` folder (the
systemd unit, provisioning script, the `platform.toml` fragments — OAuth
session longevity always, the resource allowlist when the spec restricts users
— and the runbook). Pass *server_py* to override the generated entry module
(e.g. a corpus-bound `make_search` server the composing skill wrote); pass
*refresh_token_ttl_seconds* to set the session longevity the platform fragment
configures (`0` would disable the refresh grant — see
[`render_oauth_server_toml()`](#enlace_connector.deploy.render_oauth_server_toml)). Returns the written paths.

* **Return type:**
  [`dict`](https://docs.python.org/3/builtins/stdtypes.html#dict)[[`str`](https://docs.python.org/3/builtins/stdtypes.html#str), [`Path`](https://docs.python.org/3/library/pathlib.html#pathlib.Path)]

### enlace_connector.deploy.render_allowlist_toml(spec, , issuer='https://apps.thorwhalen.com')

Render the `[auth.oauth_server.resource_allowlist]` fragment (or `""`).

Empty when `allowed_users` is empty (connector open to any authenticated
user). Otherwise maps this connector’s resource URL to the allowed emails —
paste into the platform’s `platform.toml`.

* **Return type:**
  [`str`](https://docs.python.org/3/builtins/stdtypes.html#str)

### enlace_connector.deploy.render_display_names_toml(spec, , issuer='https://apps.thorwhalen.com')

Render the `[auth.oauth_server.resource_display_names]` fragment.

The shared OAuth consent page (`enlace_auth`) shows *some* product name to
every user authorizing *any* connector on the platform — resolved from
`resource_display_names`, keyed by resource URL (see
[`resource_url()`](#enlace_connector.deploy.resource_url)), with a generic fallback when a resource has no entry.
Before this existed, that string had to be hand-typed once in platform
config and drifted the moment a second connector was added: every consent
screen showed the *first* connector’s name (i2mint/enlace_auth#18).

This makes `ConnectorSpec.title` the single source instead — paste the
fragment into the platform’s `platform.toml` alongside
[`render_allowlist_toml()`](#enlace_connector.deploy.render_allowlist_toml)’s.

* **Return type:**
  [`str`](https://docs.python.org/3/builtins/stdtypes.html#str)

```pycon
>>> from enlace_connector import ConnectorSpec
>>> spec = ConnectorSpec(name="acme", tools=["m:f"], title="Acme Knowledge")
>>> print(render_display_names_toml(spec))
[auth.oauth_server.resource_display_names]
"https://apps.thorwhalen.com/acme-mcp/mcp" = "Acme Knowledge"
```

### enlace_connector.deploy.render_oauth_server_toml(spec, , issuer='https://apps.thorwhalen.com', refresh_token_ttl_seconds=2592000)

Render the `[auth.oauth_server]` fragment that keeps sessions alive.

Companion to [`render_allowlist_toml()`](#enlace_connector.deploy.render_allowlist_toml): that one renders the
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

### enlace_connector.deploy.render_provision_script(spec, , remote_base='/opt/tw_platform')

Render the idempotent, run-as-root provisioning script for the connector.

Builds the dedicated venv (this box’s `ensurepip` is unavailable, so
`--without-pip` + `get-pip.py`, using the same base interpreter that made
the shared venv), installs `extras` + `git_installs`, creates the data
dirs, runs `post_install` (e.g. warm a model), and installs/starts the unit.

* **Return type:**
  [`str`](https://docs.python.org/3/builtins/stdtypes.html#str)

### enlace_connector.deploy.render_runbook(spec, , remote_base='/opt/tw_platform', issuer='https://apps.thorwhalen.com')

Render the human deploy checklist (ship, provision, deploy, **verify**).

The last step is the one that is easy to skip and expensive to skip: a
connector whose authorization server cannot issue refresh tokens looks fully
deployed and dies silently hours later, so the runbook states that failure mode
in plain words and gives the exact command that detects it.

* **Return type:**
  [`str`](https://docs.python.org/3/builtins/stdtypes.html#str)

### enlace_connector.deploy.render_systemd_unit(spec, , remote_base='/opt/tw_platform', issuer='https://apps.thorwhalen.com')

Render the systemd unit that runs the connector in its own venv.

* **Return type:**
  [`str`](https://docs.python.org/3/builtins/stdtypes.html#str)

### enlace_connector.deploy.resource_url(spec, , issuer='https://apps.thorwhalen.com')

The connector’s OAuth resource = its public MCP endpoint (`route + /mcp`).

* **Return type:**
  [`str`](https://docs.python.org/3/builtins/stdtypes.html#str)

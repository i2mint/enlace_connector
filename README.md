# enlace_connector

Deploy Python functions as **authenticated MCP connectors** on an
[enlace](https://github.com/i2mint/enlace) platform — so Claude.ai (and any MCP
host) can call them.

A Claude.ai "custom connector" is a remote MCP server. `enlace_connector` wraps your
tool functions with [`py2mcp`](https://github.com/thorwhalen/py2mcp), plugs auth into
the platform's [`enlace_auth`](https://github.com/i2mint/enlace_auth) OAuth server,
and follows enlace's app conventions so deployment is one declaration.

```python
from enlace_connector import ConnectorSpec, make_connector_app, scaffold_app

spec = ConnectorSpec(
    name="trufflepig",
    tools=["truffle.mcp:search_trufflepig", "truffle.mcp:search_wallow"],
    auth="enlace",                 # validate tokens issued by the platform's enlace_auth
    extras=["truffle"],            # what the connector's own venv must install
)

# Develop locally (stdio, no auth) — Claude Desktop / Claude Code:
make_stdio_server(spec).run()

# The hosted ASGI app (Streamable HTTP + OAuth) a server runs:
app = make_connector_app(spec, issuer="https://apps.thorwhalen.com")

# Or scaffold an enlace mode=process app dir (own venv for heavy deps):
scaffold_app(spec, "tw_platform/apps/trufflepig_mcp", port=8030)
```

## Why a separate venv (`mode="process"`)

A connector with heavy dependencies (ML models, large libraries) runs as an enlace
`mode="process"` app: enlace spawns it as a supervised subprocess in its **own venv**
and reverse-proxies the route to it — keeping those deps out of the shared platform
backend. The connector validates bearer tokens itself, so enlace treats it as
`access="public"` (no session gate).

## Auth is pluggable

The connector is an OAuth 2.1 *resource server* — it validates the bearer JWTs an
authorization server issued. Who that AS is is just config:

| `auth=` | Authorization server | Use |
|---|---|---|
| `"enlace"` | the platform's `enlace_auth` OAuth server | self-contained platform auth |
| `idp_resource(...)` | a managed IdP (Auth0, WorkOS, …) | offload OAuth to a vendor |
| `None` / `"none"` | — | local stdio / unauthenticated internal pilot |

The resource-server validation is identical regardless — picking an AS doesn't change
the connector, only where the token comes from.

## Deploy the whole bundle

`generate_deploy_bundle(spec, dest)` writes everything a `mode="process"` connector
needs — the app dir (`app.toml` + `server.py`), a **systemd unit** (runs it in its
own venv), a **provisioning script** (build that venv + install `extras`/`git_installs`
+ create `data` dirs + `post_install`), the **`resource_allowlist`** fragment (from
`allowed_users`), and a **runbook**:

```python
spec = ConnectorSpec(
    name="acme", tools=["acme.mcp:search"], route="/api/acme_mcp", port=8031,
    extras=["ir", "sentence-transformers"], git_installs=["git+ssh://git@github.com/acme/acme"],
    data=[("~/.local/share/ir/corpora/acme", "{base}/xdg-data/ir/corpora/acme")],
    env={"XDG_DATA_HOME": "{base}/xdg-data", "HF_HOME": "{base}/hf-cache"},
    allowed_users=["a@acme.com", "b@acme.com"],
)
generate_deploy_bundle(spec, "apps/acme_mcp")   # → app dir + deploy/{unit,provision,allowlist,runbook}
```

Platform specifics (paths, origin) are parameters with tw_platform defaults; the
package stays connector-type-agnostic (it knows nothing of `ir`).

## Cost / LLM note

A connector over `ir`'s core search is **offline and free** — no LLM, no tokens.
An *agentic* connector (query reformulation, LLM-selection, synopsis) needs an LLM;
that LLM is an injected callable and can ride the **client's Claude subscription** via
MCP sampling (where the client supports it) instead of a metered key — see `ir`'s
`ir_10` note and issue #1 here.

## Status

The connector factory, auth, **scaffolding, and full deploy-bundle generation** are
stable and tested; `auth="enlace"` is live in production. Building the connector app
directly (to attach a server icon, custom tools, etc.) is also supported — see the
`server_py=` override on `generate_deploy_bundle`.
```bash
pip install -e ".[dev]" && pytest -q
```

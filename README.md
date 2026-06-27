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

## Status

Early. The `enlace_auth` OAuth-server side (`auth="enlace"`) and the `tw_platform`
deploy wiring are tracked as follow-on work; the connector factory + scaffolding here
are stable and tested.
```bash
pip install -e ".[dev]" && pytest -q
```

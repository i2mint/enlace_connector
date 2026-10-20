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

## Usage logging is a switch, not code

A deployed connector otherwise leaves only the web server's access log. With
[`py2mcp`'s usage logger](https://github.com/i2mint/py2mcp) (its ADR-0001) the
connector can keep one record per tool call — time, caller from the OAuth token,
tool, arguments, outcome, result size, latency — and one flagged record per
handshake, so "enabled" and "used" stop looking the same. **It is off by default.**
The host switches it on with environment variables (the unit file's
`Environment=` lines), never by editing connector code:

| Variable | Meaning |
|---|---|
| `CONNECTOR_USAGE_LOG_DIR` | **absolute** directory for the day files, one per connector; **unset = off**. Use the connector's own data root, off the deploy tree (a relative path is refused) |
| `CONNECTOR_USAGE_LOG_RETENTION_DAYS` | days to keep (default 90; `0` keeps today only; `none` keeps all) |
| `CONNECTOR_USAGE_LOG_REDACT` | comma-separated argument names to mask (error text is dropped too, since it echoes arguments) |
| `CONNECTOR_USAGE_LOG_ARGS` | `0` to drop the arguments entirely |

`make_connector_app(spec)` reads them itself; a connector that builds `FastMCP`
by hand passes `middleware=usage_middleware(spec)` (an empty list when off). The
spec's `version` and `usage_outcome` (a `"module:function"` ref to the connector's
own `(tool, result) -> label | mapping` classifier, e.g. one that knows the search
tool's "no match" shape) travel into the records.
The rendered systemd unit ships the `CONNECTOR_USAGE_LOG_DIR` line commented
out. The arguments are the users' own questions: tell them before you turn it on,
and read the log with `py2mcp usage <dir>`.

## Deploy the whole bundle

`generate_deploy_bundle(spec, dest)` writes everything a `mode="process"` connector
needs — the app dir (`app.toml` + `server.py`), a **systemd unit** (runs it in its
own venv), a **provisioning script** (build that venv + install `extras`/`git_installs`
+ create `data` dirs + `post_install`), the two **`platform.toml` fragments**
(`oauth-server.toml` — session longevity; `allowlist.toml` — from `allowed_users`),
and a **runbook**. `allowed_users` is required: the platform refuses every account
for a resource it does not list, so an empty list raises instead of deploying a
connector nobody can authorize. `allowed_users=["*"]` opens it to every
authenticated platform account, and has to be written out:

```python
spec = ConnectorSpec(
    name="acme", tools=["acme.mcp:search"], route="/api/acme_mcp", port=8031,
    extras=["ir", "sentence-transformers"], git_installs=["git+ssh://git@github.com/acme/acme"],
    data=[("~/.local/share/ir/corpora/acme", "{base}/xdg-data/ir/corpora/acme")],
    env={"XDG_DATA_HOME": "{base}/xdg-data", "HF_HOME": "{base}/hf-cache"},
    allowed_users=["a@acme.com", "b@acme.com"],
)
generate_deploy_bundle(spec, "apps/acme_mcp")   # → app dir + deploy/{unit,provision,toml fragments,runbook}
```

Platform specifics (paths, origin) are parameters with tw_platform defaults; the
package stays connector-type-agnostic (it knows nothing of `ir`).

### Hosts that keep their own unit files

A host may hand-maintain its units rather than install the rendered one. The spec can still describe such a unit: `app_dir` names the directory under `apps/` and `connectors/` (e.g. `"acme_mcp"`, when it is not the spec's `name`), `environment_files` and `exec_start_pre` scope provider secrets into the process, `uvicorn_args` adds flags such as `--no-access-log`, and `service_directives` carries any other `[Service]` line (`RuntimeDirectory=`, …). Then make drift visible instead of silent:

```python
from enlace_connector import check_distinct_specs, diff_unit

check_distinct_specs(specs)          # same port (it has a default), unit name or directory: refused
for spec in specs:
    for line in diff_unit(spec, installed_unit_text(spec)):
        print(spec.name, line)       # e.g. "[Service] Environment CONNECTOR_AUDIENCE: installed lacks it"
```

`diff_unit` compares semantically (comments, directive order, whitespace and `Environment=` quoting do not count; the order of repeated `ExecStartPre=` lines does) and ignores `Description=`. It reads `Environment=` as systemd does (quotes anywhere in a word, C escapes such as `\\` and `\x41` inside quotes too) and skips comment lines inside a backslash continuation. It reads the main unit file only, not drop-ins.

## Verify before you call it deployed

A connector can be perfectly healthy and completely dead to its users. If the
platform's authorization server does not advertise the **`refresh_token` grant**,
every client session dies at the first access-token expiry (typically one hour) and
only a human re-running the interactive browser authorization can bring it back —
while the process stays up, the port answers, and nothing errors anywhere. It has
happened; the first signal was a person saying the connector had been down all day.

So the deployment isn't good until the *authorization server* is checked:

```bash
python -m enlace_connector.preflight https://apps.thorwhalen.com   # exit 1 if it would strand
```

```python
from enlace_connector import verify_deployment, format_report

results = verify_deployment(spec, issuer="https://apps.thorwhalen.com")
print(format_report(results))
assert all(results)          # or pass strict=True to raise
```

It fetches `{issuer}/.well-known/oauth-authorization-server` and asserts what the
**deployed** server advertises — config claiming refresh is enabled is not evidence,
since the running build may predate the feature. Checks are plain callables of a
`PreflightContext` (`checks=` to extend or replace them) and the HTTP fetcher is a
parameter (`fetch=`), so this is testable offline and CI-friendly.

Configure it from the start too: `deploy/oauth-server.toml` in the bundle carries the
`[auth.oauth_server] refresh_token_ttl_seconds` key (30 days by default; `0` disables
the grant), so a **new** platform doesn't inherit a stranding default.

## Cost / LLM note

A connector over `ir`'s core search is **offline and free**: no LLM, no tokens.
An *agentic* connector (query reformulation, LLM selection, synopsis) needs an LLM,
which is an injected `prompt -> str` callable. `llm_tool` wraps such a tool so it
brings its own, per request:

```python
from enlace_connector import llm_tool

@llm_tool(fallback="mypkg.llm:chat")      # optional: a prompt -> str to use instead
def search(query: str, limit: int = 5, *, llm=None) -> list[dict]:
    ...                                    # llm is None: run the offline search
```

The LLM is the **client's model via MCP sampling** when the client advertises it
(`ctx.sample`, so no metered key), else the `fallback` (a key-backed callable, or
`coact.resolve_llm()` on a developer machine), else `None` and the tool runs offline.
A sampling request that fails mid-call reruns the tool on the fallback, so the
connector never hard-fails for want of an LLM (the rerun starts the tool over, so it
must be safe to run twice up to its first LLM call). Reference the wrapped function in
the spec's `tools` as usual. Sampling needs a stateful session: set
`stateless_http=False` on the spec, since a stateless request never sees the client's
capabilities.

**Client support, checked 2026-10:** Claude's MCP client (claude.ai, Desktop, mobile,
Cowork, Claude Code) lists sampling among the MCP features it does not yet support
([Build an MCP server for Claude](https://claude.com/docs/connectors/building/index)),
so under Claude a wrapped tool runs on its fallback or offline today. Clients that do
sample get it with no change. See `ir`'s `ir_10` note.

## Status

The connector factory, auth, **scaffolding, and full deploy-bundle generation** are
stable and tested; `auth="enlace"` is live in production. A spec carries what used to
force a hand-written `server.py`: `icon`, `instructions`, `middleware` and `server_hooks`
(tools that are not `module:function` refs). `instructions` and `version` may be
`"module:ATTR"` refs (e.g. `"mypkg.prompts:INSTRUCTIONS"`, `"mypkg:__version__"`), and
`version_dist="mypkg"` reads the installed distribution's version, so neither is a
frozen copy that drifts from the package. Building the connector app directly is still
possible — see the `server_py=` override on `generate_deploy_bundle`.
```bash
pip install -e ".[dev]" && pytest -q
```

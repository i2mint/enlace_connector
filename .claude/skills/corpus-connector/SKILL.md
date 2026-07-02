---
name: corpus-connector
description: >-
  Turn an ir corpus into a deployed, access-controlled MCP connector for a client.
  Use when the user wants to "make a connector for a corpus", "deploy an ir corpus
  as a Claude connector", "create a search connector for <client>", "index these
  sources and expose them to Claude", or "give <client> a searchable knowledge
  connector". Composes ir (index/search) → py2mcp (functions→MCP) → enlace_connector
  (deploy any MCP connector) → the tw_platform server, and sets per-connector access
  control. The per-corpus work is config (a name + sources), not code.
---

# corpus-connector — an ir corpus → a deployed MCP connector

A **clean-separation pipeline** (each layer has one owner; nothing knows about the
next): `ir` indexes + searches, `py2mcp` wraps a search function as MCP,
`enlace_connector` deploys *any* MCP connector, `enlace_auth` gates it. This skill
is only the **composition**; don't push corpus/connector logic into the wrong layer.

```
sources ──ir──▶ named corpus ──ir.make_search──▶ search fn ──py2mcp/FastMCP──▶ MCP app
   └── enlace_connector.generate_deploy_bundle ──▶ app.toml + systemd + provision + allowlist + runbook
   └── ship data + provision + deploy.py + allowlist + client accounts ──▶ live, access-controlled connector
```

## Inputs to gather first

- **Corpus**: either an *existing* registered ir corpus **name**, or a **name +
  sources** to index from scratch (a folder of files, a mapping, etc.).
- **Client name / connector name** (→ app name `­{name}_mcp`, route `/api/{name}_mcp`).
- **Allowed users** (emails) — who may use this connector (access control).
- **Free port** on the box (8010/8011/8020 taken; use **8031+**, one per connector).

## Step 1 — Resolve or build the corpus (owner: `ir`)

Existing corpus → just use its name. New corpus:

```python
import ir
src = ir.CorpusSource.from_files("/path/to/sources", name="<corpus>", pattern=r".*\.md$")
# or: ir.CorpusSource.from_mapping({...}, name="<corpus>")
ir.register("<corpus>", "files", root="/path/to/sources")   # persist to the registry
corpus = ir.build(src)                                        # embed + persist (XDG store)
print(ir.tools.search("smoke test query", corpus="<corpus>", k=3))  # verify it retrieves
```

If the sources need custom parsing/chunking (like trufflepig's P2/FileMaker), write a
small **indexer package** with a `CorpusSource` + a `strategy` (see `truffle` as the
reference) — that indexing code is the *only* per-client code, and it belongs in its
own package, not here.

## Step 2 — Generate the connector (owners: `ir` + `py2mcp` + `enlace_connector`)

Write the app dir with a **corpus-bound** search tool. `ir.make_search(corpus)` gives
a runtime-bound function, so build the FastMCP app directly (mirrors the trufflepig
`server.py`) and pass it as `server_py=` to the bundle generator:

```python
SERVER_PY = '''\
"""Connector for the <corpus> corpus — ir search over one corpus, enlace OAuth."""
import os
import ir
from fastmcp import FastMCP
from py2mcp.http import mk_auth_provider
from enlace_connector import ConnectorSpec
from enlace_connector.auth import resolve_auth

_spec = ConnectorSpec(name="<name>", tools=[], route="/api/<name>_mcp", auth="enlace")
_issuer = os.environ.get("CONNECTOR_ISSUER", "https://apps.thorwhalen.com")
_auth = resolve_auth("enlace", issuer=_issuer, audience=_spec.default_audience(_issuer))

server = FastMCP("<Title>", auth=mk_auth_provider(_auth))
server.tool(ir.make_search("<corpus>", name="<name>"))   # corpus-bound MCP tool
app = server.http_app(transport="streamable-http", stateless_http=True)
'''

from enlace_connector import ConnectorSpec, generate_deploy_bundle
spec = ConnectorSpec(
    name="<name>", tools=[], title="<Title>", route="/api/<name>_mcp", port=8031,
    extras=["ir", "sentence-transformers", "py2mcp", "enlace_connector", "uvicorn"],
    data=[("~/.local/share/ir/corpora/<corpus>", "{base}/xdg-data/ir/corpora/<corpus>")],
    env={"XDG_DATA_HOME": "{base}/xdg-data", "HF_HOME": "{base}/hf-cache"},
    allowed_users=["a@client.com", "b@client.com"],
    post_install=['HF_HOME={base}/hf-cache {venv}/bin/python -c '
                  '"from sentence_transformers import SentenceTransformer as S; S(\\'BAAI/bge-base-en-v1.5\\')"'],
)
generate_deploy_bundle(spec, "<tw_platform>/apps/<name>_mcp", server_py=SERVER_PY)
```

Notes: also co-locate the **registry** (`~/.config/ir/corpora.json`) if the corpus is
referenced by name (or pass a `Corpus`/absolute store); the **embedding model** cache
is warmed by `post_install`. Match the embedder used at build time.

## Step 3 — Deploy (follow the generated `deploy/RUNBOOK.md`)

`generate_deploy_bundle` wrote the exact steps; execute them (owner: `enlace_connector`
+ tw_platform). In short:
1. `deploy.py cmd-deploy --app <name>_mcp --force` (ships the app + Traefik route).
2. `rsync -az` the corpora → the connector's `xdg-data` (data is excluded from code rsync).
3. `rsync` `deploy/` to the server; `ssh tw 'bash …/provision-<name>.sh'` (builds the venv, warms the model, starts the systemd unit).
4. Merge `deploy/allowlist.toml` into `platform.toml` `[auth.oauth_server]`, `rsync platform.toml`, restart `enlace-backend`.

## Step 4 — Client access + onboarding

- Ensure `[auth.oauth_server] enabled = true` on the platform (once, globally).
- Create each client account: `ssh tw '…/venv/bin/python -m enlace_auth set-password <email>'` (or write hashes into the user store).
- Send each user: the public URL `https://apps.thorwhalen.com/api/<name>_mcp/mcp`, their email + password, and "Claude → Settings → Connectors → Add custom connector → (blank OAuth fields) → Add → Connect → log in → Approve".

## Local testing (no deploy)

`enlace_connector.make_stdio_server(spec).run()` — or a stdio FastMCP over
`ir.make_search(corpus)` — in Claude Desktop / Claude Code to validate the tool first.

## Gotchas (hard-won — check these)

- **Audience = the MCP endpoint** (`route + /mcp`), not the base — `enlace_resource`
  handles it; if you hand-roll auth, mirror it or you get a 401 "audience mismatch".
- **`[auth.oauth_server]` + `/auth/oauth/` CSRF exemption + origin-root
  protected-resource metadata** must be live on the platform (enlace_auth ≥ 0.1.16).
- **Provisioning uses `--without-pip` + get-pip** (this box's ensurepip is broken) and
  the **pyenv** interpreter — the generator already does this.
- **`data` is shipped separately** (rsync), never via the code deploy.
- **Agentic (LLM) search** is optional and *not* offline — see `ir`'s `ir_10` and
  enlace_connector#1 before enabling it (subscription-routing is client-gated).

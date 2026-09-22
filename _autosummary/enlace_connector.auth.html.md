# enlace_connector.auth

Auth configuration for connectors — the resource-server side of MCP OAuth.

A Claude.ai custom connector is an OAuth 2.1 **resource server**: it validates the
bearer JWTs an authorization server issued (it never issues tokens itself). This
module produces the auth-config dict `py2mcp.http.mk_http_app()` consumes — a
`JWTVerifier` bound to a JWKS URI, an issuer, and an audience (the connector’s own
URL, per RFC 8707 resource indicators).

The *authorization server* is pluggable, but the resource-server config is the same
shape regardless of who issues the token — so picking an AS is just config:

- [`enlace_resource()`](#enlace_connector.auth.enlace_resource) — the platform’s own `enlace_auth` OAuth server (the
  endpoints follow the [`ENLACE_OAUTH_PATH`](#enlace_connector.auth.ENLACE_OAUTH_PATH) convention this package and
  `enlace_auth` share).
- [`idp_resource()`](#enlace_connector.auth.idp_resource) — an external managed IdP (Auth0, WorkOS, …): pass its
  `jwks_uri` / `issuer` explicitly.
- `None` / `"none"` — unauthenticated (local stdio, or an internal pilot).

### Module Attributes

| [`ENLACE_OAUTH_PATH`](#enlace_connector.auth.ENLACE_OAUTH_PATH)   | Path under the platform origin where `enlace_auth` serves its OAuth 2.1 authorization-server endpoints (authorize / token / register / jwks).   |
|----------------------------------------------------------------------|-------------------------------------------------------------------------------------------------------------------------------------------------|
| [`DFLT_SCOPES`](#enlace_connector.auth.DFLT_SCOPES)         | Default OAuth scopes a connector requires (read-only retrieval).                                                                                |

### Functions

| [`enlace_resource`](#enlace_connector.auth.enlace_resource)(\*, issuer, audience[, ...])   | Resource-server config validating tokens from the platform's `enlace_auth` AS.   |
|-------------------------------------------------------------------------------------------------|----------------------------------------------------------------------------------|
| [`idp_resource`](#enlace_connector.auth.idp_resource)(\*, jwks_uri, issuer, audience)   | Resource-server config validating tokens from an external managed IdP.           |
| [`resolve_auth`](#enlace_connector.auth.resolve_auth)(auth, \*[, issuer, audience])     | Normalize an `auth` spec to a py2mcp auth dict (or `None` for no auth).          |

### enlace_connector.auth.DFLT_SCOPES *= ('mcp:read',)*

Default OAuth scopes a connector requires (read-only retrieval).

### enlace_connector.auth.ENLACE_OAUTH_PATH *= '/auth/oauth'*

Path under the platform origin where `enlace_auth` serves its OAuth 2.1
authorization-server endpoints (authorize / token / register / jwks). The
AS *issuer* is the bare platform origin; discovery lives at the standard
`{issuer}/.well-known/oauth-authorization-server`. This constant is the
single source of truth shared with `enlace_auth` so the two never drift.

### enlace_connector.auth.enlace_resource(, issuer, audience, scopes=('mcp:read',), mcp_path='/mcp')

Resource-server config validating tokens from the platform’s `enlace_auth` AS.

* **Parameters:**
  * **issuer** ([`str`](https://docs.python.org/3/builtins/stdtypes.html#str)) – the platform origin acting as the OAuth issuer, e.g.
    `"https://apps.thorwhalen.com"` (no trailing slash needed).
  * **audience** ([`str`](https://docs.python.org/3/builtins/stdtypes.html#str)) – this connector’s **base** URL (e.g.
    `"https://apps.thorwhalen.com/api/trufflepig_mcp"`).
  * **scopes** ([`Iterable`](https://docs.python.org/3/library/typing.html#typing.Iterable)[[`str`](https://docs.python.org/3/builtins/stdtypes.html#str)]) – scopes the connector requires (default [`DFLT_SCOPES`](#enlace_connector.auth.DFLT_SCOPES)).
  * **mcp_path** ([`str`](https://docs.python.org/3/builtins/stdtypes.html#str)) – the MCP transport sub-path (FastMCP default `/mcp`).
* **Return type:**
  [`dict`](https://docs.python.org/3/builtins/stdtypes.html#dict)[[`str`](https://docs.python.org/3/builtins/stdtypes.html#str), [`Any`](https://docs.python.org/3/library/typing.html#typing.Any)]

The OAuth *resource* a connector validates is its MCP **endpoint**
(`base + mcp_path`) — that is what FastMCP advertises in the RFC 9728
protected-resource metadata, and therefore what the issued token’s `aud`
carries. So `base_url` (used to build that metadata) is the base, while the
validated `audience` is `base + mcp_path`. Setting them equal causes an
“audience mismatch” 401 at token-validation time.

### enlace_connector.auth.idp_resource(, jwks_uri, issuer, audience, authorization_servers=None, base_url=None, scopes=('mcp:read',))

Resource-server config validating tokens from an external managed IdP.

Everything is explicit because each IdP (Auth0, WorkOS, Okta…) publishes its
own `jwks_uri` / `issuer`. `authorization_servers` defaults to
`[issuer]` and `base_url` to `audience` (this connector’s URL).

* **Return type:**
  [`dict`](https://docs.python.org/3/builtins/stdtypes.html#dict)[[`str`](https://docs.python.org/3/builtins/stdtypes.html#str), [`Any`](https://docs.python.org/3/library/typing.html#typing.Any)]

### enlace_connector.auth.resolve_auth(auth, , issuer=None, audience=None)

Normalize an `auth` spec to a py2mcp auth dict (or `None` for no auth).

Accepts:

- `None` or `"none"` → unauthenticated (returns `None`).
- a ready auth dict → returned unchanged.
- `"enlace"` → [`enlace_resource()`](#enlace_connector.auth.enlace_resource) (needs *issuer* and *audience*).
- `"idp"` → not resolvable from a bare string; pass an explicit dict from
  [`idp_resource()`](#enlace_connector.auth.idp_resource) instead (raises with that guidance).

* **Return type:**
  [`dict`](https://docs.python.org/3/builtins/stdtypes.html#dict)[[`str`](https://docs.python.org/3/builtins/stdtypes.html#str), [`Any`](https://docs.python.org/3/library/typing.html#typing.Any)] | [`None`](https://docs.python.org/3/builtins/constants.html#None)

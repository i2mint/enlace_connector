"""Auth configuration for connectors — the resource-server side of MCP OAuth.

A Claude.ai custom connector is an OAuth 2.1 **resource server**: it validates the
bearer JWTs an authorization server issued (it never issues tokens itself). This
module produces the auth-config dict :func:`py2mcp.http.mk_http_app` consumes — a
``JWTVerifier`` bound to a JWKS URI, an issuer, and an audience (the connector's own
URL, per RFC 8707 resource indicators).

The *authorization server* is pluggable, but the resource-server config is the same
shape regardless of who issues the token — so picking an AS is just config:

- :func:`enlace_resource` — the platform's own ``enlace_auth`` OAuth server (the
  endpoints follow the :data:`ENLACE_OAUTH_PATH` convention this package and
  ``enlace_auth`` share).
- :func:`idp_resource` — an external managed IdP (Auth0, WorkOS, …): pass its
  ``jwks_uri`` / ``issuer`` explicitly.
- ``None`` / ``"none"`` — unauthenticated (local stdio, or an internal pilot).
"""

from __future__ import annotations

from typing import Any, Iterable

__all__ = [
    "ENLACE_OAUTH_PATH",
    "DFLT_SCOPES",
    "enlace_resource",
    "idp_resource",
    "resolve_auth",
]

#: Path under the platform origin where ``enlace_auth`` serves its OAuth 2.1
#: authorization-server endpoints (authorize / token / register / jwks). The
#: AS *issuer* is the bare platform origin; discovery lives at the standard
#: ``{issuer}/.well-known/oauth-authorization-server``. This constant is the
#: single source of truth shared with ``enlace_auth`` so the two never drift.
ENLACE_OAUTH_PATH = "/auth/oauth"

#: Default OAuth scopes a connector requires (read-only retrieval).
DFLT_SCOPES = ("mcp:read",)


def enlace_resource(
    *,
    issuer: str,
    audience: str,
    scopes: Iterable[str] = DFLT_SCOPES,
    mcp_path: str = "/mcp",
) -> dict[str, Any]:
    """Resource-server config validating tokens from the platform's ``enlace_auth`` AS.

    Args:
        issuer: the platform origin acting as the OAuth issuer, e.g.
            ``"https://apps.thorwhalen.com"`` (no trailing slash needed).
        audience: this connector's **base** URL (e.g.
            ``"https://apps.thorwhalen.com/api/trufflepig_mcp"``).
        scopes: scopes the connector requires (default :data:`DFLT_SCOPES`).
        mcp_path: the MCP transport sub-path (FastMCP default ``/mcp``).

    The OAuth *resource* a connector validates is its MCP **endpoint**
    (``base + mcp_path``) — that is what FastMCP advertises in the RFC 9728
    protected-resource metadata, and therefore what the issued token's ``aud``
    carries. So ``base_url`` (used to build that metadata) is the base, while the
    validated ``audience`` is ``base + mcp_path``. Setting them equal causes an
    "audience mismatch" 401 at token-validation time.
    """
    issuer = issuer.rstrip("/")
    base = audience.rstrip("/")
    return {
        "type": "jwt",
        "issuer": issuer,
        "jwks_uri": f"{issuer}{ENLACE_OAUTH_PATH}/jwks",
        "authorization_servers": [issuer],
        "audience": f"{base}{mcp_path}",
        "base_url": base,
        "required_scopes": list(scopes),
    }


def idp_resource(
    *,
    jwks_uri: str,
    issuer: str,
    audience: str,
    authorization_servers: Iterable[str] | None = None,
    base_url: str | None = None,
    scopes: Iterable[str] = DFLT_SCOPES,
) -> dict[str, Any]:
    """Resource-server config validating tokens from an external managed IdP.

    Everything is explicit because each IdP (Auth0, WorkOS, Okta…) publishes its
    own ``jwks_uri`` / ``issuer``. ``authorization_servers`` defaults to
    ``[issuer]`` and ``base_url`` to ``audience`` (this connector's URL).
    """
    return {
        "type": "jwt",
        "issuer": issuer,
        "jwks_uri": jwks_uri,
        "authorization_servers": list(authorization_servers or [issuer]),
        "audience": audience,
        "base_url": base_url or audience,
        "required_scopes": list(scopes),
    }


def resolve_auth(
    auth: Any,
    *,
    issuer: str | None = None,
    audience: str | None = None,
) -> dict[str, Any] | None:
    """Normalize an ``auth`` spec to a py2mcp auth dict (or ``None`` for no auth).

    Accepts:
    - ``None`` or ``"none"`` → unauthenticated (returns ``None``).
    - a ready auth dict → returned unchanged.
    - ``"enlace"`` → :func:`enlace_resource` (needs *issuer* and *audience*).
    - ``"idp"`` → not resolvable from a bare string; pass an explicit dict from
      :func:`idp_resource` instead (raises with that guidance).
    """
    if auth is None or auth == "none":
        return None
    if isinstance(auth, dict):
        return auth
    if auth == "enlace":
        if not (issuer and audience):
            raise ValueError(
                "auth='enlace' needs issuer and audience (the platform origin and "
                "this connector's public URL)."
            )
        return enlace_resource(issuer=issuer, audience=audience)
    if auth == "idp":
        raise ValueError(
            "auth='idp' can't be resolved from a bare string; build it explicitly "
            "with enlace_connector.idp_resource(jwks_uri=..., issuer=..., "
            "audience=...) and pass that dict as auth."
        )
    raise ValueError(f"Unrecognized auth spec: {auth!r}")

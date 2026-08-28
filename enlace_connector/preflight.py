"""Preflight/verify checks — is the target platform able to keep a connector *alive*?

A connector deployment can be perfectly healthy and still be **dead to its users**.
The failure this module exists to catch: the platform's OAuth 2.1 authorization
server issues a short-lived access token and **no refresh token** (it does not
advertise ``refresh_token`` in ``grant_types_supported``). Every client session then
hard-dies at the first token expiry — while the connector process stays green,
the port answers, and nothing errors anywhere. The only recovery is a human
re-running the interactive browser authorization, and the stock 401 challenge text
actively misinforms by claiming the client can renew on its own.

Nothing about the connector bundle can detect that from the inside, so it is a
*preflight of the authorization server*: fetch the AS's discovery document at
``{issuer}/.well-known/oauth-authorization-server`` and assert what it advertises.

Run it as a function, or from the shell::

    python -m enlace_connector.preflight https://apps.example.com

Checks are plain callables of a :class:`PreflightContext`, so a platform with extra
requirements passes its own ``checks=`` sequence to :func:`verify_deployment`
without this module knowing about them. The HTTP fetcher is likewise a parameter
(:func:`fetch_json` by default — stdlib only), which is what makes the whole thing
testable offline:

>>> md = {"grant_types_supported": ["authorization_code", "refresh_token"],
...       "jwks_uri": "https://p.example.com/auth/oauth/jwks"}
>>> ctx = PreflightContext(issuer="https://p.example.com", fetch=lambda url: md)
>>> check_refresh_grant_supported(ctx).ok
True
>>> print(check_refresh_grant_supported(ctx).summary)
authorization server advertises the refresh_token grant

A server missing the grant fails loudly, with the remedy attached:

>>> stale = PreflightContext(issuer="https://p.example.com",
...                          fetch=lambda url: {"grant_types_supported":
...                                             ["authorization_code"]})
>>> result = check_refresh_grant_supported(stale)
>>> bool(result)
False
>>> print(result.summary)
authorization server does NOT advertise the refresh_token grant...
"""

from __future__ import annotations

import json
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from functools import cached_property
from typing import Any, Callable, Iterable, Sequence

from .connector import ConnectorSpec

__all__ = [
    "AS_METADATA_PATH",
    "REFRESH_GRANT",
    "DFLT_TIMEOUT",
    "DFLT_REFRESH_TOKEN_TTL_SECONDS",
    "CheckResult",
    "PreflightContext",
    "PreflightError",
    "fetch_json",
    "authorization_server_metadata",
    "check_refresh_grant_supported",
    "check_jwks_uri_matches_convention",
    "DFLT_CHECKS",
    "verify_deployment",
    "format_report",
    "refresh_grant_check_commands",
    "main",
]

#: RFC 8414 discovery path, relative to the issuer origin.
AS_METADATA_PATH = "/.well-known/oauth-authorization-server"
#: The grant a long-lived connector session depends on.
REFRESH_GRANT = "refresh_token"
#: Seconds to wait on a discovery fetch before giving up.
DFLT_TIMEOUT = 10.0
#: Default refresh-token lifetime to configure on a platform (30 days). This is the
#: session longevity a connector inherits; ``0`` disables the grant entirely.
DFLT_REFRESH_TOKEN_TTL_SECONDS = 2592000

_NO_REFRESH_REMEDY = (
    "Clients will lose access at the first access-token expiry (typically 1h) with "
    "no way to renew: the connector process stays healthy while every session 401s, "
    "and a human must redo the interactive browser authorization to restore it. "
    "Fix the authorization server before calling this deployment good: upgrade the "
    "platform's enlace_auth to a build whose token endpoint implements the "
    "refresh_token grant, and set [auth.oauth_server] refresh_token_ttl_seconds > 0 "
    "in platform.toml (see deploy/oauth-server.toml in the connector bundle). Note "
    "that an installed-from-PyPI enlace_auth is NOT updated by editing a local "
    "checkout -- verify the version the running backend actually imports."
)


def fetch_json(url: str, *, timeout: float = DFLT_TIMEOUT) -> Any:
    """GET *url* and parse the response as JSON (stdlib only, no extra deps)."""
    with urllib.request.urlopen(url, timeout=timeout) as response:  # noqa: S310
        return json.loads(response.read().decode("utf-8"))


@dataclass(frozen=True)
class CheckResult:
    """Outcome of one preflight check.

    Truthy when the check passed, so ``all(results)`` reads naturally.

    Attributes:
        name: stable slug for the check (usable as a CI job/report key).
        ok: whether the checked property holds.
        summary: one line stating what was (or was not) observed.
        remedy: what to do about it — empty when ``ok``.
    """

    name: str
    ok: bool
    summary: str
    remedy: str = ""

    def __bool__(self) -> bool:
        return self.ok


@dataclass
class PreflightContext:
    """What a check is given: the target AS, the connector (if any), and a fetcher.

    Attributes:
        issuer: the authorization server's issuer origin (the platform origin).
        spec: the connector being verified — optional, so the AS itself can be
            preflighted before any connector exists.
        fetch: ``fetch(url) -> parsed_json``; defaults to :func:`fetch_json`. Pass
            your own to test offline, to add auth headers, or to use ``httpx``.
    """

    issuer: str
    spec: ConnectorSpec | None = None
    fetch: Callable[[str], Any] | None = field(default=None)

    def __post_init__(self) -> None:
        self.issuer = self.issuer.rstrip("/")
        if self.fetch is None:
            self.fetch = fetch_json

    @cached_property
    def metadata(self) -> dict[str, Any]:
        """The AS discovery document (fetched once per context, checked to be a doc)."""
        assert self.fetch is not None  # set in __post_init__
        metadata = self.fetch(self.metadata_url)
        if not isinstance(metadata, dict):
            raise ValueError(
                f"{self.metadata_url} did not serve a JSON object "
                f"(got {type(metadata).__name__}) — that is not an OAuth "
                "authorization server discovery document."
            )
        return metadata

    @property
    def metadata_url(self) -> str:
        """Where the AS discovery document lives."""
        return f"{self.issuer}{AS_METADATA_PATH}"


class PreflightError(RuntimeError):
    """Raised by :func:`verify_deployment` in ``strict`` mode when a check fails."""


def authorization_server_metadata(
    issuer: str, *, fetch: Callable[[str], Any] | None = None
) -> dict[str, Any]:
    """Fetch the RFC 8414 discovery document advertised by *issuer*."""
    return PreflightContext(issuer=issuer, fetch=fetch).metadata


def check_refresh_grant_supported(ctx: PreflightContext) -> CheckResult:
    """THE check: does the AS advertise ``refresh_token`` in ``grant_types_supported``?

    An authorization server that omits it can only ever hand out access tokens that
    expire into a dead end, which is invisible from the connector's own health.
    """
    grants = list(ctx.metadata.get("grant_types_supported") or [])
    ok = REFRESH_GRANT in grants
    if ok:
        summary = "authorization server advertises the refresh_token grant"
    else:
        summary = (
            "authorization server does NOT advertise the refresh_token grant "
            f"(grant_types_supported={grants!r} at {ctx.metadata_url}) — connector "
            "sessions will strand at the first access-token expiry"
        )
    return CheckResult(
        name="oauth_refresh_grant",
        ok=ok,
        summary=summary,
        remedy="" if ok else _NO_REFRESH_REMEDY,
    )


def check_jwks_uri_matches_convention(ctx: PreflightContext) -> CheckResult:
    """For ``auth="enlace"`` connectors: the AS's ``jwks_uri`` is the one we validate against.

    Catches an issuer/route drift that would make every token fail signature
    validation — a different symptom of "deployed, healthy, unusable".
    """
    from .auth import ENLACE_OAUTH_PATH

    name = "oauth_jwks_uri"
    if ctx.spec is not None and ctx.spec.auth != "enlace":
        return CheckResult(name, True, "not an enlace-issued connector — skipped")
    expected = f"{ctx.issuer}{ENLACE_OAUTH_PATH}/jwks"
    found = ctx.metadata.get("jwks_uri")
    ok = found == expected
    return CheckResult(
        name=name,
        ok=ok,
        summary=(
            f"jwks_uri is the expected {expected}"
            if ok
            else f"jwks_uri is {found!r}, expected {expected!r}"
        ),
        remedy=(
            ""
            if ok
            else (
                "The connector validates tokens against enlace_auth's conventional "
                "JWKS path. Either the issuer is wrong in the systemd unit "
                "(CONNECTOR_ISSUER) or the platform serves its OAuth endpoints "
                "elsewhere; reconcile before deploying."
            )
        ),
    )


#: The checks :func:`verify_deployment` runs by default (a sequence, so callers can
#: extend or replace it without this module knowing their requirements).
DFLT_CHECKS: tuple[Callable[[PreflightContext], CheckResult], ...] = (
    check_refresh_grant_supported,
    check_jwks_uri_matches_convention,
)


def _run(check: Callable[[PreflightContext], CheckResult], ctx: PreflightContext):
    """Run one check, turning an unreachable/malformed AS into a failed result."""
    try:
        return check(ctx)
    except (urllib.error.URLError, OSError, ValueError, KeyError, TypeError) as e:
        return CheckResult(
            name=getattr(check, "__name__", "check"),
            ok=False,
            summary=f"check could not run: {type(e).__name__}: {e}",
            remedy=(
                f"Could not read {ctx.metadata_url}. An authorization server that "
                "does not answer discovery cannot be verified — treat this as a "
                "failure, not as 'probably fine'."
            ),
        )


def verify_deployment(
    spec: ConnectorSpec | None = None,
    *,
    issuer: str,
    checks: Iterable[Callable[[PreflightContext], CheckResult]] = DFLT_CHECKS,
    fetch: Callable[[str], Any] | None = None,
    strict: bool = False,
) -> list[CheckResult]:
    """Run the preflight checks against *issuer*; return one result per check.

    This is the "is this deployment actually good?" gate — run it after deploying a
    connector (and, ideally, before), because the most consequential property of the
    platform is one the connector cannot observe about itself.

    Args:
        spec: the connector being verified (optional — the AS can be checked alone).
        issuer: the authorization server / platform origin.
        checks: the checks to run (defaults to :data:`DFLT_CHECKS`).
        fetch: ``fetch(url) -> parsed_json`` seam (defaults to :func:`fetch_json`).
        strict: raise :class:`PreflightError` if any check fails.

    >>> md = {"grant_types_supported": ["authorization_code"]}
    >>> results = verify_deployment(issuer="https://p.example.com",
    ...                             fetch=lambda url: md)
    >>> [r.name for r in results if not r]
    ['oauth_refresh_grant', 'oauth_jwks_uri']
    """
    ctx = PreflightContext(issuer=issuer, spec=spec, fetch=fetch)
    results = [_run(check, ctx) for check in checks]
    if strict and not all(results):
        raise PreflightError(format_report(results))
    return results


def format_report(results: Sequence[CheckResult]) -> str:
    """Render check results as a human-readable report (used by the CLI and errors).

    >>> print(format_report([CheckResult("a", True, "fine"),
    ...                      CheckResult("b", False, "broken", "fix it")]))
    PASS  a: fine
    FAIL  b: broken
          -> fix it
    """
    lines = []
    for r in results:
        lines.append(f"{'PASS' if r.ok else 'FAIL'}  {r.name}: {r.summary}")
        if r.remedy:
            lines.append(f"      -> {r.remedy}")
    return "\n".join(lines)


def refresh_grant_check_commands(issuer: str) -> str:
    """The copy-pasteable refresh-grant check, for runbooks and docs.

    >>> print(refresh_grant_check_commands("https://p.example.com/"))
    curl -s https://p.example.com/.well-known/oauth-authorization-server \\
         | python3 -c "import json,sys; print(json.load(sys.stdin).get('grant_types_supported'))"
    # must include 'refresh_token'; equivalently (exit code 1 on failure):
    python -m enlace_connector.preflight https://p.example.com
    """
    issuer = issuer.rstrip("/")
    return (
        f"curl -s {issuer}{AS_METADATA_PATH} \\\n"
        '     | python3 -c "import json,sys; '
        "print(json.load(sys.stdin).get('grant_types_supported'))\"\n"
        "# must include 'refresh_token'; equivalently (exit code 1 on failure):\n"
        f"python -m enlace_connector.preflight {issuer}"
    )


def main(argv: Sequence[str] | None = None) -> int:
    """CLI: ``python -m enlace_connector.preflight <issuer>`` → 0 if all checks pass."""
    import argparse

    parser = argparse.ArgumentParser(
        prog="python -m enlace_connector.preflight",
        description=(
            "Verify a platform's OAuth authorization server can keep connector "
            "sessions alive (refresh grant advertised, JWKS where we expect it)."
        ),
    )
    parser.add_argument("issuer", help="platform origin, e.g. https://apps.example.com")
    parser.add_argument(
        "--timeout", type=float, default=DFLT_TIMEOUT, help="HTTP timeout in seconds"
    )
    args = parser.parse_args(argv)

    def fetch(url: str) -> Any:
        return fetch_json(url, timeout=args.timeout)

    results = verify_deployment(issuer=args.issuer, fetch=fetch)
    print(format_report(results))
    return 0 if all(results) else 1


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())

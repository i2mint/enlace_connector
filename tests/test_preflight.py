"""Tests for the preflight/verify checks.

The whole point of these checks is a failure that is invisible from the connector
side, so every test drives them through the ``fetch`` seam with a canned
authorization-server discovery document — no network, no server.
"""

import urllib.error

import pytest

from enlace_connector import (
    CheckResult,
    ConnectorSpec,
    PreflightContext,
    PreflightError,
    authorization_server_metadata,
    check_jwks_uri_matches_convention,
    check_refresh_grant_supported,
    format_report,
    verify_deployment,
)
from enlace_connector import preflight as P

ISSUER = "https://apps.example.com"

GOOD_METADATA = {
    "issuer": ISSUER,
    "grant_types_supported": ["authorization_code", "refresh_token"],
    "jwks_uri": f"{ISSUER}/auth/oauth/jwks",
}
#: What the incident's server actually served: code grant only, no refresh.
STRANDING_METADATA = {
    "issuer": ISSUER,
    "grant_types_supported": ["authorization_code"],
    "jwks_uri": f"{ISSUER}/auth/oauth/jwks",
}

SPEC = ConnectorSpec(name="acme", tools=["acme.mcp:search"], route="/api/acme_mcp")


def fetcher(metadata, *, seen=None):
    def fetch(url):
        if seen is not None:
            seen.append(url)
        return metadata

    return fetch


def test_metadata_is_fetched_from_the_rfc8414_path_and_only_once():
    seen = []
    ctx = PreflightContext(issuer=ISSUER + "/", fetch=fetcher(GOOD_METADATA, seen=seen))
    assert ctx.metadata_url == f"{ISSUER}/.well-known/oauth-authorization-server"
    assert ctx.metadata is ctx.metadata  # cached: one fetch serves every check
    assert seen == [ctx.metadata_url]


def test_authorization_server_metadata_helper():
    md = authorization_server_metadata(ISSUER, fetch=fetcher(GOOD_METADATA))
    assert md == GOOD_METADATA


def test_refresh_grant_check_passes_when_advertised():
    ctx = PreflightContext(issuer=ISSUER, fetch=fetcher(GOOD_METADATA))
    result = check_refresh_grant_supported(ctx)
    assert result and result.ok and result.remedy == ""
    assert result.name == "oauth_refresh_grant"


def test_refresh_grant_check_fails_on_the_incident_configuration():
    ctx = PreflightContext(issuer=ISSUER, spec=SPEC, fetch=fetcher(STRANDING_METADATA))
    result = check_refresh_grant_supported(ctx)
    assert not result  # CheckResult is falsy when the check failed
    assert "does NOT advertise the refresh_token grant" in result.summary
    assert "['authorization_code']" in result.summary  # what was actually served
    assert "refresh_token_ttl_seconds" in result.remedy  # and how to fix it


@pytest.mark.parametrize("grants", [None, [], ["authorization_code"]])
def test_refresh_grant_check_fails_for_any_metadata_without_the_grant(grants):
    md = {"grant_types_supported": grants}
    ctx = PreflightContext(issuer=ISSUER, fetch=fetcher(md))
    assert not check_refresh_grant_supported(ctx)


def test_jwks_check_flags_drift_and_skips_non_enlace_connectors():
    drifted = dict(GOOD_METADATA, jwks_uri="https://elsewhere/jwks")
    ctx = PreflightContext(issuer=ISSUER, spec=SPEC, fetch=fetcher(drifted))
    assert not check_jwks_uri_matches_convention(ctx)
    idp_spec = ConnectorSpec(name="acme", tools=["m:f"], auth={"type": "jwt"})
    ctx2 = PreflightContext(issuer=ISSUER, spec=idp_spec, fetch=fetcher(drifted))
    assert check_jwks_uri_matches_convention(ctx2)  # someone else's AS: not our rule


def test_verify_deployment_reports_every_check():
    ok = verify_deployment(SPEC, issuer=ISSUER, fetch=fetcher(GOOD_METADATA))
    assert [r.name for r in ok] == ["oauth_refresh_grant", "oauth_jwks_uri"]
    assert all(ok)
    bad = verify_deployment(SPEC, issuer=ISSUER, fetch=fetcher(STRANDING_METADATA))
    assert not all(bad)
    assert [r.name for r in bad if not r] == ["oauth_refresh_grant"]


def test_verify_deployment_works_without_a_spec():
    assert all(verify_deployment(issuer=ISSUER, fetch=fetcher(GOOD_METADATA)))


def test_verify_deployment_strict_raises_with_the_report():
    with pytest.raises(PreflightError) as e:
        verify_deployment(
            SPEC, issuer=ISSUER, fetch=fetcher(STRANDING_METADATA), strict=True
        )
    assert "oauth_refresh_grant" in str(e.value)


def test_custom_checks_are_a_seam():
    calls = []

    def platform_specific_check(ctx):
        calls.append(ctx.issuer)
        return CheckResult("custom", True, "fine")

    results = verify_deployment(
        issuer=ISSUER, checks=[platform_specific_check], fetch=fetcher(GOOD_METADATA)
    )
    assert calls == [ISSUER] and [r.name for r in results] == ["custom"]


def test_unreachable_authorization_server_is_a_failure_not_an_exception():
    def boom(url):
        raise urllib.error.URLError("connection refused")

    results = verify_deployment(SPEC, issuer=ISSUER, fetch=boom)
    assert not any(results)
    assert "could not run" in results[0].summary


def test_malformed_metadata_is_a_failure_not_an_exception():
    results = verify_deployment(SPEC, issuer=ISSUER, fetch=lambda url: "not json")
    assert not any(results)


def test_format_report_marks_failures_and_shows_remedies():
    text = format_report(
        verify_deployment(SPEC, issuer=ISSUER, fetch=fetcher(STRANDING_METADATA))
    )
    assert "FAIL  oauth_refresh_grant" in text
    assert "PASS  oauth_jwks_uri" in text
    assert "->" in text  # the remedy is shown, not just the failure


def test_check_commands_are_copy_pasteable_and_name_the_grant():
    cmds = P.refresh_grant_check_commands(ISSUER + "/")
    assert f"{ISSUER}/.well-known/oauth-authorization-server" in cmds
    assert "grant_types_supported" in cmds and "refresh_token" in cmds
    assert "python -m enlace_connector.preflight" in cmds


def test_cli_exit_code_follows_the_checks(monkeypatch, capsys):
    monkeypatch.setattr(P, "fetch_json", lambda url, timeout=None: GOOD_METADATA)
    assert P.main([ISSUER]) == 0
    assert "PASS" in capsys.readouterr().out
    monkeypatch.setattr(P, "fetch_json", lambda url, timeout=None: STRANDING_METADATA)
    assert P.main([ISSUER]) == 1
    assert "FAIL" in capsys.readouterr().out

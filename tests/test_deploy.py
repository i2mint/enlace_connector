"""Tests for the deploy-bundle generators."""

import os

import pytest

from enlace_connector import (
    ConnectorSpec,
    generate_deploy_bundle,
    render_allowlist_toml,
    render_display_names_toml,
    render_oauth_server_toml,
    render_provision_script,
    render_runbook,
    render_systemd_unit,
    resource_url,
)

SPEC = ConnectorSpec(
    name="acme",
    tools=["acme.mcp:search"],
    title="Acme Knowledge",
    route="/api/acme_mcp",
    port=8031,
    extras=["ir", "sentence-transformers"],
    git_installs=["git+ssh://git@github.com/acme/acme"],
    data=[("~/.local/share/ir/corpora/acme", "{base}/xdg-data/ir/corpora/acme")],
    env={"XDG_DATA_HOME": "{base}/xdg-data", "HF_HOME": "{base}/hf-cache"},
    allowed_users=["a@acme.com", "b@acme.com"],
    post_install=['HF_HOME={base}/hf-cache {venv}/bin/python -c "import acme"'],
)

BASE = "/opt/tw_platform/connectors/acme"


def test_resource_url_is_route_plus_mcp():
    assert resource_url(SPEC) == "https://apps.thorwhalen.com/api/acme_mcp/mcp"


def test_systemd_unit_substitutes_and_binds_port():
    u = render_systemd_unit(SPEC)
    assert (
        f"ExecStart={BASE}/venv/bin/uvicorn server:app --host 127.0.0.1 --port 8031"
        in u
    )
    assert "WorkingDirectory=/opt/tw_platform/apps/acme" in u
    assert "Environment=CONNECTOR_ISSUER=https://apps.thorwhalen.com" in u
    assert f"Environment=XDG_DATA_HOME={BASE}/xdg-data" in u  # {base} substituted


def test_provision_script_has_venv_bootstrap_deps_and_unit():
    s = render_provision_script(SPEC)
    assert "get-pip.py" in s and "--without-pip" in s  # ensurepip-free bootstrap
    assert "git+ssh://git@github.com/acme/acme" in s
    assert "sentence-transformers" in s
    assert f"{BASE}/xdg-data/ir/corpora/acme" in s  # data dir mkdir, substituted
    assert (
        f"HF_HOME={BASE}/hf-cache {BASE}/venv/bin/python" in s
    )  # post_install substituted
    assert "systemctl enable --now" in s


def test_allowlist_toml_lists_resource_and_users_or_empty():
    t = render_allowlist_toml(SPEC)
    assert '"https://apps.thorwhalen.com/api/acme_mcp/mcp" = [' in t
    assert '"a@acme.com",' in t and '"b@acme.com",' in t
    # open connector → no allowlist
    assert render_allowlist_toml(ConnectorSpec(name="x", tools=["m:f"])) == ""


def test_display_names_toml_maps_resource_to_title_always_emitted():
    t = render_display_names_toml(SPEC)
    assert '"https://apps.thorwhalen.com/api/acme_mcp/mcp" = "Acme Knowledge"' in t
    assert "[auth.oauth_server.resource_display_names]" in t
    # emitted even for an unnamed connector -- falls back to spec.name via server_name
    unnamed = ConnectorSpec(name="x", tools=["m:f"])
    t2 = render_display_names_toml(unnamed)
    assert '"https://apps.thorwhalen.com/x-mcp/mcp" = "x"' in t2


def test_display_names_and_allowlist_toml_escape_quotes_and_backslashes():
    # a title/email with a literal " or \ must not break platform.toml's parse
    # -- these fragments are copy-pasted into it verbatim (render_runbook step 5)
    tricky = ConnectorSpec(
        name="acme",
        tools=["m:f"],
        title='Say "Hi" \\ Bot',
        allowed_users=['weird"user\\@acme.com'],
    )
    dn = render_display_names_toml(tricky)
    al = render_allowlist_toml(tricky)
    # escaped forms are present, verbatim (backslash then quote each escaped)
    assert '"Say \\"Hi\\" \\\\ Bot"' in dn
    assert '"weird\\"user\\\\@acme.com"' in al
    # and the raw, unescaped title/email must not appear anywhere
    assert 'Say "Hi" \\ Bot' not in dn
    assert 'weird"user\\@acme.com' not in al
    # round-trip through a real TOML parser when one is available (3.11+ stdlib)
    try:
        import tomllib
    except ModuleNotFoundError:
        return
    parsed_dn = tomllib.loads(dn)
    parsed_al = tomllib.loads(al)
    assert (
        parsed_dn["auth"]["oauth_server"]["resource_display_names"][
            resource_url(tricky)
        ]
        == 'Say "Hi" \\ Bot'
    )
    assert parsed_al["auth"]["oauth_server"]["resource_allowlist"][
        resource_url(tricky)
    ] == ['weird"user\\@acme.com']


def test_runbook_lists_data_ship_and_allowlist_step():
    r = render_runbook(SPEC)
    assert (
        f"rsync -az ~/.local/share/ir/corpora/acme/ tw:{BASE}/xdg-data/ir/corpora/acme/"
        in r
    )
    assert "provision-acme.sh" in r
    assert "allowlist.toml" in r
    assert "display-name.toml" in r


def test_oauth_server_toml_configures_session_longevity():
    t = render_oauth_server_toml(SPEC)
    assert "[auth.oauth_server]" in t
    assert "refresh_token_ttl_seconds = 2592000" in t  # 30 days, not 0
    # the fragment must be usable as-is, and land before the allowlist subtable
    assert t.index("[auth.oauth_server]") < t.index("refresh_token_ttl_seconds")
    assert "BEFORE any" in t and "resource_allowlist" in t
    # and it must say what happens without it
    assert "first access-token expiry" in t
    # TTL is a parameter, not a magic number baked into the template
    assert "refresh_token_ttl_seconds = 3600" in render_oauth_server_toml(
        SPEC, refresh_token_ttl_seconds=3600
    )


def test_oauth_server_toml_is_emitted_even_for_an_open_connector():
    # session longevity is platform-wide: it matters whether or not users are listed
    open_spec = ConnectorSpec(name="x", tools=["m:f"])
    assert render_allowlist_toml(open_spec) == ""
    assert "refresh_token_ttl_seconds" in render_oauth_server_toml(open_spec)


def test_runbook_states_the_silent_stranding_failure_and_the_check():
    r = render_runbook(SPEC)
    # the check that would have caught the incident, verbatim enough to paste
    assert ".well-known/oauth-authorization-server" in r
    assert "grant_types_supported" in r
    assert "python -m enlace_connector.preflight https://apps.thorwhalen.com" in r
    # and the plain-words warning: healthy-looking, needs a human, first expiry
    assert "refresh_token" in r
    assert "no way to renew" in r
    assert "systemd unit is active with zero restarts" in r
    assert "interactive browser" in r
    assert "oauth-server.toml" in r  # the fragment that fixes it


def test_generate_deploy_bundle_writes_all_artifacts(tmp_path):
    out = generate_deploy_bundle(SPEC, tmp_path / "acme")
    for rel in (
        "app.toml",
        "server.py",
        "deploy/acme-mcp.service",
        "deploy/provision-acme.sh",
        "deploy/allowlist.toml",
        "deploy/display-name.toml",
        "deploy/oauth-server.toml",
        "deploy/RUNBOOK.md",
    ):
        assert (tmp_path / "acme" / rel).exists(), rel
        assert out[rel] == tmp_path / "acme" / rel, rel  # returned map is accurate
    # server_py override is honored
    out2 = generate_deploy_bundle(
        SPEC, tmp_path / "acme2", server_py="# custom\napp = 1\n"
    )
    assert out2["server.py"].read_text() == "# custom\napp = 1\n"


@pytest.mark.skipif(
    os.name == "nt",
    reason=(
        "NTFS has no POSIX execute bit — Path.chmod on Windows only toggles the "
        "read-only flag, so the mode assertion is meaningless there. The provision "
        "script is a bash script that runs on the Linux server regardless of where "
        "the bundle was generated."
    ),
)
def test_provision_script_is_executable(tmp_path):
    out = generate_deploy_bundle(SPEC, tmp_path / "acme")
    assert out["deploy/provision-acme.sh"].stat().st_mode & 0o111


def test_bundle_ttl_is_settable_and_open_connectors_still_get_the_fragment(tmp_path):
    out = generate_deploy_bundle(
        ConnectorSpec(name="x", tools=["m:f"]),
        tmp_path / "x",
        refresh_token_ttl_seconds=604800,
    )
    assert "deploy/allowlist.toml" not in out  # open connector: no allowlist
    assert (
        "refresh_token_ttl_seconds = 604800"
        in out["deploy/oauth-server.toml"].read_text()
    )

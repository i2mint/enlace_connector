"""Tests for the deploy-bundle generators."""

from enlace_connector import (
    ConnectorSpec,
    generate_deploy_bundle,
    render_allowlist_toml,
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


def test_runbook_lists_data_ship_and_allowlist_step():
    r = render_runbook(SPEC)
    assert (
        f"rsync -az ~/.local/share/ir/corpora/acme/ tw:{BASE}/xdg-data/ir/corpora/acme/"
        in r
    )
    assert "provision-acme.sh" in r
    assert "allowlist.toml" in r


def test_generate_deploy_bundle_writes_all_artifacts(tmp_path):
    out = generate_deploy_bundle(SPEC, tmp_path / "acme")
    for rel in (
        "app.toml",
        "server.py",
        "deploy/acme-mcp.service",
        "deploy/provision-acme.sh",
        "deploy/allowlist.toml",
        "deploy/RUNBOOK.md",
    ):
        assert (tmp_path / "acme" / rel).exists(), rel
    # provision script is executable
    assert out["deploy/provision-acme.sh"].stat().st_mode & 0o111
    # server_py override is honored
    out2 = generate_deploy_bundle(
        SPEC, tmp_path / "acme2", server_py="# custom\napp = 1\n"
    )
    assert out2["server.py"].read_text() == "# custom\napp = 1\n"

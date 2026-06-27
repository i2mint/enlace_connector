"""Tests for the enlace app-dir scaffolding."""

from enlace_connector import (
    ConnectorSpec,
    render_app_toml,
    render_server_py,
    scaffold_app,
)

SPEC = ConnectorSpec(
    name="trufflepig",
    tools=["truffle.mcp:search_trufflepig"],
    auth="enlace",
    title="Trufflepig Knowledge",
    extras=["truffle"],
)


def test_render_app_toml_is_process_mode_and_public():
    toml = render_app_toml(SPEC, port=8030)
    assert 'mode = "process"' in toml
    assert 'access = "public"' in toml
    assert 'route = "/trufflepig-mcp"' in toml
    assert "port = 8030" in toml
    assert 'display_name = "Trufflepig Knowledge"' in toml


def test_render_server_py_embeds_spec_and_builds_app():
    src = render_server_py(SPEC)
    assert "ConnectorSpec(" in src
    assert "truffle.mcp:search_trufflepig" in src
    assert "make_connector_app(SPEC, issuer=_issuer)" in src
    assert "CONNECTOR_ISSUER" in src
    # The generated module must be syntactically valid Python.
    compile(src, "server.py", "exec")


def test_scaffold_app_writes_both_files(tmp_path):
    out = scaffold_app(SPEC, tmp_path / "trufflepig_mcp", port=8030)
    assert out["app_toml"].exists() and out["server_py"].exists()
    assert 'mode = "process"' in out["app_toml"].read_text()

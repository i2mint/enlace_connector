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
    assert "CONNECTOR_ISSUER" in src and "CONNECTOR_AUDIENCE" in src
    # The generated module must be syntactically valid Python.
    compile(src, "server.py", "exec")


def test_render_server_py_carries_stateless_http():
    """Every serve-time spec field must survive into the generated server.py.

    ``stateless_http`` used to be dropped, so a spec that deliberately asked for
    a stateful transport silently got the (default) stateless one in production.
    """
    stateful = ConnectorSpec(name="tp", tools=["m:f"], stateless_http=False)
    assert "stateless_http=False" in render_server_py(stateful)
    assert "stateless_http=True" in render_server_py(SPEC)  # default preserved


def test_scaffold_app_writes_both_files(tmp_path):
    out = scaffold_app(SPEC, tmp_path / "trufflepig_mcp", port=8030)
    assert out["app_toml"].exists() and out["server_py"].exists()
    assert 'mode = "process"' in out["app_toml"].read_text()


def test_server_py_passes_the_rendered_audience_through(monkeypatch):
    """The runtime takes $CONNECTOR_AUDIENCE as given, never re-deriving it (#12)."""
    import enlace_connector

    calls = []
    monkeypatch.setattr(
        enlace_connector, "make_connector_app", lambda spec, **kw: calls.append(kw)
    )
    src = render_server_py(SPEC)
    monkeypatch.setenv("CONNECTOR_ISSUER", "https://host")
    monkeypatch.setenv("CONNECTOR_AUDIENCE", "https://host/rendered")
    exec(compile(src, "server.py", "exec"), {})
    monkeypatch.delenv("CONNECTOR_AUDIENCE")
    exec(compile(src, "server.py", "exec"), {})  # an older unit: derive as before
    assert calls == [
        {"issuer": "https://host", "audience": "https://host/rendered"},
        {"issuer": "https://host", "audience": None},
    ]

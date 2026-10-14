"""The factory seams every live connector used to bypass it for (#3).

A spec now carries its icon, instructions, extra middleware and server hooks, so
a connector that needs them is still built by ``make_connector_app`` and
rendered by ``generate_deploy_bundle``; and two bundles never leak into each
other.
"""

import asyncio
import sys
import types

import pytest

pytest.importorskip("py2mcp")
from fastmcp.server.middleware import Middleware  # noqa: E402

from enlace_connector import (  # noqa: E402
    ConnectorSpec,
    generate_deploy_bundle,
    make_connector_app,
    make_stdio_server,
    render_server_py,
)
from enlace_connector import connector as connector_mod  # noqa: E402

TOOLS = ["os.path:basename"]
ICON = "data:image/png;base64,AAAA"


class _Tag(Middleware):
    def __init__(self, tag):
        self.tag = tag


@pytest.fixture
def hooks_module(monkeypatch):
    """An importable module holding the refs the specs below name."""
    mod = types.ModuleType("_ec_seams")

    def add_closure_tool(server):
        project = "bound-project"

        def which_project() -> str:
            return project

        server.tool(which_project)

    mod.add_closure_tool = add_closure_tool
    mod.gate = _Tag("gate")
    mod.pair = [_Tag("a"), _Tag("b")]
    mod.make_gate = lambda: _Tag("made")
    mod.not_middleware = 42
    monkeypatch.setitem(sys.modules, "_ec_seams", mod)
    return mod


def _tool_names(server):
    return sorted(t.name for t in asyncio.run(server.list_tools()))


def test_icon_and_instructions_reach_the_server():
    server = make_stdio_server(
        ConnectorSpec(name="x", tools=TOOLS, icon=ICON, instructions="Use me.")
    )
    [icon] = server.icons
    assert icon.src == ICON and server.instructions == "Use me."


def test_server_hooks_add_tools_that_are_not_refs(hooks_module):
    spec = ConnectorSpec(name="x", tools=TOOLS, server_hooks=["_ec_seams:add_closure_tool"])
    assert _tool_names(make_stdio_server(spec)) == ["basename", "which_project"]


def test_hosted_app_runs_hooks_and_orders_middleware(hooks_module, monkeypatch):
    seen = {}
    real = connector_mod._build_server

    def spy(spec, *, auth=None, middleware=None):
        seen["middleware"] = middleware
        seen["server"] = real(spec, auth=auth, middleware=middleware)
        return seen["server"]

    monkeypatch.setattr(connector_mod, "_build_server", spy)
    spec = ConnectorSpec(
        name="x",
        tools=TOOLS,
        auth="none",
        middleware=["_ec_seams:gate", "_ec_seams:pair", "_ec_seams:make_gate"],
        server_hooks=["_ec_seams:add_closure_tool"],
    )
    app = make_connector_app(spec, middleware=[_Tag("host")], settings={})
    assert callable(app)
    # the host's own middleware first, then the spec's, in the order named
    assert [m.tag for m in seen["middleware"]] == ["host", "gate", "a", "b", "made"]
    assert "which_project" in _tool_names(seen["server"])


def test_a_ref_that_is_not_middleware_is_refused(hooks_module):
    spec = ConnectorSpec(name="x", tools=TOOLS, auth="none", middleware=["_ec_seams:not_middleware"])
    with pytest.raises(TypeError, match="not a FastMCP Middleware"):
        make_connector_app(spec, settings={})


def test_rendered_server_carries_the_new_fields_only_when_set():
    plain = render_server_py(ConnectorSpec(name="x", tools=TOOLS))
    assert not any(f in plain for f in ("icon=", "instructions=", "middleware=", "server_hooks="))
    full = render_server_py(
        ConnectorSpec(
            name="x", tools=TOOLS, icon=ICON, instructions="Use me.",
            middleware=["m:gate"], server_hooks=["m:hook"],
        )
    )
    for line in (f"icon={ICON!r}", "instructions='Use me.'", "middleware=['m:gate']",
                 "server_hooks=['m:hook']"):
        assert line in full


def test_rendered_server_runs_with_an_icon_object(hooks_module, monkeypatch):
    """An mcp.types.Icon renders as a literal and the server.py actually executes."""
    from mcp.types import Icon

    monkeypatch.delenv("CONNECTOR_AUDIENCE", raising=False)
    spec = ConnectorSpec(
        name="x", tools=TOOLS, auth="none", icon=Icon(src=ICON, mimeType="image/png"),
        instructions="Use me.", middleware=["_ec_seams:gate"],
        server_hooks=["_ec_seams:add_closure_tool"],
    )
    namespace: dict = {}
    exec(compile(render_server_py(spec), "server.py", "exec"), namespace)
    assert callable(namespace["app"])
    assert namespace["SPEC"].icon == {"src": ICON, "mimeType": "image/png"}


def test_a_factory_needing_arguments_says_so(hooks_module):
    hooks_module.needs_args = lambda ledger: _Tag("x")
    spec = ConnectorSpec(name="x", tools=TOOLS, auth="none", middleware=["_ec_seams:needs_args"])
    with pytest.raises(TypeError, match="zero-argument factory"):
        make_connector_app(spec, settings={})


def _bundle_text(out) -> str:
    return "\n".join(p.read_text() for p in out.values() if p.is_file())


def test_two_bundles_share_no_identifier(tmp_path):
    """The issue's acceptance test: no artifact of one names the other."""
    specs = [
        ConnectorSpec(
            name="alphaconn", title="Alpha Atlas", tools=["alphapkg.tools:search"],
            port=8141, allowed_users=["owner@alpha.example"], icon="https://alpha.example/i.png",
            instructions="Alpha instructions.", middleware=["alphapkg.gate:meter"],
            server_hooks=["alphapkg.hooks:extra"], extras=["alphapkg"],
        ),
        ConnectorSpec(
            name="betaconn", title="Beta Bureau", tools=["betapkg.tools:lookup"],
            port=8142, allowed_users=["owner@beta.example"], icon="https://beta.example/i.png",
            instructions="Beta instructions.", middleware=["betapkg.gate:meter"],
            server_hooks=["betapkg.hooks:extra"], extras=["betapkg"],
        ),
    ]
    texts = [_bundle_text(generate_deploy_bundle(s, tmp_path / s.name)) for s in specs]

    def identifiers(s):
        return [s.name, s.title, str(s.port), s.allowed_users[0], s.icon, s.instructions,
                s.mount_route, *s.tools, *s.middleware, *s.server_hooks, *s.extras]

    for mine, other, text in ((specs[0], specs[1], texts[0]), (specs[1], specs[0], texts[1])):
        assert mine.title in text and mine.icon in text  # the bundle names itself...
        leaked = [i for i in identifiers(other) if i in text]
        assert not leaked, f"{mine.name}'s bundle names {other.name}'s {leaked}"

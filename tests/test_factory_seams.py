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

    def spy(spec, *, auth=None, middleware=None, **kw):
        seen["middleware"] = middleware
        seen["server"] = real(spec, auth=auth, middleware=middleware, **kw)
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


# --- instructions and version by reference (#3) -----------------------------

from enlace_connector import spec_instructions, spec_version  # noqa: E402
from enlace_connector.usage import usage_middleware  # noqa: E402


@pytest.fixture
def text_module(monkeypatch):
    mod = types.ModuleType("_ec_text")
    mod.INSTRUCTIONS = "Search the corpus."
    mod.__version__ = "3.1.4"
    mod.NOT_TEXT = 7
    monkeypatch.setitem(sys.modules, "_ec_text", mod)
    return mod


def test_instructions_by_reference_reach_the_server(text_module):
    spec = ConnectorSpec(name="x", tools=TOOLS, instructions="_ec_text:INSTRUCTIONS")
    assert spec_instructions(spec) == "Search the corpus."
    assert make_stdio_server(spec).instructions == "Search the corpus."
    text_module.INSTRUCTIONS = "Edited in the package."  # read where it is served
    assert make_stdio_server(spec).instructions == "Edited in the package."


@pytest.mark.parametrize(
    "prose", ["Use me.", "Note: search first", "see a:b c", "1.2:3", "x : y"]
)
def test_prose_is_never_taken_for_a_reference(prose):
    assert spec_instructions(ConnectorSpec(name="x", tools=[], instructions=prose)) == prose


def test_a_reference_to_something_else_than_text_is_refused(text_module):
    spec = ConnectorSpec(name="x", tools=[], instructions="_ec_text:NOT_TEXT")
    with pytest.raises(TypeError, match="names a int, not a str"):
        spec_instructions(spec)


def test_version_by_reference_and_by_distribution(text_module):
    assert spec_version(ConnectorSpec(name="x", tools=[], version="2.0")) == "2.0"
    assert spec_version(ConnectorSpec(name="x", tools=[], version="_ec_text:__version__")) == "3.1.4"
    from importlib.metadata import version

    assert spec_version(ConnectorSpec(name="x", tools=[], version_dist="pytest")) == version("pytest")
    both = ConnectorSpec(name="x", tools=[], version="2.0", version_dist="pytest")
    assert spec_version(both) == "2.0"  # an explicit version wins
    assert spec_version(ConnectorSpec(name="x", tools=[])) is None


def test_the_usage_log_records_the_resolved_version(text_module):
    spec = ConnectorSpec(name="x", tools=[], version="_ec_text:__version__")
    [logger] = usage_middleware(spec, sink=lambda record: None)
    assert logger.version == "3.1.4"


def test_rendered_server_keeps_references_and_usage_fields(text_module, monkeypatch):
    spec = ConnectorSpec(
        name="x", tools=TOOLS, auth="none", instructions="_ec_text:INSTRUCTIONS",
        version="_ec_text:__version__", version_dist="pytest", usage_outcome="m:classify",
    )
    src = render_server_py(spec)
    for line in ("instructions='_ec_text:INSTRUCTIONS'", "version='_ec_text:__version__'",
                 "version_dist='pytest'", "usage_outcome='m:classify'"):
        assert line in src
    plain = render_server_py(ConnectorSpec(name="x", tools=TOOLS))
    assert not any(f in plain for f in ("version=", "version_dist=", "usage_outcome="))


def test_a_version_that_cannot_be_resolved_degrades_to_a_label(caplog):
    assert spec_version(ConnectorSpec(name="x", tools=[], version=2)) == 2
    assert spec_version(ConnectorSpec(name="x", tools=[], version="v1:beta")) == "v1:beta"
    assert spec_version(
        ConnectorSpec(name="x", tools=[], version_dist="no-such-dist-xyz")
    ) is None
    assert "not installed" in caplog.text


def test_instructions_that_read_as_a_broken_reference_are_refused():
    spec = ConnectorSpec(name="x", tools=[], instructions="Note:x")
    with pytest.raises(ValueError, match="does not import"):
        spec_instructions(spec)

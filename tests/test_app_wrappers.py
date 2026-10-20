"""The ASGI wrap seam and builder-owned middleware ordering (#22).

A project-bound connector serves an extra mount next to the MCP endpoint, has its
own startup/shutdown work, and owns an authorization gate that must run before
metering. These tests serve such a connector from a rendered ``server.py`` and
check the middleware order on a real call, the lifespan chaining, and that the
MCP endpoint still answers after wrapping.
"""

import json
import sys
import types
from contextlib import asynccontextmanager

import pytest

pytest.importorskip("py2mcp")
from fastmcp.exceptions import ToolError  # noqa: E402
from fastmcp.server.middleware import Middleware  # noqa: E402
from starlette.applications import Starlette  # noqa: E402
from starlette.responses import PlainTextResponse  # noqa: E402
from starlette.routing import Route  # noqa: E402
from starlette.testclient import TestClient  # noqa: E402

from enlace_connector import (  # noqa: E402
    ConnectorSpec,
    chain_lifespan,
    make_connector_app,
    make_stdio_server,
    render_server_py,
)

TOOLS = ["os.path:basename"]
MCP_HEADERS = {"accept": "application/json, text/event-stream"}


class _Log(Middleware):
    """Appends its tag to *log* on every tool call; refuses the call if *deny*."""

    def __init__(self, tag, log, *, deny=False):
        self.tag, self.log, self.deny = tag, log, deny

    async def on_call_tool(self, context, call_next):
        self.log.append(self.tag)
        if self.deny:
            raise ToolError(f"{self.tag} refused the call")
        return await call_next(context)


@pytest.fixture
def wrap_module(monkeypatch):
    """An importable module holding the refs a project-bound connector names."""
    mod = types.ModuleType("_ec_wrap")
    mod.calls = []  # the order middleware saw a tool call in
    mod.events = []  # lifespan events of the wrapper's own work
    mod.deny = False

    def authz_hook(server):  # the builder's own gate, bound to the project
        return _Log("authz", mod.calls, deny=mod.deny)

    @asynccontextmanager
    async def downloads_lifespan(app):
        mod.events.append("downloads up")
        yield {"signer": "ready"}
        mod.events.append("downloads down")

    def add_downloads(app, server):
        async def download(request):
            return PlainTextResponse(f"signed by {request.state.signer}")

        app.mount("/downloads", Starlette(routes=[Route("/{name}", download)]))
        return chain_lifespan(app, downloads_lifespan)

    mod.authz_hook = authz_hook
    mod.meter = _Log("meter", mod.calls)
    mod.add_downloads = add_downloads
    mod.forgets_to_return = lambda app, server: None
    mod.returns_junk = lambda server: [42]
    mod.returns_tool = lambda server: server.tool(lambda: "hi", name="hi")
    monkeypatch.setitem(sys.modules, "_ec_wrap", mod)
    return mod


def _project_spec(**overrides):
    fields = dict(
        name="proj",
        tools=TOOLS,
        auth="none",
        middleware=["_ec_wrap:meter"],
        server_hooks=["_ec_wrap:authz_hook"],
        app_wrappers=["_ec_wrap:add_downloads"],
    )
    return ConnectorSpec(**{**fields, **overrides})


def _serve_rendered(spec, monkeypatch):
    """The ``app`` a rendered ``server.py`` for *spec* exposes."""
    monkeypatch.delenv("CONNECTOR_AUDIENCE", raising=False)
    monkeypatch.delenv("CONNECTOR_USAGE_LOG_DIR", raising=False)
    namespace: dict = {}
    exec(compile(render_server_py(spec), "server.py", "exec"), namespace)
    return namespace["app"]


def _rpc(client, method, params=None):
    """POST one JSON-RPC request to the MCP endpoint; the decoded response."""
    body = {"jsonrpc": "2.0", "id": 1, "method": method, "params": params or {}}
    r = client.post("/mcp", json=body, headers=MCP_HEADERS)
    assert r.status_code == 200, r.text
    if r.headers["content-type"].startswith("text/event-stream"):
        [data] = [ln[5:] for ln in r.text.splitlines() if ln.startswith("data:")]
        return json.loads(data)
    return r.json()


def _call_basename(client, path="/a/b.txt"):
    return _rpc(client, "tools/call", {"name": "basename", "arguments": {"p": path}})


def test_rendered_server_serves_mount_lifespan_and_mcp(wrap_module, monkeypatch):
    """The issue's acceptance: extra mount, own lifespan, builder-owned gate."""
    app = _serve_rendered(_project_spec(), monkeypatch)
    with TestClient(app) as client:
        assert wrap_module.events == ["downloads up"]
        assert client.get("/downloads/x.pdf").text == "signed by ready"
        init = _rpc(client, "initialize", {
            "protocolVersion": "2025-06-18", "capabilities": {},
            "clientInfo": {"name": "t", "version": "0"},
        })
        assert init["result"]["serverInfo"]["name"] == "proj"
        result = _call_basename(client)["result"]
        assert result["content"][0]["text"] == "b.txt"
    assert wrap_module.events == ["downloads up", "downloads down"]


def test_authz_runs_before_host_and_spec_middleware(wrap_module, monkeypatch):
    host = _Log("host", wrap_module.calls)
    app = make_connector_app(_project_spec(), middleware=[host], settings={})
    with TestClient(app) as client:
        _call_basename(client)
    assert wrap_module.calls == ["authz", "host", "meter"]


def test_a_call_authz_refuses_is_never_metered(wrap_module):
    wrap_module.deny = True
    app = make_connector_app(_project_spec(), settings={})
    with TestClient(app) as client:
        assert _call_basename(client)["result"]["isError"] is True
    assert wrap_module.calls == ["authz"]


def test_hooks_return_middleware_in_hook_order(wrap_module):
    wrap_module.second = lambda server: [_Log("authz2", wrap_module.calls)]
    wrap_module.none = lambda server: None
    spec = _project_spec(
        server_hooks=["_ec_wrap:authz_hook", "_ec_wrap:none", "_ec_wrap:second"],
        app_wrappers=[],
    )
    app = make_connector_app(spec, settings={})
    with TestClient(app) as client:
        _call_basename(client)
    assert wrap_module.calls == ["authz", "authz2", "meter"]


def test_stdio_ignores_returned_middleware(wrap_module):
    server = make_stdio_server(_project_spec())
    assert not any(isinstance(m, _Log) for m in server.middleware)


def test_a_hook_returning_a_list_of_something_else_is_refused(wrap_module):
    spec = _project_spec(server_hooks=["_ec_wrap:returns_junk"])
    with pytest.raises(TypeError, match="server hook '_ec_wrap:returns_junk' gave int"):
        make_connector_app(spec, settings={})


def test_a_hook_returning_a_tool_still_works(wrap_module):
    """Before #22 a hook's return was ignored; ``return server.tool(fn)`` still is."""
    spec = _project_spec(server_hooks=["_ec_wrap:returns_tool"], app_wrappers=[])
    with TestClient(make_connector_app(spec, settings={})) as client:
        _call_basename(client)
        tools = {t["name"] for t in _rpc(client, "tools/list")["result"]["tools"]}
    assert wrap_module.calls == ["meter"] and "hi" in tools


def test_a_refused_call_is_not_logged_as_usage(wrap_module, tmp_path):
    usage = tmp_path / "usage"
    settings = {"CONNECTOR_USAGE_LOG_DIR": str(usage)}

    def tool_calls():
        return [
            r for f in usage.glob("*.jsonl") for r in map(json.loads, f.read_text().splitlines())
            if r["event"] == "tool_call"
        ]

    with TestClient(make_connector_app(_project_spec(), settings=settings)) as client:
        _call_basename(client)
    [allowed] = tool_calls()
    assert allowed["tool"] == "basename" and wrap_module.calls == ["authz", "meter"]

    wrap_module.deny = True
    with TestClient(make_connector_app(_project_spec(), settings=settings)) as client:
        assert _call_basename(client)["result"]["isError"] is True
    assert tool_calls() == [allowed]  # authz refused it: neither metered nor logged
    assert wrap_module.calls == ["authz", "meter", "authz"]


def test_a_wrapper_must_return_the_app(wrap_module):
    spec = _project_spec(app_wrappers=["_ec_wrap:forgets_to_return"])
    with pytest.raises(TypeError, match="must return the app"):
        make_connector_app(spec, settings={})


def test_wrappers_apply_in_order_each_on_the_previous_result(wrap_module):
    from starlette.middleware.cors import CORSMiddleware

    seen = []

    def first(app, server):
        seen.append(app)
        return CORSMiddleware(chain_lifespan(app, _noop_lifespan), allow_origins=["*"])

    def second(app, server):
        seen.append((app, server))
        return app

    wrap_module.first, wrap_module.second = first, second
    spec = _project_spec(app_wrappers=["_ec_wrap:first", "_ec_wrap:second"])
    app = make_connector_app(spec, settings={})
    [built, (given, server)] = seen
    assert isinstance(given, CORSMiddleware) and given.app is built and app is given
    assert server.name == "proj"
    with TestClient(app) as client:  # the lifespan passes through the middleware
        assert _call_basename(client)["result"]["content"][0]["text"] == "b.txt"


@asynccontextmanager
async def _noop_lifespan(app):
    yield


def test_chain_lifespan_nests_inside_the_apps_own_and_merges_state():
    events = []

    @asynccontextmanager
    async def own(app):
        events.append("own up")
        yield {"a": 1, "shared": "own"}
        events.append("own down")

    @asynccontextmanager
    async def extra(app):
        events.append("extra up")
        yield {"b": 2, "shared": "extra"}
        events.append("extra down")

    async def state(request):
        s = request.state
        return PlainTextResponse(f"{s.a} {s.b} {s.shared}")

    app = chain_lifespan(Starlette(routes=[Route("/", state)], lifespan=own), extra)
    with TestClient(app) as client:
        assert client.get("/").text == "1 2 extra"
    assert events == ["own up", "extra up", "extra down", "own down"]


def test_chain_lifespan_takes_an_async_generator_and_runs_each_cycle(wrap_module):
    events = []

    async def counter(app):
        events.append("up")
        yield
        events.append("down")

    wrap_module.counted = lambda app, server: chain_lifespan(app, counter)
    app = make_connector_app(_project_spec(app_wrappers=["_ec_wrap:counted"]), settings={})
    for _ in range(2):  # FastMCP rebuilds its session manager each lifespan cycle
        with TestClient(app) as client:
            assert _call_basename(client)["result"]["content"][0]["text"] == "b.txt"
    assert events == ["up", "down", "up", "down"]


def test_chain_lifespan_refuses_what_is_not_a_starlette_app():
    async def bare_asgi(scope, receive, send):  # pragma: no cover - never called
        pass

    with pytest.raises(TypeError, match="needs a Starlette app"):
        chain_lifespan(bare_asgi, _noop_lifespan)


def test_rendered_server_carries_app_wrappers_only_when_set():
    assert "app_wrappers=" not in render_server_py(ConnectorSpec(name="x", tools=TOOLS))
    src = render_server_py(_project_spec())
    assert "app_wrappers=['_ec_wrap:add_downloads']" in src

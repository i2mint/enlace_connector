"""MCP sampling as a connector tool's LLM, with an offline fallback (#1).

Driven end to end through FastMCP's in-memory client: one with a sampling
handler (a client that samples), one without (Claude's clients today), one whose
handler fails mid-call.
"""

import asyncio

import pytest

pytest.importorskip("fastmcp")
from fastmcp import Client, FastMCP  # noqa: E402

from enlace_connector.sampling import (  # noqa: E402
    SamplingUnavailable,
    llm_tool,
    sampling_llm,
)


def search(query: str, limit: int = 3, *, llm=None) -> str:
    """Search the corpus; reformulate the query when an LLM is given."""
    q = llm(f"rewrite: {query}") if llm is not None else query
    return f"{q}|{limit}"


def _call(tool, args, **client_kwargs):
    server = FastMCP("t")
    server.tool(tool)

    async def go():
        async with Client(server, **client_kwargs) as client:
            tools = await client.list_tools()
            result = await client.call_tool(tool.__name__, args)
            return tools, result

    tools, result = asyncio.run(go())
    return tools, result.data


def _sampler(answer="sampled"):
    def handler(messages, params, context):
        return f"{answer}({messages[-1].content.text})"

    return handler


def test_offline_when_the_client_does_not_sample():
    tools, out = _call(llm_tool(search), {"query": "cats"})
    assert out == "cats|3"
    schema = tools[0].inputSchema["properties"]
    assert set(schema) == {"query", "limit"}  # no llm, no ctx in the tool's schema
    assert tools[0].description.startswith("Search the corpus")


def test_the_client_model_answers_when_it_samples():
    _, out = _call(llm_tool(search), {"query": "cats", "limit": 5}, sampling_handler=_sampler())
    assert out == "sampled(rewrite: cats)|5"


def test_the_fallback_runs_when_the_client_does_not_sample():
    tool = llm_tool(search, fallback=lambda p: "key:" + p)
    _, out = _call(tool, {"query": "cats"})
    assert out == "key:rewrite: cats|3"


def test_a_failing_sampling_request_falls_back_instead_of_failing():
    def broken(messages, params, context):
        raise RuntimeError("client refused")

    _, out = _call(llm_tool(search), {"query": "cats"}, sampling_handler=broken)
    assert out == "cats|3"  # offline
    tool = llm_tool(search, fallback=lambda p: "key")
    _, out = _call(tool, {"query": "cats"}, sampling_handler=broken)
    assert out == "key|3"


def test_sampling_can_be_switched_off():
    tool = llm_tool(search, use_sampling=False)
    _, out = _call(tool, {"query": "cats"}, sampling_handler=_sampler())
    assert out == "cats|3"


def test_decorator_form_and_a_fallback_by_reference(monkeypatch):
    import sys
    import types

    mod = types.ModuleType("_ec_llm")
    mod.chat = lambda p: "ref"
    monkeypatch.setitem(sys.modules, "_ec_llm", mod)

    @llm_tool(fallback="_ec_llm:chat")
    def find(query: str, *, llm=None) -> str:
        return llm(query) if llm else query

    _, out = _call(find, {"query": "x"})
    assert out == "ref"


@pytest.mark.parametrize(
    "fn, match",
    [
        (lambda query: query, "no 'llm' parameter"),
        (lambda query, ctx, llm=None: query, "already has a 'ctx'"),
    ],
)
def test_a_function_that_cannot_be_wrapped_is_refused(fn, match):
    with pytest.raises(TypeError, match=match):
        llm_tool(fn)


def test_an_async_function_is_refused():
    async def f(query, llm=None):
        return query

    with pytest.raises(TypeError, match="async"):
        llm_tool(f)


def test_sampling_llm_refuses_the_loop_thread_and_reports_failures():
    class Ctx:
        async def sample(self, prompt, **kw):
            raise ValueError("Client does not support sampling")

    async def go():
        llm = sampling_llm(Ctx())
        with pytest.raises(RuntimeError, match="worker thread"):
            llm("x")
        with pytest.raises(SamplingUnavailable, match="does not support"):
            await asyncio.to_thread(llm, "x")

    asyncio.run(go())

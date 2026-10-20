# enlace_connector.sampling

Run a connector tool’s LLM on the client’s model (MCP sampling), offline otherwise.

An *agentic* connector tool (query reformulation, LLM selection, a synopsis) needs
a `prompt -> str` callable. MCP *sampling* lets the server ask the connected
client’s model instead of a metered key: FastMCP exposes it as `ctx.sample`.
This module turns that into the sync callable the tool’s seams take, and makes
the tool degrade instead of fail when the client cannot sample.

**Client support (checked 2026-10).** Claude’s own MCP client (claude.ai,
Desktop, mobile, Cowork, Claude Code) lists sampling among the features it does
*not* yet support, so under Claude the tool runs on its fallback: a configured
`prompt -> str` (a key, or `coact.resolve_llm()` on a developer machine), or
no LLM at all (offline). Clients that advertise `sampling` get it with no code
change. Re-check when Claude’s connector docs change.

- [`client_supports_sampling()`](#enlace_connector.sampling.client_supports_sampling) — does this request’s client advertise it?
- [`sampling_llm()`](#enlace_connector.sampling.sampling_llm) — a sync `prompt -> str` over `ctx.sample`, to call
  from a worker thread (the tool’s seams are sync, the server loop is not).
- [`llm_tool()`](#enlace_connector.sampling.llm_tool) — wrap a sync `fn(..., llm=None)` into an async tool that
  picks the LLM per request (sampling, else *fallback*, else `None`), runs
  `fn` off the event loop, and retries on the fallback if sampling fails
  mid-call. The connector never hard-fails for want of an LLM.

```pycon
>>> def search(query: str, *, llm=None) -> str:
...     return query.upper() if llm is None else llm(query)
>>> tool = llm_tool(search)
>>> [p for p in tool.__signature__.parameters]
['query', 'ctx']
```

### Module Attributes

| [`DFLT_MAX_TOKENS`](#enlace_connector.sampling.DFLT_MAX_TOKENS)         | `max_tokens` of one sampling request (FastMCP's own default is 512, short for a synopsis).                                            |
|--------------------------------------------------------------------------|---------------------------------------------------------------------------------------------------------------------------------------|
| [`DFLT_SAMPLING_TIMEOUT_S`](#enlace_connector.sampling.DFLT_SAMPLING_TIMEOUT_S) | seconds one sampling request may take before it counts as unavailable; well under the 240 s a Claude client allows a whole tool call. |

### Functions

| [`client_supports_sampling`](#enlace_connector.sampling.client_supports_sampling)(ctx)                     | Whether the client behind *ctx* (a `fastmcp.Context`) advertises sampling.   |
|----------------------------------------------------------------------------------------------------|------------------------------------------------------------------------------|
| [`sampling_llm`](#enlace_connector.sampling.sampling_llm)(ctx, \*[, loop, system_prompt, ...]) | A sync `prompt -> str` that asks the client's model through `ctx.sample`.    |
| [`llm_tool`](#enlace_connector.sampling.llm_tool)([fn, llm_param, fallback, use_sampling]) | Wrap a sync `fn(..., llm=None)` into an async MCP tool that brings its LLM.  |

### Exceptions

| [`SamplingUnavailable`](#enlace_connector.sampling.SamplingUnavailable)   | The client cannot (or did not) answer a sampling request.   |
|------------------------------------------------------------------------|-------------------------------------------------------------|

### enlace_connector.sampling.DFLT_MAX_TOKENS *= 1024*

`max_tokens` of one sampling request (FastMCP’s own default is 512, short
for a synopsis).

### enlace_connector.sampling.DFLT_SAMPLING_TIMEOUT_S *= 60.0*

seconds one sampling request may take before it counts as unavailable;
well under the 240 s a Claude client allows a whole tool call.

### *exception* enlace_connector.sampling.SamplingUnavailable

Bases: [`RuntimeError`](https://docs.python.org/3/builtins/exceptions.html#RuntimeError)

The client cannot (or did not) answer a sampling request.

### enlace_connector.sampling.client_supports_sampling(ctx)

Whether the client behind *ctx* (a `fastmcp.Context`) advertises sampling.

`False` when it cannot be told (no session, an older SDK): the safe answer,
since the tool then runs on its fallback.

**Sampling needs a stateful session.** A connector served with
`stateless_http=True` (the `ConnectorSpec` default) builds a fresh
session per request that never saw the client’s `initialize`, so this is
always `False` there; set `stateless_http=False` on the spec for sampling.
That case is logged once, at info level, so it is not invisible.

* **Return type:**
  [`bool`](https://docs.python.org/3/builtins/functions.html#bool)

### enlace_connector.sampling.llm_tool(fn=None, , llm_param='llm', fallback=None, use_sampling=True, \*\*sampling_kwargs)

Wrap a sync `fn(..., llm=None)` into an async MCP tool that brings its LLM.

Per request, the LLM is: a [`sampling_llm()`](#enlace_connector.sampling.sampling_llm) when *use_sampling* and the
client advertises sampling; else *fallback* (a `prompt -> str`, or a
`"module:attr"` ref to one, resolved once, at wrap time); else `None`,
which `fn` must treat as “run offline”. If a sampling request fails while
`fn` runs, `fn` runs again with the fallback (or offline): the tool
answers either way. `fn` runs in a worker thread, so a slow search does not
block the server.

The rerun starts `fn` from the beginning, so `fn` must be safe to run
twice up to its first LLM call (a search is; a tool that writes before
asking the LLM is not). Only a failed sampling request triggers it, not a
[`SamplingUnavailable`](#enlace_connector.sampling.SamplingUnavailable) that `fn` raises itself. A cancelled request
cannot stop the worker thread, but its next LLM call raises at once.

The tool’s signature is `fn`’s minus *llm_param*, plus `ctx` (which
FastMCP injects and hides from the client); name and docstring are `fn`’s.
`sampling_kwargs` go to [`sampling_llm()`](#enlace_connector.sampling.sampling_llm) (`system_prompt`,
`max_tokens`, `temperature`, `timeout`). Usable bare or with arguments:
`@llm_tool` or `@llm_tool(fallback="mypkg.llm:chat")`.

### enlace_connector.sampling.sampling_llm(ctx, , loop=None, system_prompt=None, max_tokens=1024, temperature=None, timeout=60.0, cancelled=None)

A sync `prompt -> str` that asks the client’s model through `ctx.sample`.

Create it inside the async tool (so *loop* defaults to the running one) and
call it from a worker thread, as [`llm_tool()`](#enlace_connector.sampling.llm_tool) does: it schedules the
request on *loop* and waits for the answer. Calling it on the loop’s own
thread would deadlock, so that raises `RuntimeError`. Any failure of the
request (the client does not sample, it refused, it timed out) raises
[`SamplingUnavailable`](#enlace_connector.sampling.SamplingUnavailable). Once *cancelled* (an event the caller sets when
the request is abandoned) is set, every call raises at once, so a worker
thread left behind by a cancelled request stops at its next LLM call.

* **Return type:**
  [`Callable`](https://docs.python.org/3/library/typing.html#typing.Callable)[[[`str`](https://docs.python.org/3/builtins/stdtypes.html#str)], [`str`](https://docs.python.org/3/builtins/stdtypes.html#str)]

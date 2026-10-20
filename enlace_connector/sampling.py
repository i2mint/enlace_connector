"""Run a connector tool's LLM on the client's model (MCP sampling), offline otherwise.

An *agentic* connector tool (query reformulation, LLM selection, a synopsis) needs
a ``prompt -> str`` callable. MCP *sampling* lets the server ask the connected
client's model instead of a metered key: FastMCP exposes it as ``ctx.sample``.
This module turns that into the sync callable the tool's seams take, and makes
the tool degrade instead of fail when the client cannot sample.

**Client support (checked 2026-10).** Claude's own MCP client (claude.ai,
Desktop, mobile, Cowork, Claude Code) lists sampling among the features it does
*not* yet support, so under Claude the tool runs on its fallback: a configured
``prompt -> str`` (a key, or ``coact.resolve_llm()`` on a developer machine), or
no LLM at all (offline). Clients that advertise ``sampling`` get it with no code
change. Re-check when Claude's connector docs change.

- :func:`client_supports_sampling` — does this request's client advertise it?
- :func:`sampling_llm` — a sync ``prompt -> str`` over ``ctx.sample``, to call
  from a worker thread (the tool's seams are sync, the server loop is not).
- :func:`llm_tool` — wrap a sync ``fn(..., llm=None)`` into an async tool that
  picks the LLM per request (sampling, else *fallback*, else ``None``), runs
  ``fn`` off the event loop, and retries on the fallback if sampling fails
  mid-call. The connector never hard-fails for want of an LLM.

>>> def search(query: str, *, llm=None) -> str:
...     return query.upper() if llm is None else llm(query)
>>> tool = llm_tool(search)
>>> [p for p in tool.__signature__.parameters]
['query', 'ctx']
"""

from __future__ import annotations

import asyncio
import functools
import inspect
import logging
import typing
from typing import Any, Callable, Optional

__all__ = [
    "SamplingUnavailable",
    "client_supports_sampling",
    "sampling_llm",
    "llm_tool",
    "DFLT_MAX_TOKENS",
    "DFLT_SAMPLING_TIMEOUT_S",
]

logger = logging.getLogger(__name__)

LLMCallable = Callable[[str], str]

#: ``max_tokens`` of one sampling request (FastMCP's own default is 512, short
#: for a synopsis).
DFLT_MAX_TOKENS = 1024
#: seconds one sampling request may take before it counts as unavailable;
#: well under the 240 s a Claude client allows a whole tool call.
DFLT_SAMPLING_TIMEOUT_S = 60.0


class SamplingUnavailable(RuntimeError):
    """The client cannot (or did not) answer a sampling request."""


def client_supports_sampling(ctx: Any) -> bool:
    """Whether the client behind *ctx* (a ``fastmcp.Context``) advertises sampling.

    ``False`` when it cannot be told (no session, an older SDK): the safe answer,
    since the tool then runs on its fallback.
    """
    try:
        from mcp.types import ClientCapabilities, SamplingCapability

        return bool(
            ctx.session.check_client_capability(
                ClientCapabilities(sampling=SamplingCapability())
            )
        )
    except Exception:  # no session or no capability API: treat as unsupported
        return False


def sampling_llm(
    ctx: Any,
    *,
    loop: Optional[asyncio.AbstractEventLoop] = None,
    system_prompt: Optional[str] = None,
    max_tokens: int = DFLT_MAX_TOKENS,
    temperature: Optional[float] = None,
    timeout: float = DFLT_SAMPLING_TIMEOUT_S,
) -> LLMCallable:
    """A sync ``prompt -> str`` that asks the client's model through ``ctx.sample``.

    Create it inside the async tool (so *loop* defaults to the running one) and
    call it from a worker thread, as :func:`llm_tool` does: it schedules the
    request on *loop* and waits for the answer. Calling it on the loop's own
    thread would deadlock, so that raises ``RuntimeError``. Any failure of the
    request (the client does not sample, it refused, it timed out) raises
    :class:`SamplingUnavailable`.
    """
    loop = loop or asyncio.get_running_loop()

    def llm(prompt: str) -> str:
        try:
            running = asyncio.get_running_loop()
        except RuntimeError:
            running = None
        if running is loop:
            raise RuntimeError(
                "sampling_llm was called on the event loop's thread; call it from "
                "a worker thread (asyncio.to_thread), as llm_tool does"
            )
        coro = ctx.sample(
            prompt,
            system_prompt=system_prompt,
            max_tokens=max_tokens,
            temperature=temperature,
        )
        future = asyncio.run_coroutine_threadsafe(coro, loop)
        try:
            result = future.result(timeout)
        except Exception as exc:
            future.cancel()
            raise SamplingUnavailable(f"sampling failed: {exc}") from exc
        text = getattr(result, "text", result)
        if not isinstance(text, str):
            raise SamplingUnavailable(f"sampling returned no text ({type(text).__name__})")
        return text

    return llm


def _resolve_fallback(fallback: Any) -> Optional[LLMCallable]:
    """A ``prompt -> str``, a ``"module:attr"`` ref to one, or ``None`` (offline)."""
    if fallback is None or callable(fallback):
        return fallback
    if isinstance(fallback, str):
        from py2mcp.util import import_object

        obj = import_object(fallback)
        if not callable(obj):
            raise TypeError(f"fallback {fallback!r} is not callable")
        return obj
    raise TypeError(f"fallback must be a callable, a 'module:attr' ref or None, not {fallback!r}")


def llm_tool(
    fn: Optional[Callable] = None,
    *,
    llm_param: str = "llm",
    fallback: Any = None,
    use_sampling: bool = True,
    **sampling_kwargs: Any,
):
    """Wrap a sync ``fn(..., llm=None)`` into an async MCP tool that brings its LLM.

    Per request, the LLM is: a :func:`sampling_llm` when *use_sampling* and the
    client advertises sampling; else *fallback* (a ``prompt -> str``, or a
    ``"module:attr"`` ref to one, resolved once, at wrap time); else ``None``,
    which ``fn`` must treat as "run offline". If a sampling request fails while
    ``fn`` runs, ``fn`` runs again with the fallback (or offline): the tool
    answers either way. ``fn`` runs in a worker thread, so a slow search does not
    block the server.

    The tool's signature is ``fn``'s minus *llm_param*, plus ``ctx`` (which
    FastMCP injects and hides from the client); name and docstring are ``fn``'s.
    ``sampling_kwargs`` go to :func:`sampling_llm` (``system_prompt``,
    ``max_tokens``, ``temperature``, ``timeout``). Usable bare or with arguments:
    ``@llm_tool`` or ``@llm_tool(fallback="mypkg.llm:chat")``.
    """
    if fn is None:
        return functools.partial(
            llm_tool,
            llm_param=llm_param,
            fallback=fallback,
            use_sampling=use_sampling,
            **sampling_kwargs,
        )
    if inspect.iscoroutinefunction(fn):
        raise TypeError(f"llm_tool wraps a sync function; {fn.__name__} is async")
    sig = inspect.signature(fn)
    if llm_param not in sig.parameters:
        raise TypeError(f"{fn.__name__} takes no {llm_param!r} parameter to inject")
    if "ctx" in sig.parameters:
        raise TypeError(f"{fn.__name__} already has a 'ctx' parameter")
    fallback_llm = _resolve_fallback(fallback)

    from fastmcp import Context

    async def tool(*args, ctx: Context, **kwargs):
        def run(llm):
            return fn(*args, **{**kwargs, llm_param: llm})

        if use_sampling and client_supports_sampling(ctx):
            llm = sampling_llm(ctx, **sampling_kwargs)
            try:
                return await asyncio.to_thread(run, llm)
            except SamplingUnavailable as exc:
                logger.warning(
                    "%s: %s; running on the %s", fn.__name__, exc,
                    "fallback LLM" if fallback_llm else "offline path",
                )
        return await asyncio.to_thread(run, fallback_llm)

    try:  # resolved here: string annotations would not resolve in this module
        hints = typing.get_type_hints(fn)
    except Exception:
        hints = dict(getattr(fn, "__annotations__", {}))
    hints.pop(llm_param, None)
    params = [
        p.replace(annotation=hints.get(name, p.annotation))
        for name, p in sig.parameters.items()
        if name != llm_param
    ]
    ctx_param = inspect.Parameter("ctx", inspect.Parameter.KEYWORD_ONLY, annotation=Context)
    var_kw = [p for p in params if p.kind is inspect.Parameter.VAR_KEYWORD]
    params = [p for p in params if p.kind is not inspect.Parameter.VAR_KEYWORD]
    tool.__signature__ = sig.replace(
        parameters=[*params, ctx_param, *var_kw],
        return_annotation=hints.get("return", sig.return_annotation),
    )
    tool.__annotations__ = {**hints, "ctx": Context}
    tool.__name__ = fn.__name__
    tool.__qualname__ = getattr(fn, "__qualname__", fn.__name__)
    tool.__doc__ = fn.__doc__
    tool.__module__ = fn.__module__
    tool.__wrapped_llm_fn__ = fn
    return tool

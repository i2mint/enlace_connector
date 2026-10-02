"""Tests for switching the usage log on by configuration (enlace_connector.usage)."""

import asyncio
import json

import pytest
from fastmcp import Client

from enlace_connector import ConnectorSpec, make_connector_app, usage_middleware
from enlace_connector.deploy import render_systemd_unit
from enlace_connector.usage import (
    DFLT_RETENTION_DAYS,
    USAGE_LOG_ARGS,
    USAGE_LOG_DIR,
    USAGE_LOG_REDACT,
    USAGE_LOG_RETENTION_DAYS,
)

TOOLS = ["os.path:basename", "os.path:dirname"]
SPEC = ConnectorSpec(name="demo", tools=TOOLS, auth="none")


def test_off_unless_dir_is_set():
    assert usage_middleware(SPEC, settings={}) == []
    assert usage_middleware(SPEC, settings={USAGE_LOG_DIR: "  "}) == []


def test_on_with_dir_and_settings(tmp_path):
    from py2mcp.usage import JsonlSink, UsageLogger

    (mw,) = usage_middleware(
        SPEC,
        settings={
            USAGE_LOG_DIR: str(tmp_path / "usage"),
            USAGE_LOG_RETENTION_DAYS: "30",
            USAGE_LOG_REDACT: "api_key, token",
            USAGE_LOG_ARGS: "1",
        },
        version="2.0",
    )
    assert isinstance(mw, UsageLogger)
    assert mw.name == "demo" and mw.version == "2.0"
    assert mw.redact == {"api_key", "token"}
    assert mw.include_args is True
    assert isinstance(mw.sink, JsonlSink)
    assert mw.sink.root == tmp_path / "usage" and mw.sink.retention_days == 30


def test_retention_default_none_and_invalid(tmp_path):
    base = {USAGE_LOG_DIR: str(tmp_path)}
    (mw,) = usage_middleware(SPEC, settings=base)
    assert mw.sink.retention_days == DFLT_RETENTION_DAYS
    (mw,) = usage_middleware(SPEC, settings={**base, USAGE_LOG_RETENTION_DAYS: "none"})
    assert mw.sink.retention_days is None
    (mw,) = usage_middleware(SPEC, settings={**base, USAGE_LOG_RETENTION_DAYS: "0"})
    assert (
        mw.sink.retention_days == 0
    )  # today only -- the privacy direction, not "forever"
    (mw,) = usage_middleware(
        SPEC, settings={**base, USAGE_LOG_RETENTION_DAYS: "forever"}
    )
    assert mw.sink.retention_days is None
    with pytest.raises(ValueError, match="integer number of days"):
        usage_middleware(SPEC, settings={**base, USAGE_LOG_RETENTION_DAYS: "soon"})
    with pytest.raises(ValueError, match=">= 0"):
        usage_middleware(SPEC, settings={**base, USAGE_LOG_RETENTION_DAYS: "-1"})


def test_args_can_be_dropped(tmp_path):
    (mw,) = usage_middleware(
        SPEC, settings={USAGE_LOG_DIR: str(tmp_path), USAGE_LOG_ARGS: "false"}
    )
    assert mw.include_args is False
    with pytest.raises(ValueError, match=USAGE_LOG_ARGS):
        usage_middleware(
            SPEC, settings={USAGE_LOG_DIR: str(tmp_path), USAGE_LOG_ARGS: "flase"}
        )


def test_relative_dir_is_refused_and_tilde_expands(tmp_path, monkeypatch):
    for bad in ("logs/usage", "./usage", "usage"):
        with pytest.raises(ValueError, match="absolute"):
            usage_middleware(SPEC, settings={USAGE_LOG_DIR: bad})
    monkeypatch.setenv("HOME", str(tmp_path))
    (mw,) = usage_middleware(SPEC, settings={USAGE_LOG_DIR: "~/usage"})
    assert mw.sink.root == tmp_path / "usage"  # absolute after expansion, not <cwd>/~


def test_spec_version_and_outcome_ref_reach_the_logger(tmp_path):
    spec = ConnectorSpec(
        name="demo",
        tools=TOOLS,
        auth="none",
        version="3.1",
        usage_outcome="os.path:basename",
    )
    (mw,) = usage_middleware(spec, settings={USAGE_LOG_DIR: str(tmp_path)})
    import os.path

    assert mw.version == "3.1" and mw.outcome is os.path.basename
    (mw,) = usage_middleware(spec, settings={USAGE_LOG_DIR: str(tmp_path)}, version="9")
    assert mw.version == "9"


def test_a_code_sink_switches_logging_on(tmp_path):
    records = []
    (mw,) = usage_middleware(SPEC, settings={}, sink=records.append)
    assert mw.sink == records.append


def test_logger_kwargs_override_settings(tmp_path):
    sink = lambda record: None  # noqa: E731
    (mw,) = usage_middleware(
        SPEC, settings={USAGE_LOG_DIR: str(tmp_path)}, sink=sink, handshakes=False
    )
    assert mw.sink is sink and mw.handshakes is False


def test_make_connector_app_logs_when_configured(tmp_path):
    settings = {USAGE_LOG_DIR: str(tmp_path / "usage"), USAGE_LOG_REDACT: "p"}
    app = make_connector_app(SPEC, settings=settings)
    # the ASGI app wraps a FastMCP server; drive the server through its middleware
    # via the in-memory client rather than a port.
    from py2mcp import mk_mcp_from_refs

    server = mk_mcp_from_refs(
        TOOLS, name="demo", middleware=usage_middleware(SPEC, settings=settings)
    )

    async def go():
        async with Client(server) as c:
            return await c.call_tool("basename", {"p": "/a/b.txt"})

    assert asyncio.run(go()).content[0].text == "b.txt"
    assert callable(app)
    (day_file,) = (tmp_path / "usage").glob("*.jsonl")
    records = [json.loads(l) for l in day_file.read_text().splitlines()]
    call = [r for r in records if r["event"] == "tool_call"][0]
    assert call["tool"] == "basename" and call["args"] == {"p": "<redacted>"}
    assert call["server"] == "demo" and call["outcome"] == "ok"


def test_make_connector_app_off_by_default_and_accepts_extra_middleware(monkeypatch):
    monkeypatch.delenv(USAGE_LOG_DIR, raising=False)
    from fastmcp.server.middleware import Middleware

    class Gate(Middleware):
        pass

    assert callable(make_connector_app(SPEC))
    assert callable(make_connector_app(SPEC, middleware=Gate()))
    assert callable(make_connector_app(SPEC, middleware=[Gate(), Gate()]))
    assert callable(make_connector_app(SPEC, middleware=(g for g in [Gate()])))
    with pytest.raises(TypeError, match="ordered"):
        make_connector_app(SPEC, middleware={Gate()})


def test_systemd_unit_ships_the_switch_commented_out():
    spec = ConnectorSpec(name="acme", tools=TOOLS, port=8031)
    unit = render_systemd_unit(spec)
    assert (
        "#Environment=CONNECTOR_USAGE_LOG_DIR=/opt/tw_platform/connectors/acme/data/usage"
        in unit
    )
    assert "\nEnvironment=CONNECTOR_USAGE_LOG_DIR" not in unit  # off by default

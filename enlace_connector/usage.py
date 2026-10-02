"""Switch a connector's per-call usage log on by configuration alone.

The mechanism is :class:`py2mcp.usage.UsageLogger` (one record per tool call and
per handshake, to a sink). *Whether* a given deployed connector keeps that log,
*where*, for *how long*, and with *which arguments redacted* are host decisions,
so they are read here from one settings mapping — ``os.environ`` by default,
which is what a systemd unit's ``Environment=`` lines populate — and never
written into connector code:

- ``CONNECTOR_USAGE_LOG_DIR`` — the directory for the day files, **absolute**,
  one per connector. **Unset = off** (the default). Point it at the connector's
  own data root, off the deploy tree, e.g. ``<connectors>/<name>/data/usage``. A
  relative path or ``~`` is refused: the unit's working directory is the deploy
  tree, which is exactly where users' questions must never land.
- ``CONNECTOR_USAGE_LOG_RETENTION_DAYS`` — days of files to keep (default
  :data:`DFLT_RETENTION_DAYS`; ``0`` keeps today only; ``none`` keeps everything).
- ``CONNECTOR_USAGE_LOG_REDACT`` — comma-separated argument names whose values
  are replaced before the record is written (error text is then dropped too).
- ``CONNECTOR_USAGE_LOG_ARGS`` — ``0``/``false`` to drop the arguments entirely
  (keeping caller, tool, outcome, size and latency); anything other than a
  yes/no value is refused.

The spec's ``version`` and ``usage_outcome`` (a ``"module:function"`` ref to the
connector's own outcome classifier) are carried into the logger, so a connector
that knows its search tool's "no match" shape declares that once, in its spec.

:func:`usage_middleware` returns the list to pass as ``middleware=`` — empty when
logging is off, so a connector can wire it unconditionally::

    server = FastMCP(SPEC.server_name, auth=..., middleware=usage_middleware(SPEC))

:func:`make_connector_app` does this already. The arguments are the users' own
questions: turn this on for a client-facing connector only after telling them.
See py2mcp's ADR-0001 (``misc/docs/decisions/0001-usage-logging-is-a-py2mcp-middleware.md``).

>>> usage_middleware(ConnectorSpec(name="demo", tools=[]), settings={})
[]
>>> import tempfile
>>> (mw,) = usage_middleware(
...     ConnectorSpec(name="demo", tools=[]),
...     settings={"CONNECTOR_USAGE_LOG_DIR": tempfile.mkdtemp(),
...               "CONNECTOR_USAGE_LOG_REDACT": "api_key, token"},
... )
>>> mw.name, sorted(mw.redact), mw.sink.retention_days
('demo', ['api_key', 'token'], 90)
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any, Mapping, Optional

from .connector import ConnectorSpec

__all__ = [
    "usage_middleware",
    "USAGE_LOG_DIR",
    "USAGE_LOG_RETENTION_DAYS",
    "USAGE_LOG_REDACT",
    "USAGE_LOG_ARGS",
    "DFLT_RETENTION_DAYS",
]

#: Settings keys (environment variable names in the common case).
USAGE_LOG_DIR = "CONNECTOR_USAGE_LOG_DIR"
USAGE_LOG_RETENTION_DAYS = "CONNECTOR_USAGE_LOG_RETENTION_DAYS"
USAGE_LOG_REDACT = "CONNECTOR_USAGE_LOG_REDACT"
USAGE_LOG_ARGS = "CONNECTOR_USAGE_LOG_ARGS"

#: Default retention, in days, when the setting is absent.
DFLT_RETENTION_DAYS = 90

_TRUTHY = {"1", "true", "yes", "on"}
_FALSY = {"0", "false", "no", "off"}


def _flag(value: Optional[str], *, key: str, default: bool) -> bool:
    if value is None or value.strip() == "":
        return default
    v = value.strip().lower()
    if v in _TRUTHY:
        return True
    if v in _FALSY:
        return False
    raise ValueError(
        f"{key} must be one of 1/0, true/false, yes/no, on/off; got {value!r}"
    )


def _retention(value: Optional[str]) -> Optional[int]:
    if value is None or value.strip() == "":
        return DFLT_RETENTION_DAYS
    if value.strip().lower() in ("none", "forever"):
        return None
    try:
        days = int(value)
    except ValueError as exc:
        raise ValueError(
            f"{USAGE_LOG_RETENTION_DAYS} must be an integer number of days "
            f"(or 'none'), got {value!r}"
        ) from exc
    if days < 0:
        raise ValueError(f"{USAGE_LOG_RETENTION_DAYS} must be >= 0, got {days}")
    return days


def _names(value: Optional[str]) -> tuple[str, ...]:
    return tuple(n.strip() for n in (value or "").split(",") if n.strip())


def _log_dir(value: str) -> Path:
    path = Path(value.strip()).expanduser()
    if not path.is_absolute():
        raise ValueError(
            f"{USAGE_LOG_DIR} must be an absolute path (got {value!r}): a relative "
            "one resolves inside the connector's working directory, the deploy tree."
        )
    return path


def usage_middleware(
    spec: ConnectorSpec,
    *,
    settings: Optional[Mapping[str, str]] = None,
    version: Optional[str] = None,
    **logger_kwargs: Any,
) -> list:
    """The usage-logging middleware for *spec*, or ``[]`` when it is switched off.

    Args:
        spec: the connector; its ``name``, ``version`` and ``usage_outcome`` are
            carried into every record / the classifier.
        settings: where the ``CONNECTOR_USAGE_LOG_*`` keys are read from
            (default ``os.environ``). Pass a dict to configure in code or tests.
        version: overrides ``spec.version`` for the records.
        **logger_kwargs: forwarded to :class:`py2mcp.usage.UsageLogger` (e.g. a
            ``sink=`` for tests, or an ``outcome=`` callable). They override what
            the settings and the spec imply. Passing a ``sink`` switches logging
            on even without ``CONNECTOR_USAGE_LOG_DIR``.

    Returns:
        A one-element list (the ``UsageLogger``) when logging is on, else ``[]`` —
        always something ``middleware=`` accepts.

    Raises:
        ValueError: a setting is malformed (a relative log dir, a non-integer
            retention, an unrecognised yes/no). Loud at boot on purpose: these
            are configuration mistakes, not runtime conditions.
    """
    env = os.environ if settings is None else settings
    root = env.get(USAGE_LOG_DIR)
    sink = logger_kwargs.pop("sink", None)
    if sink is None and not (root and root.strip()):
        return []
    from py2mcp.usage import JsonlSink, UsageLogger

    kwargs: dict[str, Any] = {
        "name": spec.name,
        "version": version if version is not None else spec.version,
        "include_args": _flag(
            env.get(USAGE_LOG_ARGS), key=USAGE_LOG_ARGS, default=True
        ),
        "redact": _names(env.get(USAGE_LOG_REDACT)),
    }
    if spec.usage_outcome:
        from py2mcp.util import import_object

        kwargs["outcome"] = import_object(spec.usage_outcome)
    kwargs.update(logger_kwargs)
    if sink is None:
        sink = JsonlSink(
            _log_dir(root), retention_days=_retention(env.get(USAGE_LOG_RETENTION_DAYS))
        )
    return [UsageLogger(sink, **kwargs)]

# enlace_connector.usage

Switch a connector’s per-call usage log on by configuration alone.

The mechanism is `py2mcp.usage.UsageLogger` (one record per tool call and
per handshake, to a sink). *Whether* a given deployed connector keeps that log,
*where*, for *how long*, and with *which arguments redacted* are host decisions,
so they are read here from one settings mapping — `os.environ` by default,
which is what a systemd unit’s `Environment=` lines populate — and never
written into connector code:

- `CONNECTOR_USAGE_LOG_DIR` — the directory for the day files, **absolute**,
  one per connector. **Unset = off** (the default). Point it at the connector’s
  own data root, off the deploy tree, e.g. `<connectors>/<name>/data/usage`. A
  relative path or `~` is refused: the unit’s working directory is the deploy
  tree, which is exactly where users’ questions must never land.
- `CONNECTOR_USAGE_LOG_RETENTION_DAYS` — days of files to keep (default
  [`DFLT_RETENTION_DAYS`](#enlace_connector.usage.DFLT_RETENTION_DAYS); `0` keeps today only; `none` keeps everything).
- `CONNECTOR_USAGE_LOG_REDACT` — comma-separated argument names whose values
  are replaced before the record is written (error text is then dropped too).
- `CONNECTOR_USAGE_LOG_ARGS` — `0`/`false` to drop the arguments entirely
  (keeping caller, tool, outcome, size and latency); anything other than a
  yes/no value is refused.

The spec’s `version` and `usage_outcome` (a `"module:function"` ref to the
connector’s own outcome classifier) are carried into the logger, so a connector
that knows its search tool’s “no match” shape declares that once, in its spec.

[`usage_middleware()`](#enlace_connector.usage.usage_middleware) returns the list to pass as `middleware=` — empty when
logging is off, so a connector can wire it unconditionally:

```default
server = FastMCP(SPEC.server_name, auth=..., middleware=usage_middleware(SPEC))
```

`make_connector_app()` does this already. The arguments are the users’ own
questions: turn this on for a client-facing connector only after telling them.
See py2mcp’s ADR-0001 (`misc/docs/decisions/0001-usage-logging-is-a-py2mcp-middleware.md`).

```pycon
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
```

### Module Attributes

| [`USAGE_LOG_DIR`](#enlace_connector.usage.USAGE_LOG_DIR)       | Settings keys (environment variable names in the common case).   |
|----------------------------------------------------------------------|------------------------------------------------------------------|
| [`DFLT_RETENTION_DAYS`](#enlace_connector.usage.DFLT_RETENTION_DAYS) | Default retention, in days, when the setting is absent.          |

### Functions

| [`usage_middleware`](#enlace_connector.usage.usage_middleware)(spec, \*[, settings, version])   | The usage-logging middleware for *spec*, or `[]` when it is switched off.   |
|----------------------------------------------------------------------------------------------------|-----------------------------------------------------------------------------|

### enlace_connector.usage.DFLT_RETENTION_DAYS *= 90*

Default retention, in days, when the setting is absent.

### enlace_connector.usage.USAGE_LOG_DIR *= 'CONNECTOR_USAGE_LOG_DIR'*

Settings keys (environment variable names in the common case).

### enlace_connector.usage.usage_middleware(spec, , settings=None, version=None, \*\*logger_kwargs)

The usage-logging middleware for *spec*, or `[]` when it is switched off.

* **Parameters:**
  * **spec** ([`ConnectorSpec`](enlace_connector.connector.html.md#enlace_connector.connector.ConnectorSpec)) – the connector; its `name`, `version` and `usage_outcome` are
    carried into every record / the classifier.
  * **settings** ([`Optional`](https://docs.python.org/3/library/typing.html#typing.Optional)[[`Mapping`](https://docs.python.org/3/library/typing.html#typing.Mapping)[[`str`](https://docs.python.org/3/builtins/stdtypes.html#str), [`str`](https://docs.python.org/3/builtins/stdtypes.html#str)]]) – where the `CONNECTOR_USAGE_LOG_*` keys are read from
    (default `os.environ`). Pass a dict to configure in code or tests.
  * **version** ([`Optional`](https://docs.python.org/3/library/typing.html#typing.Optional)[[`str`](https://docs.python.org/3/builtins/stdtypes.html#str)]) – overrides `spec.version` for the records.
  * **\*\*logger_kwargs** ([`Any`](https://docs.python.org/3/library/typing.html#typing.Any)) – forwarded to `py2mcp.usage.UsageLogger` (e.g. a
    `sink=` for tests, or an `outcome=` callable). They override what
    the settings and the spec imply. Passing a `sink` switches logging
    on even without `CONNECTOR_USAGE_LOG_DIR`.
* **Return type:**
  [`list`](https://docs.python.org/3/builtins/stdtypes.html#list)
* **Returns:**
  A one-element list (the `UsageLogger`) when logging is on, else `[]` —
  always something `middleware=` accepts.
* **Raises:**
  [**ValueError**](https://docs.python.org/3/builtins/exceptions.html#ValueError) – a setting is malformed (a relative log dir, a non-integer
      retention, an unrecognised yes/no). Loud at boot on purpose: these
      are configuration mistakes, not runtime conditions.

# enlace_connector.preflight

Preflight/verify checks — is the target platform able to keep a connector *alive*?

A connector deployment can be perfectly healthy and still be **dead to its users**.
The failure this module exists to catch: the platform’s OAuth 2.1 authorization
server issues a short-lived access token and **no refresh token** (it does not
advertise `refresh_token` in `grant_types_supported`). Every client session then
hard-dies at the first token expiry — while the connector process stays green,
the port answers, and nothing errors anywhere. The only recovery is a human
re-running the interactive browser authorization, and the stock 401 challenge text
actively misinforms by claiming the client can renew on its own.

Nothing about the connector bundle can detect that from the inside, so it is a
*preflight of the authorization server*: fetch the AS’s discovery document at
`{issuer}/.well-known/oauth-authorization-server` and assert what it advertises.

Run it as a function, or from the shell:

```default
python -m enlace_connector.preflight https://apps.example.com
```

Checks are plain callables of a [`PreflightContext`](#enlace_connector.preflight.PreflightContext), so a platform with extra
requirements passes its own `checks=` sequence to [`verify_deployment()`](#enlace_connector.preflight.verify_deployment)
without this module knowing about them. The HTTP fetcher is likewise a parameter
([`fetch_json()`](#enlace_connector.preflight.fetch_json) by default — stdlib only), which is what makes the whole thing
testable offline:

```pycon
>>> md = {"grant_types_supported": ["authorization_code", "refresh_token"],
...       "jwks_uri": "https://p.example.com/auth/oauth/jwks"}
>>> ctx = PreflightContext(issuer="https://p.example.com", fetch=lambda url: md)
>>> check_refresh_grant_supported(ctx).ok
True
>>> print(check_refresh_grant_supported(ctx).summary)
authorization server advertises the refresh_token grant
```

A server missing the grant fails loudly, with the remedy attached:

```pycon
>>> stale = PreflightContext(issuer="https://p.example.com",
...                          fetch=lambda url: {"grant_types_supported":
...                                             ["authorization_code"]})
>>> result = check_refresh_grant_supported(stale)
>>> bool(result)
False
>>> print(result.summary)
authorization server does NOT advertise the refresh_token grant...
```

### Module Attributes

| [`AS_METADATA_PATH`](#enlace_connector.preflight.AS_METADATA_PATH)               | RFC 8414 discovery path, relative to the issuer origin.                                                                                                                                           |
|---------------------------------------------------------------------------------|---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------|
| [`REFRESH_GRANT`](#enlace_connector.preflight.REFRESH_GRANT)                  | The grant a long-lived connector session depends on.                                                                                                                                              |
| [`DFLT_TIMEOUT`](#enlace_connector.preflight.DFLT_TIMEOUT)                   | Seconds to wait on a discovery fetch before giving up.                                                                                                                                            |
| [`DFLT_REFRESH_TOKEN_TTL_SECONDS`](#enlace_connector.preflight.DFLT_REFRESH_TOKEN_TTL_SECONDS) | Default refresh-token lifetime to configure on a platform (30 days).                                                                                                                              |
| [`DFLT_CHECKS`](#enlace_connector.preflight.DFLT_CHECKS)                    | The checks [`verify_deployment()`](#enlace_connector.preflight.verify_deployment) runs by default (a sequence, so callers can extend or replace it without this module knowing their requirements). |

### Functions

| [`fetch_json`](#enlace_connector.preflight.fetch_json)(url, \*[, timeout])                     | GET *url* and parse the response as JSON (stdlib only, no extra deps).              |
|-----------------------------------------------------------------------------------------------------|-------------------------------------------------------------------------------------|
| [`authorization_server_metadata`](#enlace_connector.preflight.authorization_server_metadata)(issuer, \*[, fetch]) | Fetch the RFC 8414 discovery document advertised by *issuer*.                       |
| [`check_refresh_grant_supported`](#enlace_connector.preflight.check_refresh_grant_supported)(ctx)                 | THE check: does the AS advertise `refresh_token` in `grant_types_supported`?        |
| [`check_jwks_uri_matches_convention`](#enlace_connector.preflight.check_jwks_uri_matches_convention)(ctx)             | For `auth="enlace"` connectors: the AS's `jwks_uri` is the one we validate against. |
| [`verify_deployment`](#enlace_connector.preflight.verify_deployment)([spec, checks, fetch, strict])   | Run the preflight checks against *issuer*; return one result per check.             |
| [`format_report`](#enlace_connector.preflight.format_report)(results)                             | Render check results as a human-readable report (used by the CLI and errors).       |
| [`refresh_grant_check_commands`](#enlace_connector.preflight.refresh_grant_check_commands)(issuer)               | The copy-pasteable refresh-grant check, for runbooks and docs.                      |
| [`main`](#enlace_connector.preflight.main)([argv])                                       | CLI: `python -m enlace_connector.preflight <issuer>` → 0 if all checks pass.        |

### Classes

| [`CheckResult`](#enlace_connector.preflight.CheckResult)(name, ok, summary[, remedy])   | Outcome of one preflight check.                                              |
|---------------------------------------------------------------------------------------------|------------------------------------------------------------------------------|
| [`PreflightContext`](#enlace_connector.preflight.PreflightContext)(issuer[, spec, fetch])    | What a check is given: the target AS, the connector (if any), and a fetcher. |

### Exceptions

| [`PreflightError`](#enlace_connector.preflight.PreflightError)   | Raised by [`verify_deployment()`](#enlace_connector.preflight.verify_deployment) in `strict` mode when a check fails.   |
|-------------------------------------------------------------------|-----------------------------------------------------------------------------------------------------------------------|

### enlace_connector.preflight.AS_METADATA_PATH *= '/.well-known/oauth-authorization-server'*

RFC 8414 discovery path, relative to the issuer origin.

### *class* enlace_connector.preflight.CheckResult(name, ok, summary, remedy='')

Bases: [`object`](https://docs.python.org/3/builtins/functions.html#object)

Outcome of one preflight check.

Truthy when the check passed, so `all(results)` reads naturally.

#### name

stable slug for the check (usable as a CI job/report key).

#### ok

whether the checked property holds.

#### summary

one line stating what was (or was not) observed.

#### remedy

what to do about it — empty when `ok`.

### enlace_connector.preflight.DFLT_CHECKS *: [tuple](https://docs.python.org/3/builtins/stdtypes.html#tuple)[[Callable](https://docs.python.org/3/library/typing.html#typing.Callable)[[[PreflightContext](#enlace_connector.preflight.PreflightContext)], [CheckResult](#enlace_connector.preflight.CheckResult)], ...]* *= (<function check_refresh_grant_supported>, <function check_jwks_uri_matches_convention>)*

The checks [`verify_deployment()`](#enlace_connector.preflight.verify_deployment) runs by default (a sequence, so callers can
extend or replace it without this module knowing their requirements).

### enlace_connector.preflight.DFLT_REFRESH_TOKEN_TTL_SECONDS *= 2592000*

Default refresh-token lifetime to configure on a platform (30 days). This is the
session longevity a connector inherits; `0` disables the grant entirely.

### enlace_connector.preflight.DFLT_TIMEOUT *= 10.0*

Seconds to wait on a discovery fetch before giving up.

### *class* enlace_connector.preflight.PreflightContext(issuer, spec=None, fetch=None)

Bases: [`object`](https://docs.python.org/3/builtins/functions.html#object)

What a check is given: the target AS, the connector (if any), and a fetcher.

#### issuer

the authorization server’s issuer origin (the platform origin).

#### spec

the connector being verified — optional, so the AS itself can be
preflighted before any connector exists.

#### fetch

`fetch(url) -> parsed_json`; defaults to [`fetch_json()`](#enlace_connector.preflight.fetch_json). Pass
your own to test offline, to add auth headers, or to use `httpx`.

#### *property* metadata *: [dict](https://docs.python.org/3/builtins/stdtypes.html#dict)[[str](https://docs.python.org/3/builtins/stdtypes.html#str), [Any](https://docs.python.org/3/library/typing.html#typing.Any)]*

The AS discovery document (fetched once per context, checked to be a doc).

#### *property* metadata_url *: [str](https://docs.python.org/3/builtins/stdtypes.html#str)*

Where the AS discovery document lives.

### *exception* enlace_connector.preflight.PreflightError

Bases: [`RuntimeError`](https://docs.python.org/3/builtins/exceptions.html#RuntimeError)

Raised by [`verify_deployment()`](#enlace_connector.preflight.verify_deployment) in `strict` mode when a check fails.

### enlace_connector.preflight.REFRESH_GRANT *= 'refresh_token'*

The grant a long-lived connector session depends on.

### enlace_connector.preflight.authorization_server_metadata(issuer, , fetch=None)

Fetch the RFC 8414 discovery document advertised by *issuer*.

* **Return type:**
  [`dict`](https://docs.python.org/3/builtins/stdtypes.html#dict)[[`str`](https://docs.python.org/3/builtins/stdtypes.html#str), [`Any`](https://docs.python.org/3/library/typing.html#typing.Any)]

### enlace_connector.preflight.check_jwks_uri_matches_convention(ctx)

For `auth="enlace"` connectors: the AS’s `jwks_uri` is the one we validate against.

Catches an issuer/route drift that would make every token fail signature
validation — a different symptom of “deployed, healthy, unusable”.

* **Return type:**
  [`CheckResult`](#enlace_connector.preflight.CheckResult)

### enlace_connector.preflight.check_refresh_grant_supported(ctx)

THE check: does the AS advertise `refresh_token` in `grant_types_supported`?

An authorization server that omits it can only ever hand out access tokens that
expire into a dead end, which is invisible from the connector’s own health.

* **Return type:**
  [`CheckResult`](#enlace_connector.preflight.CheckResult)

### enlace_connector.preflight.fetch_json(url, , timeout=10.0)

GET *url* and parse the response as JSON (stdlib only, no extra deps).

* **Return type:**
  [`Any`](https://docs.python.org/3/library/typing.html#typing.Any)

### enlace_connector.preflight.format_report(results)

Render check results as a human-readable report (used by the CLI and errors).

* **Return type:**
  [`str`](https://docs.python.org/3/builtins/stdtypes.html#str)

```pycon
>>> print(format_report([CheckResult("a", True, "fine"),
...                      CheckResult("b", False, "broken", "fix it")]))
PASS  a: fine
FAIL  b: broken
      -> fix it
```

### enlace_connector.preflight.main(argv=None)

CLI: `python -m enlace_connector.preflight <issuer>` → 0 if all checks pass.

* **Return type:**
  [`int`](https://docs.python.org/3/builtins/functions.html#int)

### enlace_connector.preflight.refresh_grant_check_commands(issuer)

The copy-pasteable refresh-grant check, for runbooks and docs.

* **Return type:**
  [`str`](https://docs.python.org/3/builtins/stdtypes.html#str)

```pycon
>>> print(refresh_grant_check_commands("https://p.example.com/"))
curl -s https://p.example.com/.well-known/oauth-authorization-server \
     | python3 -c "import json,sys; print(json.load(sys.stdin).get('grant_types_supported'))"
# must include 'refresh_token'; equivalently (exit code 1 on failure):
python -m enlace_connector.preflight https://p.example.com
```

### enlace_connector.preflight.verify_deployment(spec=None, \*, issuer, checks=(<function check_refresh_grant_supported>, <function check_jwks_uri_matches_convention>), fetch=None, strict=False)

Run the preflight checks against *issuer*; return one result per check.

This is the “is this deployment actually good?” gate — run it after deploying a
connector (and, ideally, before), because the most consequential property of the
platform is one the connector cannot observe about itself.

* **Parameters:**
  * **spec** ([`ConnectorSpec`](enlace_connector.connector.md#enlace_connector.connector.ConnectorSpec) | [`None`](https://docs.python.org/3/builtins/constants.html#None)) – the connector being verified (optional — the AS can be checked alone).
  * **issuer** ([`str`](https://docs.python.org/3/builtins/stdtypes.html#str)) – the authorization server / platform origin.
  * **checks** ([`Iterable`](https://docs.python.org/3/library/typing.html#typing.Iterable)[[`Callable`](https://docs.python.org/3/library/typing.html#typing.Callable)[[[`PreflightContext`](#enlace_connector.preflight.PreflightContext)], [`CheckResult`](#enlace_connector.preflight.CheckResult)]]) – the checks to run (defaults to [`DFLT_CHECKS`](#enlace_connector.preflight.DFLT_CHECKS)).
  * **fetch** ([`Optional`](https://docs.python.org/3/library/typing.html#typing.Optional)[[`Callable`](https://docs.python.org/3/library/typing.html#typing.Callable)[[[`str`](https://docs.python.org/3/builtins/stdtypes.html#str)], [`Any`](https://docs.python.org/3/library/typing.html#typing.Any)]]) – `fetch(url) -> parsed_json` seam (defaults to [`fetch_json()`](#enlace_connector.preflight.fetch_json)).
  * **strict** ([`bool`](https://docs.python.org/3/builtins/functions.html#bool)) – raise [`PreflightError`](#enlace_connector.preflight.PreflightError) if any check fails.
* **Return type:**
  [`list`](https://docs.python.org/3/builtins/stdtypes.html#list)[[`CheckResult`](#enlace_connector.preflight.CheckResult)]

```pycon
>>> md = {"grant_types_supported": ["authorization_code"]}
>>> results = verify_deployment(issuer="https://p.example.com",
...                             fetch=lambda url: md)
>>> [r.name for r in results if not r]
['oauth_refresh_grant', 'oauth_jwks_uri']
```

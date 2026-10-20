"""Generate everything needed to deploy a connector on an enlace platform.

In production, enlace only *reverse-proxies* a ``mode="process"`` app's route to
``127.0.0.1:{port}`` — the connector's actual process runs under a **systemd
unit** in its **own venv** (enlace delegates production process management to
systemd). So a full deploy is more than an ``app.toml``; this module renders the
whole bundle from a :class:`~enlace_connector.connector.ConnectorSpec`:

- the **systemd unit** (runs the connector in its dedicated venv),
- the **provisioning script** (build that venv + install deps + create data dirs
  + install/start the unit — idempotent, run as root on the box),
- the **resource-allowlist** TOML fragment for ``platform.toml`` (access control),
- the **resource-display-names** TOML fragment (so the shared OAuth consent page
  shows *this* connector's name, not whichever connector configured it first —
  i2mint/enlace_auth#18),
- the **``[auth.oauth_server]``** fragment (session longevity — a platform without
  a refresh-token TTL strands every connector at its first token expiry),
- a **runbook** listing the human steps (ship data, provision, deploy, verify).

It generalizes the artifacts first hand-written for the trufflepig connector, so
deploying the next one is ``generate_deploy_bundle(spec)`` + following the runbook.
Platform specifics (paths, origin) are parameters with tw_platform defaults —
``enlace_connector`` stays connector-type-agnostic (it knows nothing of ``ir``).
"""

from __future__ import annotations

import re
import shlex
import unicodedata
from pathlib import Path
from urllib.parse import urlsplit

from .connector import ConnectorSpec
from .preflight import DFLT_REFRESH_TOKEN_TTL_SECONDS, refresh_grant_check_commands

__all__ = [
    "DFLT_REMOTE_BASE",
    "DFLT_ISSUER",
    "MCP_PATH",
    "DFLT_REFRESH_TOKEN_TTL_SECONDS",
    "resource_url",
    "render_systemd_unit",
    "diff_unit",
    "check_distinct_ports",
    "check_distinct_specs",
    "render_provision_script",
    "render_allowlist_toml",
    "allowlist_users",
    "ANY_ACCOUNT",
    "render_display_names_toml",
    "render_oauth_server_toml",
    "render_runbook",
    "generate_deploy_bundle",
]

#: Defaults for the tw_platform target (override per call for another platform).
DFLT_REMOTE_BASE = "/opt/tw_platform"
DFLT_ISSUER = "https://apps.thorwhalen.com"
#: FastMCP's Streamable-HTTP sub-path — the OAuth *resource* is ``route + MCP_PATH``.
MCP_PATH = "/mcp"

# Provisioning script template. Uses @@TOKEN@@ placeholders (not f-strings) so the
# shell's own ``${...}`` / ``$(...)`` never collide with Python string formatting.
_PROVISION_TEMPLATE = r"""#!/usr/bin/env bash
# Provision (or update) the @@NAME@@ connector. Run as ROOT on the server.
# Idempotent: builds the connector's own venv (heavy deps kept off the shared
# backend venv) and installs the systemd unit that runs it.
set -euo pipefail

BASE=@@BASE@@
VENV="$BASE/venv"
APP_DIR=@@APP_DIR@@
UNIT=@@UNIT@@
# Same base interpreter that built the shared venv (pyenv has venv+ensurepip; the
# bare system python3 may not). Override with $PYTHON.
PY_HOME=$(awk -F'= ' '/^home/{print $2}' @@REMOTE_BASE@@/venv/pyvenv.cfg 2>/dev/null)
PYTHON="${PYTHON:-${PY_HOME:-/usr/bin}/python}"

echo "==> dirs"; mkdir -p "$BASE"@@MKDIR_EXTRA@@

echo "==> venv ($PYTHON; --without-pip + get-pip, ensurepip unavailable here)"
rm -rf "$VENV"
"$PYTHON" -m venv --without-pip "$VENV"
curl -fsSL https://bootstrap.pypa.io/get-pip.py -o /tmp/get-pip-@@NAME@@.py
"$VENV/bin/python" /tmp/get-pip-@@NAME@@.py --quiet
"$VENV/bin/pip" install --quiet --upgrade pip

echo "==> deps"; "$VENV/bin/pip" install --quiet @@PIP_SPECS@@
@@POST@@
echo "==> systemd unit"
install -m 0644 "$(dirname "$0")/$UNIT" "/etc/systemd/system/$UNIT"
systemctl daemon-reload
systemctl enable --now "$UNIT"
systemctl --no-pager --lines=5 status "$UNIT" || true
echo "==> done. verify: curl -s http://127.0.0.1:@@PORT@@/ ; data under $BASE"
"""


def _toml_string(value: str) -> str:
    """Escape *value* for use inside a TOML basic (double-quoted) string.

    Both ``resource_allowlist`` and ``resource_display_names`` fragments are
    documented as copy-paste-into-``platform.toml`` output (see
    :func:`render_runbook`), so an unescaped ``"`` or ``\\`` in an interpolated
    value (an email, or — more plausibly — a freeform connector ``title``) would
    produce invalid TOML and break the *entire* platform config on paste, not
    just this connector's entry.
    """
    return value.replace("\\", "\\\\").replace('"', '\\"')


def _paths(spec: ConnectorSpec, remote_base: str) -> dict[str, str]:
    if spec.app_dir is not None and not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]*", spec.app_dir):
        raise ValueError(
            f"app_dir {spec.app_dir!r}: one directory name (letters, digits, '.', '_', "
            "'-'), not a path"
        )
    base = f"{remote_base}/connectors/{spec.dir_name}"
    return {
        "name": spec.name,
        "remote_base": remote_base,
        "base": base,
        "venv": f"{base}/venv",
        "app_dir": f"{remote_base}/apps/{spec.dir_name}",
        "unit": f"{spec.name}-mcp.service",
        "port": str(spec.port),
    }


def _subst(text: str, paths: dict[str, str]) -> str:
    """Substitute path placeholders (``{base}``, ``{venv}``, …) in *text*."""
    for key in ("base", "venv", "app_dir", "remote_base", "name", "port"):
        text = text.replace("{" + key + "}", paths[key])
    return text


_ENV_NAME = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")


def _systemd_environment_line(name: str, value: str) -> str:
    """One ``Environment=`` line that hands the process exactly ``name=value``.

    systemd expands ``%`` specifiers in these values, so a literal ``%`` (a
    percent-encoded route in ``CONNECTOR_AUDIENCE``, say) is written ``%%``.
    Without that, ``%2F`` is an "invalid slot" and systemd drops the whole line
    (#14). It also splits the line on whitespace and strips quotes, so such a
    value is double-quoted, with ``\\`` and ``"`` escaped. Plain values are
    left unquoted, so the line reads as it always has.

    >>> _systemd_environment_line("AUD", "https://h/api/a%2Fb-mcp")
    'Environment=AUD=https://h/api/a%%2Fb-mcp'
    >>> _systemd_environment_line("GREETING", 'say "hi" now')
    'Environment="GREETING=say \\\\"hi\\\\" now"'
    """
    if not _ENV_NAME.fullmatch(name):
        raise ValueError(f"not a valid environment variable name: {name!r}")
    bad = next(
        (c for c in value if c != "\t" and unicodedata.category(c) in ("Cc", "Cs")),
        None,
    )
    if bad is not None:
        raise ValueError(
            f"{name}: control character U+{ord(bad):04X} cannot go in a systemd "
            "Environment= line"
        )
    assignment = f"{name}={value}".replace("%", "%%")
    if any(c.isspace() or c in "\"'\\" for c in value):
        escaped = assignment.replace("\\", "\\\\").replace('"', '\\"')
        return f'Environment="{escaped}"'
    return f"Environment={assignment}"


def _non_canonical(url: str) -> str | None:
    """Why *url* is not the one spelling enlace_auth accepts as a resource key, if so.

    Mirrors ``enlace_auth.resource_policy`` (which refuses such a key when the platform
    config loads, taking every app down with it), without importing it: this package
    renders the key on a machine that need not have enlace_auth installed.
    """
    parts = urlsplit(url)
    if parts.scheme not in ("http", "https") or not parts.netloc:
        return "not an absolute http(s) URL"
    if any(c.isspace() or not c.isprintable() for c in url):
        # enlace_auth refuses whitespace; a control character would not even get
        # that far, since it makes the platform TOML unparseable.
        return "whitespace or a control character"
    if parts.query or parts.fragment or "@" in parts.netloc:
        return "a query, fragment or userinfo"
    if not url.startswith(parts.scheme + "://"):
        return "an uppercase scheme"
    if parts.netloc != parts.netloc.lower():
        return "an uppercase host"
    if (parts.hostname or "").endswith("."):
        return "a trailing dot on the host"
    try:
        port = parts.port
    except ValueError:
        return "a port that is not a number"
    if (parts.scheme, port) in (("https", 443), ("http", 80)):
        return "a default port written out"
    if any(seg in ("", ".", "..") for seg in parts.path.rstrip("/").split("/")[1:]):
        return "an empty, '.' or '..' path segment"
    return None


def resource_url(spec: ConnectorSpec, *, issuer: str = DFLT_ISSUER) -> str:
    """The connector's OAuth resource = its public MCP endpoint (``route + /mcp``).

    The result is the allowlist key, so it must be canonical: enlace_auth refuses any
    other spelling at config load. The route is normalized by
    :attr:`ConnectorSpec.mount_route`; an issuer that is not canonical (an uppercase
    host, a default port, a path segment that is empty or a dot) is refused here
    rather than lowercased, because the same issuer is the connector's runtime
    ``iss``/audience origin and must be fixed at its source (#10).

    >>> resource_url(ConnectorSpec(name="x", tools=[], route="/api/x_mcp/"))
    'https://apps.thorwhalen.com/api/x_mcp/mcp'
    """
    url = f"{issuer.rstrip('/')}{spec.mount_route}{MCP_PATH}"
    if why := _non_canonical(url):
        raise ValueError(
            f"resource URL {url!r} has {why}, so enlace_auth would refuse it as an "
            f"allowlist key and refuse to start. Spell the issuer {issuer!r} and the "
            f"route {spec.mount_route!r} canonically (lowercase scheme and host, no default "
            "port, no empty or dot path segments)."
        )
    return url


#: ``[Service]`` directives the renderer writes itself, each from its own spec
#: field; a ``service_directives`` entry may not repeat or override one.
_OWNED_DIRECTIVES = {
    "Type": None,
    "User": None,
    "WorkingDirectory": "app_dir",
    "Environment": "env",
    "EnvironmentFile": "environment_files",
    "ExecStartPre": "exec_start_pre",
    "ExecStart": "uvicorn_args",
    "Restart": None,
    "RestartSec": None,
}


def _unit_value(key: str, value: str) -> str:
    """*value*, checked for a ``key=`` line of a unit file, which it cannot span."""
    if not re.fullmatch(r"(X-)?[A-Za-z][A-Za-z0-9]*", key):
        raise ValueError(f"not a systemd directive name: {key!r}")
    bad = next(
        (c for c in value if unicodedata.category(c) in ("Cc", "Cs", "Zl", "Zp")),
        None,
    )
    if bad is not None:
        raise ValueError(
            f"{key}: control character U+{ord(bad):04X} cannot go in a unit file line"
        )
    if value.endswith("\\"):
        # A trailing backslash continues the line: the next directive (ExecStart=,
        # say) would become part of this value.
        raise ValueError(f"{key}: a value cannot end in a backslash: {value!r}")
    return value


def _service_directive(key: str, value: str) -> str:
    if key in _OWNED_DIRECTIVES:
        field = _OWNED_DIRECTIVES[key]
        hint = f"; use the spec's {field!r}" if field else ""
        raise ValueError(
            f"service_directives cannot set {key}=: the renderer writes it{hint}"
        )
    return _unit_value(key, value)


def _exec_start(spec: ConnectorSpec, p: dict[str, str]) -> str:
    """The ``uvicorn`` command line that runs the connector in its own venv."""
    for arg in spec.uvicorn_args:
        # Each is one token of ExecStart=, where whitespace splits, quotes group
        # and "%" is a specifier: refuse rather than mis-render.
        if not arg or arg == ";" or any(c.isspace() or c in "\"'%\\" for c in arg):
            raise ValueError(
                f"uvicorn argument {arg!r}: must be one non-empty token without "
                "whitespace, quotes, backslashes or '%', and not ';'"
            )
    return " ".join(
        [
            f"{p['venv']}/bin/uvicorn server:app --host 127.0.0.1 --port {spec.port}",
            *(_unit_value("ExecStart", a) for a in spec.uvicorn_args),
        ]
    )


def render_systemd_unit(
    spec: ConnectorSpec,
    *,
    remote_base: str = DFLT_REMOTE_BASE,
    issuer: str = DFLT_ISSUER,
) -> str:
    """Render the systemd unit that runs the connector in its own venv.

    A host that hand-maintains its units can treat this as the reference: run
    :func:`diff_unit` against each installed unit, so the two cannot drift apart
    silently (#15). The spec carries what such units need: an ``app_dir`` name,
    ``environment_files`` and ``exec_start_pre`` for scoped secrets,
    ``uvicorn_args``, and other ``service_directives``.

    ``CONNECTOR_AUDIENCE`` is rendered next to ``CONNECTOR_ISSUER`` by the same code
    that renders the allowlist key, and :func:`render_server_py` passes it through
    explicitly, so the runtime never re-derives it: a connector venv holding an older
    ``enlace_connector`` (whose ``mount_route`` spelled the route differently) still
    validates tokens for exactly the key the platform allows (#12).
    """
    p = _paths(spec, remote_base)
    for key in ("app_dir", "venv"):
        # These go into WorkingDirectory= and ExecStart= unquoted, where a "%" is
        # a specifier and whitespace splits the command line.
        if any(c == "%" or c.isspace() for c in p[key]):
            raise ValueError(
                f"{p[key]!r}: a connector path cannot contain '%' or whitespace "
                "(check the spec name and remote_base)"
            )
    env = {"CONNECTOR_ISSUER": issuer, **spec.env}
    # From the issuer the unit actually sets, so a spec.env override of it keeps
    # iss and aud from one origin; an explicit spec.env audience still wins.
    env.setdefault("CONNECTOR_AUDIENCE", spec.default_audience(env["CONNECTOR_ISSUER"]))
    env_lines = "\n".join(
        _systemd_environment_line(k, _subst(str(v), p)) for k, v in env.items()
    )
    exec_start = _exec_start(spec, p)
    service_lines = "".join(
        [
            *(
                f"{key}={_service_directive(key, _subst(value, p))}\n"
                for key, value in spec.service_directives
            ),
            *(
                f"ExecStartPre={_unit_value('ExecStartPre', _subst(cmd, p))}\n"
                for cmd in spec.exec_start_pre
            ),
            *(
                f"EnvironmentFile={_unit_value('EnvironmentFile', _subst(f, p))}\n"
                for f in spec.environment_files
            ),
        ]
    )
    description = f"{spec.server_name} MCP connector (mode=process :{spec.port})"
    description = description.replace("%", "%%")  # a specifier otherwise
    usage_log_line = _systemd_environment_line(
        "CONNECTOR_USAGE_LOG_DIR", f"{p['base']}/data/usage"
    )
    return (
        f"# {spec.name} connector — the production process for apps/{spec.dir_name}\n"
        "# (a mode=process enlace app). enlace only reverse-proxies the route to\n"
        f"# this unit on 127.0.0.1:{spec.port}; provisioned via the runbook.\n"
        "[Unit]\n"
        f"Description={description}\n"
        "After=network-online.target\n"
        "Wants=network-online.target\n\n"
        "[Service]\n"
        "Type=simple\n"
        "User=root\n"
        f"WorkingDirectory={p['app_dir']}\n"
        f"{env_lines}\n"
        "# Per-call usage logging (py2mcp ADR-0001): OFF until the line below is\n"
        "# uncommented. The arguments it records are the users' own questions, so\n"
        "# switch it on only after telling them. Files are pruned to 90 days by default\n"
        "# (CONNECTOR_USAGE_LOG_RETENTION_DAYS); CONNECTOR_USAGE_LOG_REDACT masks fields.\n"
        f"#{usage_log_line}\n"
        f"{service_lines}"
        f"ExecStart={exec_start}\n"
        "Restart=on-failure\n"
        "RestartSec=3\n\n"
        "[Install]\n"
        "WantedBy=multi-user.target\n"
    )


def render_provision_script(
    spec: ConnectorSpec, *, remote_base: str = DFLT_REMOTE_BASE
) -> str:
    """Render the idempotent, run-as-root provisioning script for the connector.

    Builds the dedicated venv (this box's ``ensurepip`` is unavailable, so
    ``--without-pip`` + ``get-pip.py``, using the same base interpreter that made
    the shared venv), installs ``extras`` + ``git_installs``, creates the data
    dirs, runs ``post_install`` (e.g. warm a model), and installs/starts the unit.
    """
    p = _paths(spec, remote_base)
    data_dirs = " ".join(shlex.quote(_subst(remote, p)) for _, remote in spec.data)
    pip_specs = " ".join(shlex.quote(s) for s in [*spec.extras, *spec.git_installs])
    post = "\n".join(_subst(cmd, p) for cmd in spec.post_install)
    repl = {
        "@@NAME@@": spec.name,
        "@@BASE@@": p["base"],
        "@@APP_DIR@@": p["app_dir"],
        "@@UNIT@@": p["unit"],
        "@@REMOTE_BASE@@": remote_base,
        "@@MKDIR_EXTRA@@": f" {data_dirs}" if data_dirs else "",
        "@@PIP_SPECS@@": pip_specs or "pip",
        "@@POST@@": post,
        "@@PORT@@": str(spec.port),
    }
    out = _PROVISION_TEMPLATE
    for token, value in repl.items():
        out = out.replace(token, value)
    return out


#: enlace_auth's spelling of "every authenticated account" in a resource
#: allowlist entry (``enlace_auth.resource_policy.ANY_ACCOUNT``).
ANY_ACCOUNT = "*"


def allowlist_users(spec: ConnectorSpec) -> list[str]:
    """``spec.allowed_users``, refused when it cannot mean what it seems to.

    enlace_auth fails closed: a resource missing from
    ``[auth.oauth_server.resource_allowlist]`` is refused to everyone
    (i2mint/enlace_auth#34). So an empty list no longer means "open". It
    would deploy a connector that nobody can authorize, and nothing would
    error until someone tried (#8). Opening a connector to every account is
    an explicit ``["*"]``.

    >>> from enlace_connector import ConnectorSpec
    >>> allowlist_users(ConnectorSpec(name="x", tools=["m:f"], allowed_users=["*"]))
    ['*']
    >>> allowlist_users(ConnectorSpec(name="x", tools=["m:f"]))
    Traceback (most recent call last):
    ...
    ValueError: Connector 'x' has no allowed_users...
    """
    if isinstance(spec.allowed_users, str):
        # list("*") == ["*"] would silently open the connector; list("a@b.com")
        # splits it into characters and breaks the pasted platform.toml.
        raise ValueError(
            f"Connector {spec.name!r}: allowed_users must be a list of emails, "
            f"got the string {spec.allowed_users!r}."
        )
    users = list(spec.allowed_users)
    if not users:
        raise ValueError(
            f"Connector {spec.name!r} has no allowed_users. The platform refuses "
            "every account for a resource it does not list, so this connector "
            "could not be authorized by anyone. List the emails allowed to use "
            f'it, or allowed_users=["{ANY_ACCOUNT}"] for every authenticated '
            "platform account."
        )
    if ANY_ACCOUNT in users and len(users) > 1:
        raise ValueError(
            f"Connector {spec.name!r}: allowed_users mixes {ANY_ACCOUNT!r} with "
            f"emails, but {ANY_ACCOUNT!r} already admits every account. Use "
            f"[{ANY_ACCOUNT!r}] alone, or only the emails."
        )
    bad = [u for u in users if u != ANY_ACCOUNT and not _is_plain_email(u)]
    if bad:
        # enlace_auth refuses these at config load, which takes the whole
        # platform down, not just this connector: refuse them here instead.
        raise ValueError(
            f"Connector {spec.name!r}: allowed_users entries must be plain emails "
            f"(or {ANY_ACCOUNT!r} alone): {bad!r}"
        )
    return users


def _is_plain_email(value: str) -> bool:
    """One ``local@domain``, no whitespace, no ``*``, no display-name form.

    >>> [_is_plain_email(v) for v in ("a@b.com", " a@b.com", "*@b.com", "a b <c@d>")]
    [True, False, False, False]
    """
    if not isinstance(value, str) or not value or value != value.strip():
        return False
    if any(c.isspace() for c in value) or any(c in value for c in "*<>,;"):
        return False
    local, sep, domain = value.partition("@")
    return bool(sep and local and domain and "@" not in domain)


def render_allowlist_toml(spec: ConnectorSpec, *, issuer: str = DFLT_ISSUER) -> str:
    """Render the ``[auth.oauth_server.resource_allowlist]`` fragment.

    Maps this connector's resource URL to the allowed emails (or ``"*"``) —
    paste into the platform's ``platform.toml``. Raises ``ValueError`` when
    ``allowed_users`` is empty: see :func:`allowlist_users`.
    """
    users = "\n".join(f'    "{_toml_string(u)}",' for u in allowlist_users(spec))
    return (
        "[auth.oauth_server.resource_allowlist]\n"
        f'"{_toml_string(resource_url(spec, issuer=issuer))}" = [\n{users}\n]\n'
    )


def render_display_names_toml(spec: ConnectorSpec, *, issuer: str = DFLT_ISSUER) -> str:
    """Render the ``[auth.oauth_server.resource_display_names]`` fragment.

    The shared OAuth consent page (``enlace_auth``) shows *some* product name to
    every user authorizing *any* connector on the platform — resolved from
    ``resource_display_names``, keyed by resource URL (see
    :func:`resource_url`), with a generic fallback when a resource has no entry.
    Before this existed, that string had to be hand-typed once in platform
    config and drifted the moment a second connector was added: every consent
    screen showed the *first* connector's name (i2mint/enlace_auth#18).

    This makes :attr:`ConnectorSpec.title` the single source instead — paste the
    fragment into the platform's ``platform.toml`` alongside
    :func:`render_allowlist_toml`'s.

    >>> from enlace_connector import ConnectorSpec
    >>> spec = ConnectorSpec(name="acme", tools=["m:f"], title="Acme Knowledge")
    >>> print(render_display_names_toml(spec))  # doctest: +ELLIPSIS
    [auth.oauth_server.resource_display_names]
    "https://apps.thorwhalen.com/acme-mcp/mcp" = "Acme Knowledge"
    <BLANKLINE>
    """
    return (
        "[auth.oauth_server.resource_display_names]\n"
        f'"{_toml_string(resource_url(spec, issuer=issuer))}" = '
        f'"{_toml_string(spec.server_name)}"\n'
    )


def render_oauth_server_toml(
    spec: ConnectorSpec,
    *,
    issuer: str = DFLT_ISSUER,
    refresh_token_ttl_seconds: int = DFLT_REFRESH_TOKEN_TTL_SECONDS,
) -> str:
    """Render the ``[auth.oauth_server]`` fragment that keeps sessions alive.

    Companion to :func:`render_allowlist_toml`: that one renders the
    ``[auth.oauth_server.resource_allowlist]`` *subtable*, this one the scalar keys
    of the parent table — so a **new** platform is configured for connector-length
    sessions from the start instead of inheriting a default that issues no refresh
    tokens. Paste this block *before* the allowlist fragment (TOML requires a
    table's own keys to precede its subtables).

    >>> from enlace_connector import ConnectorSpec
    >>> spec = ConnectorSpec(name="acme", tools=["m:f"])
    >>> print(render_oauth_server_toml(spec))  # doctest: +ELLIPSIS
    #...
    [auth.oauth_server]
    refresh_token_ttl_seconds = 2592000
    <BLANKLINE>
    """
    return (
        "# --- paste into the platform's platform.toml, BEFORE any\n"
        "# [auth.oauth_server.*] subtable (e.g. the resource_allowlist fragment) ---\n"
        "#\n"
        "# Session longevity for every connector this platform authorizes. The\n"
        "# authorization server only issues refresh tokens when this is > 0; with 0\n"
        f"# (or an older build that lacks the grant) every {spec.name} session dies at\n"
        "# the first access-token expiry and ONLY an interactive browser\n"
        "# re-authorization can revive it -- while the connector process itself keeps\n"
        "# looking perfectly healthy.\n"
        "#\n"
        "# The resource allowlist is re-evaluated on every refresh, so it doubles as\n"
        "# the revocation path: de-listing a user ends their access at the next\n"
        "# refresh (access tokens are self-contained JWTs and cannot be revoked).\n"
        "#\n"
        "# Verify the DEPLOYED server actually advertises the grant (config saying so\n"
        "# is not evidence -- the running build may be older):\n"
        f"#   python -m enlace_connector.preflight {issuer.rstrip('/')}\n"
        "[auth.oauth_server]\n"
        f"refresh_token_ttl_seconds = {refresh_token_ttl_seconds}\n"
    )


def render_runbook(
    spec: ConnectorSpec,
    *,
    remote_base: str = DFLT_REMOTE_BASE,
    issuer: str = DFLT_ISSUER,
) -> str:
    """Render the human deploy checklist (ship, provision, deploy, **verify**).

    The last step is the one that is easy to skip and expensive to skip: a
    connector whose authorization server cannot issue refresh tokens looks fully
    deployed and dies silently hours later, so the runbook states that failure mode
    in plain words and gives the exact command that detects it.
    """
    p = _paths(spec, remote_base)
    data_lines = (
        "\n".join(
            f"   rsync -az {local}/ tw:{_subst(remote, p)}/"
            for local, remote in spec.data
        )
        or "   (no data to ship)"
    )
    who = (
        "every authenticated platform account (`*`)"
        if allowlist_users(spec) == [ANY_ACCOUNT]
        else "who may authorize this connector; no one else can"
    )
    allow = (
        "5. Platform config fragments → the platform's `platform.toml`, then restart\n"
        "   the backend: `deploy/oauth-server.toml` (session longevity — paste first),\n"
        "   `deploy/display-name.toml` (what the consent screen calls this connector),\n"
        f"   then `deploy/allowlist.toml` ({who}). Skipping the allowlist does not\n"
        "   leave the connector open: the platform refuses every account for an\n"
        "   unlisted resource."
    )
    return (
        f"# Deploy runbook — {spec.name} connector\n\n"
        f"Public URL: `{resource_url(spec, issuer=issuer)}`\n\n"
        "1. Ship code: deploy the app dir (`app.toml` + `server.py`) via the "
        f"platform deploy (rsync to `{p['app_dir']}`).\n"
        "2. Ship data (rsynced separately from code):\n"
        f"{data_lines}\n"
        "3. Provision (root on the box): copy `deploy/` onto the server and run\n"
        f"   `ssh tw 'bash {p['base']}/provision-{spec.name}.sh'` — builds the venv,\n"
        "   installs deps, warms models, installs + starts the systemd unit.\n"
        "4. Deploy the platform config (route + backend restart) via the platform "
        "deploy tool.\n"
        f"{allow}\n"
        "6. Add the connector in the client (Claude.ai → custom connector → the "
        "public URL), or run it stdio locally for testing.\n"
        "7. **Verify — the deployment is not done until this passes:** run the\n"
        "   refresh-grant check below. Skipping it is how a connector ships broken\n"
        "   and looks fine for an hour.\n\n"
        "## The failure this verification exists to catch\n\n"
        "A client's MCP session lives on an access token that expires (typically one\n"
        "hour). If the platform's OAuth authorization server does not advertise the\n"
        "`refresh_token` grant, the client has **no way to renew**: the session dies\n"
        "at that expiry and stays dead until a human re-runs the interactive browser\n"
        "authorization. Everything you would normally look at says the connector is\n"
        "fine — the systemd unit is active with zero restarts, the port answers, the\n"
        "logs show no errors — because nothing *is* broken on this side. The 401 the\n"
        "client shows is worse than useless: it says the client should\n"
        '"automatically re-register and obtain new tokens", which is false — dynamic\n'
        "client registration yields a `client_id`, never a token. Expect the first\n"
        "signal to be a person telling you the connector has been down all day.\n\n"
        "So check the authorization server, not the connector:\n\n"
        "```\n"
        f"{refresh_grant_check_commands(issuer)}\n"
        "```\n\n"
        "If `refresh_token` is missing from `grant_types_supported`:\n\n"
        "- upgrade the platform's `enlace_auth` to a build whose token endpoint\n"
        "  implements the refresh grant, and check the version the running backend\n"
        "  actually imports (an installed-from-PyPI package is not updated by editing\n"
        "  a local checkout of it);\n"
        "- set `[auth.oauth_server] refresh_token_ttl_seconds` > 0 in `platform.toml`\n"
        "  (`deploy/oauth-server.toml` in this bundle) — 0 disables the grant;\n"
        "- re-run the check. Config that *says* refresh is enabled is not evidence;\n"
        "  only the deployed server's discovery document is.\n\n"
        "Two consequences worth knowing once refresh is on: refresh tokens rotate\n"
        "(each use returns a successor and replaying a consumed one revokes the whole\n"
        "family), and the resource allowlist is re-evaluated on **every** refresh —\n"
        "which makes de-listing a user the platform's real revocation path, taking\n"
        "effect at their next refresh rather than instantly.\n"
    )


def generate_deploy_bundle(
    spec: ConnectorSpec,
    dest: str | Path,
    *,
    remote_base: str = DFLT_REMOTE_BASE,
    issuer: str = DFLT_ISSUER,
    server_py: str | None = None,
    refresh_token_ttl_seconds: int = DFLT_REFRESH_TOKEN_TTL_SECONDS,
) -> dict[str, Path]:
    """Write the full deploy bundle for *spec* under *dest*.

    Writes the app dir (``app.toml`` + ``server.py``) and a ``deploy/`` folder (the
    systemd unit, provisioning script, the ``platform.toml`` fragments — OAuth
    session longevity, the display name and the resource allowlist — and the
    runbook). Raises ``ValueError``, writing nothing, when ``allowed_users`` is
    empty (see :func:`allowlist_users`). Pass *server_py* to override the generated entry module
    (e.g. a corpus-bound ``make_search`` server the composing skill wrote); pass
    *refresh_token_ttl_seconds* to set the session longevity the platform fragment
    configures (``0`` would disable the refresh grant — see
    :func:`render_oauth_server_toml`). Returns the written paths.
    """
    from .scaffold import render_app_toml, render_server_py

    # Refuse before writing anything: a half-written bundle for a connector no
    # one could authorize is worse than none.
    allowlist = render_allowlist_toml(spec, issuer=issuer)
    dest = Path(dest)
    (dest / "deploy").mkdir(parents=True, exist_ok=True)
    p = _paths(spec, remote_base)
    command = _exec_start(spec, p)

    written: dict[str, Path] = {}

    def _w(rel: str, text: str) -> None:
        path = dest / rel
        path.write_text(text, encoding="utf-8")
        written[rel] = path

    _w("app.toml", render_app_toml(spec, port=spec.port, command=command))
    _w("server.py", server_py if server_py is not None else render_server_py(spec))
    _w(
        f"deploy/{spec.name}-mcp.service",
        render_systemd_unit(spec, remote_base=remote_base, issuer=issuer),
    )
    prov = dest / "deploy" / f"provision-{spec.name}.sh"
    prov.write_text(
        render_provision_script(spec, remote_base=remote_base), encoding="utf-8"
    )
    prov.chmod(0o755)
    written[f"deploy/provision-{spec.name}.sh"] = prov
    _w(
        "deploy/oauth-server.toml",
        render_oauth_server_toml(
            spec, issuer=issuer, refresh_token_ttl_seconds=refresh_token_ttl_seconds
        ),
    )
    _w("deploy/display-name.toml", render_display_names_toml(spec, issuer=issuer))
    _w("deploy/allowlist.toml", allowlist)
    _w(
        "deploy/RUNBOOK.md",
        render_runbook(spec, remote_base=remote_base, issuer=issuer),
    )
    return written


def _clashes(specs, key, what: str) -> list[str]:
    """``"<what>: <value> (<names>)"`` for each *key* value two or more *specs* share."""
    by_value: dict = {}
    for spec in specs:
        by_value.setdefault(key(spec), []).append(spec.name)
    return [
        f"{what}: {value} ({', '.join(names)})"
        for value, names in sorted(by_value.items())
        if len(names) > 1
    ]


def check_distinct_ports(specs) -> None:
    """Refuse *specs* that would bind the same local port.

    ``port`` has a default, so two specs that both omit it render units that
    collide on one box, and the second connector never starts (#15). Prefer
    :func:`check_distinct_specs`, which also checks unit names and directories.

    >>> check_distinct_ports([ConnectorSpec(name="a", tools=[], port=8031),
    ...                       ConnectorSpec(name="b", tools=[], port=8032)])
    >>> check_distinct_ports([ConnectorSpec(name="a", tools=[]),
    ...                       ConnectorSpec(name="b", tools=[])])
    Traceback (most recent call last):
      ...
    ValueError: connectors share a port: 8030 (a, b)
    """
    clashes = _clashes(specs, lambda s: s.port, "a port")
    if clashes:
        raise ValueError("connectors share " + "; ".join(clashes))


def check_distinct_specs(specs) -> None:
    """Refuse *specs* that would collide on one host: same port, unit or directory.

    Run it over every connector a host deploys. Two specs collide when they bind
    the same ``port`` (it has a default), share a ``name`` (one
    ``<name>-mcp.service``, one resource URL), or share a directory under
    ``apps/`` and ``connectors/`` (``app_dir``, else ``name``): the second
    install would overwrite the first (#18). Every clash is listed in one error.

    >>> check_distinct_specs([ConnectorSpec(name="a", tools=[], port=8031),
    ...                       ConnectorSpec(name="b", tools=[], port=8032)])
    >>> check_distinct_specs([ConnectorSpec(name="a", tools=[], port=8031),
    ...                       ConnectorSpec(name="b", tools=[], port=8032, app_dir="a")])
    Traceback (most recent call last):
      ...
    ValueError: connectors share a directory: a (a, b)
    """
    specs = list(specs)
    clashes = [
        *_clashes(specs, lambda s: s.port, "a port"),
        *_clashes(specs, lambda s: s.name, "a unit name"),
        *_clashes(specs, lambda s: s.dir_name, "a directory"),
    ]
    if clashes:
        raise ValueError("connectors share " + "; ".join(clashes))


#: Unit lines :func:`diff_unit` ignores by default: prose, not behaviour.
DFLT_DIFF_IGNORE = frozenset({("Unit", "Description")})


#: systemd's C escapes (``cunescape``) with a one-character result
_C_ESCAPES = {
    "a": "\a", "b": "\b", "f": "\f", "n": "\n", "r": "\r", "t": "\t",
    "v": "\v", "\\": "\\", '"': '"', "'": "'", "s": " ",
}
#: ``\x``, ``\u``, ``\U`` escapes: how many hex digits follow
_HEX_ESCAPES = {"x": 2, "u": 4, "U": 8}


def _c_unescape(value: str, i: int) -> tuple[str, int]:
    """The character the C escape at ``value[i]`` (just after a backslash) stands
    for, and the index after it; ``ValueError`` where systemd's ``cunescape``
    fails."""
    if i >= len(value):
        raise ValueError(f"trailing backslash in {value!r}")
    e = value[i]
    if e in _C_ESCAPES:
        return _C_ESCAPES[e], i + 1
    if e in _HEX_ESCAPES:
        digits = value[i + 1 : i + 1 + _HEX_ESCAPES[e]]
        if not re.fullmatch(rf"[0-9A-Fa-f]{{{_HEX_ESCAPES[e]}}}", digits):
            raise ValueError(f"bad \\{e} escape in {value!r}")
        code, end = int(digits, 16), i + 1 + len(digits)
    elif re.fullmatch(r"[0-7]{3}", value[i : i + 3]):
        code, end = int(value[i : i + 3], 8), i + 3
    else:
        raise ValueError(f"unknown escape \\{e} in {value!r}")
    if code == 0 or code > 0x10FFFF:
        raise ValueError(f"escape out of range in {value!r}")
    return chr(code), end


def _split_environment(value: str) -> list[str]:
    r"""The words of an ``Environment=`` value, read as systemd reads them.

    systemd splits with ``extract_first_word(..., EXTRACT_UNQUOTE |
    EXTRACT_CUNESCAPE)``: words are separated by whitespace, ``'`` and ``"``
    quote anywhere in a word, and a backslash starts a C escape *inside quotes
    as well as outside* (``\n`` is a newline, ``\\`` one backslash, ``\x41``
    an ``A``). That is not POSIX shell: ``shlex`` reads an unquoted ``a\b`` as
    ``ab``, systemd as ``a`` + backspace + ``b``. An unknown escape makes systemd
    reject the line; here it raises ``ValueError`` (as do unbalanced quotes).

    >>> _split_environment(r'A=1 "B=two words" C=a\\b D=\x41 E="\101" F=x"y z"')
    ['A=1', 'B=two words', 'C=a\\b', 'D=A', 'E=A', 'F=xy z']
    """
    words: list[str] = []
    word: list[str] = []
    in_word, quote, i = False, "", 0
    while i < len(value):
        c = value[i]
        i += 1
        if c == "\\":
            ch, i = _c_unescape(value, i)
            word.append(ch)
            in_word = True
        elif quote:
            if c == quote:
                quote = ""
            else:
                word.append(c)
        elif c in "'\"":
            quote, in_word = c, True
        elif c.isspace():
            if in_word:
                words.append("".join(word))
                word, in_word = [], False
        else:
            word.append(c)
            in_word = True
    if quote:
        raise ValueError(f"unbalanced quotes in {value!r}")
    if in_word:
        words.append("".join(word))
    return words


def _parse_unit(text: str) -> dict[tuple[str, str], list[str]]:
    """``(section, key) -> values`` of a unit file, in order, comments dropped.

    ``Environment=`` is split into one ``NAME=value`` entry per assignment, with
    systemd's quoting, C escapes and ``%%`` undone (:func:`_split_environment`),
    so two spellings of the same environment compare equal. Other values are
    compared with whitespace runs collapsed. As in systemd, a comment line inside
    a backslash continuation is skipped, not joined into the value.
    """
    lines, pending = [], ""
    for raw in text.splitlines():
        line = raw.strip()
        if line[:1] in ("#", ";") or (not pending and not line):
            continue
        if line.endswith("\\"):
            pending += line[:-1] + " "
            continue
        lines.append(pending + line)
        pending = ""
    if pending:
        lines.append(pending)

    parsed: dict[tuple[str, str], list[str]] = {}
    section = ""
    for line in lines:
        if line.startswith("[") and line.endswith("]"):
            section = line[1:-1].strip()
            continue
        key, sep, value = line.partition("=")
        if not sep:
            continue
        key, value = key.strip(), value.strip()
        if key == "Environment" and not value:
            # An empty assignment resets the list, as in systemd.
            parsed[(section, key)] = []
            continue
        if key == "Environment":
            try:
                values = [a.replace("%%", "%") for a in _split_environment(value)]
            except ValueError:  # systemd would reject it: compare it as written
                values = [value]
        else:
            values = [" ".join(value.split())]
        parsed.setdefault((section, key), []).extend(values)
    return parsed


def _environment(assignments: list[str]) -> dict[str, str]:
    env: dict[str, str] = {}
    for assignment in assignments:
        name, _, value = assignment.partition("=")
        env[name] = value  # a later assignment wins, as in systemd
    return env


def diff_unit(
    spec: ConnectorSpec,
    installed: str,
    *,
    remote_base: str = DFLT_REMOTE_BASE,
    issuer: str = DFLT_ISSUER,
    ignore=DFLT_DIFF_IGNORE,
) -> list[str]:
    """How the *installed* unit text differs from what *spec* renders; ``[]`` if not.

    For a host that keeps its own unit files: run it per connector at deploy time
    and report the lines, so a unit and its spec cannot drift apart unnoticed
    (#15). The comparison is semantic: comments, blank lines, line order across
    directives, whitespace runs and ``Environment=`` quoting do not count; the
    order of repeated directives (``ExecStartPre=``) does. *ignore* is a set of
    ``(section, key)`` pairs left out (the ``Description=`` prose, by default).
    Drop-ins (``<unit>.d/*.conf``) are not read: pass the main unit file.

    >>> spec = ConnectorSpec(name="x", tools=[], port=8040)
    >>> diff_unit(spec, render_systemd_unit(spec))
    []
    >>> diff_unit(spec, render_systemd_unit(spec).replace("8040", "8041"))[0][:21]
    '[Service] ExecStart: '
    """
    want = _parse_unit(render_systemd_unit(spec, remote_base=remote_base, issuer=issuer))
    have = _parse_unit(installed)
    diffs: list[str] = []
    for section, key in sorted(want.keys() | have.keys()):
        if (section, key) in ignore:
            continue
        w, h = want.get((section, key), []), have.get((section, key), [])
        if key == "Environment":
            we, he = _environment(w), _environment(h)
            for name in sorted(we.keys() | he.keys()):
                if name not in he:
                    diffs.append(f"[{section}] Environment {name}: installed lacks it")
                elif name not in we:
                    diffs.append(f"[{section}] Environment {name}: not in the spec")
                elif we[name] != he[name]:
                    diffs.append(
                        f"[{section}] Environment {name}: rendered {we[name]!r}, "
                        f"installed {he[name]!r}"
                    )
        elif w != h:
            diffs.append(f"[{section}] {key}: rendered {w!r}, installed {h!r}")
    return diffs

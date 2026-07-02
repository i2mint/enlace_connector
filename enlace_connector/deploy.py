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
- a **runbook** listing the human steps (ship data, provision, deploy, connect).

It generalizes the artifacts first hand-written for the trufflepig connector, so
deploying the next one is ``generate_deploy_bundle(spec)`` + following the runbook.
Platform specifics (paths, origin) are parameters with tw_platform defaults —
``enlace_connector`` stays connector-type-agnostic (it knows nothing of ``ir``).
"""

from __future__ import annotations

import shlex
from pathlib import Path

from .connector import ConnectorSpec

__all__ = [
    "DFLT_REMOTE_BASE",
    "DFLT_ISSUER",
    "MCP_PATH",
    "resource_url",
    "render_systemd_unit",
    "render_provision_script",
    "render_allowlist_toml",
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


def _paths(spec: ConnectorSpec, remote_base: str) -> dict[str, str]:
    base = f"{remote_base}/connectors/{spec.name}"
    return {
        "name": spec.name,
        "remote_base": remote_base,
        "base": base,
        "venv": f"{base}/venv",
        "app_dir": f"{remote_base}/apps/{spec.name}",
        "unit": f"{spec.name}-mcp.service",
        "port": str(spec.port),
    }


def _subst(text: str, paths: dict[str, str]) -> str:
    """Substitute path placeholders (``{base}``, ``{venv}``, …) in *text*."""
    for key in ("base", "venv", "app_dir", "remote_base", "name", "port"):
        text = text.replace("{" + key + "}", paths[key])
    return text


def resource_url(spec: ConnectorSpec, *, issuer: str = DFLT_ISSUER) -> str:
    """The connector's OAuth resource = its public MCP endpoint (``route + /mcp``)."""
    return f"{issuer.rstrip('/')}{spec.mount_route}{MCP_PATH}"


def render_systemd_unit(
    spec: ConnectorSpec,
    *,
    remote_base: str = DFLT_REMOTE_BASE,
    issuer: str = DFLT_ISSUER,
) -> str:
    """Render the systemd unit that runs the connector in its own venv."""
    p = _paths(spec, remote_base)
    env = {"CONNECTOR_ISSUER": issuer, **spec.env}
    env_lines = "\n".join(
        f"Environment={k}={_subst(str(v), p)}" for k, v in env.items()
    )
    exec_start = (
        f"{p['venv']}/bin/uvicorn server:app --host 127.0.0.1 --port {spec.port}"
    )
    return (
        f"# {spec.name} connector — the production process for apps/{spec.name}\n"
        "# (a mode=process enlace app). enlace only reverse-proxies the route to\n"
        f"# this unit on 127.0.0.1:{spec.port}; provisioned via the runbook.\n"
        "[Unit]\n"
        f"Description={spec.server_name} MCP connector (mode=process :{spec.port})\n"
        "After=network-online.target\n"
        "Wants=network-online.target\n\n"
        "[Service]\n"
        "Type=simple\n"
        "User=root\n"
        f"WorkingDirectory={p['app_dir']}\n"
        f"{env_lines}\n"
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


def render_allowlist_toml(spec: ConnectorSpec, *, issuer: str = DFLT_ISSUER) -> str:
    """Render the ``[auth.oauth_server.resource_allowlist]`` fragment (or ``""``).

    Empty when ``allowed_users`` is empty (connector open to any authenticated
    user). Otherwise maps this connector's resource URL to the allowed emails —
    paste into the platform's ``platform.toml``.
    """
    if not spec.allowed_users:
        return ""
    users = "\n".join(f'    "{u}",' for u in spec.allowed_users)
    return (
        "[auth.oauth_server.resource_allowlist]\n"
        f'"{resource_url(spec, issuer=issuer)}" = [\n{users}\n]\n'
    )


def render_runbook(
    spec: ConnectorSpec,
    *,
    remote_base: str = DFLT_REMOTE_BASE,
    issuer: str = DFLT_ISSUER,
) -> str:
    """Render the human deploy checklist (ship data, provision, deploy, connect)."""
    p = _paths(spec, remote_base)
    data_lines = (
        "\n".join(
            f"   rsync -az {local}/ tw:{_subst(remote, p)}/"
            for local, remote in spec.data
        )
        or "   (no data to ship)"
    )
    allow = (
        "5. Add the allowlist fragment (`deploy/allowlist.toml`) to the platform's "
        "`platform.toml`, then restart the backend."
        if spec.allowed_users
        else "5. (No allowlist — open to any authenticated user.)"
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
    )


def generate_deploy_bundle(
    spec: ConnectorSpec,
    dest: str | Path,
    *,
    remote_base: str = DFLT_REMOTE_BASE,
    issuer: str = DFLT_ISSUER,
    server_py: str | None = None,
) -> dict[str, Path]:
    """Write the full deploy bundle for *spec* under *dest*.

    Writes the app dir (``app.toml`` + ``server.py``) and a ``deploy/`` folder (the
    systemd unit, provisioning script, allowlist fragment, runbook). Pass
    *server_py* to override the generated entry module (e.g. a corpus-bound
    ``make_search`` server the composing skill wrote). Returns the written paths.
    """
    from .scaffold import render_app_toml, render_server_py

    dest = Path(dest)
    (dest / "deploy").mkdir(parents=True, exist_ok=True)
    p = _paths(spec, remote_base)
    command = f"{p['venv']}/bin/uvicorn server:app --host 127.0.0.1 --port {spec.port}"

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
    allowlist = render_allowlist_toml(spec, issuer=issuer)
    if allowlist:
        _w("deploy/allowlist.toml", allowlist)
    _w(
        "deploy/RUNBOOK.md",
        render_runbook(spec, remote_base=remote_base, issuer=issuer),
    )
    return written

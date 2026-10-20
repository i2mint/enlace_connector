"""Tests for the deploy-bundle generators."""

import os
import shutil
import subprocess

import pytest

from enlace_connector import (
    ConnectorSpec,
    generate_deploy_bundle,
    render_allowlist_toml,
    render_display_names_toml,
    render_oauth_server_toml,
    render_provision_script,
    render_runbook,
    render_systemd_unit,
    resource_url,
)
from enlace_connector.deploy import DFLT_ISSUER, MCP_PATH

SPEC = ConnectorSpec(
    name="acme",
    tools=["acme.mcp:search"],
    title="Acme Knowledge",
    route="/api/acme_mcp",
    port=8031,
    extras=["ir", "sentence-transformers"],
    git_installs=["git+ssh://git@github.com/acme/acme"],
    data=[("~/.local/share/ir/corpora/acme", "{base}/xdg-data/ir/corpora/acme")],
    env={"XDG_DATA_HOME": "{base}/xdg-data", "HF_HOME": "{base}/hf-cache"},
    allowed_users=["a@acme.com", "b@acme.com"],
    post_install=['HF_HOME={base}/hf-cache {venv}/bin/python -c "import acme"'],
)

BASE = "/opt/tw_platform/connectors/acme"


def test_resource_url_is_route_plus_mcp():
    assert resource_url(SPEC) == "https://apps.thorwhalen.com/api/acme_mcp/mcp"


def test_systemd_unit_substitutes_and_binds_port():
    u = render_systemd_unit(SPEC)
    assert (
        f"ExecStart={BASE}/venv/bin/uvicorn server:app --host 127.0.0.1 --port 8031"
        in u
    )
    assert "WorkingDirectory=/opt/tw_platform/apps/acme" in u
    assert "Environment=CONNECTOR_ISSUER=https://apps.thorwhalen.com" in u
    assert f"Environment=XDG_DATA_HOME={BASE}/xdg-data" in u  # {base} substituted


def test_provision_script_has_venv_bootstrap_deps_and_unit():
    s = render_provision_script(SPEC)
    assert "get-pip.py" in s and "--without-pip" in s  # ensurepip-free bootstrap
    assert "git+ssh://git@github.com/acme/acme" in s
    assert "sentence-transformers" in s
    assert f"{BASE}/xdg-data/ir/corpora/acme" in s  # data dir mkdir, substituted
    assert (
        f"HF_HOME={BASE}/hf-cache {BASE}/venv/bin/python" in s
    )  # post_install substituted
    assert "systemctl enable --now" in s


def test_allowlist_toml_lists_resource_and_users_or_refuses():
    t = render_allowlist_toml(SPEC)
    assert '"https://apps.thorwhalen.com/api/acme_mcp/mcp" = [' in t
    assert '"a@acme.com",' in t and '"b@acme.com",' in t
    # no users → refused, never silently "open" (enlace_auth fails closed, #8)
    with pytest.raises(ValueError, match="no allowed_users"):
        render_allowlist_toml(ConnectorSpec(name="x", tools=["m:f"]))


def test_display_names_toml_maps_resource_to_title_always_emitted():
    t = render_display_names_toml(SPEC)
    assert '"https://apps.thorwhalen.com/api/acme_mcp/mcp" = "Acme Knowledge"' in t
    assert "[auth.oauth_server.resource_display_names]" in t
    # emitted even for an unnamed connector -- falls back to spec.name via server_name
    unnamed = ConnectorSpec(name="x", tools=["m:f"])
    t2 = render_display_names_toml(unnamed)
    assert '"https://apps.thorwhalen.com/x-mcp/mcp" = "x"' in t2


def test_display_names_and_allowlist_toml_escape_quotes_and_backslashes():
    # a title/email with a literal " or \ must not break platform.toml's parse
    # -- these fragments are copy-pasted into it verbatim (render_runbook step 5)
    tricky = ConnectorSpec(
        name="acme",
        tools=["m:f"],
        title='Say "Hi" \\ Bot',
        allowed_users=['weird"user\\@acme.com'],
    )
    dn = render_display_names_toml(tricky)
    al = render_allowlist_toml(tricky)
    # escaped forms are present, verbatim (backslash then quote each escaped)
    assert '"Say \\"Hi\\" \\\\ Bot"' in dn
    assert '"weird\\"user\\\\@acme.com"' in al
    # and the raw, unescaped title/email must not appear anywhere
    assert 'Say "Hi" \\ Bot' not in dn
    assert 'weird"user\\@acme.com' not in al
    # round-trip through a real TOML parser when one is available (3.11+ stdlib)
    try:
        import tomllib
    except ModuleNotFoundError:
        return
    parsed_dn = tomllib.loads(dn)
    parsed_al = tomllib.loads(al)
    assert (
        parsed_dn["auth"]["oauth_server"]["resource_display_names"][
            resource_url(tricky)
        ]
        == 'Say "Hi" \\ Bot'
    )
    assert parsed_al["auth"]["oauth_server"]["resource_allowlist"][
        resource_url(tricky)
    ] == ['weird"user\\@acme.com']


def test_runbook_lists_data_ship_and_allowlist_step():
    r = render_runbook(SPEC)
    assert (
        f"rsync -az ~/.local/share/ir/corpora/acme/ tw:{BASE}/xdg-data/ir/corpora/acme/"
        in r
    )
    assert "provision-acme.sh" in r
    assert "allowlist.toml" in r
    assert "display-name.toml" in r


def test_oauth_server_toml_configures_session_longevity():
    t = render_oauth_server_toml(SPEC)
    assert "[auth.oauth_server]" in t
    assert "refresh_token_ttl_seconds = 2592000" in t  # 30 days, not 0
    # the fragment must be usable as-is, and land before the allowlist subtable
    assert t.index("[auth.oauth_server]") < t.index("refresh_token_ttl_seconds")
    assert "BEFORE any" in t and "resource_allowlist" in t
    # and it must say what happens without it
    assert "first access-token expiry" in t
    # TTL is a parameter, not a magic number baked into the template
    assert "refresh_token_ttl_seconds = 3600" in render_oauth_server_toml(
        SPEC, refresh_token_ttl_seconds=3600
    )


def test_oauth_server_toml_is_emitted_even_for_an_open_connector():
    # session longevity is platform-wide: it matters whether or not users are listed
    open_spec = ConnectorSpec(name="x", tools=["m:f"], allowed_users=["*"])
    assert '"*",' in render_allowlist_toml(open_spec)
    assert "refresh_token_ttl_seconds" in render_oauth_server_toml(open_spec)


def test_any_account_is_explicit_and_alone():
    """``["*"]`` is enlace_auth's "every account"; mixing it with emails is refused."""
    from enlace_connector import ANY_ACCOUNT

    spec = ConnectorSpec(name="x", tools=["m:f"], allowed_users=[ANY_ACCOUNT])
    rendered = render_allowlist_toml(spec)
    assert '= [\n    "*",\n]' in rendered
    try:  # round-trip through a real TOML parser when one is available (3.11+)
        import tomllib
    except ModuleNotFoundError:
        pass
    else:
        parsed = tomllib.loads(rendered)["auth"]["oauth_server"]["resource_allowlist"]
        assert list(parsed.values()) == [["*"]]
    assert "every authenticated platform account" in render_runbook(spec)
    mixed = ConnectorSpec(name="x", tools=["m:f"], allowed_users=["*", "a@b.com"])
    with pytest.raises(ValueError, match="mixes"):
        render_allowlist_toml(mixed)


def test_the_runbook_never_calls_a_connector_open_by_omission():
    r = render_runbook(SPEC)
    assert "open to any authenticated user" not in r
    assert "refuses every account for an" in r


def test_runbook_states_the_silent_stranding_failure_and_the_check():
    r = render_runbook(SPEC)
    # the check that would have caught the incident, verbatim enough to paste
    assert ".well-known/oauth-authorization-server" in r
    assert "grant_types_supported" in r
    assert "python -m enlace_connector.preflight https://apps.thorwhalen.com" in r
    # and the plain-words warning: healthy-looking, needs a human, first expiry
    assert "refresh_token" in r
    assert "no way to renew" in r
    assert "systemd unit is active with zero restarts" in r
    assert "interactive browser" in r
    assert "oauth-server.toml" in r  # the fragment that fixes it


def test_generate_deploy_bundle_writes_all_artifacts(tmp_path):
    out = generate_deploy_bundle(SPEC, tmp_path / "acme")
    for rel in (
        "app.toml",
        "server.py",
        "deploy/acme-mcp.service",
        "deploy/provision-acme.sh",
        "deploy/allowlist.toml",
        "deploy/display-name.toml",
        "deploy/oauth-server.toml",
        "deploy/RUNBOOK.md",
    ):
        assert (tmp_path / "acme" / rel).exists(), rel
        assert out[rel] == tmp_path / "acme" / rel, rel  # returned map is accurate
    # server_py override is honored
    out2 = generate_deploy_bundle(
        SPEC, tmp_path / "acme2", server_py="# custom\napp = 1\n"
    )
    assert out2["server.py"].read_text() == "# custom\napp = 1\n"


@pytest.mark.skipif(
    os.name == "nt",
    reason=(
        "NTFS has no POSIX execute bit — Path.chmod on Windows only toggles the "
        "read-only flag, so the mode assertion is meaningless there. The provision "
        "script is a bash script that runs on the Linux server regardless of where "
        "the bundle was generated."
    ),
)
def test_provision_script_is_executable(tmp_path):
    out = generate_deploy_bundle(SPEC, tmp_path / "acme")
    assert out["deploy/provision-acme.sh"].stat().st_mode & 0o111


def test_bundle_ttl_is_settable_and_open_connectors_still_get_the_fragment(tmp_path):
    out = generate_deploy_bundle(
        ConnectorSpec(name="x", tools=["m:f"], allowed_users=["*"]),
        tmp_path / "x",
        refresh_token_ttl_seconds=604800,
    )
    assert '"*",' in out["deploy/allowlist.toml"].read_text()
    assert (
        "refresh_token_ttl_seconds = 604800"
        in out["deploy/oauth-server.toml"].read_text()
    )


def test_a_bundle_without_users_is_refused_before_anything_is_written(tmp_path):
    with pytest.raises(ValueError, match="no allowed_users"):
        generate_deploy_bundle(ConnectorSpec(name="x", tools=["m:f"]), tmp_path / "x")
    assert not (tmp_path / "x").exists()


@pytest.mark.parametrize(
    "users",
    [
        "*",
        "a@acme.com",
        [""],
        [" * "],
        ["**"],
        ["*@acme.com"],
        ["  a@acme.com "],
        ["ann <m@evil.com>"],
        ["no-at-sign"],
    ],
)
def test_malformed_allowed_users_are_refused(users):
    """Review of #9: a string, or an entry enlace_auth would refuse at load time."""
    with pytest.raises(ValueError):
        render_allowlist_toml(
            ConnectorSpec(name="x", tools=["m:f"], allowed_users=users)
        )


def test_the_rendered_allowlist_is_what_enlace_auth_accepts():
    rp = pytest.importorskip("enlace_auth.resource_policy")
    pytest.importorskip("tomllib")
    import tomllib

    for users in (["*"], ["a@acme.com", "B@Acme.com"]):
        spec = ConnectorSpec(name="x", tools=["m:f"], allowed_users=users)
        table = tomllib.loads(render_allowlist_toml(spec))["auth"]["oauth_server"]
        rp.parse_resource_allowlist(table["resource_allowlist"])  # does not raise


# --- the resource URL is the allowlist key, so it must be canonical (#10) ---------


@pytest.mark.parametrize("route", ["/api/acme_mcp/", "api/acme_mcp", "/api/acme_mcp//"])
def test_a_stray_slash_in_the_route_still_renders_the_canonical_key(route):
    spec = ConnectorSpec(name="acme", tools=[], route=route)
    assert resource_url(spec) == "https://apps.thorwhalen.com/api/acme_mcp/mcp"
    # the runtime audience derives from the same route, so the two cannot disagree
    assert f"{spec.default_audience(DFLT_ISSUER)}{MCP_PATH}" == resource_url(spec)


@pytest.mark.parametrize(
    "issuer, why",
    [
        ("https://Apps.example.com", "uppercase host"),
        ("HTTPS://apps.example.com", "uppercase scheme"),
        ("https://apps.example.com:443", "default port"),
        ("https://apps.example.com.", "trailing dot"),
        ("apps.example.com", "absolute"),
        ("https://apps.example.com/a//b", "path segment"),
        ("https://apps.example.com/./b", "path segment"),
        ("https://apps.example.com?x=1", "query"),
    ],
)
def test_a_non_canonical_issuer_is_refused_not_rendered(issuer, why):
    with pytest.raises(ValueError, match=why):
        resource_url(SPEC, issuer=issuer)
    with pytest.raises(ValueError, match=why):
        render_allowlist_toml(SPEC, issuer=issuer)


@pytest.mark.parametrize("route", ["/x\x7fy", "/x\x01y", "/x y", "/x\u200by"])
def test_a_route_with_a_control_or_space_character_is_refused(route):
    with pytest.raises(ValueError, match="whitespace or a control character"):
        resource_url(ConnectorSpec(name="acme", tools=[], route=route))


def test_a_route_with_an_inner_empty_segment_is_refused():
    with pytest.raises(ValueError, match="path segment"):
        resource_url(ConnectorSpec(name="acme", tools=[], route="/api//acme_mcp"))


def test_a_canonical_non_default_port_and_path_issuer_is_accepted():
    url = resource_url(SPEC, issuer="https://apps.example.com:8443/base/")
    assert url == "https://apps.example.com:8443/base/api/acme_mcp/mcp"


@pytest.mark.parametrize(
    "route, issuer",
    [
        ("/api/acme_mcp", DFLT_ISSUER),
        ("/api/acme_mcp/", DFLT_ISSUER),
        ("api/acme_mcp", "http://localhost:8000/"),
    ],
)
def test_every_rendered_key_round_trips_through_enlace_auth(route, issuer):
    resource_policy = pytest.importorskip("enlace_auth.resource_policy")
    tomllib = pytest.importorskip("tomllib")
    spec = ConnectorSpec(name="acme", tools=[], route=route, allowed_users=["a@acme.com"])
    table = tomllib.loads(render_allowlist_toml(spec, issuer=issuer))
    raw = table["auth"]["oauth_server"]["resource_allowlist"]
    parsed = resource_policy.parse_resource_allowlist(raw)
    assert set(parsed) == {resource_url(spec, issuer=issuer)}


@pytest.mark.parametrize("route", ["x", "//x", "/x/", "/api/x"])
def test_the_unit_carries_the_audience_the_allowlist_key_names(route):
    """An older runtime would re-derive a different audience for a stray slash (#12).

    The unit renders it with the same code as the key, and the connector's auth
    appends the MCP path to it exactly as ``resource_url`` does.
    """
    from enlace_connector.auth import enlace_resource

    spec = ConnectorSpec(name="x", tools=[], route=route)
    unit = render_systemd_unit(spec)
    (aud,) = [
        ln.split("=", 2)[2]
        for ln in unit.splitlines()
        if ln.startswith("Environment=CONNECTOR_AUDIENCE=")
    ]
    validated = enlace_resource(issuer=DFLT_ISSUER, audience=aud)["audience"]
    assert validated == resource_url(spec)


def test_spec_env_still_overrides_the_rendered_audience():
    spec = ConnectorSpec(name="x", tools=[], env={"CONNECTOR_AUDIENCE": "https://o"})
    assert "Environment=CONNECTOR_AUDIENCE=https://o" in render_systemd_unit(spec)


def test_a_spec_env_issuer_override_keeps_the_audience_on_the_same_origin():
    spec = ConnectorSpec(name="x", tools=[], env={"CONNECTOR_ISSUER": "https://other"})
    assert "Environment=CONNECTOR_AUDIENCE=https://other/x-mcp" in render_systemd_unit(spec)


def _systemd_unquote(line: str) -> tuple[str, str]:
    """Undo ``Environment=`` rendering as systemd does: quotes, escapes, ``%%``."""
    rhs = line.removeprefix("Environment=")
    if rhs.startswith('"'):
        assert rhs.endswith('"')
        rhs = rhs[1:-1].replace('\\"', '"').replace("\\\\", "\\")
    name, _, value = rhs.replace("%%", "%").partition("=")
    return name, value


def test_a_percent_in_the_route_survives_systemd_specifier_expansion():
    """systemd reads ``%2F`` as a specifier and drops the line (#14)."""
    spec = ConnectorSpec(name="x", tools=[], route="/api/a%2Fb")
    unit = render_systemd_unit(spec)
    (line,) = [
        ln for ln in unit.splitlines() if ln.startswith("Environment=CONNECTOR_AUDIENCE")
    ]
    assert "%%2F" in line
    assert "%2F" not in line.replace("%%2F", "")
    assert _systemd_unquote(line) == ("CONNECTOR_AUDIENCE", spec.default_audience(DFLT_ISSUER))


@pytest.mark.parametrize("value", ["50%", "a b", 'say "hi"', "it's", "%%n %i", "plain"])
def test_every_spec_env_value_reaches_the_process_unchanged(value):
    spec = ConnectorSpec(name="x", tools=[], env={"SOME_VAR": value})
    (line,) = [
        ln
        for ln in render_systemd_unit(spec).splitlines()
        if "SOME_VAR=" in ln and not ln.startswith("#")
    ]
    assert _systemd_unquote(line) == ("SOME_VAR", value)


def test_plain_values_render_exactly_as_before():
    spec = ConnectorSpec(name="x", tools=[], env={"HF_HOME": "/srv/x/data/hf"})
    assert "\nEnvironment=HF_HOME=/srv/x/data/hf\n" in render_systemd_unit(spec)


_TRICKY_VALUES = [
    "50%", "a b", 'say "hi"', "back\\slash", "it's", "%%n %i", "plain",
    "C:\\new\\table", "\\x41", "abc\\", "$HOME ${HOME}", "#x", ";x", "a=b=c",
    "", "tab\there", "nbsp\u00a0here", "caf\u00e9",
]


@pytest.mark.skipif(not shutil.which("systemd-analyze"), reason="needs systemd")
def test_systemd_itself_parses_every_value_back_unchanged(tmp_path):
    """The oracle that is not the implementation (review of #16).

    ``systemd-analyze verify`` only parses the unit; at debug level it dumps the
    environment it parsed. Nothing is loaded or started.
    """
    from enlace_connector.deploy import _systemd_environment_line

    names = [f"V{i}" for i in range(len(_TRICKY_VALUES))]
    unit = tmp_path / "oracle-ec14.service"
    unit.write_text(
        "[Service]\nType=oneshot\nExecStart=/bin/true\n"
        + "".join(
            _systemd_environment_line(n, v) + "\n"
            for n, v in zip(names, _TRICKY_VALUES)
        )
    )
    out = subprocess.run(
        ["systemd-analyze", "verify", str(unit)],
        env={**os.environ, "SYSTEMD_LOG_LEVEL": "debug"},
        capture_output=True,
        text=True,
        timeout=60,
    )
    parsed = {}
    for line in (out.stdout + out.stderr).splitlines():
        line = line.strip()
        if line.startswith("Environment: V"):
            name, _, value = line.removeprefix("Environment: ").partition("=")
            parsed[name] = value
    if not parsed:
        pytest.skip("this systemd-analyze does not dump the parsed environment")
    for name, value in zip(names, _TRICKY_VALUES):
        if value.strip() != value or "\t" in value:
            continue  # the dump line is stripped/escaped: not comparable here
        assert parsed.get(name) == value, (name, value, parsed.get(name))


@pytest.mark.parametrize(
    "env", [{"BAD NAME": "v"}, {"V": "line1\nline2"}, {"1V": "v"}, {"V": "nul\x00"}]
)
def test_an_inexpressible_env_entry_is_refused_at_render_time(env):
    with pytest.raises(ValueError):
        render_systemd_unit(ConnectorSpec(name="x", tools=[], env=env))


def test_other_rendered_lines_carry_no_live_specifier():
    spec = ConnectorSpec(name="x", tools=[], title="Top 50% %n search")
    unit = render_systemd_unit(spec)
    (desc,) = [ln for ln in unit.splitlines() if ln.startswith("Description=")]
    assert "50%% %%n" in desc
    assert "#Environment=CONNECTOR_USAGE_LOG_DIR=" in unit


@pytest.mark.parametrize("remote_base", ["/srv/my apps", "/srv/a%2Fb"])
def test_an_unrenderable_path_is_refused(remote_base):
    with pytest.raises(ValueError, match="cannot contain"):
        render_systemd_unit(ConnectorSpec(name="x", tools=[]), remote_base=remote_base)


# --- #15: specs that describe hand-maintained units, and drift detection ------

from enlace_connector import check_distinct_ports, diff_unit  # noqa: E402

HOSTED = ConnectorSpec(
    name="audio",
    tools=[],
    app_dir="audio_mcp",
    port=8041,
    env={"AUDIO_DATA_HOME": "{base}/data"},
    service_directives=[("RuntimeDirectory", "audio-mcp")],
    exec_start_pre=[
        "/bin/sh -c 'umask 077 && grep -E \"^AUDIO_KEY=\" {remote_base}/.env "
        "> /run/audio-mcp/scoped.env'"
    ],
    environment_files=["-/run/audio-mcp/scoped.env"],
    uvicorn_args=["--no-access-log"],
)


def test_app_dir_names_the_directories_but_not_the_unit():
    u = render_systemd_unit(HOSTED, remote_base="/srv/p")
    assert "WorkingDirectory=/srv/p/apps/audio_mcp\n" in u
    assert "ExecStart=/srv/p/connectors/audio_mcp/venv/bin/uvicorn" in u
    assert "Environment=AUDIO_DATA_HOME=/srv/p/connectors/audio_mcp/data" in u


def test_unit_renders_secrets_scoping_and_extra_args():
    u = render_systemd_unit(HOSTED, remote_base="/srv/p")
    assert "\nRuntimeDirectory=audio-mcp\n" in u
    assert "\nExecStartPre=/bin/sh -c 'umask 077 && grep -E \"^AUDIO_KEY=\" /srv/p/.env" in u
    assert "\nEnvironmentFile=-/run/audio-mcp/scoped.env\n" in u
    assert u.rstrip().count("--port 8041 --no-access-log\n") == 1


def test_bundle_app_toml_runs_the_same_command_as_the_unit(tmp_path):
    spec = ConnectorSpec(
        name="audio", tools=[], port=8041, uvicorn_args=["--no-access-log"],
        allowed_users=["*"],
    )
    written = generate_deploy_bundle(spec, tmp_path)
    assert "--port 8041 --no-access-log" in written["app.toml"].read_text()


@pytest.mark.parametrize("arg", ["", "--a b", "--x=%n", '--q="1"', "a\\b"])
def test_a_uvicorn_arg_that_is_not_one_token_is_refused(arg):
    with pytest.raises(ValueError):
        render_systemd_unit(ConnectorSpec(name="x", tools=[], uvicorn_args=[arg]))


@pytest.mark.parametrize(
    "field", ["exec_start_pre", "environment_files", "service_directives"]
)
def test_a_newline_cannot_inject_a_unit_line(field):
    value = ("A", "x\nExecStart=/bin/evil") if field == "service_directives" else (
        "x\nExecStart=/bin/evil"
    )
    with pytest.raises(ValueError):
        render_systemd_unit(ConnectorSpec(name="x", tools=[], **{field: [value]}))


def test_ports_that_collide_are_refused():
    check_distinct_ports([HOSTED, ConnectorSpec(name="b", tools=[], port=8042)])
    with pytest.raises(ValueError, match="8041 \\(audio, b\\)"):
        check_distinct_ports([HOSTED, ConnectorSpec(name="b", tools=[], port=8041)])


def test_a_unit_rendered_from_its_spec_has_no_drift():
    assert diff_unit(HOSTED, render_systemd_unit(HOSTED)) == []


def test_drift_ignores_comments_order_quoting_and_description():
    rendered = render_systemd_unit(HOSTED)
    service = [
        ln for ln in rendered.split("[Service]\n")[1].split("\n\n")[0].splitlines()
        if ln and not ln.startswith("#")
    ]
    env = [ln for ln in service if ln.startswith("Environment=")]
    rest = [ln for ln in service if not ln.startswith("Environment=")]
    hand = (
        "# maintained by hand\n[Unit]\nDescription=whatever the host calls it\n"
        "After=network-online.target\nWants=network-online.target\n\n"
        "[Service]\n"
        + "\n".join(reversed(rest))  # only one of each, so order is free
        + "\n"
        + "\n".join(
            'Environment="' + ln.removeprefix("Environment=") + '"' for ln in env
        )
        + "\n\n[Install]\nWantedBy=multi-user.target\n"
    )
    assert diff_unit(HOSTED, hand) == []


def test_drift_is_reported_line_by_line():
    installed = (
        render_systemd_unit(HOSTED)
        .replace("EnvironmentFile=-/run/audio-mcp/scoped.env\n", "")
        .replace(" --no-access-log", "")
        .replace("Environment=CONNECTOR_AUDIENCE=", "Environment=OLD_AUDIENCE=")
    )
    drift = diff_unit(HOSTED, installed)
    assert any(d.startswith("[Service] EnvironmentFile:") for d in drift)
    assert any(d.startswith("[Service] ExecStart:") for d in drift)
    assert "[Service] Environment CONNECTOR_AUDIENCE: installed lacks it" in drift
    assert "[Service] Environment OLD_AUDIENCE: not in the spec" in drift


def test_the_order_of_repeated_exec_start_pre_lines_counts():
    spec = ConnectorSpec(name="x", tools=[], exec_start_pre=["/bin/a", "/bin/b"])
    swapped = render_systemd_unit(spec).replace(
        "ExecStartPre=/bin/a\nExecStartPre=/bin/b", "ExecStartPre=/bin/b\nExecStartPre=/bin/a"
    )
    assert diff_unit(spec, swapped) == [
        "[Service] ExecStartPre: rendered ['/bin/a', '/bin/b'], "
        "installed ['/bin/b', '/bin/a']"
    ]


# Found by the adversarial review of #17.


@pytest.mark.parametrize(
    "field", ["exec_start_pre", "environment_files", "service_directives"]
)
def test_a_trailing_backslash_cannot_swallow_the_next_line(field):
    value = ("RuntimeDirectory", "foo\\") if field == "service_directives" else "foo\\"
    with pytest.raises(ValueError, match="backslash"):
        render_systemd_unit(ConnectorSpec(name="x", tools=[], **{field: [value]}))


@pytest.mark.parametrize(
    "key", ["ExecStart", "Type", "User", "WorkingDirectory", "Environment", "Restart"]
)
def test_service_directives_cannot_override_what_the_renderer_owns(key):
    spec = ConnectorSpec(name="x", tools=[], service_directives=[(key, "/bin/true")])
    with pytest.raises(ValueError, match=f"cannot set {key}="):
        render_systemd_unit(spec)


def test_a_lone_semicolon_is_not_a_uvicorn_arg():
    """systemd reads it as a command separator; app.toml would pass it to uvicorn."""
    with pytest.raises(ValueError):
        render_systemd_unit(ConnectorSpec(name="x", tools=[], uvicorn_args=[";", "/bin/true"]))


def test_an_empty_environment_line_resets_what_came_before():
    spec = ConnectorSpec(name="x", tools=[], env={"FOO": "1"})
    installed = render_systemd_unit(spec).replace(
        "Environment=FOO=1\n", "Environment=FOO=1\nEnvironment=\n"
    )
    drift = diff_unit(spec, installed)
    assert "[Service] Environment FOO: installed lacks it" in drift


@pytest.mark.parametrize("app_dir", ["../evil", "x/y", ".", ""])
def test_app_dir_is_one_directory_name(app_dir):
    with pytest.raises(ValueError, match="app_dir"):
        render_systemd_unit(ConnectorSpec(name="x", tools=[], app_dir=app_dir))


# --- #18: distinct names and directories; systemd's reading of a unit ---------

from enlace_connector import check_distinct_specs  # noqa: E402
from enlace_connector.deploy import _parse_unit, _split_environment  # noqa: E402


def test_specs_that_share_a_port_a_name_or_a_directory_are_refused():
    b = ConnectorSpec(name="b", tools=[], port=8042)
    check_distinct_specs([HOSTED, b])
    with pytest.raises(ValueError, match="a port: 8041 \\(audio, b\\)"):
        check_distinct_specs([HOSTED, ConnectorSpec(name="b", tools=[], port=8041)])
    with pytest.raises(ValueError, match="a unit name: audio \\(audio, audio\\)"):
        check_distinct_specs([HOSTED, ConnectorSpec(name="audio", tools=[], port=8042)])
    with pytest.raises(ValueError, match="a directory: audio_mcp \\(audio, b\\)"):
        check_distinct_specs(
            [HOSTED, ConnectorSpec(name="b", tools=[], port=8042, app_dir="audio_mcp")]
        )
    # a spec without app_dir uses its name as its directory
    with pytest.raises(ValueError, match="a directory: b \\(b, c\\)"):
        check_distinct_specs([b, ConnectorSpec(name="c", tools=[], port=8043, app_dir="b")])


def test_every_clash_is_listed_in_one_error():
    with pytest.raises(ValueError) as e:
        check_distinct_specs([ConnectorSpec(name="a", tools=[])] * 2)
    assert all(w in str(e.value) for w in ("a port", "a unit name", "a directory"))


def test_check_distinct_specs_takes_an_iterator():
    with pytest.raises(ValueError, match="a unit name"):
        check_distinct_specs(iter([ConnectorSpec(name="a", tools=[], port=1),
                                   ConnectorSpec(name="a", tools=[], port=2)]))


def test_a_comment_inside_a_continuation_is_skipped_as_systemd_does():
    unit = "[Service]\nExecStart=/bin/echo foo \\\n# a comment\n; another\n    bar\n"
    assert _parse_unit(unit)[("Service", "ExecStart")] == ["/bin/echo foo bar"]


@pytest.mark.parametrize(
    "written, read",
    [
        (r"T=a\\b", ["T=a\\b"]),           # an escaped backslash is one backslash
        (r'"T=a\\b"', ["T=a\\b"]),
        (r"'T=a\\b'", ["T=a\\b"]),         # escapes apply inside single quotes too
        (r"T=a\bc", ["T=a\x08c"]),        # \b is a backspace; shlex would read "abc"
        (r"T=\x41\101\u00e9", ["T=AAé"]),
        (r'T=x"y z"w U=1', ["T=xy zw", "U=1"]),
        (r'"A=x\"y"', ['A=x"y']),
        ('"" X=1', ["", "X=1"]),
    ],
)
def test_environment_is_read_as_systemd_reads_it(written, read):
    assert _split_environment(written) == read


@pytest.mark.parametrize("bad", [r"T=a\q", "T=a\\", r"T=\x4", r"T=\000", "T='a"])
def test_an_environment_systemd_would_reject_raises(bad):
    with pytest.raises(ValueError):
        _split_environment(bad)


def test_drift_reads_a_backslash_in_an_installed_environment_like_systemd():
    spec = ConnectorSpec(name="x", tools=[], port=8040, env={"T": "a\\b"})
    rendered = render_systemd_unit(spec)
    assert diff_unit(spec, rendered) == []
    hand = rendered.replace('Environment="T=a\\\\b"', "Environment=T=a\\\\b")
    assert hand != rendered and diff_unit(spec, hand) == []  # same value, other spelling
    wrong = rendered.replace('Environment="T=a\\\\b"', "Environment=T=a\\b")
    assert diff_unit(spec, wrong) != []  # systemd reads a backspace there, not "a\b"

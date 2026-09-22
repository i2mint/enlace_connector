# enlace_connector.scaffold

Generate the enlace app directory that serves a connector.

A connector with heavy dependencies (ML models, large libraries) should not be
mounted in-process with the rest of the platform — it runs as an enlace
`mode="process"` app: enlace spawns it as a supervised subprocess in its \*\*own
venv\*\* and reverse-proxies the route to it. This module renders that app dir — an
`app.toml` (access=public, mode=process, route) and a `server.py` that builds
the connector app from its [`ConnectorSpec`](enlace_connector.connector.html.md#enlace_connector.connector.ConnectorSpec).

The connector authenticates clients itself (bearer JWTs), so at the enlace layer it
is `access="public"` — enlace does not gate it with session cookies.

### Functions

| [`render_app_toml`](#enlace_connector.scaffold.render_app_toml)(spec, \*, port[, command])        | Render the enlace `app.toml` for *spec* as a `mode="process"` app.     |
|----------------------------------------------------------------------------------------------------|------------------------------------------------------------------------|
| [`render_server_py`](#enlace_connector.scaffold.render_server_py)(spec)                            | Render the `server.py` that exposes `app` for enlace's process runner. |
| [`scaffold_app`](#enlace_connector.scaffold.scaffold_app)(spec, dest_dir, \*, port[, command]) | Write `app.toml` and `server.py` for *spec* into *dest_dir*.           |

### enlace_connector.scaffold.render_app_toml(spec, , port, command=None)

Render the enlace `app.toml` for *spec* as a `mode="process"` app.

* **Return type:**
  [`str`](https://docs.python.org/3/builtins/stdtypes.html#str)

### enlace_connector.scaffold.render_server_py(spec)

Render the `server.py` that exposes `app` for enlace’s process runner.

The embedded `SPEC` carries every field `
make_connector_app()` reads at serve time — tools, auth, name/title, route and
`stateless_http`. Deploy-time-only fields (`extras`, `git_installs`,
`data`, `env`, `post_install`, `allowed_users`) are deliberately
omitted: they are consumed by the provisioning bundle, not by the process.

* **Return type:**
  [`str`](https://docs.python.org/3/builtins/stdtypes.html#str)

### enlace_connector.scaffold.scaffold_app(spec, dest_dir, , port, command=None)

Write `app.toml` and `server.py` for *spec* into *dest_dir*.

*dest_dir* is the enlace app directory (e.g. `tw_platform/apps/<name>`).
Returns the paths written. Creates *dest_dir* if needed; overwrites the two
generated files (they are derived artifacts).

* **Return type:**
  [`dict`](https://docs.python.org/3/builtins/stdtypes.html#dict)[[`str`](https://docs.python.org/3/builtins/stdtypes.html#str), [`Path`](https://docs.python.org/3/library/pathlib.html#pathlib.Path)]

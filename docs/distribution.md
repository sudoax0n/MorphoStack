# Distribution Notes

MorphoStack should grow through these stages:

1. Local source checkout with `python -m pip install -e ".[dev]"`.
2. Python application install through `pipx install morphostack`.
3. GitHub Releases with packaged Windows builds.
4. Windows package-manager manifests for winget, Scoop, or Chocolatey.
5. Optional desktop wrapper around the same local web app.

The canonical command is `morphostack`. The short alias is `mst`.
First-run setup is owned by `morphostack init`; pass `--web` to include the
browser UI's npm dependencies and `--yes` for unattended setup in a known-safe
environment.

For day-to-day lab use on one machine:

```powershell
morphostack init --web --yes
morphostack app
```

`morphostack app` serves the built browser UI and API together on one port
(default `http://127.0.0.1:8000`). Developers can still use `morphostack dev`
for hot-reload during UI work.

Remote script installation such as `irm ... | iex` can be convenient, but should
be optional because institutional systems may block or distrust it.

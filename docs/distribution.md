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

## Wheel packaging

To build a wheel that bundles the compiled browser UI:

```powershell
.\scripts\build_wheel.ps1
```

The script runs `npm run build` in `apps/web`, then `python -m build --wheel`.
Installed wheels expose the UI through `morphostack/_web_static`, which `morphostack app`
uses automatically when a source checkout is not present.

Install the wheel in an isolated environment:

```powershell
pipx install dist\morphostack-0.1.0-py3-none-any.whl
morphostack app
```

For a full analysis stack, install optional dependencies as well:

```powershell
pip install "morphostack[all] @ file:///D:/MorphoStack/dist/morphostack-0.1.0-py3-none-any.whl"
```

## GitHub Releases

Tag a version to build and attach a wheel automatically:

```powershell
git tag v0.1.0
git push origin v0.1.0
```

The `.github/workflows/release.yml` workflow builds `apps/web`, packages `morphostack/_web_static`,
and uploads `dist/*.whl` to the GitHub Release. Install from a release asset with pipx:

```powershell
pipx install https://github.com/<org>/MorphoStack/releases/download/v0.1.0/morphostack-0.1.0-py3-none-any.whl
morphostack app
```

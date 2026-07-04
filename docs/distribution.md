# Distribution Notes

MorphoStack should grow through these stages:

1. Local source checkout with `python -m pip install -e ".[dev]"`.
2. Python application install through `pipx install morphostack`.
3. GitHub Releases with packaged Windows builds.
4. Windows package-manager manifests for winget, Scoop, or Chocolatey.
5. Optional desktop wrapper around the same local web app.

The canonical command is `morphostack`. The short alias is `mst`.

Remote script installation such as `irm ... | iex` can be convenient, but should
be optional because institutional systems may block or distrust it.


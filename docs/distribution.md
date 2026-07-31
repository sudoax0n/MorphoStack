# Distribution

How MorphoStack is installed and packaged. Canonical command: **`morphostack`**. Short alias: **`mst`**.

## Intended stages

1. Local source: `pip install -e ".[all]"`
2. Isolated app install: `pipx install` from a wheel / release asset
3. GitHub Releases with built wheels (UI static assets included)
4. Optional later: winget / Scoop / Chocolatey manifests
5. Optional later: desktop wrapper around the same local web app

## Day-to-day lab machine

```bash
morphostack init --web --yes
morphostack app
# http://127.0.0.1:8000
```

- `morphostack app` — built UI + API on one port  
- `morphostack dev` — hot-reload for UI development  

First-run setup is owned by `morphostack init` (`--web` for npm UI deps, `--yes` for unattended).

## Wheel packaging

```powershell
./scripts/build_wheel.ps1
```

Builds `apps/web`, then `python -m build --wheel`. The wheel embeds UI files as `morphostack/_web_static` for `morphostack app`.

Local install:

```powershell
pipx install dist/morphostack-1.0.0-py3-none-any.whl
morphostack app
```

Full analysis extras:

```bash
pip install "morphostack[all] @ file:///absolute/path/to/morphostack-1.0.0-py3-none-any.whl"
```

## Local wheel verification

Before tagging a release:

```powershell
./scripts/verify_release_wheel.ps1
```

## GitHub Releases

```bash
git tag v1.0.0
git push origin v1.0.0
```

`.github/workflows/release.yml` builds the web UI, packages the wheel, and uploads `dist/*.whl` to the release.

```bash
pipx install https://github.com/sudoax0n/MorphoStack/releases/download/v1.0.0/morphostack-1.0.0-py3-none-any.whl
morphostack app
```

Respect the dual license ([LICENSE](../LICENSE)): AGPL-3.0-only **or** PolyForm Noncommercial 1.0.0. Commercial closed-source use needs a separate agreement with the author.

## What not to ship in the git tree

See root `.gitignore`:

- `.venv/`, `node_modules/`, `apps/web/dist/`
- raw stacks (`*.tif`, `*.czi`, `*.lsm`, …)
- local tooling: `mcps/`, `scratch/`, `terminals/`, `.clones/`
- personal notes (`AGENTS.md`, `improvements.md`, …)

Keep intentional `validation/runs/` metrics and reports; avoid committing private raw data.

## Related

[getting-started.md](getting-started.md) · root [README.md](../README.md)

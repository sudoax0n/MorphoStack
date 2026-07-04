# MorphoStack

MorphoStack is a planned local morphometry toolkit for microscopy Z-stacks, starting with vesicle analysis and expanding to red blood cell analysis.

The first milestone is intentionally small: prove the project structure, command ownership, and diagnostics before migrating scientific code from the older Shape-Analysis prototype.

## Current Commands

```bash
morphostack doctor
morphostack init
mst doctor
```

Both commands use the same CLI entry point. `mst` is the short alias.

## Development Install

```bash
python -m venv .venv
.\.venv\Scripts\python -m pip install -e ".[dev]"
.\.venv\Scripts\morphostack doctor
```

To inspect the machine and optionally install the heavier analysis/API
dependencies into the active environment:

```bash
.\.venv\Scripts\morphostack init
```

## Architecture Direction

- Python core package for scientific analysis.
- FastAPI backend for local app/runtime APIs.
- Vite web frontend in `apps/web`.
- Later packaging through `pipx`, GitHub Releases, and a Windows installer.

No GitHub remote is configured yet.

# Reference and External Folders

Some directories at the MorphoStack repo root are **not** MorphoStack product
source. They come from local tooling sessions, cloned research software, or
scratch work. Do not edit, move, or delete their contents as part of normal
MorphoStack development.

## Folders

| Folder | Purpose |
|--------|---------|
| `mcps/` | Local MCP server configs and tooling artifacts from agent/IDE sessions. |
| `scratch/` | Throwaway scripts, temp outputs, and ad-hoc experiments. |
| `terminals/` | Captured terminal session logs from development tooling. |
| `.clones/` | Cloned external research software (e.g. LimeSeg-work) kept for reference. |

## What belongs in the repo

MorphoStack product code lives under:

- `src/morphostack/` — Python core, CLI, API
- `apps/web/` — browser UI
- `tests/` — unit and integration tests
- `validation/` — intentional validation runs and reference metrics
- `docs/` — user and developer documentation

## Git hygiene

The folders listed above are listed in `.gitignore` so they do not re-dirty the
working tree. They may remain on disk locally; that is expected.

Validation artifacts under `validation/runs/` are **intentional project outputs**
and are tracked unless a run is explicitly local-only.
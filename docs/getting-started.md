# Getting Started

MorphoStack runs **locally**. The canonical command is `morphostack`; the short alias is `mst` (same entry point).

<p align="center">
  <img src="public/hero-banner.jpg" alt="MorphoStack" width="90%" />
</p>

## Requirements

- **Python 3.11+**
- Optional for analysis: OpenCV, scikit-image, scipy, tifffile, czifile, … (`pip install -e ".[analysis]"` or `".[all]"`)
- Optional for API/UI: FastAPI, uvicorn (`".[api]"`), Node.js for web build/dev

## Install from source

```bash
git clone https://github.com/sudoax0n/MorphoStack.git
cd MorphoStack
python -m venv .venv
```

License: dual **AGPL-3.0-only** or **PolyForm Noncommercial 1.0.0** — see [LICENSE](../LICENSE). Cite MorphoStack if you use it ([CITATION.cff](../CITATION.cff)).

**Windows (PowerShell):**

```powershell
.\.venv\Scripts\python -m pip install -e ".[all]"
.\.venv\Scripts\morphostack doctor
.\.venv\Scripts\morphostack init --web   # optional UI deps
```

**macOS / Linux:**

```bash
source .venv/bin/activate
python -m pip install -e ".[all]"
morphostack doctor
morphostack init --web
```

Confirm both commands:

```bash
morphostack --version   # MorphoStack 0.1.0
mst --version           # MorphoStack 0.1.0
```

## First analysis (CLI)

```bash
# Inspect shape + voxel source
morphostack inspect path/to/stack.tif

# Suggest a threshold
morphostack threshold path/to/stack.tif --method auto

# Run analysis with calibration overrides
morphostack analyze path/to/stack.tif \
  --threshold 100 \
  --voxel-x 0.1 --voxel-y 0.1 --voxel-z 0.5 \
  --out metrics.csv --report --mesh
```

Outputs next to (or under) your chosen paths:

| Artifact | Contents |
| --- | --- |
| `metrics.csv` | Per-frame shape metrics |
| `metrics.csv.manifest.json` | Provenance (SHA-256, settings, warnings) |
| `metrics.csv.report.md` | Human-readable summary (`--report`) |
| mesh file | With `--mesh-export mesh.obj` (or STL/PLY/GLB) |

Use `--bundle-dir runs` to write `metrics.csv` + `manifest.json` + `report.md` into one folder.

## Which mode should I use?

| Goal | Mode (UI) | CLI |
| --- | --- | --- |
| Single GUV / vesicle | **Standard** | `--profile vesicle` (default) |
| One vesicle in a **crowded** field | **Standard** + object seed | `--profile vesicle` + `--seed-x/y/frame` |
| Red blood cells | **RBC** | `--profile rbc` |
| Threshold cannot hold the membrane | **Experimental** (slow) | `--profile active_surfaces` + seed |

Crowded multi-vesicle images still use **Standard** — pick the object with a seed. Experimental is not “multi mode”; it is a slow single-object refine. Details: [usage.md](usage.md#modes-profiles).

## Crowded field (one object)

```bash
morphostack analyze path/to/crowded.czi \
  --threshold 190 \
  --profile vesicle \
  --seed-x 360 --seed-y 517 --seed-frame 105 \
  --mesh --mesh-export mesh.obj \
  --bundle-dir runs
```

## Browser UI

**Developer mode** (API + Vite hot reload):

```bash
morphostack dev --check
morphostack dev
# open http://127.0.0.1:5173
```

**Single-port app** (built UI + API; after `npm run build` or a release wheel):

```bash
morphostack app
# open http://127.0.0.1:8000
```

## Next steps

- Full UI/CLI walkthrough: [usage.md](usage.md)
- Metric definitions: [metrics.md](metrics.md)
- Scientific caveats: [limitations.md](limitations.md)
- If something fails: [troubleshooting.md](troubleshooting.md)

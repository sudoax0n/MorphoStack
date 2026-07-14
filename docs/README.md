# MorphoStack Documentation

<p align="center">
  <img src="public/logo-mark.jpg" alt="MorphoStack" width="160" />
</p>

Local morphometry for microscopy Z-stacks: vesicles, GUVs, RBCs, and seeded objects in crowded fields.

| Start here | When you need it |
| --- | --- |
| [Getting started](getting-started.md) | Install, doctor, first `analyze` |
| [Usage guide](usage.md) | Browser UI + CLI workflows |
| [Metrics](metrics.md) | What every CSV column means |
| [Methods](methods.md) | Paste-ready methods supplement |
| [Limitations](limitations.md) | Calibration, tracking, profiles |
| [Usage — Modes](usage.md#modes-profiles) | Standard vs RBC vs Experimental; single vs multi-vesicle |
| [Active surfaces](active-surfaces.md) | Experimental profile notes |
| [Validation](validation.md) | Regression runs & scripts |
| [Troubleshooting](troubleshooting.md) | Common failures |
| [Distribution](distribution.md) | Wheels, pipx, GitHub Releases |
| [Citations](citations.md) | Libraries & data acknowledgements |

Assets used on GitHub live in [`public/`](public/). Product roadmap notes: [`../improvements.md`](../improvements.md). Contributor guide: [`../AGENTS.md`](../AGENTS.md).

```text
Stack (TIFF / LSM / CZI)
        │
        ▼
 Inspect → Threshold / Sweep → Preview
        │
        ▼
 Analyze (seed · ROI · Z-range · profile)
        │
        ├── CSV metrics
        ├── Manifest + report
        └── Mesh / mask export
```

<p align="center">
  <img src="public/pipeline-concept.jpg" alt="Pipeline concept" width="85%" />
</p>

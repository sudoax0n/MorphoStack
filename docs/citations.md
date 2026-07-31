# Citations and Acknowledgements

Use this list for methods supplements, license review, and dataset attribution.

## Cite MorphoStack (required shoutout)

If you use MorphoStack in research, teaching, benchmarks, products, or derivative
tools, please:

1. **Cite the software** using [`CITATION.cff`](../CITATION.cff) (GitHub “Cite this repository”).
2. **Name MorphoStack** in papers, READMEs, or product docs where practical.
3. **Keep license notices** when you redistribute code (see [LICENSE](../LICENSE)).

Suggested citation:

> Abhinav. *MorphoStack: local morphometry toolkit for microscopy Z-stacks* (v1.0.0). 2026.  
> https://github.com/sudoax0n/MorphoStack

BibTeX-style:

```bibtex
@software{morphostack2026,
  author  = {Abhinav},
  title   = {MorphoStack: local morphometry toolkit for microscopy Z-stacks},
  version = {1.0.0},
  year    = {2026},
  url     = {https://github.com/sudoax0n/MorphoStack}
}
```

## MorphoStack license (dual)

| Option | SPDX | Use when |
| --- | --- | --- |
| GNU AGPL v3 only | `AGPL-3.0-only` | You can comply with copyleft / network source disclosure |
| PolyForm Noncommercial 1.0.0 | `PolyForm-Noncommercial-1.0.0` | Noncommercial research, education, personal use |

Commercial closed-source use: contact the author (see [LICENSE](../LICENSE)).

Full texts:

- [LICENSE](../LICENSE) (dual-license summary)
- [LICENSE-AGPL-3.0.txt](../LICENSE-AGPL-3.0.txt)
- [LICENSE-POLYFORM-NONCOMMERCIAL-1.0.0.txt](../LICENSE-POLYFORM-NONCOMMERCIAL-1.0.0.txt)

Third-party JavaScript loaded at runtime in standalone mesh HTML exports (e.g. Plotly CDN) remains under the respective library licenses.

## Core libraries

| Component | Role in MorphoStack | Suggested citation / reference |
| --- | --- | --- |
| NumPy | Arrays and numerics | Harris et al., Nature 585, 357–362 (2020) |
| SciPy | Morphology, marching cubes helpers | Virtanen et al., Nature Methods 17, 261–272 (2020) |
| scikit-image | Segmentation helpers, marching cubes | van der Walt et al., PeerJ 2:e453 (2014) |
| OpenCV | Contours and morphology | Bradski, Dr. Dobb's Journal (2000) |
| Plotly | Browser 3D mesh preview | Plotly Technologies Inc. |
| tifffile / czifile | Stack I/O | Library docs / format specs |
| Shapely | Polygon utilities | shapely.readthedocs.io |
| FastAPI / Uvicorn | Local API server | fastapi.tiangolo.com |

## Methods notes

- **Threshold + connected components** — standard image-processing practice; MorphoStack’s implementation is original but follows common Fiji/ImageJ and OpenCV workflows.
- **Active surfaces** — in-house experimental surfel refinement. Describe as experimental in methods text; not a third-party plugin port.

## Reference datasets

- **DOPC Movie 1** (`syst202400052-sup-0001-movie1-dopc.tif`) — supplementary data associated with *Shape Analysis of Biomimetic and Plasma Membrane Vesicles* (DOI [10.1002/syst.202400052](https://doi.org/10.1002/syst.202400052)). Cite the original paper when using this dataset in figures or validation tables.

## Related

[methods.md](methods.md) · [validation.md](validation.md) · [../LICENSE](../LICENSE)

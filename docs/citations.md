# Citations and Acknowledgements

Use this list for methods supplements, license review, and dataset attribution.

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

## MorphoStack software citation

> MorphoStack v0.1.0 — local morphometry toolkit for microscopy Z-stacks. Source available at the MorphoStack repository; analysis performed on [date] with Python 3.11+.

Add author list, repository URL, and commit hash when publishing.

## License

MorphoStack is released under the **MIT License** (see [LICENSE](../LICENSE)). Third-party JS loaded at runtime in standalone mesh HTML exports (e.g. Plotly CDN) remains under the respective library licenses.

## Related

[methods.md](methods.md) · [validation.md](validation.md)

# Citations And External Algorithm Notes

MorphoStack combines original pipeline code with well-known libraries and published methods.
Use this list when preparing acknowledgements, a methods supplement, or license compliance review.

## Core libraries

| Component | Use in MorphoStack | Suggested citation / reference |
| --- | --- | --- |
| NumPy | Array storage and numeric operations | Harris et al., Nature 585, 357–362 (2020) |
| SciPy | Distance transforms, marching cubes, morphology | Virtanen et al., Nature Methods 17, 261–272 (2020) |
| scikit-image | Segmentation helpers, marching cubes | van der Walt et al., PeerJ 2:e453 (2014) |
| OpenCV | Contour extraction and morphology | Bradski, Dr. Dobb's Journal of Software Tools (2000) |
| Plotly | Interactive 3D mesh preview in browser | Plotly Technologies Inc. plotly.com |
| tifffile / czifile | Microscopy stack loading | Library documentation and respective file-format specs |
| Shapely | Polygon geometry utilities | Gillies et al., https://shapely.readthedocs.io |
| FastAPI / Uvicorn | Local web API and app server | Ramírez, fastapi.tiangolo.com |

## Segmentation methods

- **Threshold segmentation with connected components** — standard image-processing practice; MorphoStack implementation is original but follows approaches common in Fiji/ImageJ and OpenCV workflows.
- **Active surfaces (experimental profile)** — MorphoStack's in-house surfel-based surface evolution for seeded objects. Describe it as an experimental refinement step in methods text; it is not a third-party plugin port.

## Reference datasets

- **DOPC Movie 1** (`syst202400052-sup-0001-movie1-dopc.tif`) — supplementary data associated with *Shape Analysis of Biomembrane and Plasma Membrane Vesicles* (DOI [10.1002/syst.202400052](https://doi.org/10.1002/syst.202400052)). Cite the original paper when using this dataset in figures or validation tables.

## Software citation (MorphoStack)

Suggested software mention:

> MorphoStack v0.1.0 — local morphometry toolkit for microscopy Z-stacks. Source available at the MorphoStack repository; analysis performed on [date] with Python 3.11+.

Add author, repository URL, and commit hash when publishing.

## Licenses

MorphoStack is released under the MIT License. Bundled browser UI assets built with Vite are part of the same distribution. Third-party JavaScript loaded at runtime in standalone mesh HTML exports (Plotly CDN) is subject to Plotly's license terms.
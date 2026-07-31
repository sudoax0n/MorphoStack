# Contour Smoothing for MorphoStack

## Executive summary

Your current `cv2.approxPolyDP` step is behaving exactly as its design suggests: it is a polyline simplifier, not a denoising smoother. The scikit-image documentation makes the same point in different words: Douglas–Peucker-style approximation reduces vertices while staying within the convex hull of the original polygon, which does not remove pixel-scale zig-zagging from a thresholded membrane boundary. That makes it a poor choice when perimeter is a primary readout, because digital boundary jaggedness inflates arclength much more than it changes enclosed area. Crofton perimeter estimators were created precisely because pixel-border perimeters are sensitive to digitization, and scikit-image explicitly documents Crofton as a continuous-space perimeter approximation that is generally more accurate than simpler border-pixel counts. citeturn46view0turn12search7

Across the sources I reviewed, the most defensible replacement for `approxPolyDP` under your constraints is **periodic cubic B-spline smoothing on a uniformly arc-length–resampled contour**, using `scipy.interpolate.splprep(..., per=True, k=3, s=...)` and choosing `s` from an estimated boundary-noise level rather than from an arbitrary geometric tolerance. SciPy’s FITPACK wrapper defines `s` as a bound on the weighted residual sum of squares, and recommends values near the number of data points `m` when the weights are inverse standard deviations. That gives a principled starting rule: if you use per-point weights `w_i = 1 / σ_i`, then start with `s ≈ m`; if you use unit weights, the equivalent scaling is `s ≈ m σ²`. citeturn6view0turn6view1

For your use case, **mask-domain Gaussian blur before thresholding is the weaker option**. Gaussian smoothing is isotropic, so it smooths across region boundaries and can shift the membrane position before any contour is extracted. The scale-space literature also warns that Gaussian smoothing of closed curves causes shrinkage, and the same concern appears in early curve-analysis literature and image-smoothing work. A post-extraction, closed-curve–aware smoother keeps the segmentation mask fixed and limits the operation to the already selected contour, which is easier to calibrate against your area/perimeter bias targets. citeturn11view1turn11view2turn37search4

I did **not** find a published GUV paper that directly validates a spline-smoothed contour perimeter against a Crofton perimeter measured on the same binary mask. What I did find is a strong adjacent literature: spline-smoothed outlines validated on synthetic shapes for perimeter/area accuracy, classic GUV contour-detection papers that use subpixel contour extraction rather than polygon simplification, and recent GUV software papers that validate automated detection/selection against manual analysis or simulated 3D ground truth. So the best recommendation is evidence-based but still partly an engineering synthesis rather than a copied precedent from one exact paper. citeturn45view0turn15view0turn30search0turn25search2

## Spline smoothing and measurement bias

SciPy’s `splprep` fits an N-D parametric spline subject to a smoothing condition on the weighted residuals, `sum((w * (y - g))**2) <= s`, and notes that if the weights are inverse standard deviations, then useful `s` values are typically near `m ± sqrt(2m)`, where `m` is the number of input samples. In practice, that means `s` is not a geometric “radius” parameter; it is a **noise-budget parameter**. If your contour coordinates are sampled with roughly homoscedastic boundary noise of standard deviation `σ` pixels and you use unit weights, the same rule becomes the familiar engineering approximation `s ≈ mσ²`. citeturn6view0turn6view1

For near-circular contours, increasing `s` has a recognizable bias curve even though SciPy does not publish a closed-form area/perimeter error law. The high-frequency 1–2 px boundary oscillations added by thresholding primarily inflate perimeter, while the area is much less sensitive. As smoothing increases from zero, perimeter usually **drops first toward the true value** while area changes little; once the spline begins suppressing real low-frequency shape modes instead of just pixel noise, both perimeter and area become negatively biased. This interpretation is consistent with two independent literatures: scikit-image’s continuous-space Crofton perimeter motivation, and the synthetic-shape validation study by Bartlett et al., which found that smoothing splines can produce reasonably accurate perimeter and area on digitized outlines, but also that strong smoothing underestimates curvature and increasingly underestimates perimeter on complex shapes. citeturn46view0turn36view0turn45view0turn45view2turn45view4

That trade-off matters for your geometry. Your GUV rings are mostly simple closed curves with radii 30–120 px, and the features you care about preserving are around 5–20 px. Bartlett et al. found that simple shapes tolerate noticeably more smoothing than complex ones because many of their pixel samples are redundant, while complex outlines require less smoothing because more samples carry real shape information. Their paper even makes the circle the extreme example of a shape that can be represented with very strong smoothing and very few points, whereas more dendritic or concave shapes cannot. For MorphoStack, that strongly suggests **one global `s` is risky** across slices and object types: circles can absorb more smoothing than biconcave RBC notches or budding vesicle protrusions. citeturn45view1turn36view0

A principled practical rule is therefore:

- resample the raw contour to **uniform arc-length spacing** before fitting;
- estimate boundary noise `σ` in pixels from the contour itself or from a synthetic-circle calibration of your thresholding pipeline;
- use `w_i = 1/σ_i` if you have local confidence estimates, otherwise a constant `w = 1/σ`;
- start from `s ≈ m` in the weighted formulation, or `s ≈ mσ²` in the unweighted formulation;
- then cap `s` by calibration on synthetic circles so that projected-area bias stays below 2% and perimeter bias below 3%. citeturn6view0turn6view1turn45view0

That last step is important because I did not find a paper that converts `s`, `N`, and `R` directly into a guaranteed area/perimeter bias bound for digital membrane contours. The literature supports the **direction** of the trade-off and the **noise-based scaling** of `s`; it does not give a universal closed-form guarantee for your exact imaging chain. citeturn6view0turn45view0turn36view0

## Gaussian alternatives and where the bias enters

`skimage.filters.gaussian` is a multidimensional Gaussian filter whose smoothing strength is set by `sigma`. That makes it straightforward to apply either to a binary mask or to contour-coordinate sequences. The crucial difference is **where** the smoothing occurs. If you blur the binary mask and then threshold again, you are not just removing jaggies; you are changing the image from which the boundary is defined. Because Gaussian smoothing is isotropic, it smooths across region boundaries, and the level-set literature explicitly notes that such smoothing compromises boundary spatial position. citeturn44view4turn11view1

That is a real risk for thin membrane rings. Your rings are only about 2–4 px thick. A mask-domain Gaussian blur with `sigma` much above roughly 1 px will spread the ring intensity across its inner and outer edges, making the recovered contour threshold-dependent. In effect, the blur and the re-thresholding together define a new contour. For membrane objects, that can systematically move the contour inward or outward depending on ring thickness, local intensity asymmetry, and threshold choice. I did not find a GUV paper that quantifies this shrinkage for fluorescence membrane rings specifically, but the general image-smoothing literature and the active-curve literature both warn that Gaussian smoothing displaces boundaries and that Gaussian smoothing of closed curves causes shrinkage. citeturn11view1turn11view2turn37search4

For that reason, **post-contour periodic Gaussian smoothing is less biased than pre-mask Gaussian smoothing** for your use case. If you first lock in the membrane mask and then smooth only the extracted closed contour, you avoid a second thresholding step and keep the operation periodic and curve-aware. The downside is that direct Gaussian smoothing of contour coordinates is itself a closed-curve shrinkage operator unless you correct for it, a classic issue in curvature scale-space work. Lowe’s paper is explicit that shrinkage during Gaussian smoothing was a major practical obstacle, and the scale-space literature around curvature-based shape representations makes the same point. citeturn11view2turn37search4turn37search18

For the specific 1–2 px jaggies you described, the evidence supports a conservative contour-domain Gaussian only as a **secondary** option:

- if contour points are resampled to about **1 px arc-length spacing**, a periodic Gaussian smoothing of about **0.8–1.2 samples** is a reasonable first denoising scale for 1 px oscillations;
- for more severe 2 px oscillations, **1.2–1.5 samples** is usually the upper end before 5–10 px buds and notches start attenuating noticeably;
- values near or above **2 samples** are much more likely to suppress the very features you said must survive. citeturn44view4turn37search4turn36view0

The main reason I prefer spline smoothing over contour-domain Gaussian smoothing is not speed; both are fast enough on 100–600-point contours. It is that FITPACK gives you a more principled noise-to-smoothing mapping, whereas raw Gaussian smoothing gives you a low-pass scale but no direct residual criterion. Gaussian-on-mask is the least attractive of the three because it mixes denoising with contour relocation. citeturn6view0turn44view4turn11view1

## Active contour as a refiner rather than a segmenter

`skimage.segmentation.active_contour` fits open or closed splines to image features, and the API documentation is very clear about what its main shape parameters do: **higher `alpha` makes the snake contract faster**, and **higher `beta` makes it smoother**. It also supports `boundary_condition='periodic'`, which is necessary for your closed curves. That makes it technically suitable as a curvature-regularized refiner initialized from an already-segmented boundary. citeturn39view0

The same parameter descriptions are also why this is not my first recommendation. If you want to avoid over-shrinkage on nearly circular vesicles, you should drive `alpha` **well below the default contraction strength**, keep `beta` only moderately above the minimum needed to suppress pixel noise, and use small `max_px_move` together with a limited iteration count. In practical terms, that means using an `alpha` lower than the documented default of `0.01`, not higher, and treating `beta` as a “just enough” smoothness term rather than a strong curvature prior. This is an engineering inference from the documented parameter roles; I did not find a GUV paper that reports a standard `alpha`/`beta` recipe for this exact post-segmentation use. citeturn39view0

I also did not find evidence that **per-slice active contours as a post-hoc smoother** are common in published GUV morphometry pipelines. What I found instead were three nearby uses of deformable models:

- LimeSeg uses a **3D active surface** with curvature regularization, which is conceptually closest to what you want to mimic in 2D. citeturn2search3
- Fidorra et al. report **3D active surface models** for segmenting phase-separated lipid domains in GUV fluorescence stacks. citeturn27search1
- More general fluorescence-membrane segmentation papers do use active contours, but not as a common published standard for 2D GUV perimeter/circularity metrology in the papers I reviewed. citeturn41search1turn39view0

On runtime, the official scikit-image sources do not provide a benchmark for “256 points on a 128×128 crop.” What they do show is that `active_contour` is an iterative optimizer with defaults like `max_num_iter=2500`, explicit per-iteration movement control, and convergence criteria. That makes its runtime inherently less predictable than a one-shot periodic spline fit or one-dimensional Gaussian coordinate smoothing, and therefore the riskiest choice for a hard **<200 ms per slice** budget on laptop CPUs. citeturn39view0

## What the published vesicle literature actually uses

The GUV and vesicle-analysis literature is more diverse than it first appears. Most published tools prioritize **detection**, **selection**, or **subpixel contour localization** over explicit polygon smoothing, and very few report a dedicated “boundary smoother” as a headline method. The closest matches I found are summarized below.

| Paper | Imaging / target | Method used | Validation reported | Relevance to MorphoStack |
|---|---|---|---|---|
| Pécréaux et al., 2004 | GUVs, phase contrast | High-resolution **subpixel contour detection** for fluctuation analysis | Improved fluctuation-spectrum access at higher modes; foundational contour-localization method | Classic reference for precise vesicle contours, but not fluorescence and not a smoothing study. citeturn27search2 |
| Hermann et al., 2014 | Fluorescence GUVs | **Circular Hough transform** plus contrast boosting and slight boxcar smoothing | Compared automated vs manual analysis on 200 GUVs; automated analysis was much faster and semi-automatic/manual-corrected results matched manual analysis | Good precedent for automated fluorescence GUV analysis, but focused on circular detection rather than smooth noncircular contours. citeturn15view0turn16view0turn16view2 |
| Sych et al., 2019 | Confocal fluorescence GUVs | FIJI macro that detects **circular particles** and derives centers/radii | Tested on confocal images for membrane-dye/protein-binding analysis | Useful recent tool, but again centered on circular detection, not fine boundary smoothing. citeturn22view0 |
| Lee et al., 2022 | Confocal fluorescence GUV z-stacks | CNN-assisted **whole-z-stack classification and automated selection** with intensity analysis | Accuracy close to manual performance for vesicle selection and state determination | Strong for selection/automation, weakly relevant for contour smoothing itself. citeturn31view0 |
| Zupanc et al., 2014 | Light video microscopy of giant lipid vesicles | Custom **Markov random field segmentation** producing binary masks, then diameter and isoperimetric quotient from masks | Operator correction after automatic segmentation; repeatability of size and roundness statistics across samples | Especially relevant because it computes a roundness metric from segmented masks, though not fluorescence. citeturn32search0turn33view1turn33view0 |
| Usenik et al., 2011 | Vesicles, phase contrast video | Gradient-based contour tracking with **uniform angular sampling in polar coordinates** | Artificial images with known ground-truth contours; accuracy 34.1 nm and precision 26.9 nm at stated SNR/pixel size | Very relevant methodologically: closed contour, polar representation, synthetic-ground-truth validation. citeturn30search0 |
| van Buren et al., 2023 DisGUVery | Microscopy images of GUVs, including nonspherical cases | Multiple detection modules and a new **membrane segmentation algorithm** for nonspherical vesicles | Performance analysis across image types; shape and membrane fluorescence readouts | Strong modern prior art for general GUV analysis, but public abstract does not expose the exact contour-smoothing operator. citeturn17view0turn19search6 |
| Dreher et al., 2023 GeoV | Confocal z-stacks of GUVs and related objects | 3D reconstruction and mesh analysis from fluorescence z-stacks | Validation on simulated shapes using Hausdorff distance, curvature, and bending energy | Highly relevant for your 3D downstream metrics, though it is a 3D reconstruction pipeline rather than a 2D slice smoother. citeturn25search0turn25search2 |

The practical takeaway from this literature is that **published GUV tools do not converge on Gaussian mask blur plus contour extraction** as the standard route for quantitative morphometry. The more accurate pipelines either exploit subpixel contour localization directly, use circle/particle models when shapes are near-spherical, or move to deformable/active-surface formulations when 3D geometry matters. That pattern supports replacing `approxPolyDP` with a real contour-domain smoother rather than further tweaking binary-mask preprocessing. citeturn27search2turn15view0turn17view0turn25search2

## Recommendation

The best-practice choice for MorphoStack is:

**Periodic cubic B-spline smoothing of a uniformly arc-length–resampled contour**, implemented with `scipy.interpolate.splprep` using `per=True, k=3`, followed by dense evaluation with `splev`. citeturn6view0turn6view1

A robust implementation pattern is:

```python
# x, y are contour coordinates resampled to uniform arc-length spacing
tck, u = splprep([x, y], per=True, k=3, s=s_target, w=w)
xs, ys = splev(np.linspace(0, 1, M, endpoint=False), tck)
```

What to use for `s_target`:

Start with a **noise-based** rather than heuristic rule.

If you can estimate contour noise `σ` in pixels and use **unit weights**:
- `s_target ≈ M * σ**2`

If you instead use **weights `w_i = 1/σ_i`**:
- start at `s_target ≈ M`
- sweep in a narrow band around that, guided by FITPACK’s `m ± sqrt(2m)` rule. citeturn6view0turn6view1

For your objects, a good operational envelope is:

- resample to **0.5–1.0 px arc-length spacing**;
- evaluate the spline at **at least the same number of points**, often 2× more for stable perimeter integration;
- use `k=3`, `per=True`;
- estimate `σ` from synthetic-circle residuals of your existing thresholding pipeline and keep `s_target` in the regime that removes only pixel-scale oscillations. citeturn6view0turn45view0

In practice, that usually means:

- **near-circular GUV slices** can tolerate the upper end of your calibrated `s`;
- **RBC slices with biconcavity** and **vesicles with 5–10 px buds** should use the lower end or a locally confidence-weighted fit;
- if you cannot afford calibration complexity, a conservative default is to use **small smoothing only**, then reject any slice where the spline changes area or perimeter versus the raw mask beyond your acceptable threshold. This last check is an engineering safeguard, not a published standard. citeturn36view0turn45view4

Why this is preferable to the alternatives:

**Better than `approxPolyDP`** because it actually smooths rather than just decimates vertices. citeturn46view0turn12search7

**Better than Gaussian mask pre-smoothing** because it avoids boundary migration introduced by blur-plus-threshold on a 2–4 px membrane ring. citeturn11view1turn44view4

**Better than contour-domain Gaussian alone** because it gives you a noise-budget interpretation of the tuning parameter instead of just a blur width, while still respecting closure. citeturn6view0turn37search4

**Safer than active contour** for your time budget because it is one-shot and deterministic rather than iterative and parameter-coupled. citeturn39view0

A pragmatic fallback, if you want something even simpler and faster, is:

**Periodic Gaussian smoothing of contour coordinates after uniform arc-length resampling**, using a wrapped 1-D Gaussian on `x(s)` and `y(s)` separately, with a small sigma around **0.8–1.2 contour samples** and a strict cap near **1.5** if 5–10 px buds must survive. I would choose this only if implementation simplicity beats the value of an `s` parameter tied to noise statistics. It is still preferable to Gaussian mask blur before contouring. citeturn44view4turn37search4turn11view1

Known failure modes and edge cases:

- **Over-smoothing small real buds or deep notches.** Bartlett et al. explicitly show that smoothing free of pixel noise can still underestimate high-curvature regions. citeturn45view4
- **Nonuniform point density from `findContours`.** Always resample by arc length before smoothing; otherwise the spline or Gaussian acts partly on sampling artifacts rather than geometry. This is an engineering conclusion supported by the requirement in active contour and spline methods that point density be adequate and well behaved. citeturn39view0turn6view0
- **Very few points on small top/bottom z-slices.** In very small contours, smoothing can dominate the shape. Clamp smoothing downward or skip 3D metrics for slices below a minimum perimeter/area threshold. This is a pipeline safeguard rather than a published rule.
- **Self-intersections or strongly non-star-shaped contours.** Periodic splines remain closed, but if the raw contour is topologically poor, smoothing cannot fix a bad segmentation. Use segmentation QC upstream. citeturn47view0

## Open questions and limitations

I did not locate a **published, GUV-specific head-to-head study** that compares `splprep`-smoothed contour perimeter against `perimeter_crofton` on the same binary mask. The closest evidence comes from synthetic-shape validation in adjacent fields and from GUV contour/detection papers that validate automation or subpixel localization rather than perimeter bias directly. citeturn45view0turn46view0turn15view0turn25search2

I also did not find a published **standard `alpha`/`beta` tuning guide** for using `skimage.segmentation.active_contour` as a post-segmentation GUV smoother. The parameter directions are clear from the API, but the exact numeric range for “safe” use on your membrane rings remains an engineering choice rather than a literature consensus. citeturn39view0

So the strongest evidence-based path is this: use **periodic spline smoothing**, calibrate `s` on your own synthetic spheres and a small panel of feature-bearing contours, and treat Crofton perimeter from the binary mask as the independent digital-geometry reference when you quantify perimeter bias. That is the cleanest way to satisfy your bias targets without importing LimeSeg’s full 3D machinery. citeturn46view0turn6view0turn45view0
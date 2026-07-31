# Reliable Single-Vesicle Tracking in Crowded Confocal Z-Stacks

## Executive recommendation

For a Python lab tool that must be **reliable first** on crowded confocal Z-stacks of hollow fluorescent vesicles, the best overall choice is **not** a deeper thresholding pipeline and **not** off-the-shelf deep learning. The best default is a **seeded, local, slice-by-slice segmentation pipeline** that treats the user click in the lumen as a **marker for the lumen/background class**, not as object foreground, then recovers the vesicle boundary from a local **inside-versus-outside partition** using **random walker** or, secondarily, **marker-controlled watershed**, followed by **contour refinement** with a fast morphological active contour and strict cross-slice gating by overlap, centroid/radius smoothness, and one-vesicle-only association. This formulation matches the physics of ring-labeled membranes, avoids neighbor-jumping better than thresholded connected components, stays implementable in a 1–2 week upgrade with `numpy/scipy/scikit-image`, and leaves room for optional heavier backends only as rescue tools. citeturn13view0turn13view1turn13view2turn9view3turn8search9turn23search3turn14view0

## What established practice actually looks like

In the GUV literature, “standard practice” is still much more fragmented than many lab pipelines assume. Automated work has historically focused on either **single-plane circular detection** or **population-scale screening**, not on a single seeded vesicle with faithful membrane contours through a crowded 3D stack. Hermann et al. presented a circular Hough transform framework for automated GUV detection, tracking, and analysis on microscopy images; GUV-AP provided a Fiji macro for circular-segment analysis and intensity profiling; DisGUVery later broadened this with circular Hough, multiscale template matching, and flood-fill detection plus a membrane-segmentation module for nonspherical vesicles; and Lee et al. used whole 3D Z-stacks with a CNN mainly to **identify vesicles with desired morphology** after initial masking/segmentation, bringing automated selection closer to manual inspection rather than providing a universally reliable ring-contouring engine. citeturn10view3turn10view2turn23search3turn19view0

That matters for your design brief because it means the most defensible lab architecture is **semi-supervised local instance isolation**, not “solve the whole field and hope the right label is stable.” Fiji’s TrackMate is often useful in practice **after** segmentation already exists, especially now that TrackMate v7 can use shape-aware 2D detectors and label images. But TrackMate’s own documentation also says its Simple LAP/LAP trackers are best suited for particles undergoing Brownian motion and that density hurts reliability; its label-image detector is explicitly meant for already separated touching instances. In other words, **TrackMate is a good stitcher/exporter of labels, not the primary segmenter for crowded static Z-stacks**. Treating Z as time is a pragmatic convenience, not the core segmentation answer. citeturn14view0turn13view3turn13view4turn13view5

Your current baseline has the right instincts in three places: it restricts analysis to a local crop, it keeps the user seed central to identity, and it imposes area sanity checks. The weak link is that it still makes a **thresholded ring fragment** the fundamental unit of truth. GUV populations are heterogeneous, threshold values vary by field, touching vesicles merge under binary masks, and confocal cross-sections can show **out-of-focus fluorescence projected into the lumen**, which biases boundary finding if you rely on simple intensity or component logic. A more reliable formulation is to segment the **lumen-versus-exterior partition** from markers and derive the membrane boundary from that partition, instead of asking thresholded membrane pixels to carry the whole job. citeturn24view0turn8search9turn25search0turn31view0turn13view0

## Ranked methods for MorphoStack

The table below ranks methods for **your exact use case**: one seeded vesicle, crowded field, hollow ring membranes, Python, reliability first, then speed, then dependency weight.

| Method | Reliability | Speed | Dependency weight | Fit for hollow GUVs | Verdict |
|---|---|---:|---:|---|---|
| **Seeded local inside/outside segmentation with random walker, then MorphGAC contour refinement and Z-gating** | **Highest overall** | Fast enough for interactive crops | Light | **Excellent** | Best overall choice. Random walker is inherently marker-driven and resists crossing strong gradients; MorphGAC gives a fast, numerically stable contour refinement; using a lumen marker plus crop-border exterior marker matches ring geometry better than threshold-first logic. citeturn13view0turn13view1turn13view2turn8search9 |
| **Marker-controlled watershed on edge/gradient image with h-minima suppression, plus contour smoothing** | High | **Very fast** | Light | Good | Strong second choice and easiest drop-in replacement for threshold+CC. MorphoLibJ and scikit-image both expose watershed-style workflows; however watershed is more sensitive to marker placement and can create anatomically implausible split lines if necks or touching vesicles are poorly marked. citeturn9view3turn21view0turn9view8 |
| **Local graph cuts with seed markers, optionally with ellipse/shape prior** | High to very high | Medium | Medium to heavy | Very good | Graph cuts give global minima for a useful class of energies and can be made more robust with shape priors, but Python implementations usually mean a GPL dependency and more custom energy engineering than a 1–2 week lab upgrade usually tolerates. Excellent rescue backend, not the default first implementation. citeturn35view0turn35view1turn30search3 |
| **Radial contour sampling with circle/ellipse warm start** | Medium-high on isolated near-spherical slices | **Fastest** | Light | Good when equatorial and isolated | Very useful for initialization, radius estimation, and sanity-gating because GUV workflows already use circular/radial profiles, but not reliable enough by itself in crowded or touching data. Circular Hough is known to bias toward circular profiles. citeturn10view3turn24view0turn19view0turn8search0 |
| **TrackMate label-image linking with Z-as-time** | Medium | Fast after labels exist | Medium | Indirect | Good as a label stitcher or QC/export layer once per-slice labels already exist. Not a primary segmentation solution for your problem because TrackMate’s LAP assumptions are about frame-to-frame particle linking, not ring membrane delineation in dense static stacks. citeturn13view3turn13view4turn13view5 |
| **Full 3D deformable surface or surfel active surface** | Medium for interactive use | Slow | Medium to heavy | Good in principle | Theoretical appeal is high because all Z slices are coupled, but for an interactive lab tool this is usually too slow and parameter-heavy compared with a seeded per-slice method plus 3D reconstruction afterward. Better as a later advanced backend than as the first upgrade. citeturn32view0turn32view1turn11search1 |
| **Off-the-shelf DL with pretrained Cellpose/StarDist/SAM-class tools** | Low to medium out of the box | Medium to fast with GPU | **Heavy** | Mixed | Weak default choice for ring membranes in crowded GUV Z-stacks. Cellpose is generalist cell segmentation; StarDist assumes star-convex blob-like objects and pretrained models are heavily nuclei-centered; TrackMate-StarDist’s own tutorials use nuclei models and a slice-by-slice 3D workaround. Use only as an optional custom-trained proposal generator, not default truth. citeturn20view0turn20view1turn20view2turn13view6turn19view0 |

For **hollow fluorescent rings**, the rigorous way to interpret a lumen click is simple but important: the click should define a **lumen marker**, not a membrane foreground seed. In a local crop, give the lumen one label, give the crop border an exterior/background label, and let the segmentation method determine the separating boundary; then turn that boundary into a membrane contour or a thin annulus if you want a membrane mask. This is mathematically cleaner than trying to “grow” the membrane from a dark interior point, and it aligns with how random walker, flood-fill, and hole-filling/reconstruction operators are defined. Confocal GUV work also shows that the interior can be contaminated by out-of-focus fluorescence, which is another reason to prefer a marker-based inside/outside partition over raw thresholding of rim pixels. citeturn13view0turn13view2turn25search0turn31view0turn8search9

When objects touch, the safest separation methods for **morphometry**, not just counting, are the ones that keep the seed and the local geometry central: seeded random walker, graph cuts, or a seeded contour evolution constrained by the previous slice. Distance-transform watershed is still useful, especially with controlled markers and h-minima suppression, but it tends to place a split line where the topology forces one, not necessarily where the membrane geometry is biologically plausible. In a crowded one-vesicle workflow, that makes watershed better as a fast fallback or proposal generator than as the only source of truth. citeturn9view3turn21view0turn9view8turn35view0

## Proposed default pipeline

The default MorphoStack pipeline should be built around a **local, seeded, one-object-only state machine**, not around global image segmentation. On the first seeded slice, use a local crop to estimate scale from radial intensity or gradient peaks, create a lumen marker from the click or a small user-drawn circle, create an exterior marker from the crop border, compute a membrane-evidence image from denoised gradients or inverse Gaussian gradient, solve a local random-walker segmentation, then optionally refine the boundary with MorphGAC on the same crop. On neighboring slices, propagate the previous contour as a soft prior, keep the same local crop center unless the contour says otherwise, and score candidate solutions with overlap, centroid drift, radius smoothness, and contour-shape continuity. Only after the right object is locked should you derive the **solid interior mask** for area, Crofton perimeter, skeleton centerline, and 3D meshing. This strategy is consistent with GUV radial contour practice, marker-based segmentation, and modern open-source Python implementations. citeturn8search0turn8search9turn13view0turn13view1turn22search3

```python
def segment_seeded_vesicle(stack, z0, seed_xy, voxel_spacing=None):
    # load lazily if possible; only pull one Z slice or local crop into memory

    # --- initialize on seeded slice ---
    crop0 = local_crop(stack[z0], center=seed_xy, radius=estimate_crop_radius(seed_xy))
    I0 = preprocess(crop0)  # light denoise + background flattening + contrast normalization

    # Step 1: estimate vesicle scale from radial intensity / gradient peaks
    r0 = estimate_radius_from_radial_profiles(I0, seed_xy)

    # Step 2: create markers
    lumen_marker = flood_from_seed(I0, seed_xy, tolerance=local_lumen_tolerance(I0))
    exterior_marker = crop_border_marker(I0, margin=2)
    allowed_band = annulus_or_signed_distance_gate(center=seed_xy, radius=r0, width=0.4 * r0)

    # Step 3: build membrane-evidence image
    edge_img = inverse_gaussian_gradient(I0)          # for MorphGAC
    rw_img   = normalized_gradient_or_ridge(I0)       # for random walker

    # Step 4: inside/outside partition
    partition = seeded_random_walker(
        rw_img,
        markers={"lumen": lumen_marker, "outside": exterior_marker},
        mask=allowed_band
    )

    contour0 = boundary_between_labels(partition, "lumen", "outside")

    # Step 5: optional contour refinement
    contour0 = refine_with_morphgac(edge_img, init=contour0, mask=allowed_band)

    # Step 6: derive outputs
    solid_mask0 = fill_holes(label_to_interior_mask(partition))
    membrane_mask0 = thin_annulus_around(contour0, I0, target="rim")
    state = init_track_state(z0, contour0, solid_mask0, membrane_mask0)

    # --- propagate through Z ---
    for z in neighbors_outward(z0):
        crop = local_crop(stack[z], center=state.pred_center, radius=state.pred_crop_radius)
        I = preprocess(crop)

        prior_gate = signed_distance_gate_from_prev(state.prev_contour, max_expand_px=delta_r(z))
        lumen_marker = projected_lumen_seed(state.prev_solid_mask, I.shape)
        exterior_marker = crop_border_marker(I, margin=2)

        partition = seeded_random_walker(
            normalized_gradient_or_ridge(I),
            markers={"lumen": lumen_marker, "outside": exterior_marker},
            mask=prior_gate
        )

        contour = refine_with_morphgac(inverse_gaussian_gradient(I), init=boundary_between_labels(partition), mask=prior_gate)
        solid_mask = fill_holes(label_to_interior_mask(partition))
        membrane_mask = thin_annulus_around(contour, I, target="rim")

        score = association_score(
            contour, solid_mask,
            prev_contour=state.prev_contour,
            prev_mask=state.prev_solid_mask,
            weights={"IoU": 0.45, "centroid": 0.20, "radius": 0.20, "shape": 0.15}
        )

        if score < FAIL_THRESHOLD:
            mark_slice_untrusted(z)
            if weak_signal_at_pole(I):
                continue  # allow sparse missing polar slices
            else:
                request_user_reseed_or_exclude(z)

        store_slice_outputs(z, contour, solid_mask, membrane_mask)
        state = update_state(z, contour, solid_mask, membrane_mask)

    # --- metrics and 3D reconstruction ---
    per_slice_area = mask_area(all_solid_masks)
    per_slice_perimeter = crofton_or_subpixel_contour_perimeter(all_solid_masks, all_contours)
    per_slice_centerline = optional_medial_axis(all_solid_masks)
    volume_mask = stack_masks_to_3d(all_solid_masks)

    mesh = marching_cubes(volume_mask, spacing=voxel_spacing, method="lewiner")
    return results
```

For measurements, use the **filled interior mask** for area and for building the 3D volume that will feed marching cubes; use either a **subpixel contour length** from the recovered boundary or a **Crofton perimeter** from the filled 2D mask for perimeter statistics. Do **not** use a skeleton as the primary perimeter estimator. Skeletonization and medial axis transforms are designed to reduce objects to topology-preserving centerlines and local widths, which is exactly why they are useful for optional centerlines or branch analysis, not as the main vesicle perimeter measurement. For the mesh, `skimage.measure.marching_cubes(..., spacing=voxel_spacing, method="lewiner")` is the right default because scikit-image’s Lewiner implementation is faster, resolves ambiguities, and is documented as topologically correct. citeturn33view0turn33view1turn33view2turn33view3turn22search3

On the specific question of **Vossepoel–Smeulders-style perimeter ideas versus contour perimeter**, the modern practical answer is straightforward. Chain-code perimeter estimators belong to the digital-geometry literature because naive pixel counting is anisotropic; scikit-image’s own examples now emphasize Crofton-style estimators as more accurate than classic approximations across object rotations. For GUV cross-sections, that means you should prefer either a **subpixel contour length** if the contour itself is trustworthy, or **Crofton perimeter** if you want a robust digital-mask estimator from the filled interior. Reserve the medial axis for centerline extraction in tubulated or strongly invaginated specimens. citeturn15search0turn33view0turn33view1turn33view3

## What not to do and the right stance on deep learning

Do **not** make global thresholding the backbone of the system. Do **not** ask a lumen click to stand in for membrane foreground. Do **not** trust connected components to preserve object identity in a crowded field. Do **not** rely on TrackMate’s LoG spot detector for ring membranes in touching vesicles. Do **not** compute a 3D mesh from a thin ring mask; mesh a filled solid mask instead. And do **not** replace contour perimeter with a skeleton unless what you truly need is a centerline or branch topology. Each of those choices either mismatches the ring-labeled imaging physics or throws away the object-identity constraints that make the workflow reliable. citeturn14view0turn24view0turn25search0turn33view1turn33view2turn22search3

The deep-learning answer for this project is **no as a default, yes only in narrow cases**. I did find a GUV-specific CNN paper, but its main contribution was **whole-Z-stack vesicle identification/classification** to approach manual selection performance after initial masking, not a demonstrated win for precise membrane-ring contouring in crowded confocal stacks. By contrast, StarDist is explicitly built around **star-convex blob-like shapes**, its pretrained models are heavily nuclei-oriented, and its Fiji/TrackMate integrations carry TensorFlow and slice-by-slice 3D compromises; Cellpose is broader and powerful, but it is still a generalist **cell** segmenter with much heavier PyTorch-based dependencies and I did not find a ring-membrane benchmark showing clear superiority over a seeded classical pipeline for your domain. The evidence for “drop-in DL beats seeded classical CV on hollow GUV rings” is therefore **weak**, and in places arguably the wrong domain. citeturn19view0turn20view1turn20view2turn13view6turn20view0turn39view0

If you later choose to add DL, the safest use is as a **proposal generator or rescue backend**, not as the sole arbiter of morphology. In practice that means: run a custom-trained local StarDist or Cellpose model only on the user’s crop or on the seeded slice; use the DL mask as an initialization or a vetoed proposal; and still pass its result through the same seed-consistency, overlap, shape-smoothness, and user-QC logic as the classical path. That gives you a path to exploit DL if the lab later produces annotations, without betting the entire tool on an unvalidated pretrained model. citeturn20view2turn39view0turn19view0

## Implementation priorities, backends, must-reads, and open questions

For a **1–2 week improvement window**, I would prioritize four changes in this order. First, replace threshold+connected-components with a **seeded lumen-versus-exterior local segmenter** on the current crop. Second, add **cross-slice gating** based on overlap, centroid drift, and radius/shape smoothness, so the tool refuses to jump to neighbors even when a tempting bright ring appears nearby. Third, separate the notions of **membrane contour**, **filled interior mask**, and **review status**, because they serve different downstream tasks. Fourth, expose simple user recovery actions: re-seed, paint an exclusion scribble, skip weak polar slices, or lock one slice as manual truth. Those changes keep the UX you already have, but move the geometry to a much safer representation. citeturn13view0turn13view1turn24view0turn8search9

A practical backend stack for MorphoStack looks like this:

| Backend | Role in the tool | License | Install weight | Recommendation |
|---|---|---|---:|---|
| `numpy` + `scipy` + `scikit-image` | Core segmentation, morphology, measurements, marching cubes | BSD-style / BSD-3-Clause | Light | Default computational stack. `scikit-image` provides random walker, MorphGAC/MorphACWE, morphology, Crofton perimeter, and marching cubes; SciPy provides binary hole filling. citeturn29search0turn29search1turn13view0turn13view1turn22search3turn25search0 |
| `tifffile` | OME-TIFF/TIFF reading and metadata | BSD-3-Clause | Light | Best minimal TIFF path. Good for offline lab installs focused on TIFF/OME-TIFF. citeturn28search0turn37search5 |
| `AICSImageIO` | Lazy microscopy I/O, dimension normalization, metadata access | BSD-3-Clause core | Medium | Very helpful when you want lazy, consistent `TCZYX` loading. Note that CZI support is not included in the open-license `[all]` extra because that path uses GPL components. citeturn40view0turn40view1 |
| `aicspylibczi` | Direct CZI access and metadata | GPL-3.0-or-later | Medium | Useful when native CZI access matters more than permissive licensing. Reads subsets and metadata directly. citeturn40view2 |
| `napari` | Interactive seed/QC GUI | BSD-3-Clause | Medium | Strong choice for click/scribble review UX, but not required for the segmentation engine itself. citeturn29search3turn29search19 |
| `opencv-python` | Optional Hough/ellipse warm start | MIT wrapper / OpenCV Apache 2 | Medium-light | Nice if you want very fast circle/ellipse initialization, but optional. citeturn29search2turn29search6 |
| `PyMaxflow` | Optional graph-cut rescue backend | GPL | Medium | Good only if you explicitly want graph-cut experiments; license and custom-energy complexity make it a poor default. citeturn30search2turn30search3 |
| `StarDist` | Optional custom-trained proposal backend | BSD-3-Clause + TensorFlow | Heavy | Only worthwhile if you later train on your own ring data. Pretrained models are not aligned to this problem. citeturn38view0turn20view1 |
| `Cellpose` | Optional custom-trained proposal backend | BSD-3-Clause + PyTorch | Heavy | Strong ecosystem, but too heavy and too off-domain to be the default here. citeturn39view0 |

The most important papers and plugins to keep at your elbow are these:

| Paper or plugin | Why it matters here |
|---|---|
| **Hermann et al., automated GUV analysis by circular Hough transform** | The classic automated GUV detection/tracking reference; excellent for understanding where circle-based automation works and where it biases results. citeturn10view3 |
| **Sych et al., GUV-AP** | Fiji-based practical tool for circular-segment workflows and membrane intensity analysis; good reference for pragmatic vesicle QA. citeturn10view2 |
| **van Buren et al., DisGUVery** | Probably the most relevant vesicle-analysis software paper for your brief because it explicitly combines multiple detection modes and adds membrane segmentation for nonspherical vesicles. citeturn23search3turn23search4 |
| **Dreher et al., GeoV** | Best “what do I do after segmentation?” reference for 3D vesicle reconstruction and shape analysis from confocal Z-stacks. citeturn11search1turn11search0 |
| **Pécréaux et al., refined contour analysis of GUVs** | The classic contour-analysis reference and a reminder that careful boundary finding matters directly for vesicle mechanics and morphometry. citeturn8search0 |
| **Faizi et al., confocal fluctuation spectroscopy caveats** | Essential warning that out-of-focus fluorescence can shift confocal contour detection inward; directly relevant to lumen-seed handling and weak polar slices. citeturn8search9 |
| **TrackMate LAP docs + label-image detector** | Best practical reference if you decide to export your per-slice labels into Fiji for linking, annotation, and QC. citeturn13view3turn13view4 |
| **MorphoLibJ** | The Fiji reference for marker-controlled watershed and touching-object separation; useful to mirror or benchmark your Python implementation. citeturn9view3 |
| **Grady random walker** | The theoretical basis for the seeded segmentation step I recommend as the default. citeturn13view0turn12search18 |
| **Chan–Vese and Geodesic Active Contours** | The core deformable-contour papers behind the refinement stage and any later level-set backend. citeturn32view1turn32view0 |

The main open questions that still need **lab validation on real CZI data** are not conceptual; they are empirical tuning questions. The most important are how much out-of-focus fluorescence in your confocal settings contaminates the lumen near non-equatorial slices; how often touching vesicles require explicit negative scribbles rather than automatic gates; whether weak polar slices should be automatically interpolated or explicitly marked “untrusted” for downstream meshing; and whether your voxel anisotropy is mild enough that slice-wise tracking plus marching cubes is sufficient, or severe enough that you should later test a truly 3D segmenter. Those are exactly the kinds of failure modes highlighted by the GUV and confocal contour papers, and they are where a fast local prototype will tell you more than another month of architectural debate. citeturn8search9turn24view0turn40view0turn11search1
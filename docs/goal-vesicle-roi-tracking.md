# Goal: Fiji circle ROI + reliable single-vesicle tracking

## Reference models

### Fiji
- **Oval / Circle ROI**: user draws circle; center + radius define the object.
- ROI is spatial constraint, not a 10px click.
- Threshold/analyze often limited to ROI.

### LimeSeg (`SphereSeg`)
- Reads `OvalRoi` from ROI Manager.
- `r0 = (width+height)/4`, center = ROI center, Z from ROI position.
- Initializes a **sphere seed** of that radius; optimizes 3D surface (does not re-pick global CC each slice).
- Multi-object: one sphere per ROI; surfaces repel.

## MorphoStack target behavior
1. User draws **circle** on full-field preview (drag radius).
2. Script uses (cx, cy, R) as hard prior every Z.
3. Contour is **one** vesicle; full field still displayed for QC.
4. Track: update (cx, cy) with contour centroid; keep R from user circle (slight adapt only).
5. Touching neighbors outside circle ignored.

## Non-goals
- Cellpose/StarDist required deps.
- Preview zoom-to-crop (user must see full field).

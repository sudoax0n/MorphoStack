# Synthetic Touching Vesicles — Negative Reference

Two touching vesicles in a 5-slice stack (large r=12 µm at x=30, small r=8 µm at x=48).
Circle seed is on the large vesicle only.

This run documents an **expected failure mode** for threshold-only vesicle tracking:
the seed does not change the merged mesh compared with the unseeded run.

Run (fast, threshold only):

```powershell
python scripts/validate_synthetic_touching.py
```

Optional Active Surfaces comparison (slow):

```powershell
python scripts/validate_synthetic_touching.py --with-active_surfaces
```

- Threshold-only mesh volume: 2430.7 µm³
- Threshold seeded mesh volume: 1660.0 µm³
- Failure mode confirmed: `True`

Use ROI crop, polygon seed, or Active Surfaces when objects touch.

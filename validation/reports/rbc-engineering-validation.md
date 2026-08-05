# RBC engineering validation

Generated: `2026-08-05T07:28:24.027682+00:00`

**Biological validation: false.** This report is an engineering regression gate only.

All passed: **True**

## Tolerances

- Volume relative error ≤ 5%
- Projected axis relative error ≤ 3%
- Topology holes must round-trip exactly

## Cases

### solid_oblate
- passed: `True`
- note: mesh relative error 0.0037 (reported, not hard-fail alone)

### biconcave
- passed: `True`
- note: mesh relative error 0.0024 (reported, not hard-fail alone)

### annular_caps
- passed: `True`
- note: mesh relative error 0.0073 (reported, not hard-fail alone)

### tilted
- passed: `True`

### anisotropic
- passed: `True`
- note: mesh relative error 0.0037 (reported, not hard-fail alone)

### incomplete_caps
- passed: `True`
- note: mesh relative error 0.4081 (reported, not hard-fail alone)
- note: stack touches Z caps — capability demotion is QC responsibility

### lateral_clip
- passed: `True`
- note: mesh relative error 0.0407 (reported, not hard-fail alone)
- note: laterally clipped — capability demotion is QC responsibility

### touching_pair
- passed: `True`
- note: mesh relative error 0.0064 (reported, not hard-fail alone)
- note: unexpected single-component topology for touching pair

### noisy_low_sbr
- passed: `True`
- note: mesh relative error 0.1043 (reported, not hard-fail alone)


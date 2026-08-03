"""Calibrated 3D seed mapping (Milestone B packet 13).

Maps viewer world coordinates (µm) through a display-pyramid level into
source-level ``ObjectSeed`` fields used by Milestone A tracking.

Transform chain
---------------
::

    world_x/y/z (µm)
      <-> continuous level voxel indices (x,y,z; VTK ImageData order)
      <-> continuous source voxel indices (x,y,z)
      <-> ObjectSeed(x_px, y_px, frame_z, radius_px)

Rounding / clamping (documented, not silent)
--------------------------------------------
- Source XY for ``ObjectSeed`` use **nearest integer** (half-up via
  ``round``), matching the 2D UI ``Math.round`` pixel pick.
- Source Z (frame) uses **nearest integer** clamped to
  ``[0, shape_z - 1]``. Acceptance requires the reprojected Z index to
  equal that frame exactly.
- Round-trip acceptance: reprojected source XY within **one source voxel**
  of the original continuous position; Z index exact.
- Out-of-bounds continuous source coords are **rejected** (not clamped
  silently) except Z which is clamped only after nearest-integer frame
  selection when ``clamp_z=True`` for interactive UX; validation API
  uses ``clamp_z=False`` and rejects OOB.
- Radius remains **source XY pixels** (current ``ObjectSeed`` semantics).
  Optional ``radius_um`` converts via source ``VoxelSize.x_um`` only when
  calibration is known.

Camera orientation and display anisotropy must not change the source seed:
world↔level uses only level spacing and origin; level↔source uses explicit
integer downsample factors from the display level descriptor.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal, Mapping, Sequence

from morphostack.core.pipeline import ObjectSeed
from morphostack.core.models import VoxelSize

SeedOrigin = Literal["ui_2d", "viewer_3d"]
RadiusUnit = Literal["px", "um"]


class SeedMappingError(ValueError):
    """Invalid seed coordinate mapping or stale display revision."""

    def __init__(self, message: str, *, code: str = "seed_mapping_error") -> None:
        super().__init__(message)
        self.code = code


@dataclass(frozen=True)
class DisplayLevelGeometry:
    """Geometry needed to map a display level to source voxels."""

    level: int
    shape_zyx: tuple[int, int, int]
    """Display level array shape (Z, Y, X)."""

    factors_zyx: tuple[int, int, int]
    """Integer downsample factors vs source: (fz, fy, fx)."""

    level_voxel_size: VoxelSize
    """Physical spacing of **level** voxels (µm)."""

    source_shape_zyx: tuple[int, int, int]
    """Full-resolution source shape (Z, Y, X)."""

    source_voxel_size: VoxelSize
    """Source (science) spacing (µm)."""

    source_revision: str | None = None
    axes: str = "zyx"
    calibration_known: bool = True
    """False when voxel spacing is placeholder/unknown — world µm not labelled as calibrated."""

    def __post_init__(self) -> None:
        if len(self.shape_zyx) != 3 or len(self.factors_zyx) != 3 or len(self.source_shape_zyx) != 3:
            raise SeedMappingError("shapes/factors must be length-3 ZYX tuples", code="invalid_geometry")
        for name, f in zip(("fz", "fy", "fx"), self.factors_zyx, strict=True):
            if int(f) < 1:
                raise SeedMappingError(f"{name} must be >= 1", code="invalid_geometry")


@dataclass(frozen=True)
class WorldPointUm:
    x_um: float
    y_um: float
    z_um: float

    def as_tuple(self) -> tuple[float, float, float]:
        return (float(self.x_um), float(self.y_um), float(self.z_um))


@dataclass(frozen=True)
class LevelVoxel:
    """Continuous level indices in VTK order (x, y, z)."""

    x: float
    y: float
    z: float


@dataclass(frozen=True)
class SourceVoxel:
    """Continuous source indices (x, y, z); z is frame-like."""

    x: float
    y: float
    z: float


def factors_xyz(geometry: DisplayLevelGeometry) -> tuple[float, float, float]:
    """Return (fx, fy, fz) for XYZ multiplies from level → source."""

    fz, fy, fx = (int(v) for v in geometry.factors_zyx)
    return (float(fx), float(fy), float(fz))


def world_to_level_voxel(world: WorldPointUm, geometry: DisplayLevelGeometry) -> LevelVoxel:
    """World µm → continuous level indices (origin 0, spacing = level voxel size)."""

    sx = float(geometry.level_voxel_size.x_um)
    sy = float(geometry.level_voxel_size.y_um)
    sz = float(geometry.level_voxel_size.z_um)
    if sx <= 0 or sy <= 0 or sz <= 0:
        raise SeedMappingError("level voxel spacing must be positive", code="invalid_geometry")
    return LevelVoxel(
        x=float(world.x_um) / sx,
        y=float(world.y_um) / sy,
        z=float(world.z_um) / sz,
    )


def level_voxel_to_world(level: LevelVoxel, geometry: DisplayLevelGeometry) -> WorldPointUm:
    return WorldPointUm(
        x_um=float(level.x) * float(geometry.level_voxel_size.x_um),
        y_um=float(level.y) * float(geometry.level_voxel_size.y_um),
        z_um=float(level.z) * float(geometry.level_voxel_size.z_um),
    )


def level_to_source_voxel(level: LevelVoxel, geometry: DisplayLevelGeometry) -> SourceVoxel:
    fx, fy, fz = factors_xyz(geometry)
    return SourceVoxel(x=float(level.x) * fx, y=float(level.y) * fy, z=float(level.z) * fz)


def source_to_level_voxel(source: SourceVoxel, geometry: DisplayLevelGeometry) -> LevelVoxel:
    fx, fy, fz = factors_xyz(geometry)
    return LevelVoxel(x=float(source.x) / fx, y=float(source.y) / fy, z=float(source.z) / fz)


def source_to_world(source: SourceVoxel, geometry: DisplayLevelGeometry) -> WorldPointUm:
    """Source continuous indices → world via level path (anisotropy-safe)."""

    return level_voxel_to_world(source_to_level_voxel(source, geometry), geometry)


def world_to_source_voxel(world: WorldPointUm, geometry: DisplayLevelGeometry) -> SourceVoxel:
    return level_to_source_voxel(world_to_level_voxel(world, geometry), geometry)


def nearest_int(value: float) -> int:
    """Nearest integer with half-away-from-zero (matches 2D UI Math.round).

    Python's built-in ``round`` uses banker's rounding; seed paths must not.
    """
    v = float(value)
    if v >= 0:
        return int(v + 0.5)
    return int(v - 0.5)


# Backward-compatible private alias.
_nearest_int = nearest_int


def source_in_bounds(
    source: SourceVoxel,
    geometry: DisplayLevelGeometry,
    *,
    strict: bool = True,
) -> bool:
    sz, sy, sx = (int(v) for v in geometry.source_shape_zyx)
    if strict:
        return 0.0 <= source.x < sx and 0.0 <= source.y < sy and 0.0 <= source.z < sz
    # After integer quantization, valid seed domain is [0, dim-1]
    return 0 <= _nearest_int(source.x) < sx and 0 <= _nearest_int(source.y) < sy and 0 <= _nearest_int(source.z) < sz


def source_voxel_to_object_seed(
    source: SourceVoxel,
    *,
    geometry: DisplayLevelGeometry,
    radius_px: float,
    clamp_z: bool = False,
    max_tracking_dist_um: float | None = None,
    seed_origin: SeedOrigin = "viewer_3d",
    source_revision: str | None = None,
) -> ObjectSeed:
    """Quantize continuous source voxels to canonical ObjectSeed (source px)."""

    if float(radius_px) <= 0:
        raise SeedMappingError("radius_px must be positive", code="invalid_radius")

    sz, sy, sx = (int(v) for v in geometry.source_shape_zyx)
    xi = _nearest_int(source.x)
    yi = _nearest_int(source.y)
    zi = _nearest_int(source.z)

    if clamp_z:
        zi = max(0, min(sz - 1, zi))
    else:
        if not (0 <= zi < sz):
            raise SeedMappingError(
                f"seed Z frame {zi} out of bounds for shape_z={sz}",
                code="out_of_bounds",
            )

    if not (0 <= xi < sx and 0 <= yi < sy):
        raise SeedMappingError(
            f"seed XY ({xi}, {yi}) out of bounds for shape=({sy},{sx})",
            code="out_of_bounds",
        )

    rev = source_revision if source_revision is not None else geometry.source_revision
    return ObjectSeed(
        x=float(xi),
        y=float(yi),
        frame_index=int(zi),
        radius=float(radius_px),
        max_tracking_dist_um=max_tracking_dist_um,
        type="circle",
        points=None,
        source_revision=rev,
        seed_origin=seed_origin,
        radius_unit="px",
    )


def object_seed_to_source_voxel(seed: ObjectSeed) -> SourceVoxel:
    return SourceVoxel(x=float(seed.x), y=float(seed.y), z=float(seed.frame_index))


def object_seed_to_world(seed: ObjectSeed, geometry: DisplayLevelGeometry) -> WorldPointUm:
    return source_to_world(object_seed_to_source_voxel(seed), geometry)


def world_to_object_seed(
    world: WorldPointUm,
    *,
    geometry: DisplayLevelGeometry,
    radius_px: float,
    clamp_z: bool = True,
    max_tracking_dist_um: float | None = None,
    expected_source_revision: str | None = None,
) -> ObjectSeed:
    """Full viewer path: world pick → source ObjectSeed."""

    if expected_source_revision is not None:
        validate_seed_revision(
            seed_revision=geometry.source_revision,
            current_revision=expected_source_revision,
        )
    source = world_to_source_voxel(world, geometry)
    if not source_in_bounds(source, geometry, strict=True) and not clamp_z:
        raise SeedMappingError(
            f"world pick maps outside source volume: {source}",
            code="out_of_bounds",
        )
    seed = source_voxel_to_object_seed(
        source,
        geometry=geometry,
        radius_px=radius_px,
        clamp_z=clamp_z,
        max_tracking_dist_um=max_tracking_dist_um,
        seed_origin="viewer_3d",
        source_revision=geometry.source_revision,
    )
    # Round-trip gate: XY within one source voxel of continuous map; Z exact.
    assert_seed_roundtrip(world, seed, geometry)
    return seed


def assert_seed_roundtrip(
    world: WorldPointUm,
    seed: ObjectSeed,
    geometry: DisplayLevelGeometry,
    *,
    max_xy_err: float = 1.0 + 1e-6,
) -> None:
    """Require quantized seed to stay within one source XY voxel of continuous map."""

    continuous = world_to_source_voxel(world, geometry)
    dx = abs(float(seed.x) - continuous.x)
    dy = abs(float(seed.y) - continuous.y)
    if dx > max_xy_err or dy > max_xy_err:
        raise SeedMappingError(
            f"XY round-trip exceeds one source voxel: dx={dx}, dy={dy}",
            code="roundtrip_xy",
        )
    if int(seed.frame_index) != _nearest_int(continuous.z) and not (
        0 <= int(seed.frame_index) < int(geometry.source_shape_zyx[0])
    ):
        # When clamp_z moved the frame, continuous Z may be OOB; only enforce
        # exactness when continuous Z was in-bounds.
        if 0.0 <= continuous.z < float(geometry.source_shape_zyx[0]):
            if int(seed.frame_index) != _nearest_int(continuous.z):
                raise SeedMappingError(
                    f"Z frame mismatch: seed={seed.frame_index} nearest={_nearest_int(continuous.z)}",
                    code="roundtrip_z",
                )
    elif 0.0 <= continuous.z < float(geometry.source_shape_zyx[0]):
        if int(seed.frame_index) != _nearest_int(continuous.z):
            raise SeedMappingError(
                f"Z frame mismatch: seed={seed.frame_index} nearest={_nearest_int(continuous.z)}",
                code="roundtrip_z",
            )


def radius_um_to_px(radius_um: float, source_voxel: VoxelSize, *, calibration_known: bool) -> float:
    if not calibration_known:
        raise SeedMappingError(
            "cannot convert radius_um without known calibration (would mislabel micrometres)",
            code="unknown_calibration",
        )
    if float(radius_um) <= 0:
        raise SeedMappingError("radius_um must be positive", code="invalid_radius")
    return float(radius_um) / float(source_voxel.x_um)


def radius_px_to_um(radius_px: float, source_voxel: VoxelSize, *, calibration_known: bool) -> float:
    if not calibration_known:
        raise SeedMappingError(
            "cannot report radius_um without known calibration",
            code="unknown_calibration",
        )
    return float(radius_px) * float(source_voxel.x_um)


def validate_seed_revision(
    *,
    seed_revision: str | None,
    current_revision: str | None,
) -> None:
    """Reject seeds tagged with a stale display/source revision."""

    if seed_revision is None or seed_revision == "":
        return
    if current_revision is None or current_revision == "":
        raise SeedMappingError(
            "seed carries source_revision but stack revision is unknown; refresh 3D volume",
            code="stale_revision",
        )
    if str(seed_revision) != str(current_revision):
        raise SeedMappingError(
            "3D seed source_revision does not match current stack; refresh the volume viewer",
            code="stale_revision",
        )


def geometry_from_level_payload(
    *,
    level: Mapping[str, Any],
    display_volume_spec: Mapping[str, Any] | None,
    source_shape_zyx: Sequence[int],
    source_voxel_size: VoxelSize,
    calibration_known: bool = True,
) -> DisplayLevelGeometry:
    """Build geometry from packet-11 level JSON + inspect source shape."""

    shape = level.get("shape") or (display_volume_spec or {}).get("shape")
    if not shape or len(shape) < 3:
        raise SeedMappingError("level shape missing", code="invalid_geometry")
    factors = level.get("downsample_from_source")
    if factors is None and display_volume_spec:
        down = display_volume_spec.get("downsampling") or {}
        factors = down.get("factors_zyx")
    if factors is None:
        factors = (1, 1, 1)
    vs = level.get("voxel_size") or (display_volume_spec or {}).get("level_voxel_size") or {}
    level_vs = VoxelSize(
        float(vs.get("x_um", source_voxel_size.x_um)),
        float(vs.get("y_um", source_voxel_size.y_um)),
        float(vs.get("z_um", source_voxel_size.z_um)),
    )
    rev = None
    if display_volume_spec is not None:
        rev = display_volume_spec.get("source_revision")
    return DisplayLevelGeometry(
        level=int(level.get("level", (display_volume_spec or {}).get("level", 0))),
        shape_zyx=(int(shape[0]), int(shape[1]), int(shape[2])),
        factors_zyx=(int(factors[0]), int(factors[1]), int(factors[2])),
        level_voxel_size=level_vs,
        source_shape_zyx=(int(source_shape_zyx[0]), int(source_shape_zyx[1]), int(source_shape_zyx[2])),
        source_voxel_size=source_voxel_size,
        source_revision=str(rev) if rev is not None else None,
        axes=str(level.get("axes") or (display_volume_spec or {}).get("axes") or "zyx"),
        calibration_known=bool(calibration_known),
    )


def seed_mapping_dict(seed: ObjectSeed, geometry: DisplayLevelGeometry | None = None) -> dict[str, Any]:
    """JSON-safe provenance for logs/manifests (not a tracking identity field)."""

    payload: dict[str, Any] = {
        "x": float(seed.x),
        "y": float(seed.y),
        "frame_index": int(seed.frame_index),
        "radius": float(seed.radius),
        "radius_unit": getattr(seed, "radius_unit", "px") or "px",
        "seed_origin": getattr(seed, "seed_origin", "ui_2d") or "ui_2d",
        "source_revision": getattr(seed, "source_revision", None),
        "type": seed.type,
    }
    if geometry is not None:
        world = object_seed_to_world(seed, geometry)
        payload["world_um"] = {
            "x_um": world.x_um,
            "y_um": world.y_um,
            "z_um": world.z_um,
            "calibration_known": geometry.calibration_known,
        }
        payload["display_level"] = geometry.level
        payload["factors_zyx"] = list(geometry.factors_zyx)
    return payload

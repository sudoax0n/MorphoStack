/**
 * Contained, display-only browser volume navigation (Milestone B / packet 12).
 *
 * Loads one bounded coarse level from POST /display-pyramid/level, renders with
 * bundled VTK.js/WebGL, and never feeds analysis or measurement APIs.
 *
 * Rollback: set localStorage morphostack.enableVolumeViewer=0 or ?volume=0
 */

export const NAVIGATION_ONLY_LABEL = "Navigation only — not segmented";
export const DEFAULT_VOLUME_MAX_BYTES = 8 * 1024 * 1024;
export const VOLUME_FEATURE_STORAGE_KEY = "morphostack.enableVolumeViewer";

/** Warm first-paint engineering target (ms). */
export const WARM_FIRST_PAINT_BUDGET_MS = 2000;
/** Interactive FPS minimum / target. */
export const INTERACTION_FPS_MIN = 15;
export const INTERACTION_FPS_TARGET = 30;

export type VolumeBlendMode = "mip" | "composite";

export type VoxelSpacingUm = {
  x_um: number;
  y_um: number;
  z_um: number;
};

export type DisplayVolumeSpecJson = {
  role?: string;
  source_revision?: string | null;
  level: number;
  shape: number[];
  dtype: string;
  axes: string;
  level_voxel_size: VoxelSpacingUm;
  downsampling?: Record<string, unknown>;
  intensity_window?: [number, number] | number[] | null;
  display_only?: boolean;
};

export type DisplayLevelResponse = {
  cache_key: string;
  display_only?: boolean;
  level: {
    level: number;
    shape: number[];
    dtype: string;
    axes: string;
    scale_zyx?: number[];
    voxel_size: VoxelSpacingUm;
    nbytes: number;
    display_only?: boolean;
    downsample_from_source?: number[];
  };
  display_volume_spec: DisplayVolumeSpecJson;
  transfer_nbytes: number;
  within_budget: boolean;
  dtype?: string;
  shape?: number[];
  byteorder?: string;
  data_b64?: string;
};

export type VolumeFallbackReason =
  | "feature_disabled"
  | "no_webgl"
  | "over_budget"
  | "missing_binary"
  | "endpoint_error"
  | "allocation_failure"
  | "unsupported_dtype"
  | "stale_generation"
  | "disposed";

export type VolumeViewerStatus =
  | { kind: "idle" }
  | { kind: "loading"; message: string }
  | { kind: "ready"; message: string; meta: VolumeReadyMeta }
  | { kind: "fallback"; reason: VolumeFallbackReason; message: string };

export type VolumeReadyMeta = {
  cacheKey: string;
  level: number;
  shapeZyx: [number, number, number];
  dtype: string;
  spacingUm: VoxelSpacingUm;
  transferBytes: number;
  blendMode: VolumeBlendMode;
  displayOnly: true;
  loadMs: number;
  sourceRevision: string | null;
  factorsZyx: [number, number, number];
  sourceShapeZyx: [number, number, number] | null;
  calibrationKnown: boolean;
};

/** Packet 13: display-level geometry for world ↔ source seed mapping. */
export type DisplayLevelGeometry = {
  level: number;
  shapeZyx: [number, number, number];
  factorsZyx: [number, number, number]; // (fz, fy, fx) vs source
  levelVoxelSize: VoxelSpacingUm;
  sourceShapeZyx: [number, number, number];
  sourceVoxelSize: VoxelSpacingUm;
  sourceRevision: string | null;
  calibrationKnown: boolean;
};

export type WorldPointUm = { x_um: number; y_um: number; z_um: number };
export type LevelVoxel = { x: number; y: number; z: number };
export type SourceVoxel = { x: number; y: number; z: number };

export type MappedObjectSeed = {
  x: number;
  y: number;
  frame_index: number;
  radius: number;
  type: "circle";
  source_revision: string | null;
  seed_origin: "viewer_3d" | "ui_2d";
  radius_unit: "px";
  max_tracking_dist_um?: number;
};

export class SeedMappingError extends Error {
  readonly code: string;
  constructor(message: string, code = "seed_mapping_error") {
    super(message);
    this.name = "SeedMappingError";
    this.code = code;
  }
}

export function nearestInt(value: number): number {
  const v = Number(value);
  return v >= 0 ? Math.trunc(v + 0.5) : Math.trunc(v - 0.5);
}

export function worldToLevelVoxel(world: WorldPointUm, g: DisplayLevelGeometry): LevelVoxel {
  const sx = g.levelVoxelSize.x_um;
  const sy = g.levelVoxelSize.y_um;
  const sz = g.levelVoxelSize.z_um;
  if (!(sx > 0 && sy > 0 && sz > 0)) {
    throw new SeedMappingError("level voxel spacing must be positive", "invalid_geometry");
  }
  return { x: world.x_um / sx, y: world.y_um / sy, z: world.z_um / sz };
}

export function levelToWorld(level: LevelVoxel, g: DisplayLevelGeometry): WorldPointUm {
  return {
    x_um: level.x * g.levelVoxelSize.x_um,
    y_um: level.y * g.levelVoxelSize.y_um,
    z_um: level.z * g.levelVoxelSize.z_um
  };
}

export function levelToSource(level: LevelVoxel, g: DisplayLevelGeometry): SourceVoxel {
  const [fz, fy, fx] = g.factorsZyx;
  return { x: level.x * fx, y: level.y * fy, z: level.z * fz };
}

export function sourceToLevel(source: SourceVoxel, g: DisplayLevelGeometry): LevelVoxel {
  const [fz, fy, fx] = g.factorsZyx;
  return { x: source.x / fx, y: source.y / fy, z: source.z / fz };
}

export function worldToSource(world: WorldPointUm, g: DisplayLevelGeometry): SourceVoxel {
  return levelToSource(worldToLevelVoxel(world, g), g);
}

export function sourceToWorld(source: SourceVoxel, g: DisplayLevelGeometry): WorldPointUm {
  return levelToWorld(sourceToLevel(source, g), g);
}

export function geometryFromLevelPayload(
  payload: DisplayLevelResponse,
  sourceShapeZyx: [number, number, number],
  sourceVoxelSize: VoxelSpacingUm,
  calibrationKnown = true
): DisplayLevelGeometry {
  const level = payload.level;
  const spec = payload.display_volume_spec;
  const shape = (payload.shape ?? level?.shape ?? spec?.shape) as number[];
  if (!shape || shape.length < 3) {
    throw new SeedMappingError("level shape missing", "invalid_geometry");
  }
  let factors =
    (level?.downsample_from_source as number[] | undefined) ??
    ((spec?.downsampling?.factors_zyx as number[] | undefined) ?? null);
  if (!factors || factors.length < 3) {
    factors = [1, 1, 1];
  }
  const vs = level?.voxel_size ?? spec?.level_voxel_size ?? sourceVoxelSize;
  return {
    level: Number(level?.level ?? spec?.level ?? 0),
    shapeZyx: [Number(shape[0]), Number(shape[1]), Number(shape[2])],
    factorsZyx: [Number(factors[0]), Number(factors[1]), Number(factors[2])],
    levelVoxelSize: {
      x_um: Number(vs.x_um),
      y_um: Number(vs.y_um),
      z_um: Number(vs.z_um)
    },
    sourceShapeZyx,
    sourceVoxelSize,
    sourceRevision: (spec?.source_revision as string | null | undefined) ?? null,
    calibrationKnown
  };
}

export function sourceToObjectSeed(
  source: SourceVoxel,
  g: DisplayLevelGeometry,
  radiusPx: number,
  options: { clampZ?: boolean; maxTrackingDistUm?: number } = {}
): MappedObjectSeed {
  if (!(radiusPx > 0)) {
    throw new SeedMappingError("radius_px must be positive", "invalid_radius");
  }
  const [sz, sy, sx] = g.sourceShapeZyx;
  let xi = nearestInt(source.x);
  let yi = nearestInt(source.y);
  let zi = nearestInt(source.z);
  if (options.clampZ) {
    zi = Math.max(0, Math.min(sz - 1, zi));
  } else if (!(zi >= 0 && zi < sz)) {
    throw new SeedMappingError(`seed Z frame ${zi} out of bounds for Z=${sz}`, "out_of_bounds");
  }
  if (!(xi >= 0 && xi < sx && yi >= 0 && yi < sy)) {
    throw new SeedMappingError(
      `seed XY (${xi}, ${yi}) out of bounds for XY=(${sx}, ${sy})`,
      "out_of_bounds"
    );
  }
  return {
    x: xi,
    y: yi,
    frame_index: zi,
    radius: radiusPx,
    type: "circle",
    source_revision: g.sourceRevision,
    seed_origin: "viewer_3d",
    radius_unit: "px",
    max_tracking_dist_um: options.maxTrackingDistUm
  };
}

export function worldToObjectSeed(
  world: WorldPointUm,
  g: DisplayLevelGeometry,
  radiusPx: number,
  options: { clampZ?: boolean; maxTrackingDistUm?: number; expectedRevision?: string | null } = {}
): MappedObjectSeed {
  if (options.expectedRevision != null && options.expectedRevision !== "") {
    if (!g.sourceRevision || g.sourceRevision !== options.expectedRevision) {
      throw new SeedMappingError(
        "3D seed source_revision does not match current stack; refresh the volume viewer",
        "stale_revision"
      );
    }
  }
  const continuous = worldToSource(world, g);
  const seed = sourceToObjectSeed(continuous, g, radiusPx, {
    clampZ: options.clampZ ?? true,
    maxTrackingDistUm: options.maxTrackingDistUm
  });
  // Round-trip: XY within one source voxel; Z exact when continuous Z in-bounds.
  const dx = Math.abs(seed.x - continuous.x);
  const dy = Math.abs(seed.y - continuous.y);
  if (dx > 1 + 1e-6 || dy > 1 + 1e-6) {
    throw new SeedMappingError(`XY round-trip exceeds one source voxel: dx=${dx}, dy=${dy}`, "roundtrip_xy");
  }
  if (continuous.z >= 0 && continuous.z < g.sourceShapeZyx[0]) {
    if (seed.frame_index !== nearestInt(continuous.z)) {
      throw new SeedMappingError(
        `Z frame mismatch: seed=${seed.frame_index} nearest=${nearestInt(continuous.z)}`,
        "roundtrip_z"
      );
    }
  }
  return seed;
}

export function objectSeedToWorld(
  seed: { x: number; y: number; frame_index: number },
  g: DisplayLevelGeometry
): WorldPointUm {
  return sourceToWorld({ x: seed.x, y: seed.y, z: seed.frame_index }, g);
}

export function radiusPxToWorldUm(
  radiusPx: number,
  sourceVoxel: VoxelSpacingUm,
  calibrationKnown: boolean
): number {
  if (!calibrationKnown) {
    // Still size the marker using placeholder spacing, but callers must not label as calibrated µm.
    return radiusPx * sourceVoxel.x_um;
  }
  return radiusPx * sourceVoxel.x_um;
}

export class VolumeViewerError extends Error {
  readonly reason: VolumeFallbackReason;

  constructor(reason: VolumeFallbackReason, message: string) {
    super(message);
    this.name = "VolumeViewerError";
    this.reason = reason;
  }
}

/** Feature flag: localStorage + optional ?volume=0 URL override. Default enabled. */
export function isVolumeViewerEnabled(
  storage: Pick<Storage, "getItem"> | null = typeof localStorage !== "undefined" ? localStorage : null,
  search: string = typeof location !== "undefined" ? location.search : ""
): boolean {
  try {
    const params = new URLSearchParams(search);
    const q = params.get("volume");
    if (q === "0" || q === "false" || q === "off") {
      return false;
    }
    if (q === "1" || q === "true" || q === "on") {
      return true;
    }
  } catch {
    /* ignore */
  }
  if (!storage) {
    return true;
  }
  const raw = storage.getItem(VOLUME_FEATURE_STORAGE_KEY);
  if (raw === null || raw === "") {
    return true;
  }
  return !(raw === "0" || raw === "false" || raw === "off");
}

export function setVolumeViewerEnabled(
  enabled: boolean,
  storage: Pick<Storage, "setItem"> | null = typeof localStorage !== "undefined" ? localStorage : null
): void {
  if (!storage) {
    return;
  }
  storage.setItem(VOLUME_FEATURE_STORAGE_KEY, enabled ? "1" : "0");
}

export function detectWebGLSupport(
  createCanvas: () => HTMLCanvasElement = () => document.createElement("canvas")
): boolean {
  try {
    const canvas = createCanvas();
    const gl =
      canvas.getContext("webgl2", { failIfMajorPerformanceCaveat: false }) ||
      canvas.getContext("webgl", { failIfMajorPerformanceCaveat: false }) ||
      canvas.getContext("experimental-webgl");
    return gl != null;
  } catch {
    return false;
  }
}

export function isWithinBudget(
  nbytes: number,
  maxBytes: number = DEFAULT_VOLUME_MAX_BYTES
): boolean {
  return Number.isFinite(nbytes) && nbytes >= 0 && nbytes <= maxBytes;
}

export function normalizeDtype(dtype: string): string {
  return String(dtype || "")
    .trim()
    .toLowerCase()
    .replace(/^(numpy\.)?/, "")
    .replace(/^<|>$/, "");
}

export function bytesPerSample(dtype: string): number {
  switch (normalizeDtype(dtype)) {
    case "uint8":
    case "int8":
    case "bool":
      return 1;
    case "uint16":
    case "int16":
    case "float16":
      return 2;
    case "uint32":
    case "int32":
    case "float32":
      return 4;
    case "uint64":
    case "int64":
    case "float64":
      return 8;
    default:
      throw new VolumeViewerError(
        "unsupported_dtype",
        `Unsupported display volume dtype: ${dtype}`
      );
  }
}

/**
 * Decode standard base64 to bytes (browser + Node Buffer-compatible path).
 */
export function decodeBase64Binary(dataB64: string): Uint8Array {
  if (!dataB64) {
    throw new VolumeViewerError("missing_binary", "Level payload has no data_b64");
  }
  if (typeof atob === "function") {
    const bin = atob(dataB64);
    const out = new Uint8Array(bin.length);
    for (let i = 0; i < bin.length; i += 1) {
      out[i] = bin.charCodeAt(i);
    }
    return out;
  }
  // Node test fallback
  const buf = Buffer.from(dataB64, "base64");
  return new Uint8Array(buf.buffer, buf.byteOffset, buf.byteLength);
}

/**
 * Map MorphoStack ZYX shape + axes to VTK XYZ dimensions (x fastest in buffer).
 * NumPy C-order (Z,Y,X) already stores x fastest — same as VTK point scalars.
 */
export function shapeZyxToXyzDims(shape: number[], axes = "zyx"): [number, number, number] {
  const a = axes.toLowerCase().replace(/[^xyz]/g, "");
  if (shape.length < 3) {
    throw new VolumeViewerError("allocation_failure", "Volume shape must be 3D (Z,Y,X)");
  }
  if (a === "zyx" || a === "") {
    return [shape[2], shape[1], shape[0]];
  }
  if (a === "xyz") {
    return [shape[0], shape[1], shape[2]];
  }
  // Generic permutation: find each axis index
  const zi = a.indexOf("z");
  const yi = a.indexOf("y");
  const xi = a.indexOf("x");
  if (zi < 0 || yi < 0 || xi < 0) {
    throw new VolumeViewerError("allocation_failure", `Unrecognized axes order: ${axes}`);
  }
  return [shape[xi], shape[yi], shape[zi]];
}

export function worldSpacingFromSpec(
  voxel: VoxelSpacingUm,
  axes = "zyx"
): [number, number, number] {
  // VTK spacing is (sx, sy, sz) in world units along x,y,z axes.
  void axes;
  return [voxel.x_um, voxel.y_um, voxel.z_um];
}

/**
 * World extent sizes (µm) for anisotropy checks: physical size of the volume box.
 */
export function worldExtentUm(
  shapeZyx: [number, number, number],
  spacing: VoxelSpacingUm
): { x: number; y: number; z: number } {
  const [z, y, x] = shapeZyx;
  return {
    x: Math.max(0, x - 1) * spacing.x_um,
    y: Math.max(0, y - 1) * spacing.y_um,
    z: Math.max(0, z - 1) * spacing.z_um
  };
}

export function createTypedScalars(
  bytes: Uint8Array,
  dtype: string,
  expectedCount: number
): { values: ArrayBufferView; dataType: string; rangeHint: [number, number] } {
  const dt = normalizeDtype(dtype);
  const bps = bytesPerSample(dt);
  if (bytes.byteLength < expectedCount * bps) {
    throw new VolumeViewerError(
      "allocation_failure",
      `Binary shorter than shape×dtype (${bytes.byteLength} < ${expectedCount * bps})`
    );
  }
  const buf = bytes.buffer.slice(bytes.byteOffset, bytes.byteOffset + expectedCount * bps);
  switch (dt) {
    case "uint8":
    case "bool":
      return { values: new Uint8Array(buf), dataType: "Uint8Array", rangeHint: [0, 255] };
    case "int8":
      return { values: new Int8Array(buf), dataType: "Int8Array", rangeHint: [-128, 127] };
    case "uint16":
      return { values: new Uint16Array(buf), dataType: "Uint16Array", rangeHint: [0, 65535] };
    case "int16":
      return { values: new Int16Array(buf), dataType: "Int16Array", rangeHint: [-32768, 32767] };
    case "uint32":
      return { values: new Uint32Array(buf), dataType: "Uint32Array", rangeHint: [0, 1e6] };
    case "int32":
      return { values: new Int32Array(buf), dataType: "Int32Array", rangeHint: [-1e6, 1e6] };
    case "float32":
      return { values: new Float32Array(buf), dataType: "Float32Array", rangeHint: [0, 1] };
    case "float64":
      return { values: new Float64Array(buf), dataType: "Float64Array", rangeHint: [0, 1] };
    default:
      throw new VolumeViewerError("unsupported_dtype", `Unsupported dtype for scalars: ${dtype}`);
  }
}

export function estimateScalarRange(
  values: ArrayBufferView,
  sampleLimit = 65536
): [number, number] {
  const arr = values as unknown as ArrayLike<number> & { length: number };
  const n = arr.length;
  if (n === 0) {
    return [0, 1];
  }
  const step = Math.max(1, Math.floor(n / sampleLimit));
  let min = Number.POSITIVE_INFINITY;
  let max = Number.NEGATIVE_INFINITY;
  for (let i = 0; i < n; i += step) {
    const v = Number(arr[i]);
    if (!Number.isFinite(v)) {
      continue;
    }
    if (v < min) min = v;
    if (v > max) max = v;
  }
  if (!Number.isFinite(min) || !Number.isFinite(max)) {
    return [0, 1];
  }
  if (min === max) {
    return [min, min + 1];
  }
  return [min, max];
}

export function validateLevelPayload(
  payload: DisplayLevelResponse,
  maxBytes: number = DEFAULT_VOLUME_MAX_BYTES
): {
  shapeZyx: [number, number, number];
  dtype: string;
  spacing: VoxelSpacingUm;
  nbytes: number;
} {
  if (payload.display_only === false) {
    // Defensive: never treat a non-display product as viewer input.
    throw new VolumeViewerError(
      "endpoint_error",
      "Server returned a non-display volume; refused for navigation viewer"
    );
  }
  const shape = (payload.shape ?? payload.level?.shape ?? payload.display_volume_spec?.shape) as
    | number[]
    | undefined;
  const dtype = String(
    payload.dtype ?? payload.level?.dtype ?? payload.display_volume_spec?.dtype ?? ""
  );
  if (!shape || shape.length < 3) {
    throw new VolumeViewerError("allocation_failure", "Level shape missing or not 3D");
  }
  const shapeZyx: [number, number, number] = [
    Number(shape[0]),
    Number(shape[1]),
    Number(shape[2])
  ];
  const spacing =
    payload.display_volume_spec?.level_voxel_size ??
    payload.level?.voxel_size ??
    ({ x_um: 1, y_um: 1, z_um: 1 } as VoxelSpacingUm);
  const nbytes = Number(payload.transfer_nbytes ?? payload.level?.nbytes ?? 0);
  if (!isWithinBudget(nbytes, maxBytes) || payload.within_budget === false) {
    throw new VolumeViewerError(
      "over_budget",
      `Bounded level ${nbytes} bytes exceeds budget ${maxBytes}; staying on 2D`
    );
  }
  if (!payload.data_b64) {
    throw new VolumeViewerError("missing_binary", "Level response missing data_b64");
  }
  // expected size check
  const expected = shapeZyx[0] * shapeZyx[1] * shapeZyx[2] * bytesPerSample(dtype);
  if (nbytes > 0 && Math.abs(nbytes - expected) > bytesPerSample(dtype)) {
    // soft warn only — still try if buffer decodes
  }
  return { shapeZyx, dtype, spacing, nbytes };
}

export function fallbackMessage(reason: VolumeFallbackReason, detail?: string): string {
  const base: Record<VolumeFallbackReason, string> = {
    feature_disabled: "3D volume navigation is turned off (feature flag).",
    no_webgl: "WebGL unavailable — using 2D preview only.",
    over_budget: "Volume level exceeds transfer/GPU budget — using 2D preview only.",
    missing_binary: "Display volume binary missing — using 2D preview only.",
    endpoint_error: "Display pyramid unavailable — using 2D preview only.",
    allocation_failure: "Could not allocate volume GPU buffers — using 2D preview only.",
    unsupported_dtype: "Unsupported volume dtype — using 2D preview only.",
    stale_generation: "Volume load cancelled (stack changed).",
    disposed: "Volume viewer disposed."
  };
  return detail ? `${base[reason]} ${detail}` : base[reason];
}

/** Runtime VTK handles — kept loosely typed; VTK.js path types are structural. */
// eslint-disable-next-line @typescript-eslint/no-explicit-any
type VtkAny = any;

type VtkBundle = {
  genericRenderWindow: VtkAny;
  volume: VtkAny;
  mapper: VtkAny;
  imageData: VtkAny;
  ctfun: VtkAny;
  ofun: VtkAny;
  dataArray: VtkAny;
};

async function loadVtkFactories(): Promise<{
  vtkGenericRenderWindow: VtkAny;
  vtkImageData: VtkAny;
  vtkDataArray: VtkAny;
  vtkVolume: VtkAny;
  vtkVolumeMapper: VtkAny;
  vtkColorTransferFunction: VtkAny;
  vtkPiecewiseFunction: VtkAny;
}> {
  // Side-effect: register OpenGL volume mappers (WebGL path).
  await import("@kitware/vtk.js/Rendering/Profiles/Volume");
  const [
    grwMod,
    imageMod,
    dataArrayMod,
    volumeMod,
    mapperMod,
    ctfMod,
    pwMod
  ] = await Promise.all([
    import("@kitware/vtk.js/Rendering/Misc/GenericRenderWindow"),
    import("@kitware/vtk.js/Common/DataModel/ImageData"),
    import("@kitware/vtk.js/Common/Core/DataArray"),
    import("@kitware/vtk.js/Rendering/Core/Volume"),
    import("@kitware/vtk.js/Rendering/Core/VolumeMapper"),
    import("@kitware/vtk.js/Rendering/Core/ColorTransferFunction"),
    import("@kitware/vtk.js/Common/DataModel/PiecewiseFunction")
  ]);
  return {
    vtkGenericRenderWindow: (grwMod as VtkAny).default,
    vtkImageData: (imageMod as VtkAny).default,
    vtkDataArray: (dataArrayMod as VtkAny).default,
    vtkVolume: (volumeMod as VtkAny).default,
    vtkVolumeMapper: (mapperMod as VtkAny).default,
    vtkColorTransferFunction: (ctfMod as VtkAny).default,
    vtkPiecewiseFunction: (pwMod as VtkAny).default
  };
}

export type VolumeViewerMountOptions = {
  container: HTMLElement;
  payload: DisplayLevelResponse;
  blendMode?: VolumeBlendMode;
  /** Composite opacity gain 0–1 (ignored for pure MIP). */
  opacityGain?: number;
  maxBytes?: number;
  /** Interaction sample quality scale (higher = coarser while dragging). */
  interactionScale?: number;
  background?: [number, number, number];
  /** Source stack shape (Z,Y,X) from inspect — required for seed mapping. */
  sourceShapeZyx?: [number, number, number];
  sourceVoxelSize?: VoxelSpacingUm;
  calibrationKnown?: boolean;
  /** Called when user picks a world point in seed-pick mode (no intensity snap). */
  onWorldPick?: (world: WorldPointUm, display: { x: number; y: number }) => void;
};

/**
 * One mounted VTK volume instance. Call dispose() on stack change / unmount.
 */
export class VolumeViewerSession {
  private disposed = false;
  private vtk: VtkBundle | null = null;
  private blendMode: VolumeBlendMode = "mip";
  private opacityGain = 0.35;
  private scalarRange: [number, number] = [0, 255];
  private meta: VolumeReadyMeta | null = null;
  private resizeObserver: ResizeObserver | null = null;
  private geometry: DisplayLevelGeometry | null = null;
  private seedPickEnabled = false;
  private onWorldPick: VolumeViewerMountOptions["onWorldPick"] = undefined;
  private pickSub: { unsubscribe: () => void } | null = null;
  private pointerDown: { x: number; y: number; t: number } | null = null;
  private seedActor: VtkAny | null = null;
  private seedMapper: VtkAny | null = null;
  private seedSource: VtkAny | null = null;

  get isDisposed(): boolean {
    return this.disposed;
  }

  get readyMeta(): VolumeReadyMeta | null {
    return this.meta;
  }

  get currentBlendMode(): VolumeBlendMode {
    return this.blendMode;
  }

  get levelGeometry(): DisplayLevelGeometry | null {
    return this.geometry;
  }

  static async mount(options: VolumeViewerMountOptions): Promise<VolumeViewerSession> {
    const session = new VolumeViewerSession();
    await session._mount(options);
    return session;
  }

  private async _mount(options: VolumeViewerMountOptions): Promise<void> {
    const t0 =
      typeof performance !== "undefined" && performance.now ? performance.now() : Date.now();
    if (!detectWebGLSupport()) {
      throw new VolumeViewerError("no_webgl", fallbackMessage("no_webgl"));
    }
    const maxBytes = options.maxBytes ?? DEFAULT_VOLUME_MAX_BYTES;
    const validated = validateLevelPayload(options.payload, maxBytes);
    const axes = options.payload.level?.axes ?? options.payload.display_volume_spec?.axes ?? "zyx";
    const [dimX, dimY, dimZ] = shapeZyxToXyzDims([...validated.shapeZyx], axes);
    const expectedCount = dimX * dimY * dimZ;
    const bytes = decodeBase64Binary(options.payload.data_b64!);
    const scalars = createTypedScalars(bytes, validated.dtype, expectedCount);
    this.scalarRange = estimateScalarRange(scalars.values);
    const windowFromSpec = options.payload.display_volume_spec?.intensity_window;
    if (windowFromSpec && windowFromSpec.length >= 2) {
      const lo = Number(windowFromSpec[0]);
      const hi = Number(windowFromSpec[1]);
      if (Number.isFinite(lo) && Number.isFinite(hi) && hi > lo) {
        this.scalarRange = [lo, hi];
      }
    }

    let factories;
    try {
      factories = await loadVtkFactories();
    } catch (err) {
      throw new VolumeViewerError(
        "allocation_failure",
        `Failed to load VTK.js renderer: ${err instanceof Error ? err.message : String(err)}`
      );
    }

    try {
      const fullScreen = factories.vtkGenericRenderWindow.newInstance({
        background: options.background ?? [0.06, 0.09, 0.14],
        listenWindowResize: false
      });
      fullScreen.setContainer(options.container);

      const imageData = factories.vtkImageData.newInstance();
      const [sx, sy, sz] = worldSpacingFromSpec(validated.spacing, axes);
      // VTK.js setters take Vector3 / number[] (not loose x,y,z args).
      imageData.setOrigin([0, 0, 0]);
      imageData.setSpacing([sx, sy, sz]);
      imageData.setExtent(0, dimX - 1, 0, dimY - 1, 0, dimZ - 1);

      const dataArray = factories.vtkDataArray.newInstance({
        name: "scalars",
        numberOfComponents: 1,
        values: scalars.values
      });
      imageData.getPointData().setScalars(dataArray);

      const mapper = factories.vtkVolumeMapper.newInstance();
      mapper.setInputData(imageData);
      mapper.setAutoAdjustSampleDistances(true);
      mapper.setInitialInteractionScale?.(options.interactionScale ?? 2);
      // Coarser image samples while interacting; idle refine via still update rate.
      mapper.setImageSampleDistance(1.5);
      mapper.setSampleDistance(Math.max(sx, sy, sz) * 0.5);
      mapper.setMaximumSamplesPerRay(800);

      const volume = factories.vtkVolume.newInstance();
      volume.setMapper(mapper);

      const ctfun = factories.vtkColorTransferFunction.newInstance();
      const ofun = factories.vtkPiecewiseFunction.newInstance();
      this.blendMode = options.blendMode ?? "mip";
      this.opacityGain = options.opacityGain ?? 0.35;
      this.applyTransferFunctions(ctfun, ofun, mapper);

      volume.getProperty().setRGBTransferFunction(0, ctfun);
      volume.getProperty().setScalarOpacity(0, ofun);
      volume.getProperty().setInterpolationTypeToLinear();
      volume.getProperty().setShade(false);
      const unitDist = Math.max(sx, sy, sz);
      volume.getProperty().setScalarOpacityUnitDistance(0, unitDist);

      const renderer = fullScreen.getRenderer();
      renderer.addVolume(volume);
      renderer.resetCamera();
      // Slight elevation so anisotropic Z is visible for navigation.
      try {
        renderer.getActiveCamera().elevation(25);
        renderer.getActiveCamera().azimuth(20);
      } catch {
        /* cameras may vary */
      }
      renderer.resetCamera();

      const interactor = fullScreen.getRenderWindow().getInteractor();
      interactor.setDesiredUpdateRate(INTERACTION_FPS_TARGET);
      interactor.setStillUpdateRate(0.001);

      fullScreen.resize();
      fullScreen.getRenderWindow().render();

      this.vtk = {
        genericRenderWindow: fullScreen,
        volume,
        mapper,
        imageData,
        ctfun,
        ofun,
        dataArray
      };
      this.onWorldPick = options.onWorldPick;
      this.wirePickHandlers(options.container);

      // Seed geometry (source shape optional until inspect provides it).
      const srcShape = options.sourceShapeZyx;
      const srcVoxel = options.sourceVoxelSize ?? validated.spacing;
      if (srcShape) {
        this.geometry = geometryFromLevelPayload(
          options.payload,
          srcShape,
          srcVoxel,
          options.calibrationKnown ?? true
        );
      }

      if (typeof ResizeObserver !== "undefined") {
        this.resizeObserver = new ResizeObserver(() => {
          if (this.disposed || !this.vtk) return;
          try {
            this.vtk.genericRenderWindow.resize();
            this.vtk.genericRenderWindow.getRenderWindow().render();
          } catch {
            /* ignore resize after teardown */
          }
        });
        this.resizeObserver.observe(options.container);
      }

      const t1 =
        typeof performance !== "undefined" && performance.now ? performance.now() : Date.now();
      const factors =
        this.geometry?.factorsZyx ??
        ((options.payload.level?.downsample_from_source as [number, number, number] | undefined) ??
          [1, 1, 1]);
      this.meta = {
        cacheKey: options.payload.cache_key,
        level: Number(
          options.payload.level?.level ?? options.payload.display_volume_spec?.level ?? 0
        ),
        shapeZyx: validated.shapeZyx,
        dtype: validated.dtype,
        spacingUm: validated.spacing,
        transferBytes: validated.nbytes,
        blendMode: this.blendMode,
        displayOnly: true,
        loadMs: Math.max(0, t1 - t0),
        sourceRevision:
          (options.payload.display_volume_spec?.source_revision as string | null | undefined) ??
          null,
        factorsZyx: [Number(factors[0]), Number(factors[1]), Number(factors[2])],
        sourceShapeZyx: srcShape ?? null,
        calibrationKnown: options.calibrationKnown ?? true
      };
    } catch (err) {
      this.dispose();
      if (err instanceof VolumeViewerError) {
        throw err;
      }
      throw new VolumeViewerError(
        "allocation_failure",
        `Volume GPU setup failed: ${err instanceof Error ? err.message : String(err)}`
      );
    }
  }

  private applyTransferFunctions(ctfun: VtkAny, ofun: VtkAny, mapper: VtkAny): void {
    const [lo, hi] = this.scalarRange;
    const span = hi - lo || 1;
    ctfun.removeAllPoints();
    ofun.removeAllPoints();
    // Cyan–white fluorescence-like ramp for navigation (not a scientific LUT claim).
    ctfun.addRGBPoint(lo, 0.0, 0.05, 0.12);
    ctfun.addRGBPoint(lo + 0.35 * span, 0.05, 0.45, 0.55);
    ctfun.addRGBPoint(lo + 0.7 * span, 0.35, 0.9, 0.75);
    ctfun.addRGBPoint(hi, 1.0, 1.0, 0.95);

    if (this.blendMode === "mip") {
      mapper.setBlendModeToMaximumIntensity();
      ofun.addPoint(lo, 0.0);
      ofun.addPoint(lo + 0.15 * span, 0.05);
      ofun.addPoint(hi, 1.0);
    } else {
      mapper.setBlendModeToComposite();
      const g = Math.max(0.02, Math.min(1, this.opacityGain));
      ofun.addPoint(lo, 0.0);
      ofun.addPoint(lo + 0.25 * span, 0.02 * g);
      ofun.addPoint(lo + 0.55 * span, 0.25 * g);
      ofun.addPoint(hi, 0.85 * g);
    }
  }

  setBlendMode(mode: VolumeBlendMode): void {
    if (this.disposed || !this.vtk) return;
    this.blendMode = mode;
    this.applyTransferFunctions(this.vtk.ctfun, this.vtk.ofun, this.vtk.mapper);
    if (this.meta) {
      this.meta = { ...this.meta, blendMode: mode };
    }
    this.vtk.genericRenderWindow.getRenderWindow().render();
  }

  setOpacityGain(gain: number): void {
    if (this.disposed || !this.vtk) return;
    this.opacityGain = Math.max(0.02, Math.min(1, gain));
    if (this.blendMode !== "composite") return;
    this.applyTransferFunctions(this.vtk.ctfun, this.vtk.ofun, this.vtk.mapper);
    this.vtk.genericRenderWindow.getRenderWindow().render();
  }

  setSourceGeometry(
    sourceShapeZyx: [number, number, number],
    sourceVoxelSize: VoxelSpacingUm,
    calibrationKnown: boolean,
    payload: DisplayLevelResponse
  ): void {
    this.geometry = geometryFromLevelPayload(
      payload,
      sourceShapeZyx,
      sourceVoxelSize,
      calibrationKnown
    );
    if (this.meta) {
      this.meta = {
        ...this.meta,
        sourceShapeZyx,
        sourceRevision: this.geometry.sourceRevision,
        factorsZyx: this.geometry.factorsZyx,
        calibrationKnown
      };
    }
  }

  setSeedPickEnabled(enabled: boolean): void {
    this.seedPickEnabled = enabled;
    if (this.vtk) {
      const el = this.vtk.genericRenderWindow.getContainer?.() as HTMLElement | undefined;
      if (el) {
        el.style.cursor = enabled ? "crosshair" : "";
      }
    }
  }

  get seedPickIsEnabled(): boolean {
    return this.seedPickEnabled;
  }

  /**
   * Geometric display→world pick (depth buffer mid-plane). No intensity/glow snap.
   */
  pickWorldFromDisplay(displayX: number, displayY: number): WorldPointUm | null {
    if (this.disposed || !this.vtk) return null;
    try {
      const grw = this.vtk.genericRenderWindow;
      const renderer = grw.getRenderer();
      const api = grw.getApiSpecificRenderWindow();
      // displayToWorld(x, y, z, renderer) — z in [0,1] NDC depth; 0.5 = mid volume.
      const world = api.displayToWorld(displayX, displayY, 0.5, renderer) as number[];
      if (!world || world.length < 3) return null;
      return { x_um: Number(world[0]), y_um: Number(world[1]), z_um: Number(world[2]) };
    } catch {
      return null;
    }
  }

  async setSeedMarker(
    seed: { x: number; y: number; frame_index: number; radius: number },
    geometry?: DisplayLevelGeometry | null
  ): Promise<void> {
    if (this.disposed || !this.vtk) return;
    const g = geometry ?? this.geometry;
    if (!g) return;
    const world = objectSeedToWorld(seed, g);
    const radiusUm = radiusPxToWorldUm(seed.radius, g.sourceVoxelSize, g.calibrationKnown);
    await this.ensureSeedActor();
    if (!this.seedSource || !this.seedActor || !this.vtk) return;
    this.seedSource.setCenter(world.x_um, world.y_um, world.z_um);
    this.seedSource.setRadius(Math.max(radiusUm, g.sourceVoxelSize.x_um));
    this.seedActor.setVisibility(true);
    this.vtk.genericRenderWindow.getRenderWindow().render();
  }

  clearSeedMarker(): void {
    if (this.seedActor && this.vtk) {
      try {
        this.seedActor.setVisibility(false);
        this.vtk.genericRenderWindow.getRenderWindow().render();
      } catch {
        /* ignore */
      }
    }
  }

  private async ensureSeedActor(): Promise<void> {
    if (this.seedActor || !this.vtk) return;
    // Geometry profile registers OpenGL actor/mapper backends (volume profile alone is insufficient).
    await import("@kitware/vtk.js/Rendering/Profiles/Geometry");
    const [{ default: vtkSphereSource }, { default: vtkActor }, { default: vtkMapper }] =
      await Promise.all([
        import("@kitware/vtk.js/Filters/Sources/SphereSource"),
        import("@kitware/vtk.js/Rendering/Core/Actor"),
        import("@kitware/vtk.js/Rendering/Core/Mapper")
      ]);
    const source = (vtkSphereSource as VtkAny).newInstance({
      radius: 1,
      thetaResolution: 24,
      phiResolution: 24
    });
    const mapper = (vtkMapper as VtkAny).newInstance();
    mapper.setInputConnection(source.getOutputPort());
    const actor = (vtkActor as VtkAny).newInstance();
    actor.setMapper(mapper);
    actor.getProperty().setColor(1.0, 0.85, 0.15);
    actor.getProperty().setOpacity(0.85);
    actor.setVisibility(false);
    this.vtk.genericRenderWindow.getRenderer().addActor(actor);
    this.seedSource = source;
    this.seedMapper = mapper;
    this.seedActor = actor;
  }

  private wirePickHandlers(container: HTMLElement): void {
    const onDown = (ev: PointerEvent) => {
      if (!this.seedPickEnabled || this.disposed) return;
      this.pointerDown = { x: ev.clientX, y: ev.clientY, t: Date.now() };
    };
    const onUp = (ev: PointerEvent) => {
      if (!this.seedPickEnabled || this.disposed || !this.pointerDown || !this.vtk) {
        this.pointerDown = null;
        return;
      }
      const dx = ev.clientX - this.pointerDown.x;
      const dy = ev.clientY - this.pointerDown.y;
      const dist = Math.hypot(dx, dy);
      this.pointerDown = null;
      // Ignore drags so orbit still works when pick mode is off; when on, require click.
      if (dist > 6) return;
      const rect = container.getBoundingClientRect();
      // VTK display coords: origin bottom-left.
      const displayX = ev.clientX - rect.left;
      const displayY = rect.height - (ev.clientY - rect.top);
      const world = this.pickWorldFromDisplay(displayX, displayY);
      if (world && this.onWorldPick) {
        this.onWorldPick(world, { x: displayX, y: displayY });
      }
    };
    container.addEventListener("pointerdown", onDown);
    container.addEventListener("pointerup", onUp);
    this.pickSub = {
      unsubscribe: () => {
        container.removeEventListener("pointerdown", onDown);
        container.removeEventListener("pointerup", onUp);
      }
    };
  }

  render(): void {
    if (this.disposed || !this.vtk) return;
    this.vtk.genericRenderWindow.getRenderWindow().render();
  }

  /**
   * Release GPU/DOM resources. Safe to call multiple times.
   */
  dispose(): void {
    if (this.disposed) return;
    this.disposed = true;
    this.meta = null;
    this.geometry = null;
    this.seedPickEnabled = false;
    if (this.pickSub) {
      try {
        this.pickSub.unsubscribe();
      } catch {
        /* ignore */
      }
      this.pickSub = null;
    }
    if (this.resizeObserver) {
      try {
        this.resizeObserver.disconnect();
      } catch {
        /* ignore */
      }
      this.resizeObserver = null;
    }
    for (const obj of [this.seedActor, this.seedMapper, this.seedSource]) {
      try {
        obj?.delete?.();
      } catch {
        /* ignore */
      }
    }
    this.seedActor = null;
    this.seedMapper = null;
    this.seedSource = null;
    const handles = this.vtk;
    this.vtk = null;
    if (!handles) return;
    try {
      handles.genericRenderWindow.delete();
    } catch {
      /* ignore */
    }
    for (const key of ["volume", "mapper", "imageData", "ctfun", "ofun"] as const) {
      const obj = handles[key] as { delete?: () => void };
      try {
        obj.delete?.();
      } catch {
        /* ignore */
      }
    }
  }
}

export type PyramidBuildBody = {
  path?: string;
  stack_id?: string;
  voxel?: VoxelSpacingUm | null;
  max_levels?: number;
  max_level_bytes?: number;
  max_source_bytes?: number;
  background?: boolean;
};

export type PyramidStatusJson = {
  cache_key?: string;
  state?: string;
  levels_ready?: number[];
  error?: string | null;
  display_only?: boolean;
  [key: string]: unknown;
};

/**
 * Poll display-pyramid status until a level is ready, failed, or timeout.
 * Does not block 2D; caller should ignore stale generations.
 */
export async function waitForPyramidLevelReady(options: {
  cacheKey: string;
  pollStatus: (cacheKey: string) => Promise<PyramidStatusJson>;
  intervalMs?: number;
  timeoutMs?: number;
  isCancelled?: () => boolean;
}): Promise<PyramidStatusJson> {
  const interval = options.intervalMs ?? 250;
  const timeout = options.timeoutMs ?? 120_000;
  const start = Date.now();
  let last: PyramidStatusJson = { cache_key: options.cacheKey, state: "queued" };
  while (Date.now() - start < timeout) {
    if (options.isCancelled?.()) {
      throw new VolumeViewerError("stale_generation", fallbackMessage("stale_generation"));
    }
    last = await options.pollStatus(options.cacheKey);
    const state = String(last.state ?? "missing");
    const ready = Array.isArray(last.levels_ready) ? last.levels_ready : [];
    if (state === "failed") {
      throw new VolumeViewerError(
        "endpoint_error",
        fallbackMessage("endpoint_error", String(last.error ?? "pyramid build failed"))
      );
    }
    if (state === "missing") {
      throw new VolumeViewerError(
        "endpoint_error",
        fallbackMessage("endpoint_error", "pyramid cache missing")
      );
    }
    if ((state === "partial" || state === "complete") && ready.length > 0) {
      return last;
    }
    await sleep(interval);
  }
  throw new VolumeViewerError(
    "endpoint_error",
    fallbackMessage("endpoint_error", `pyramid not ready within ${timeout} ms`)
  );
}

function sleep(ms: number): Promise<void> {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

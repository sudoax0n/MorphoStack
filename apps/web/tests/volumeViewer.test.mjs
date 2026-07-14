/**
 * Unit tests for display-only volumeViewer pure helpers (no WebGL required).
 * Run: node apps/web/tests/volumeViewer.test.mjs
 */

import assert from "node:assert/strict";
import { pathToFileURL } from "node:url";
import path from "node:path";
import { fileURLToPath } from "node:url";

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const srcPath = path.join(__dirname, "..", "src", "volumeViewer.ts");
const transferPath = path.join(__dirname, "..", "src", "volumeTransfer.ts");

async function loadModule() {
  try {
    return await import(pathToFileURL(srcPath).href);
  } catch (err) {
    console.error(
      "Failed to import volumeViewer.ts (need Node with TS stripping, e.g. Node 22+).",
      err
    );
    process.exit(1);
  }
}

function b64(bytes) {
  return Buffer.from(bytes).toString("base64");
}

async function main() {
  const m = await loadModule();
  const t = await import(pathToFileURL(transferPath).href);

  // --- feature flag ---
  const mem = new Map();
  const storage = {
    getItem: (k) => (mem.has(k) ? mem.get(k) : null),
    setItem: (k, v) => mem.set(k, String(v))
  };
  assert.equal(m.isVolumeViewerEnabled(storage, ""), true);
  m.setVolumeViewerEnabled(false, storage);
  assert.equal(m.isVolumeViewerEnabled(storage, ""), false);
  assert.equal(m.isVolumeViewerEnabled(storage, "?volume=1"), true);
  assert.equal(m.isVolumeViewerEnabled(storage, "?volume=0"), false);
  m.setVolumeViewerEnabled(true, storage);
  assert.equal(m.isVolumeViewerEnabled(storage, ""), true);

  // --- budget ---
  assert.equal(m.isWithinBudget(100, 200), true);
  assert.equal(m.isWithinBudget(201, 200), false);
  assert.equal(m.isWithinBudget(m.DEFAULT_VOLUME_MAX_BYTES), true);
  assert.equal(m.isWithinBudget(m.DEFAULT_VOLUME_MAX_BYTES + 1), false);

  // --- dtype / shape ---
  assert.equal(m.bytesPerSample("uint8"), 1);
  assert.equal(m.bytesPerSample("float32"), 4);
  assert.deepEqual(m.shapeZyxToXyzDims([10, 20, 30], "zyx"), [30, 20, 10]);
  assert.deepEqual(m.worldSpacingFromSpec({ x_um: 0.5, y_um: 0.5, z_um: 2.0 }), [0.5, 0.5, 2.0]);

  // Anisotropy: cubic voxels in index space become stretched world box when z_um > x_um
  const extent = m.worldExtentUm([5, 5, 5], { x_um: 1, y_um: 1, z_um: 4 });
  assert.equal(extent.x, 4);
  assert.equal(extent.y, 4);
  assert.equal(extent.z, 16);
  assert.ok(extent.z / extent.x === 4, "anisotropic Z must be 4× physical vs XY for this fixture");

  // --- base64 + typed scalars ---
  const raw = new Uint8Array([0, 10, 20, 30, 40, 50, 60, 255]);
  const decoded = m.decodeBase64Binary(b64(raw));
  assert.deepEqual([...decoded], [...raw]);
  const scalars = m.createTypedScalars(decoded, "uint8", 8);
  assert.equal(scalars.values.length, 8);
  const range = m.estimateScalarRange(scalars.values);
  assert.equal(range[0], 0);
  assert.equal(range[1], 255);

  // --- payload validation / over-budget ---
  const goodShape = [2, 2, 2];
  const goodBytes = new Uint8Array(8).fill(128);
  const goodPayload = {
    cache_key: "abc",
    display_only: true,
    level: {
      level: 1,
      shape: goodShape,
      dtype: "uint8",
      axes: "zyx",
      voxel_size: { x_um: 1, y_um: 1, z_um: 2 },
      nbytes: 8,
      display_only: true
    },
    display_volume_spec: {
      role: "display_volume",
      level: 1,
      shape: goodShape,
      dtype: "uint8",
      axes: "zyx",
      level_voxel_size: { x_um: 1, y_um: 1, z_um: 2 },
      display_only: true
    },
    transfer_nbytes: 8,
    within_budget: true,
    dtype: "uint8",
    shape: goodShape,
    data_b64: b64(goodBytes)
  };
  const validated = m.validateLevelPayload(goodPayload, 1024);
  assert.deepEqual(validated.shapeZyx, [2, 2, 2]);
  assert.equal(validated.spacing.z_um, 2);

  assert.throws(
    () => m.validateLevelPayload({ ...goodPayload, transfer_nbytes: 99999, within_budget: false }, 1024),
    (err) => err instanceof m.VolumeViewerError && err.reason === "over_budget"
  );
  assert.throws(
    () => m.validateLevelPayload({ ...goodPayload, data_b64: undefined }, 1024),
    (err) => err instanceof m.VolumeViewerError && err.reason === "missing_binary"
  );

  // --- waitForPyramidLevelReady ---
  let polls = 0;
  const status = await m.waitForPyramidLevelReady({
    cacheKey: "k1",
    intervalMs: 5,
    timeoutMs: 1000,
    pollStatus: async () => {
      polls += 1;
      if (polls < 3) return { cache_key: "k1", state: "running", levels_ready: [] };
      return { cache_key: "k1", state: "partial", levels_ready: [1] };
    }
  });
  assert.equal(status.state, "partial");
  assert.ok(polls >= 3);

  let cancelled = false;
  await assert.rejects(
    () =>
      m.waitForPyramidLevelReady({
        cacheKey: "k2",
        intervalMs: 5,
        timeoutMs: 500,
        isCancelled: () => true,
        pollStatus: async () => ({ cache_key: "k2", state: "running", levels_ready: [] })
      }),
    (err) => err instanceof m.VolumeViewerError && err.reason === "stale_generation"
  );
  cancelled = true;
  assert.equal(cancelled, true);

  await assert.rejects(
    () =>
      m.waitForPyramidLevelReady({
        cacheKey: "k3",
        intervalMs: 5,
        timeoutMs: 40,
        pollStatus: async () => ({ cache_key: "k3", state: "running", levels_ready: [] })
      }),
    (err) => err instanceof m.VolumeViewerError && err.reason === "endpoint_error"
  );

  // --- labels / fallback copy ---
  assert.match(m.NAVIGATION_ONLY_LABEL, /Navigation only/);
  assert.match(m.fallbackMessage("no_webgl"), /WebGL/);
  assert.match(m.fallbackMessage("over_budget"), /budget/);

  // --- Packet 06: appearance control contract ---
  assert.equal(m.appearanceControlForBlend("mip"), "black_level");
  assert.equal(m.appearanceControlForBlend("composite"), "opacity");

  // Black level raises window floor; keeps hi fixed; never inverted.
  const win0 = m.intensityWindowFromBlackLevel([0, 1000], 0);
  assert.deepEqual(win0, [0, 1000]);
  const winHalf = m.intensityWindowFromBlackLevel([0, 1000], 0.5);
  assert.equal(winHalf[0], 500);
  assert.equal(winHalf[1], 1000);
  const winHigh = m.intensityWindowFromBlackLevel([100, 200], 0.95);
  assert.ok(winHigh[0] < winHigh[1], "window must remain non-empty");
  assert.equal(winHigh[1], 200);
  assert.equal(m.clamp01(-1), 0);
  assert.equal(m.clamp01(2), 1);

  // Projected fill: taller host improves width fill for square AABB (Scout 07 model).
  const oldHost = m.estimateAabbProjectedFill(1344, 378); // min(42vh,380) @ 1400×900
  const newHost = m.estimateAabbProjectedFill(1344, 522); // min(58vh,540) @ 1400×900 ≈ 522
  assert.ok(oldHost.heightLimited && newHost.heightLimited);
  assert.ok(
    newHost.fillWidth > oldHost.fillWidth + 0.04,
    `fill width must improve materially: old=${oldHost.fillWidth.toFixed(3)} new=${newHost.fillWidth.toFixed(3)}`
  );
  assert.ok(newHost.fillHeight >= 0.85, "full physical AABB still height-fitted");
  assert.ok(newHost.fillWidth < 1.0, "must not crop — fill width stays within canvas");

  // CSS contract constants match styles intent
  assert.match(m.VOLUME_CANVAS_HOST_HEIGHT_CSS, /58vh/);
  assert.match(m.VOLUME_CANVAS_HOST_HEIGHT_CSS, /540px/);
  assert.equal(m.VOLUME_CANVAS_HOST_MIN_HEIGHT_PX, 320);
  assert.ok(m.VOLUME_FIT_CPU_BUDGET_MS <= 50);
  assert.ok(m.VOLUME_FIT_RESIZE_DEBOUNCE_MS > 0);

  // --- display-only robust transfer math ---
  const sparse = new Float32Array(1000);
  sparse.set([10, 20, 30, 40, 50], 995);
  const sparseWindows = t.estimateVolumeWindows(sparse);
  assert.equal(sparseWindows.full[0], 0);
  assert.ok(sparseWindows.auto[1] > 0, "sparse foreground must produce a visible auto window");
  const degenerate = t.estimateVolumeWindows(new Float32Array([NaN, NaN]));
  assert.deepEqual(degenerate.full, [0, 1]);
  const constant = t.estimateVolumeWindows(new Float32Array([7, 7, 7]));
  assert.ok(constant.full[1] > constant.full[0]);

  const neutral = t.sanitizeVolumeTone({ exposureEv: 0, contrast: 1, gamma: 1, opacityGain: 1 });
  const bright = t.sanitizeVolumeTone({ exposureEv: 99, contrast: 99, gamma: -1, opacityGain: 99 });
  assert.equal(bright.exposureEv, 8);
  assert.equal(bright.contrast, 4);
  assert.equal(bright.gamma, 0.2);
  assert.equal(bright.opacityGain, 4);
  assert.ok(t.mapVolumeIntensity(0.1, bright) >= t.mapVolumeIntensity(0.1, neutral));

  const zeroOpacity = t.buildVolumeTransferPoints([0, 100], { ...neutral, opacityGain: 0 });
  assert.ok(zeroOpacity.every((point) => point.opacity === 0));
  const maxOpacity = t.buildVolumeTransferPoints([0, 100], { ...neutral, opacityGain: 4 });
  assert.ok(maxOpacity.every((point) => point.opacity >= 0 && point.opacity <= 1));
  assert.ok(maxOpacity.at(-1).opacity > 0.99);
  assert.deepEqual(t.windowFromFractions([0, 100], 0.2, 0.8), [20, 80]);
  const fractions = t.fractionsFromWindow([0, 100], [20, 80]);
  assert.ok(Math.abs(fractions[0] - 0.2) < 1e-9 && Math.abs(fractions[1] - 0.8) < 1e-9);

  // Session API surface (no GPU mount in unit tests)
  assert.equal(typeof m.VolumeViewerSession, "function");
  assert.equal(typeof m.detectWebGLSupport, "function");
  const proto = m.VolumeViewerSession.prototype;
  assert.equal(typeof proto.fitCamera, "function");
  assert.equal(typeof proto.setBlackLevel, "function");
  assert.equal(typeof proto.setIntensityWindow, "function");
  assert.equal(typeof proto.setOpacityGain, "function");
  assert.equal(typeof proto.setExposureEv, "function");
  assert.equal(typeof proto.setContrast, "function");
  assert.equal(typeof proto.setGamma, "function");
  assert.equal(typeof proto.autoMap, "function");
  assert.equal(typeof proto.resetDisplay, "function");

  console.log("volumeViewer.test.mjs: all passed");
}

main().catch((err) => {
  console.error(err);
  process.exit(1);
});

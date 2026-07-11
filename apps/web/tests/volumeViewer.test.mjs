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

  // --- disposal contract (no GPU): session not required for pure helpers ---
  assert.equal(typeof m.VolumeViewerSession, "function");
  assert.equal(typeof m.detectWebGLSupport, "function");

  console.log("volumeViewer.test.mjs: all passed");
}

main().catch((err) => {
  console.error(err);
  process.exit(1);
});

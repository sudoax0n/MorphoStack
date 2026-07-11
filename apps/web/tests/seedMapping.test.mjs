/**
 * Packet 13 pure coordinate-transform tests (no WebGL).
 * Run: node apps/web/tests/seedMapping.test.mjs
 */

import assert from "node:assert/strict";
import { pathToFileURL } from "node:url";
import path from "node:path";
import { fileURLToPath } from "node:url";

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const srcPath = path.join(__dirname, "..", "src", "volumeViewer.ts");

async function main() {
  const m = await import(pathToFileURL(srcPath).href);

  const geometry = {
    level: 1,
    shapeZyx: [10, 32, 32],
    factorsZyx: [2, 2, 2],
    levelVoxelSize: { x_um: 1.0, y_um: 1.0, z_um: 4.0 },
    sourceShapeZyx: [20, 64, 64],
    sourceVoxelSize: { x_um: 0.5, y_um: 0.5, z_um: 2.0 },
    sourceRevision: "session:test",
    calibrationKnown: true
  };

  // Integer source center round-trip
  const world = m.sourceToWorld({ x: 20, y: 24, z: 6 }, geometry);
  const seed = m.worldToObjectSeed(world, geometry, 12, { clampZ: false });
  assert.equal(seed.x, 20);
  assert.equal(seed.y, 24);
  assert.equal(seed.frame_index, 6);
  assert.equal(seed.radius, 12);
  assert.equal(seed.seed_origin, "viewer_3d");
  assert.equal(seed.radius_unit, "px");
  assert.equal(seed.source_revision, "session:test");

  // Anisotropy: world Z uses level spacing path
  const cont = m.worldToSource({ x_um: 10, y_um: 12, z_um: 8 }, geometry);
  assert.ok(Math.abs(cont.z - 4) < 1e-9); // 8 / 4 level z * factor 2? 
  // level_z = world_z / level_sz = 8/4 = 2; source_z = 2 * 2 = 4
  assert.equal(m.nearestInt(cont.z), 4);

  // Stale revision
  assert.throws(
    () =>
      m.worldToObjectSeed(world, geometry, 10, {
        expectedRevision: "session:other"
      }),
    (err) => err instanceof m.SeedMappingError && err.code === "stale_revision"
  );

  // OOB XY
  assert.throws(
    () => m.worldToObjectSeed({ x_um: 999, y_um: 1, z_um: 1 }, geometry, 5, { clampZ: false }),
    (err) => err instanceof m.SeedMappingError && err.code === "out_of_bounds"
  );

  // 2D-equivalent key fields (parity of quantized seed)
  const seed2d = { x: 20, y: 24, frame_index: 6, radius: 12 };
  const w2 = m.objectSeedToWorld(seed2d, geometry);
  const seed3d = m.worldToObjectSeed(w2, geometry, 12, { clampZ: false });
  assert.equal(seed3d.x, seed2d.x);
  assert.equal(seed3d.y, seed2d.y);
  assert.equal(seed3d.frame_index, seed2d.frame_index);

  console.log("seedMapping.test.mjs: all passed");
}

main().catch((err) => {
  console.error(err);
  process.exit(1);
});

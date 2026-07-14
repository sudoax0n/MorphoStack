/**
 * Packet 07 unit tests for display mesh preview helpers (no WebGL required).
 * Run: node apps/web/tests/meshPreview.test.mjs
 */

import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";
import { pathToFileURL } from "node:url";
import { fileURLToPath } from "node:url";

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const srcPath = path.join(__dirname, "..", "src", "meshPreview.ts");
const vendorPath = path.join(__dirname, "..", "public", "vendor", "plotly-2.35.2.min.js");

async function loadModule() {
  try {
    return await import(pathToFileURL(srcPath).href);
  } catch (err) {
    console.error("Failed to import meshPreview.ts", err);
    process.exit(1);
  }
}

async function main() {
  const m = await loadModule();

  // Vendored Plotly pin present (CDN independence)
  assert.ok(fs.existsSync(vendorPath), "public/vendor/plotly-2.35.2.min.js must exist");
  const vendorBytes = fs.statSync(vendorPath).size;
  assert.ok(vendorBytes > 1_000_000, `Plotly vendor too small: ${vendorBytes}`);
  assert.equal(m.PLOTLY_VENDOR_VERSION, "2.35.2");
  assert.match(m.PLOTLY_VENDOR_PATH, /plotly-2\.35\.2\.min\.js/);
  assert.equal(m.plotlyScriptUrl("http://127.0.0.1:8765"), "http://127.0.0.1:8765/vendor/plotly-2.35.2.min.js");
  assert.ok(!m.plotlyScriptUrl("http://127.0.0.1:8765").includes("cdn.plot.ly"));

  // Bounds + physical camera
  const verts = [
    [1, 2, 3],
    [4, 6, 9],
    [1, 6, 3]
  ];
  const b = m.meshBounds(verts);
  assert.deepEqual(b, { xmin: 1, ymin: 2, zmin: 3, xmax: 4, ymax: 6, zmax: 9 });
  const ext = m.meshExtentsUm(b);
  assert.equal(ext.dx, 3);
  assert.equal(ext.dy, 4);
  assert.equal(ext.dz, 6);
  const cam = m.meshCameraFromExtents(ext.dx, ext.dy, ext.dz);
  assert.ok(cam.eye.x > cam.center.x);
  assert.ok(cam.eye.y > cam.center.y);
  assert.ok(cam.eye.z > cam.center.z);
  assert.deepEqual(cam.center, { x: 1.5, y: 2, z: 3 });

  // HTML: local plotly, no CDN, fail-loud hooks, aspectmode data
  const payload = {
    vertices: [
      [0, 0, 0],
      [1, 0, 0],
      [0, 1, 0],
      [0, 0, 2]
    ],
    faces: [
      [0, 1, 2],
      [0, 1, 3]
    ],
    source_path: "D:/lab/mesh_demo.tif",
    surface_area_um2: 12.5,
    volume_um3: 3.25
  };
  const html = m.meshPreviewHtml(payload, {
    plotlyUrl: "http://127.0.0.1:9/vendor/plotly-2.35.2.min.js"
  });
  assert.ok(!html.includes("cdn.plot.ly"), "must not depend on public CDN");
  assert.ok(html.includes("/vendor/plotly-2.35.2.min.js"));
  assert.ok(html.includes('aspectmode: "data"') || html.includes("aspectmode: \"data\"") || html.includes('aspectmode:"data"') || html.includes("aspectmode: \"data\""));
  // Layout is built as JS object with aspectmode: "data"
  assert.match(html, /aspectmode:\s*"data"/);
  assert.ok(html.includes("Plotly failed to load") || html.includes("plotly_load"));
  assert.ok(html.includes(".catch"));
  assert.ok(html.includes("postMessage"));
  assert.ok(html.includes(m.MESH_PREVIEW_MESSAGE_TYPE));
  assert.ok(html.includes("mesh-error"));
  assert.ok(html.includes("scene.camera") || html.includes("camera:"));

  // Broken plotly URL path still embeds fail-loud (script tag present)
  const offlineHtml = m.meshPreviewHtml(payload, { plotlyUrl: "/vendor/plotly-2.35.2.min.js" });
  assert.ok(offlineHtml.includes('src="/vendor/plotly-2.35.2.min.js"'));
  assert.ok(!offlineHtml.includes("https://cdn.plot.ly"));

  // Message type guard
  assert.equal(
    m.isMeshPreviewMessage({ type: m.MESH_PREVIEW_MESSAGE_TYPE, status: "ok", plot_ms: 1, vertex_count: 1, face_count: 1 }),
    true
  );
  assert.equal(m.isMeshPreviewMessage({ type: "other" }), false);

  console.log("meshPreview.test.mjs: all passed");
}

main().catch((err) => {
  console.error(err);
  process.exit(1);
});

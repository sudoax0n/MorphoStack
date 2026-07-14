/**
 * Packet 08 pure contain-transform tests (no DOM).
 * Models CSS: width:100%; height:auto; max-height:min(70vh,720px); object-fit:contain
 * Run: node apps/web/tests/previewCoords.test.mjs
 */

import assert from "node:assert/strict";
import path from "node:path";
import { pathToFileURL } from "node:url";
import { fileURLToPath } from "node:url";

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const srcPath = path.join(__dirname, "..", "src", "previewCoords.ts");

async function main() {
  const m = await import(pathToFileURL(srcPath).href);

  // Square image in wider box → side letterbox, isotropic scale
  const square = m.containLayout(800, 480, 512, 512);
  assert.ok(Math.abs(square.scale - 480 / 512) < 1e-12);
  assert.ok(Math.abs(square.wRendered - 480) < 1e-9);
  assert.ok(Math.abs(square.hRendered - 480) < 1e-9);
  assert.ok(Math.abs(square.xOffset - (800 - 480) / 2) < 1e-9);
  assert.equal(square.yOffset, 0);

  // Wide image height-limited
  const wide = m.containLayout(800, 400, 1024, 512);
  assert.equal(wide.scale, Math.min(800 / 1024, 400 / 512));

  // Tall image width-limited
  const tall = m.containLayout(360, 480, 200, 800);
  assert.equal(tall.scale, Math.min(360 / 200, 480 / 800));

  // Zero / invalid
  assert.equal(m.containLayout(0, 100, 50, 50).scale, 0);
  assert.equal(m.containLayout(100, 100, 0, 50).scale, 0);
  assert.equal(m.imageDisplayScalePure(0, 10, 10, 10), 0);

  // Round-trip for integer centers
  const layout = m.containLayout(640, 480, 512, 512);
  for (const [ix, iy] of [
    [0, 0],
    [256, 256],
    [511, 511],
    [100, 200]
  ]) {
    const client = m.imageToContentPoint(ix, iy, layout);
    const back = m.contentToImagePoint(client.x, client.y, layout, 512, 512);
    assert.equal(back.x, ix, `round-trip x ${ix},${iy}`);
    assert.equal(back.y, iy, `round-trip y ${ix},${iy}`);
  }

  // Full client path with border/padding
  const metrics = {
    wBox: 800,
    hBox: 480,
    wSrc: 512,
    hSrc: 512,
    borderLeft: 1,
    borderTop: 1,
    paddingLeft: 0,
    paddingTop: 0
  };
  const c = m.imageToClientPointPure(256, 256, metrics);
  const img = m.clientToImagePointPure(c.x + 10, c.y + 20, 10, 20, metrics);
  assert.equal(img.x, 256);
  assert.equal(img.y, 256);

  assert.equal(m.imageDisplayScalePure(800, 480, 512, 512), square.scale);

  // CSS model: width fills container (UPSCALES past natural); height clamps
  const cases = [
    { id: "V1", vw: 1280, vh: 720, wSrc: 512, hSrc: 512 },
    { id: "V2", vw: 1366, vh: 768, wSrc: 1024, hSrc: 1024 },
    { id: "V3", vw: 1920, vh: 1080, wSrc: 512, hSrc: 512 },
    { id: "V4", vw: 2560, vh: 1440, wSrc: 2048, hSrc: 1024 },
    { id: "V5", vw: 390, vh: 844, wSrc: 512, hSrc: 512 }
  ];
  const panelPad = 18 * 2 + 12 * 2;
  for (const c of cases) {
    const containerW = Math.max(1, c.vw - panelPad);
    const maxH = Math.min(0.7 * c.vh, 720);
    const box = m.intrinsicContainBox(c.wSrc, c.hSrc, containerW, maxH);
    // Layout width always fills container (upscale path)
    assert.equal(box.wBox, containerW, `${c.id} layout width fills container`);
    assert.ok(box.hBox <= maxH + 1e-6, `${c.id} height within max`);
    assert.ok(box.scale > 0);
    // Upscale when natural is smaller than available box
    if (c.wSrc < containerW && c.hSrc < maxH) {
      assert.ok(box.scale > 1 || box.wPainted >= c.wSrc - 1e-6, `${c.id} may upscale`);
    }
    // Painted never exceeds layout; aspect preserved
    assert.ok(box.wPainted <= box.wBox + 1e-6);
    assert.ok(box.hPainted <= box.hBox + 1e-6);
    assert.ok(Math.abs(box.wPainted / box.hPainted - c.wSrc / c.hSrc) < 1e-9);
    // Height growth vs old 480 when clamp is above 480 and width allows
    if (maxH > 480 && containerW * (c.hSrc / c.wSrc) > 480) {
      assert.ok(box.hBox > 480 - 1e-6, `${c.id} taller than old 480 cap`);
    }
    // Overlay round-trip ≤ 1 image px (maps to ≤1–2 CSS px after scale)
    const L = m.containLayout(box.wBox, box.hBox, c.wSrc, c.hSrc);
    const mid = m.imageToContentPoint(c.wSrc / 2, c.hSrc / 2, L);
    const back = m.contentToImagePoint(mid.x, mid.y, L, c.wSrc, c.hSrc);
    assert.ok(Math.abs(back.x - c.wSrc / 2) <= 1);
    assert.ok(Math.abs(back.y - c.hSrc / 2) <= 1);
  }

  // Explicit upscale: 512² into 1800×720 max → layout 1800×720, paint 720×720
  const v3 = m.intrinsicContainBox(512, 512, 1800, Math.min(0.7 * 1080, 720));
  assert.equal(v3.wBox, 1800);
  assert.equal(v3.hBox, 720);
  assert.ok(Math.abs(v3.scale - 720 / 512) < 1e-12);
  assert.ok(Math.abs(v3.wPainted - 720) < 1e-6);
  assert.ok(v3.hBox > 480, "512² at wide desktop exceeds old 480 height");

  // Natural-size path when container is smaller than natural: downscale only
  const phone = m.intrinsicContainBox(512, 512, 330, Math.min(0.7 * 844, 720));
  assert.equal(phone.wBox, 330);
  assert.ok(phone.scale < 1);
  assert.ok(Math.abs(phone.hBox - 330) < 1e-6);

  console.log("previewCoords.test.mjs: all passed");
}

main().catch((err) => {
  console.error(err);
  process.exit(1);
});

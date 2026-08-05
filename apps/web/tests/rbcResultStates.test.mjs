/**
 * RBC result state contracts in main.ts (source assertions — no DOM).
 * Run: node apps/web/tests/rbcResultStates.test.mjs
 */

import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const mainTs = fs.readFileSync(path.join(__dirname, "..", "src", "main.ts"), "utf8");
const styles = fs.readFileSync(path.join(__dirname, "..", "src", "styles.css"), "utf8");

function main() {
  // Profile help no longer claims "same pipeline".
  assert.doesNotMatch(mainTs, /RBC: same pipeline/);
  assert.match(mainTs, /Capability badges show MEASURED/);

  // Typed envelope rendering exists.
  assert.match(mainTs, /function renderRbcEnvelope/);
  assert.match(mainTs, /rbc-badge-measured/);
  assert.match(mainTs, /rbc-badge-estimated/);
  assert.match(mainTs, /rbc-badge-withheld/);

  // Disclaimer + ESTIMATED path for uncalibrated LSM (no hard refuse).
  const renderFnStart = mainTs.indexOf("function renderRbcEnvelope");
  assert.ok(renderFnStart >= 0);
  const slice = mainTs.slice(renderFnStart, renderFnStart + 4000);
  assert.ok(slice.includes("rbc-disclaimer"), "disclaimer required");
  assert.match(slice, /ESTIMATED/);
  assert.match(slice, /manual X\/Y\/Z|Convert LSM/i);
  assert.match(slice, /never overwrites MEASURED/);

  // Measured and estimated stay separate.
  assert.match(slice, /rbc-measured/);
  assert.match(slice, /rbc-estimated-layer/);

  // Styles for authority badges.
  assert.match(styles, /\.rbc-badge-measured/);
  assert.match(styles, /\.rbc-badge-estimated/);
  assert.match(styles, /\.rbc-badge-withheld/);
  assert.match(styles, /\.rbc-estimated-layer/);

  console.log("rbcResultStates.test.mjs: ok");
}

main();

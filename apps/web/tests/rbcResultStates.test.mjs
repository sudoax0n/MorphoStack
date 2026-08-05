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

  // Disclaimer precedes estimate action; production estimate disabled.
  const renderFnStart = mainTs.indexOf("function renderRbcEnvelope");
  assert.ok(renderFnStart >= 0);
  const slice = mainTs.slice(renderFnStart, renderFnStart + 3500);
  const disclaimerIdx = slice.indexOf("rbc-disclaimer");
  const buttonIdx = slice.indexOf("rbc-show-estimate");
  assert.ok(disclaimerIdx >= 0, "disclaimer required");
  assert.ok(buttonIdx > disclaimerIdx, "disclaimer must appear before estimate button");
  assert.match(slice, /disabled/);
  assert.match(slice, /cannot be measured from this stack/i);

  // Measured and estimated stay separate.
  assert.match(slice, /rbc-measured/);
  assert.match(slice, /rbc-estimated-layer/);
  assert.doesNotMatch(slice, /overwrite MEASURED/i); // note text is fine
  assert.match(slice, /never overwrites MEASURED/);

  // Styles for authority badges.
  assert.match(styles, /\.rbc-badge-measured/);
  assert.match(styles, /\.rbc-badge-estimated/);
  assert.match(styles, /\.rbc-badge-withheld/);
  assert.match(styles, /\.rbc-estimated-layer/);

  console.log("rbcResultStates.test.mjs: ok");
}

main();

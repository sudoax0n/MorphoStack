/**
 * Kimi audit UI contracts (bugs 14-16) + preserve Step 2 stepper behavior.
 * Source assertions — no browser. Run: node apps/web/tests/kimiAuditUi.test.mjs
 */

import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const mainTs = fs.readFileSync(path.join(__dirname, "..", "src", "main.ts"), "utf8");

function extractFunction(source, name) {
  const start = source.indexOf(`function ${name}(`);
  assert.ok(start >= 0, `expected function ${name}`);
  // Skip TypeScript param/return type braces; open body after the param list's ')'.
  let depthParen = 0;
  let i = start + `function ${name}`.length;
  for (; i < source.length; i++) {
    const ch = source[i];
    if (ch === "(") depthParen++;
    else if (ch === ")") {
      depthParen--;
      if (depthParen === 0) {
        i++;
        break;
      }
    }
  }
  while (i < source.length && source[i] !== "{") i++;
  assert.ok(i < source.length && source[i] === "{", `expected body for ${name}`);
  let depth = 0;
  for (; i < source.length; i++) {
    const ch = source[i];
    if (ch === "{") depth++;
    else if (ch === "}") {
      depth--;
      if (depth === 0) {
        return source.slice(start, i + 1);
      }
    }
  }
  assert.fail(`unclosed function ${name}`);
}

function main() {
  const previewJsonBody = extractFunction(mainTs, "previewJsonBody");
  const applyObjectSeedFrom3D = extractFunction(mainTs, "applyObjectSeedFrom3D");
  const readThreshold = extractFunction(mainTs, "readThreshold");
  const completeStep = extractFunction(mainTs, "completeStep");
  const applyExactPayload = extractFunction(mainTs, "applyExactPayload");
  const updateObjectSeedStatus = extractFunction(mainTs, "updateObjectSeedStatus");

  // Bug 14: preview always sends profile
  assert.match(previewJsonBody, /profile:\s*readProfile\s*\(\s*\)/);
  assert.match(previewJsonBody, /threshold:\s*readThreshold\s*\(\s*\)/);

  // Bug 15: 3D pick converts global frame to local Z-range index
  assert.match(applyObjectSeedFrom3D, /zRange\.zmin/);
  assert.match(applyObjectSeedFrom3D, /localFrame/);
  assert.match(applyObjectSeedFrom3D, /clamp\s*\(/);

  // Bug 16: empty threshold rejected
  assert.match(readThreshold, /trim\s*\(\s*\)/);
  assert.match(readThreshold, /Threshold is required/);
  assert.doesNotMatch(readThreshold, /Number\s*\(\s*""\s*\)/);

  // Preserve prior stepper fix
  assert.match(completeStep, /index !== 1/);
  assert.match(applyExactPayload, /markStepDone\s*\(\s*1\s*\)/);
  assert.doesNotMatch(updateObjectSeedStatus, /completeStep\s*\(\s*1\s*\)/);

  console.log("kimiAuditUi.test.mjs: ok");
}

main();

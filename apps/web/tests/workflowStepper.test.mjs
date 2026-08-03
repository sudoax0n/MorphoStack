/**
 * Workflow stepper call-site contract (Step 2 stays open for outline review).
 * Source assertions — no DOM/browser. Run: node apps/web/tests/workflowStepper.test.mjs
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
  let i = source.indexOf("{", start);
  assert.ok(i >= 0, `expected body for ${name}`);
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
  const completeStep = extractFunction(mainTs, "completeStep");
  const markStepDone = extractFunction(mainTs, "markStepDone");
  const applyExactPayload = extractFunction(mainTs, "applyExactPayload");
  const updateObjectSeedStatus = extractFunction(mainTs, "updateObjectSeedStatus");

  // Status-only helper must not navigate.
  assert.match(markStepDone, /textContent = "Done"/);
  assert.doesNotMatch(markStepDone, /openStep\s*\(/);

  // completeStep must refuse auto-advance for Step 2 (index 1).
  assert.match(completeStep, /index !== 1/);
  assert.match(completeStep, /openStep\s*\(/);
  assert.match(completeStep, /markStepDone\s*\(\s*index\s*\)/);

  // Seed set/move/import/clear must not complete Step 2.
  assert.doesNotMatch(updateObjectSeedStatus, /completeStep\s*\(\s*1\s*\)/);
  assert.doesNotMatch(updateObjectSeedStatus, /markStepDone\s*\(\s*1\s*\)/);

  // Authoritative exact paint marks Step 2 Done without using completeStep(1).
  assert.match(applyExactPayload, /markStepDone\s*\(\s*1\s*\)/);
  assert.doesNotMatch(applyExactPayload, /completeStep\s*\(\s*1\s*\)/);

  // Inspect and Analyze still complete their steps (auto-advance preserved).
  assert.match(mainTs, /completeStep\s*\(\s*0\s*\)/);
  assert.match(mainTs, /completeStep\s*\(\s*2\s*\)/);
  // No remaining completeStep(1) caller should exist.
  assert.doesNotMatch(mainTs, /completeStep\s*\(\s*1\s*\)/);

  console.log("workflowStepper.test.mjs: ok");
}

main();

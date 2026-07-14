import assert from "node:assert/strict";
import { pathToFileURL } from "node:url";
import path from "node:path";
import { fileURLToPath } from "node:url";
const root = path.dirname(fileURLToPath(import.meta.url));
const m = await import(pathToFileURL(path.join(root, "..", "src", "multiscaleConsensusUi.ts")).href);

assert.equal(m.multiscaleConsensusRequestValue("vesicle", true, true, false), true);
assert.equal(m.multiscaleConsensusRequestValue("rbc", true, true, false), true);
assert.equal(m.multiscaleConsensusRequestValue("active_surfaces", true, true, false), false);
assert.equal(m.multiscaleConsensusRequestValue("vesicle", false, true, false), false);
assert.equal(m.multiscaleConsensusRequestValue("vesicle", true, true, true), false);
assert.deepEqual(m.multiscaleConsensusField({
  profile: "rbc", hasObjectSeed: true, checkboxChecked: true, competitiveChecked: false
}), { multiscale_consensus: true });
assert.equal(m.multiscaleConsensusControlState("active_surfaces", true, false).visible, false);
assert.equal(m.multiscaleConsensusControlState("vesicle", false, false).enabled, false);
assert.equal(m.multiscaleConsensusControlState("rbc", true, false).enabled, true);
console.log("multiscaleConsensusUi.test.mjs: all passed");

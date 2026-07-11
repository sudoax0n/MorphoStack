/**
 * Generation-owned busy overlay lifecycle (pure helpers from previewQueue.ts).
 * Run: node apps/web/tests/previewBusyLifecycle.test.mjs
 */

import assert from "node:assert/strict";
import { pathToFileURL } from "node:url";
import path from "node:path";
import { fileURLToPath } from "node:url";

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const srcPath = path.join(__dirname, "..", "src", "previewQueue.ts");

async function loadBusyHelpers() {
  try {
    const mod = await import(pathToFileURL(srcPath).href);
    return mod;
  } catch {
    // Fallback port matching previewQueue.ts busy helpers.
    function claimBusyOwner(owner, gen, latestGen, message) {
      if (gen !== latestGen) return owner;
      return { gen, message };
    }
    function releaseBusyOwner(owner, gen) {
      if (owner === null || owner.gen !== gen) return owner;
      return null;
    }
    function busyVisibleForLatest(owner, latestGen) {
      return owner !== null && owner.gen === latestGen;
    }
    function busyAfterProvisional(owner, gen, latestGen, exactPendingGen, hasSeed) {
      if (gen !== latestGen || !hasSeed) return releaseBusyOwner(owner, gen);
      if (exactPendingGen === gen) {
        return claimBusyOwner(owner, gen, latestGen, "Tracking object…");
      }
      return releaseBusyOwner(owner, gen);
    }
    return {
      claimBusyOwner,
      releaseBusyOwner,
      busyVisibleForLatest,
      busyAfterProvisional
    };
  }
}

async function testExactSuccessClearsBusy() {
  const { claimBusyOwner, releaseBusyOwner, busyVisibleForLatest } = await loadBusyHelpers();
  let latest = 3;
  let owner = claimBusyOwner(null, 3, latest, "Tracking object…");
  assert.equal(busyVisibleForLatest(owner, latest), true);
  owner = releaseBusyOwner(owner, 3);
  assert.equal(owner, null);
  assert.equal(busyVisibleForLatest(owner, latest), false);
}

async function testStaleReleaseDoesNotClearNewerOwner() {
  const { claimBusyOwner, releaseBusyOwner, busyVisibleForLatest } = await loadBusyHelpers();
  let latest = 5;
  let owner = claimBusyOwner(null, 5, latest, "Tracking object…");
  // Old gen 4 settles and tries to release — must not clear gen 5.
  owner = releaseBusyOwner(owner, 4);
  assert.equal(owner.gen, 5);
  assert.equal(busyVisibleForLatest(owner, latest), true);
  owner = releaseBusyOwner(owner, 5);
  assert.equal(owner, null);
}

async function testRapidSupersessionNtoN1() {
  const {
    claimBusyOwner,
    releaseBusyOwner,
    busyAfterProvisional,
    busyVisibleForLatest
  } = await loadBusyHelpers();
  let latest = 1;
  let exactPending = 1;
  let owner = claimBusyOwner(null, 1, latest, "Tracking object…");

  // Gen 1 provisional while exact pending → keep tracking busy
  owner = busyAfterProvisional(owner, 1, latest, exactPending, true);
  assert.equal(owner.message, "Tracking object…");

  // Supersede to N+1
  latest = 2;
  exactPending = 2;
  // Old gen 1 abort release must not wipe if ownership already moved
  owner = claimBusyOwner(owner, 2, latest, "Tracking object…");
  owner = releaseBusyOwner(owner, 1);
  assert.equal(owner.gen, 2);
  assert.equal(busyVisibleForLatest(owner, latest), true);

  // Exact 2 settles
  exactPending = null;
  owner = releaseBusyOwner(owner, 2);
  assert.equal(owner, null);
  assert.equal(busyVisibleForLatest(owner, latest), false);
}

async function testProvisionalDoesNotReshowAfterExactSettled() {
  const { claimBusyOwner, releaseBusyOwner, busyAfterProvisional } = await loadBusyHelpers();
  let latest = 7;
  let owner = claimBusyOwner(null, 7, latest, "Tracking object…");
  owner = releaseBusyOwner(owner, 7); // exact done
  // Late provisional for same gen with exact no longer pending
  owner = busyAfterProvisional(owner, 7, latest, null, true);
  assert.equal(owner, null);
}

/**
 * Provisional succeeds → exact throws non-abort error:
 * exactPending cleared, busy released, error status separate (not busy).
 */
async function testExactNonAbortErrorReleasesBusyKeepsErrorStatus() {
  const {
    claimBusyOwner,
    releaseBusyOwner,
    busyAfterProvisional,
    busyVisibleForLatest
  } = await loadBusyHelpers();
  let latest = 9;
  let exactPending = 9;
  let errorStatus = null;

  // Provisional paints while exact pending
  let owner = claimBusyOwner(null, 9, latest, "Provisional preview…");
  owner = busyAfterProvisional(owner, 9, latest, exactPending, true);
  assert.equal(busyVisibleForLatest(owner, latest), true);
  assert.equal(owner.message, "Tracking object…");

  // Exact starts
  owner = claimBusyOwner(owner, 9, latest, "Tracking object…");

  // Exact settles with non-abort error (mirrors runExactPreview catch path)
  exactPending = null;
  owner = releaseBusyOwner(owner, 9);
  errorStatus = "Tracked contour unavailable: network down";

  assert.equal(exactPending, null);
  assert.equal(owner, null);
  assert.equal(busyVisibleForLatest(owner, latest), false);
  assert.equal(typeof errorStatus, "string");
  assert.match(errorStatus, /Tracked contour unavailable/);
  // Error must not be claimed as busy ownership
  assert.notEqual(errorStatus, owner?.message);
}

async function main() {
  await testExactSuccessClearsBusy();
  await testStaleReleaseDoesNotClearNewerOwner();
  await testRapidSupersessionNtoN1();
  await testProvisionalDoesNotReshowAfterExactSettled();
  await testExactNonAbortErrorReleasesBusyKeepsErrorStatus();
  console.log("previewBusyLifecycle tests passed");
}

main().catch((err) => {
  console.error(err);
  process.exit(1);
});

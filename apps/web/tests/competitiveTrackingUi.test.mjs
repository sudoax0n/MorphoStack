/**
 * Packet 11 correction — browser request propagation + profile gating.
 * Pure helpers (no full DOM). Run: node apps/web/tests/competitiveTrackingUi.test.mjs
 */

import assert from "node:assert/strict";
import path from "node:path";
import { pathToFileURL } from "node:url";
import { fileURLToPath } from "node:url";

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const srcPath = path.join(__dirname, "..", "src", "competitiveTrackingUi.ts");

async function main() {
  const m = await import(pathToFileURL(srcPath).href);

  // --- Profile gating: only vesicle + seed supports competitive ---
  assert.equal(m.isCompetitiveTrackingSupported("vesicle", true), true);
  assert.equal(m.isCompetitiveTrackingSupported("vesicle", false), false);
  assert.equal(m.isCompetitiveTrackingSupported("rbc", true), false);
  assert.equal(m.isCompetitiveTrackingSupported("active_surfaces", true), false);

  // Request value forced false outside vesicle seeded workflow even if checkbox on
  assert.equal(m.competitiveTrackingRequestValue("vesicle", true, true), true);
  assert.equal(m.competitiveTrackingRequestValue("vesicle", true, false), false);
  assert.equal(m.competitiveTrackingRequestValue("vesicle", false, true), false);
  assert.equal(m.competitiveTrackingRequestValue("rbc", true, true), false);
  assert.equal(m.competitiveTrackingRequestValue("active_surfaces", true, true), false);

  // UI control visibility
  const rbc = m.competitiveTrackingControlState("rbc", true);
  assert.equal(rbc.visible, false);
  assert.equal(rbc.enabled, false);

  const vesicleNoSeed = m.competitiveTrackingControlState("vesicle", false);
  assert.equal(vesicleNoSeed.visible, true);
  assert.equal(vesicleNoSeed.enabled, false);

  const vesicleSeeded = m.competitiveTrackingControlState("vesicle", true);
  assert.equal(vesicleSeeded.visible, true);
  assert.equal(vesicleSeeded.enabled, true);

  // Preview / analyze / correction body field
  const previewOn = m.competitiveTrackingField({
    profile: "vesicle",
    hasObjectSeed: true,
    checkboxChecked: true
  });
  assert.deepEqual(previewOn, { competitive_tracking: true });

  const analyzeRbc = m.competitiveTrackingField({
    profile: "rbc",
    hasObjectSeed: true,
    checkboxChecked: true
  });
  assert.deepEqual(analyzeRbc, { competitive_tracking: false });

  const correctionNoSeed = m.competitiveTrackingField({
    profile: "vesicle",
    hasObjectSeed: false,
    checkboxChecked: true
  });
  assert.deepEqual(correctionNoSeed, { competitive_tracking: false });

  // Correction profile must use profile-input values (not missing profile-select)
  assert.equal(m.correctionProfileValue("vesicle"), "vesicle");
  assert.equal(m.correctionProfileValue("rbc"), "rbc");
  assert.equal(m.correctionProfileValue("active_surfaces"), "active_surfaces");
  assert.equal(m.correctionProfileValue(null), "vesicle");
  assert.equal(m.correctionProfileValue(""), "vesicle");
  assert.equal(m.correctionProfileValue("bogus"), "vesicle");

  // Simulated request assembly for the three surfaces
  function buildPreviewBody(profile, hasSeed, checked) {
    return {
      threshold: 100,
      object_seed: hasSeed ? { x: 1, y: 2, frame_index: 0, radius: 10 } : null,
      profile,
      ...m.competitiveTrackingField({
        profile,
        hasObjectSeed: hasSeed,
        checkboxChecked: checked
      })
    };
  }
  function buildAnalyzeBody(profile, hasSeed, checked) {
    return {
      threshold: 100,
      object_seed: hasSeed ? { x: 1, y: 2, frame_index: 0, radius: 10 } : null,
      profile,
      ...m.competitiveTrackingField({
        profile,
        hasObjectSeed: hasSeed,
        checkboxChecked: checked
      })
    };
  }
  function buildCorrectionBody(profileInputValue, hasSeed, checked) {
    const profile = m.correctionProfileValue(profileInputValue);
    return {
      action: "reject_frame",
      profile,
      object_seed: hasSeed ? { x: 1, y: 2, frame_index: 0, radius: 10 } : null,
      ...m.competitiveTrackingField({
        profile,
        hasObjectSeed: hasSeed,
        checkboxChecked: checked
      })
    };
  }

  assert.equal(buildPreviewBody("vesicle", true, true).competitive_tracking, true);
  assert.equal(buildPreviewBody("rbc", true, true).competitive_tracking, false);
  assert.equal(buildAnalyzeBody("vesicle", true, true).competitive_tracking, true);
  assert.equal(buildAnalyzeBody("active_surfaces", true, true).competitive_tracking, false);
  assert.equal(buildCorrectionBody("rbc", true, true).profile, "rbc");
  assert.equal(buildCorrectionBody("rbc", true, true).competitive_tracking, false);
  assert.equal(buildCorrectionBody("vesicle", true, true).competitive_tracking, true);
  // Bug regression: missing profile-select used to always default vesicle + still send true
  assert.equal(buildCorrectionBody(undefined, true, true).profile, "vesicle");

  assert.ok(String(m.COMPETITIVE_TRACKING_UI_WARNING).includes("Touching-vesicle real-data sign-off incomplete"));

  console.log("competitiveTrackingUi.test.mjs: all passed");
}

main().catch((err) => {
  console.error(err);
  process.exit(1);
});

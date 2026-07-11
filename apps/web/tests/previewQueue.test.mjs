/**
 * Async unit test for ProvisionalPreviewScheduler.
 * Run: node apps/web/tests/previewQueue.test.mjs
 *
 * Uses dynamic import of the TypeScript source via Node strip-types when available,
 * otherwise a minimal inlined port of the scheduler for CI without TS loaders.
 */

import assert from "node:assert/strict";
import { pathToFileURL } from "node:url";
import path from "node:path";
import { fileURLToPath } from "node:url";

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const srcPath = path.join(__dirname, "..", "src", "previewQueue.ts");

async function loadScheduler() {
  try {
    // Node 22+: experimental TypeScript stripping
    const mod = await import(pathToFileURL(srcPath).href);
    return mod;
  } catch {
    // Fallback: self-contained port matching previewQueue.ts semantics.
    class ProvisionalPreviewScheduler {
      constructor(getLatestGen, runOne) {
        this.getLatestGen = getLatestGen;
        this.runOne = runOne;
        this.inFlight = false;
        this.pendingGen = null;
        this.abort = null;
      }
      get busy() {
        return this.inFlight;
      }
      get pendingGeneration() {
        return this.pendingGen;
      }
      request(gen) {
        const latest = this.getLatestGen();
        if (gen !== latest) return;
        if (this.inFlight) {
          this.pendingGen = gen;
          this.abort?.abort();
          return;
        }
        void this.drain(gen);
      }
      cancel() {
        this.pendingGen = null;
        this.abort?.abort();
      }
      async drain(startGen) {
        this.inFlight = true;
        let gen = startGen;
        try {
          while (true) {
            const latest = this.getLatestGen();
            if (this.pendingGen !== null && this.pendingGen === latest) {
              gen = this.pendingGen;
            } else if (latest !== gen && this.pendingGen === null) {
              break;
            } else if (this.pendingGen !== null && this.pendingGen !== latest) {
              gen = latest;
            }
            this.pendingGen = null;
            this.abort?.abort();
            this.abort = new AbortController();
            const signal = this.abort.signal;
            const runGen = gen;
            try {
              await this.runOne(runGen, signal);
            } catch (error) {
              if (!(error && error.name === "AbortError")) {
                /* continue handoff */
              }
            }
            if (this.pendingGen !== null && this.pendingGen === this.getLatestGen()) {
              gen = this.pendingGen;
              continue;
            }
            break;
          }
        } finally {
          this.inFlight = false;
          const latest = this.getLatestGen();
          if (this.pendingGen !== null && this.pendingGen === latest) {
            const next = this.pendingGen;
            this.pendingGen = null;
            void this.drain(next);
          }
        }
      }
    }
    function shouldApplyPreview(gen, latestGen, frameIndex, quality, lastApplied) {
      if (gen !== latestGen) return false;
      if (
        lastApplied &&
        lastApplied.gen === gen &&
        lastApplied.frameIndex === frameIndex &&
        lastApplied.quality === "exact" &&
        quality === "provisional"
      ) {
        return false;
      }
      return true;
    }
    return { ProvisionalPreviewScheduler, shouldApplyPreview };
  }
}

function delay(ms) {
  return new Promise((r) => setTimeout(r, ms));
}

async function testAAbortedBStillRenders() {
  const { ProvisionalPreviewScheduler, shouldApplyPreview } = await loadScheduler();

  let latestGen = 0;
  const rendered = [];
  const started = [];

  const sched = new ProvisionalPreviewScheduler(
    () => latestGen,
    async (gen, signal) => {
      started.push(gen);
      // A is slow; B is fast after supersede.
      const waitMs = gen === 1 ? 80 : 10;
      await Promise.race([
        delay(waitMs),
        new Promise((_, reject) => {
          if (signal.aborted) {
            reject(Object.assign(new Error("aborted"), { name: "AbortError" }));
            return;
          }
          signal.addEventListener(
            "abort",
            () => reject(Object.assign(new Error("aborted"), { name: "AbortError" })),
            { once: true }
          );
        }),
      ]);
      if (signal.aborted) {
        throw Object.assign(new Error("aborted"), { name: "AbortError" });
      }
      if (
        shouldApplyPreview(gen, latestGen, gen, "provisional", null)
      ) {
        rendered.push(gen);
      }
    }
  );

  // Generation A starts.
  latestGen = 1;
  sched.request(1);
  await delay(15);
  assert.equal(started.includes(1), true, "A should have started");

  // B supersedes A while A is still in flight.
  latestGen = 2;
  sched.request(2);
  assert.equal(sched.pendingGeneration, 2, "B must be queued as pending gen");

  // Wait for drain handoff to finish B.
  await delay(200);

  assert.equal(rendered.includes(1), false, "aborted A must never paint");
  assert.equal(rendered.includes(2), true, "B must still render after A aborts");
  assert.deepEqual(
    rendered.filter((g) => g === 2),
    [2],
    "B should render exactly once"
  );
}

async function testExactWinsOverProvisional() {
  const { shouldApplyPreview } = await loadScheduler();
  const last = { gen: 5, frameIndex: 3, quality: "exact" };
  assert.equal(shouldApplyPreview(5, 5, 3, "provisional", last), false);
  assert.equal(shouldApplyPreview(5, 5, 3, "exact", last), true);
  assert.equal(shouldApplyPreview(4, 5, 3, "exact", last), false);
}

async function main() {
  await testAAbortedBStillRenders();
  await testExactWinsOverProvisional();
  console.log("previewQueue tests passed");
}

main().catch((err) => {
  console.error(err);
  process.exit(1);
});

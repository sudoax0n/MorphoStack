/**
 * Generation-aware provisional preview queue.
 *
 * Problem fixed: when request A is in flight and B supersedes it, a boolean
 * "retry after flight" flag plus AbortError early-return can drop B forever.
 * This scheduler always stores the latest pending generation and drains it in
 * ``finally`` so the newest request still renders after A aborts.
 */

export type PreviewQuality = "provisional" | "exact";

export type AppliedPreview = {
  gen: number;
  frameIndex: number;
  quality: PreviewQuality;
};

/**
 * Stale-response gate: only the newest generation may paint the overlay.
 * Within the same generation, provisional must not replace an exact result.
 */
export function shouldApplyPreview(
  gen: number,
  latestGen: number,
  frameIndex: number,
  quality: PreviewQuality,
  lastApplied: AppliedPreview | null
): boolean {
  if (gen !== latestGen) {
    return false;
  }
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

export function isAbortError(error: unknown): boolean {
  if (!error || typeof error !== "object") {
    return false;
  }
  const name = "name" in error ? String((error as { name?: unknown }).name) : "";
  return name === "AbortError";
}

/**
 * Generation-owned busy indicator for exact tracking.
 *
 * Only the generation that currently owns the busy state may show or clear it.
 * An older request settling after supersession must not hide a newer owner's text.
 */
export type BusyOwner = {
  gen: number;
  message: string;
};

/** Claim busy for ``gen`` when it is still the latest generation. */
export function claimBusyOwner(
  owner: BusyOwner | null,
  gen: number,
  latestGen: number,
  message: string
): BusyOwner | null {
  if (gen !== latestGen) {
    return owner;
  }
  return { gen, message };
}

/**
 * Release busy only when ``gen`` still owns it.
 * Returns the (possibly unchanged) owner after the release attempt.
 */
export function releaseBusyOwner(owner: BusyOwner | null, gen: number): BusyOwner | null {
  if (owner === null || owner.gen !== gen) {
    return owner;
  }
  return null;
}

/** True when busy should be painted for the current latest generation. */
export function busyVisibleForLatest(owner: BusyOwner | null, latestGen: number): boolean {
  return owner !== null && owner.gen === latestGen;
}

/**
 * After provisional paint: show "Tracking object…" only while exact for the
 * same generation is still pending.
 */
export function busyAfterProvisional(
  owner: BusyOwner | null,
  gen: number,
  latestGen: number,
  exactPendingGen: number | null,
  hasSeed: boolean
): BusyOwner | null {
  if (gen !== latestGen || !hasSeed) {
    return releaseBusyOwner(owner, gen);
  }
  if (exactPendingGen === gen) {
    return claimBusyOwner(owner, gen, latestGen, "Tracking object…");
  }
  // Exact already settled for this gen — do not re-show busy.
  return releaseBusyOwner(owner, gen);
}

/**
 * Serialises provisional fetch/render work with generation-aware handoff.
 *
 * - Only one run is in flight at a time.
 * - Superseding requests store ``pendingGen`` (not a bare boolean) and abort.
 * - After abort or completion, the latest pending generation is always drained.
 * - Callers pass the generation at schedule time; painting must still call
 *   :func:`shouldApplyPreview` so exact results win over provisional.
 */
export class ProvisionalPreviewScheduler {
  private inFlight = false;
  /** Latest generation waiting to run after the current flight ends/aborts. */
  private pendingGen: number | null = null;
  private abort: AbortController | null = null;

  constructor(
    private readonly getLatestGen: () => number,
    private readonly runOne: (gen: number, signal: AbortSignal) => Promise<void>
  ) {}

  /** True while a provisional request is executing (for tests/diagnostics). */
  get busy(): boolean {
    return this.inFlight;
  }

  get pendingGeneration(): number | null {
    return this.pendingGen;
  }

  /**
   * Request a provisional run for ``gen``. Older gens are ignored.
   * If a run is already in flight, records the newest pending gen and aborts.
   */
  request(gen: number): void {
    const latest = this.getLatestGen();
    if (gen !== latest) {
      return;
    }
    if (this.inFlight) {
      this.pendingGen = gen;
      this.abort?.abort();
      return;
    }
    void this.drain(gen);
  }

  /** Abort any in-flight provisional work (e.g. seed clear / authoritative). */
  cancel(): void {
    this.pendingGen = null;
    this.abort?.abort();
  }

  private async drain(startGen: number): Promise<void> {
    this.inFlight = true;
    let gen = startGen;
    try {
      while (true) {
        const latest = this.getLatestGen();
        // Prefer the newest known generation (pending or global).
        if (this.pendingGen !== null && this.pendingGen === latest) {
          gen = this.pendingGen;
        } else if (latest !== gen && this.pendingGen === null) {
          // Global gen moved ahead without going through request() — still safe-stop.
          break;
        } else if (this.pendingGen !== null && this.pendingGen !== latest) {
          // Stale pending; follow global latest if it still wants work.
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
          if (!isAbortError(error)) {
            // Non-abort errors are left to the runner; still hand off pending gens.
            if (runGen === this.getLatestGen()) {
              // runner already logged/handled if it swallowed; rethrow only if unhandled
            }
          }
          // AbortError: fall through to pending handoff.
        }

        // Handoff: if a newer gen was queued while we ran/aborted, continue loop.
        if (this.pendingGen !== null && this.pendingGen === this.getLatestGen()) {
          gen = this.pendingGen;
          continue;
        }
        break;
      }
    } finally {
      this.inFlight = false;
      // Critical: pending may have been set after the while-break check but
      // before inFlight was cleared — start a fresh drain for the latest gen.
      const latest = this.getLatestGen();
      if (this.pendingGen !== null && this.pendingGen === latest) {
        const next = this.pendingGen;
        this.pendingGen = null;
        void this.drain(next);
      }
    }
  }
}

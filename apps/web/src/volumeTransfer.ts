/**
 * Pure display-only intensity mapping for the browser volume navigator.
 *
 * These helpers only build VTK transfer-function points. They never mutate the
 * source scalar buffer or feed analysis, segmentation, export, or measurement.
 */

export const VOLUME_EXPOSURE_RANGE = { min: -4, max: 8, step: 0.25 } as const;
export const VOLUME_CONTRAST_RANGE = { min: 0.25, max: 4, step: 0.05 } as const;
export const VOLUME_GAMMA_RANGE = { min: 0.2, max: 4, step: 0.05 } as const;
export const VOLUME_OPACITY_RANGE = { min: 0, max: 4, step: 0.05 } as const;

export type VolumeToneSettings = {
  exposureEv: number;
  contrast: number;
  gamma: number;
  opacityGain: number;
};

export type VolumeTransferPoint = {
  scalar: number;
  red: number;
  green: number;
  blue: number;
  opacity: number;
};

/** Bright, conservative defaults applied with a robust data-derived window. */
export const AUTO_VOLUME_TONE: Readonly<VolumeToneSettings> = Object.freeze({
  exposureEv: 1,
  contrast: 1.1,
  gamma: 1.2,
  opacityGain: 0.8
});

/** Neutral mapping used by Reset; unlike Auto, it uses the full sampled range. */
export const RESET_VOLUME_TONE: Readonly<VolumeToneSettings> = Object.freeze({
  exposureEv: 0,
  contrast: 1,
  gamma: 1,
  opacityGain: 0.35
});

export function clamp(value: number, low: number, high: number): number {
  const v = Number(value);
  if (!Number.isFinite(v)) return low;
  return Math.max(low, Math.min(high, v));
}

export function stableScalarRange(
  range: readonly number[],
  fallback: [number, number] = [0, 1]
): [number, number] {
  const lo = Number(range[0]);
  const hi = Number(range[1]);
  if (!Number.isFinite(lo) || !Number.isFinite(hi)) return [...fallback];
  if (hi > lo) return [lo, hi];
  const pad = Math.max(1, Math.abs(lo) * 1e-6);
  return [lo, lo + pad];
}

function quantile(sorted: number[], q: number): number {
  if (sorted.length === 0) return Number.NaN;
  if (sorted.length === 1) return sorted[0];
  const index = clamp(q, 0, 1) * (sorted.length - 1);
  const lower = Math.floor(index);
  const upper = Math.ceil(index);
  if (lower === upper) return sorted[lower];
  const fraction = index - lower;
  return sorted[lower] * (1 - fraction) + sorted[upper] * fraction;
}

/**
 * Deterministic sampled full range plus robust display window. If a stack is
 * mostly one background value, the upper window is estimated from the
 * non-background samples so sparse vesicle/RBC signal remains visible.
 */
export function estimateVolumeWindows(
  values: ArrayLike<number>,
  sampleLimit = 65536
): { full: [number, number]; auto: [number, number]; finiteSamples: number } {
  const n = Math.max(0, Number(values.length) || 0);
  if (n === 0) return { full: [0, 1], auto: [0, 1], finiteSamples: 0 };

  const limit = Math.max(32, Math.floor(Number(sampleLimit) || 65536));
  const step = Math.max(1, Math.ceil(n / limit));
  const sampled: number[] = [];
  for (let i = 0; i < n; i += step) {
    const value = Number(values[i]);
    if (Number.isFinite(value)) sampled.push(value);
  }
  // Always consider the last voxel without making sampling nondeterministic.
  if ((n - 1) % step !== 0) {
    const last = Number(values[n - 1]);
    if (Number.isFinite(last)) sampled.push(last);
  }
  if (sampled.length === 0) return { full: [0, 1], auto: [0, 1], finiteSamples: 0 };

  sampled.sort((a, b) => a - b);
  const rawMin = sampled[0];
  const rawMax = sampled[sampled.length - 1];
  const full = stableScalarRange([rawMin, rawMax]);
  if (rawMin === rawMax) {
    return { full, auto: [...full], finiteSamples: sampled.length };
  }

  let lo = quantile(sampled, 0.005);
  let hi = quantile(sampled, 0.995);
  const fullSpan = full[1] - full[0];
  const epsilon = Math.max(Number.EPSILON, fullSpan * 1e-9);

  // Sparse fluorescence can have >99.5% exact background. In that case, use
  // the non-background population instead of returning an empty black window.
  if (!(hi > lo + epsilon)) {
    const foreground = sampled.filter((value) => value > rawMin + epsilon);
    if (foreground.length > 0) {
      lo = rawMin;
      hi = quantile(foreground, 0.99);
    }
  }
  if (!(hi > lo + epsilon)) {
    return { full, auto: [...full], finiteSamples: sampled.length };
  }

  lo = clamp(lo, full[0], full[1]);
  hi = clamp(hi, lo + epsilon, full[1]);
  return { full, auto: stableScalarRange([lo, hi], full), finiteSamples: sampled.length };
}

export function sanitizeVolumeTone(
  input: Partial<VolumeToneSettings>,
  fallback: Readonly<VolumeToneSettings> = AUTO_VOLUME_TONE
): VolumeToneSettings {
  return {
    exposureEv: clamp(
      input.exposureEv ?? fallback.exposureEv,
      VOLUME_EXPOSURE_RANGE.min,
      VOLUME_EXPOSURE_RANGE.max
    ),
    contrast: clamp(
      input.contrast ?? fallback.contrast,
      VOLUME_CONTRAST_RANGE.min,
      VOLUME_CONTRAST_RANGE.max
    ),
    gamma: clamp(input.gamma ?? fallback.gamma, VOLUME_GAMMA_RANGE.min, VOLUME_GAMMA_RANGE.max),
    opacityGain: clamp(
      input.opacityGain ?? fallback.opacityGain,
      VOLUME_OPACITY_RANGE.min,
      VOLUME_OPACITY_RANGE.max
    )
  };
}

/** Map a window-normalized scalar to display intensity. Positive EV is brighter. */
export function mapVolumeIntensity(normalized: number, tone: VolumeToneSettings): number {
  const s = sanitizeVolumeTone(tone);
  let value = clamp(normalized, 0, 1);
  value *= 2 ** s.exposureEv;
  value = (value - 0.5) * s.contrast + 0.5;
  value = clamp(value, 0, 1);
  return clamp(value ** (1 / s.gamma), 0, 1);
}

export function windowFromFractions(
  fullRange: [number, number],
  lowFraction: number,
  highFraction: number
): [number, number] {
  const full = stableScalarRange(fullRange);
  const low = clamp(lowFraction, 0, 0.999);
  const high = clamp(highFraction, low + 0.001, 1);
  const span = full[1] - full[0];
  return stableScalarRange([full[0] + low * span, full[0] + high * span], full);
}

export function fractionsFromWindow(
  fullRange: [number, number],
  window: [number, number]
): [number, number] {
  const full = stableScalarRange(fullRange);
  const span = full[1] - full[0];
  return [
    clamp((window[0] - full[0]) / span, 0, 1),
    clamp((window[1] - full[0]) / span, 0, 1)
  ];
}

function navigationColor(value: number): [number, number, number] {
  const y = clamp(value, 0, 1);
  // Cyan-white display LUT with a deliberately visible midrange.
  return [
    clamp(0.02 + 0.98 * y ** 1.35, 0, 1),
    clamp(0.04 + 0.96 * y ** 0.72, 0, 1),
    clamp(0.08 + 0.92 * y ** 0.58, 0, 1)
  ];
}

/** Build monotonic scalar nodes for VTK color and opacity functions. */
export function buildVolumeTransferPoints(
  window: [number, number],
  toneInput: Partial<VolumeToneSettings>,
  pointCount = 33
): VolumeTransferPoint[] {
  const [lo, hi] = stableScalarRange(window);
  const tone = sanitizeVolumeTone(toneInput);
  const count = Math.max(3, Math.min(257, Math.floor(Number(pointCount) || 33)));
  const span = hi - lo;
  const points: VolumeTransferPoint[] = [];
  for (let i = 0; i < count; i += 1) {
    const t = i / (count - 1);
    const intensity = mapVolumeIntensity(t, tone);
    const [red, green, blue] = navigationColor(intensity);
    points.push({
      scalar: lo + t * span,
      red,
      green,
      blue,
      opacity: clamp(tone.opacityGain * intensity ** 1.35, 0, 1)
    });
  }
  return points;
}
